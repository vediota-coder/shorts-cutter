"""Auto-генерация SEO-метаданных для каждого клипа: заголовок, описание, хэштеги под платформу.

Дёргаем Claude Code CLI (без API-ключа) с контекстом:
- транскрипт фрагмента клипа
- тема клипа от picker'а (заголовок-крючок)
- бренд (ниша, ЦА, voice)
- CTA конкретного клипа

На выходе JSON: title (≤60), description (150-200) с UTM-ссылкой,
hashtags по платформам {youtube: [...], instagram: [...], vk: [...]}.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional

from .llm import default_provider, get_provider
from .prompts import load_prompt


_LEGACY_SYSTEM = """Ты — SEO-маркетолог для коротких вертикальных видео в B2B-нишах.
По фрагменту видео + информации о бренде сгенерируй метаданные публикации
ОТДЕЛЬНО для YouTube Shorts, Instagram Reels и ВК Клипов.

Правила:
- Заголовок (title): один на все платформы, до 60 символов, цепляющий, без кликбейта
- Описание (description): отдельное под каждую платформу
  - YouTube: 200-300 символов, упомяни ключевые слова, в конце CTA + ссылка
  - Instagram: 150-220 символов, эмоциональнее, эмоджи допустимы, в конце CTA, БЕЗ кликабельных ссылок (IG их режет)
  - ВК: 150-250 символов, нейтрально-экспертный тон, ссылка в конце
- Хэштеги: 7-12 на каждую платформу. Узкие нишевые > широкие. Часть на русском, часть на английском (где уместно)
- НЕ изобретай факты, держись транскрипта
- Голос бренда соблюдай

Возвращай СТРОГО JSON БЕЗ markdown:
{
  "title": "...",
  "descriptions": {"youtube": "...", "instagram": "...", "vk": "..."},
  "hashtags": {"youtube": ["#a","#b",...], "instagram": [...], "vk": [...]}
}"""


@dataclass
class ClipMeta:
    title: str = ""
    descriptions: dict[str, str] = field(default_factory=dict)
    hashtags: dict[str, list[str]] = field(default_factory=dict)
    lead_links: dict[str, str] = field(default_factory=dict)  # platform -> URL с UTM
    usage: dict = field(default_factory=dict)


def _utm_link(base_url: str, platform: str, clip_slug: str, brand: str) -> str:
    if not base_url:
        return ""
    sep = "&" if "?" in base_url else "?"
    params = urllib.parse.urlencode({
        "utm_source": platform,
        "utm_medium": "shorts",
        "utm_campaign": brand,
        "utm_content": clip_slug,
    })
    return f"{base_url}{sep}{params}"


def _extract_json(raw: str) -> dict:
    raw = re.sub(r"^```(?:json)?", "", raw.strip(), flags=re.MULTILINE).strip()
    raw = re.sub(r"```$", "", raw, flags=re.MULTILINE).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1:
        raw = raw[start:end + 1]
    return json.loads(raw)


def generate_clip_meta(
    *,
    clip_title: str,        # из picker'а
    clip_transcript: str,   # текст фрагмента
    brand_name: str,
    brand_lead_url: str,
    brand_niche: str,
    brand_audience: str,
    brand_voice: str,
    cta_text: str,
    clip_slug: str = "",
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> ClipMeta:
    user_msg = f"""ТЕМА КЛИПА (от человека-куратора): {clip_title}

ТРАНСКРИПТ ФРАГМЕНТА:
{clip_transcript}

БРЕНД: {brand_name}
НИША: {brand_niche}
ЦЕЛЕВАЯ АУДИТОРИЯ: {brand_audience}
ГОЛОС БРЕНДА: {brand_voice}
CTA В КОНЦЕ КЛИПА: {cta_text}
БАЗОВАЯ ССЫЛКА (она будет добавлена в конец описания где уместно): {brand_lead_url}

Сгенерируй метаданные. Только JSON, без пояснений.
"""
    SYSTEM = load_prompt("metadata")
    prov = get_provider(provider or default_provider())
    # для метаданных «balanced» tier — sonnet/4.1/flash, дешевле и быстрее picker'а
    if not model:
        try:
            model = prov.model_for_tier("balanced") or None
        except Exception:
            model = None
    resp = prov.generate(
        system=SYSTEM, user=user_msg,
        max_tokens=2000, response_json=True, model=model,
    )
    parsed = _extract_json(resp.text)

    title = parsed.get("title", clip_title).strip()
    descriptions = parsed.get("descriptions", {}) or {}
    hashtags_raw = parsed.get("hashtags", {}) or {}
    hashtags = {}
    for plat, tags in hashtags_raw.items():
        if isinstance(tags, list):
            hashtags[plat] = [t if t.startswith("#") else f"#{t}" for t in tags if t]

    lead_links = {
        plat: _utm_link(brand_lead_url, plat, clip_slug, brand_name)
        for plat in ("youtube", "vk", "instagram")
    }
    # вшиваем UTM-ссылку в конец description для платформ, где ссылки кликабельны
    for plat in ("youtube", "vk"):
        if plat in descriptions and lead_links.get(plat) and lead_links[plat] not in descriptions[plat]:
            descriptions[plat] = descriptions[plat].rstrip() + "\n\n" + lead_links[plat]

    return ClipMeta(
        title=title,
        descriptions=descriptions,
        hashtags=hashtags,
        lead_links=lead_links,
        usage=resp.to_usage_dict(),
    )


def collect_transcript_for_clip(segments, start: float, end: float) -> str:
    """Собирает текст транскрипта для отрезка [start, end]."""
    lines = []
    for seg in segments:
        if seg.end < start or seg.start > end:
            continue
        lines.append(seg.text)
    return " ".join(lines).strip()
