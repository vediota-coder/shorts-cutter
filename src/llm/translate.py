"""Generic batch-translate helper для произвольных пар языков.

Используется и для субтитров (текст для отображения), и в voiceover.py
(через _parse_json_items). Dub-specific промпт остаётся в voiceover.py,
здесь — нейтральный перевод текста-как-текста.
"""
from __future__ import annotations

import json
import re
from typing import Callable, Optional

from . import default_provider, get_provider


PROGRESS = Callable[[float, str], None]


def _noop(_p: float, _m: str) -> None:
    pass


_LANG_NAMES = {
    "ru": "русский",
    "en": "English",
    "pt": "português brasileiro",
    "pt-br": "português brasileiro",
    "es": "español",
    "de": "Deutsch",
    "fr": "français",
    "it": "italiano",
    "zh": "中文",
    "ja": "日本語",
}


def _lang_name(code: str) -> str:
    return _LANG_NAMES.get(code.lower().strip(), code)


def _build_system(source_lang: str, target_lang: str) -> str:
    src = _lang_name(source_lang)
    tgt = _lang_name(target_lang)
    return (
        f"Ты — переводчик коротких фраз с {src} на {tgt} для субтитров видео.\n"
        "\n"
        "Правила:\n"
        f"- Переведи каждую фразу на {tgt}, сохраняя смысл, тон, длину.\n"
        "- НЕ добавляй пояснений, не объединяй и не дроби фразы.\n"
        "- Имена собственные оставляй как принято в целевом языке.\n"
        "- Если фраза — короткое восклицание, перевод тоже короткий.\n"
        "- Технические термины — оставляй латиницей, если так принято.\n"
        "\n"
        'Возвращай СТРОГО JSON: {"items": [{"i": 0, "t": "..."}, ...]}\n'
    )


def _parse_json_items(text: str, key: str = "t") -> dict[int, str]:
    """Достаёт {i: text} из ответа LLM, толерантно к markdown-обёрткам.

    Универсальный парсер — переиспользуется voiceover.py (передаёт key="ru").
    """
    text = text.strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    items = data.get("items") or []
    out: dict[int, str] = {}
    for it in items:
        try:
            out[int(it["i"])] = str(it.get(key) or "")
        except (KeyError, ValueError, TypeError):
            continue
    return out


def translate_strings(
    items: list[str],
    *,
    source_lang: str,
    target_lang: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    batch_size: int = 80,
    on_progress: PROGRESS = _noop,
) -> list[str]:
    """Переводит список строк батчами через LLM. Возвращает list той же длины.

    Если LLM не вернул перевод для какой-то позиции — fallback на оригинал.
    """
    if not items:
        return []
    if source_lang.lower() == target_lang.lower():
        return list(items)

    prov = get_provider(provider or default_provider())
    system = _build_system(source_lang, target_lang)

    out: list[str] = [""] * len(items)
    total = len(items)

    for batch_start in range(0, total, batch_size):
        batch = items[batch_start:batch_start + batch_size]
        payload = [{"i": batch_start + idx, "t": s} for idx, s in enumerate(batch)]
        user = json.dumps({"items": payload}, ensure_ascii=False)
        on_progress(
            batch_start / total * 100,
            f"перевод {batch_start + 1}–{batch_start + len(batch)} из {total}",
        )
        resp = prov.generate(
            system=system, user=user,
            max_tokens=4000, response_json=True, model=model,
        )
        translated = _parse_json_items(resp.text, key="t")
        for idx, src_text in enumerate(batch):
            i = batch_start + idx
            out[i] = (translated.get(i) or "").strip() or src_text
    on_progress(100, f"переведено {len(out)} строк")
    return out
