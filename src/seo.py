"""SEO для финальных шортсов: генерация и зашивание метаданных в MP4.

Используется ВО ВСЁМ shorts-cutter:
- pipeline.py (нарезка длинного видео на шортсы)
- pipeline_record.py (запись через телесуфлер)
- ручная загрузка через UI

ffmpeg-metadata, которую читают YouTube/Google/Vimeo/Facebook:
- title
- description / synopsis / comment
- keywords / genre
- artist (для бренда)
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SEOData:
    """Готовая SEO-упаковка для одного видео."""
    title: str = ""          # ≤95 симв., #Shorts добавится автоматически
    description: str = ""    # ≤4900 симв.
    tags: list[str] = field(default_factory=list)  # без #, до 30 шт., общая длина ≤500
    hashtags: list[str] = field(default_factory=list)  # с # для description

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
            "hashtags": self.hashtags,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SEOData":
        return cls(
            title=(d.get("title") or "")[:95],
            description=(d.get("description") or "")[:4900],
            tags=[t.lstrip("#")[:30] for t in (d.get("tags") or []) if t][:30],
            hashtags=[("#" + h.lstrip("#")) for h in (d.get("hashtags") or []) if h][:8],
        )


SEO_SYSTEM = """Ты — SEO-копирайтер шортсов. По сценарию и нише генерируй упаковку под YouTube Shorts:
- title (до 90 симв.): цепляющий, с ключевыми словами. БЕЗ #Shorts.
- description (180–400 симв.): первая строка с ключами + 1-2 строки CTA + ссылка если есть.
- tags: 8-12 строк без решёток, общая длина ≤ 450 симв. Только релевантные нише.
- hashtags: 4-6 хэштегов для description (#nicheword, #brandword и т.п.).

Алгоритм:
1. Извлеки 2-3 ключевые сущности из сценария.
2. Сделай title с цифрой/вопросом/обещанием (как у лучших шортсов рунета).
3. Description: первая строка-крюк, потом раскрытие, потом CTA.
4. Tags: миксуй broad (1-2 слова, "продажи в b2b") и narrow (4-5 слов конкретно).

Ответ строго JSON без markdown:
{"title":"...","description":"...","tags":["...","..."],"hashtags":["#...","#..."]}"""


def generate_seo(
    *,
    script: str,
    niche: str = "",
    product: str = "",
    brand: str = "",
    lead_url: str = "",
    provider_name: str = "anthropic",
    model: Optional[str] = None,
) -> SEOData:
    """Просит LLM упаковать сценарий в SEO. Использует registry провайдеров."""
    try:
        from .llm.registry import get_provider
    except Exception as e:
        raise RuntimeError(f"LLM registry недоступен: {e}")

    provider = get_provider(provider_name)
    if not provider.is_configured():
        raise RuntimeError(f"LLM-провайдер {provider_name} не настроен")

    user = (
        (f"Ниша: {niche}\n" if niche else "")
        + (f"Продукт: {product}\n" if product else "")
        + (f"Бренд: {brand}\n" if brand else "")
        + (f"Ссылка для CTA: {lead_url}\n" if lead_url else "")
        + f"\nСценарий шортса:\n{script}\n\n"
        + "Сгенерируй упаковку (JSON)."
    )

    resp = provider.generate(
        system=SEO_SYSTEM,
        user=user,
        max_tokens=1200,
        response_json=True,
        model=model,
    )
    txt = (resp.text or "").strip()
    # удаляем возможный markdown-fence
    txt = re.sub(r"^```(?:json)?\s*", "", txt)
    txt = re.sub(r"```\s*$", "", txt)
    try:
        data = json.loads(txt)
    except Exception as e:
        raise RuntimeError(f"LLM вернул не-JSON: {txt[:200]}")
    return SEOData.from_dict(data)


def stamp_metadata(
    src: Path,
    out: Path,
    *,
    seo: Optional[SEOData] = None,
    title: str = "",
    description: str = "",
    tags: Optional[list[str]] = None,
    artist: str = "",
    extra: Optional[dict] = None,
) -> Path:
    """Зашивает в MP4-контейнер metadata. Stream-copy — без перекодирования.

    Принимает SEOData объект ИЛИ отдельные поля. SEOData приоритетнее.
    """
    if seo:
        title = title or seo.title
        description = description or seo.description
        tags = tags or seo.tags

    args = ["ffmpeg", "-y", "-i", str(src), "-c", "copy", "-movflags", "+faststart"]
    if title:
        args += ["-metadata", f"title={title[:200]}"]
    if description:
        # description дублируем во все совместимые слоты разных плееров/платформ
        args += [
            "-metadata", f"description={description[:1000]}",
            "-metadata", f"comment={description[:1000]}",
            "-metadata", f"synopsis={description[:1000]}",
        ]
    if tags:
        kw = ",".join(t.lstrip("#") for t in tags[:30])[:500]
        args += ["-metadata", f"keywords={kw}", "-metadata", f"genre={kw[:120]}"]
    if artist:
        args += ["-metadata", f"artist={artist[:100]}", "-metadata", f"album_artist={artist[:100]}"]
    if extra:
        for k, v in extra.items():
            args += ["-metadata", f"{k}={str(v)[:500]}"]
    args.append(str(out))
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg metadata failed: {proc.stderr[-500:]}")
    return out


def read_metadata(src: Path) -> dict:
    """Читает metadata MP4 через ffprobe — для проверки и UI-предпросмотра."""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams",
             "-of", "json", str(src)],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(proc.stdout)
        tags = (data.get("format") or {}).get("tags") or {}
        return {k.lower(): v for k, v in tags.items()}
    except Exception:
        return {}
