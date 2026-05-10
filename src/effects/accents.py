"""LLM-режиссёр эффектов: один запрос → план акцентов / эмодзи / sfx / хука.

Стратегия: чтобы не платить за 4 отдельных LLM-запроса на каждый клип, делаем
ОДИН вызов с word-level таймкодами и просим вернуть полный EffectsPlan. Дешевле
и согласованнее (если в момент 5.2 sec — ding, то и emoji там же будет уместен).
"""
from __future__ import annotations

import json
import re
from typing import Optional

from ..llm import default_provider, get_provider
from ..transcribe import Segment
from .types import Accent, EffectsPlan, EmojiCue, HookOverlay, SfxCue


SYSTEM_DIRECTOR = """Ты — режиссёр коротких вертикальных видео в стиле Submagic / Captions.
Твоя задача: разметить эффекты для одного клипа (≤60 сек), чтобы поднять retention
и engagement в TikTok / Reels / YouTube Shorts.

На вход — слова с таймкодами (clip-relative, секунды от 0). На выход — JSON-план эффектов.

Принципы:
- НЕ перегружай. На клип 30-60 сек: 2-4 zoom-акцента, 1-3 эмодзи, 0-2 sfx, 1 hook.
- Эффекты ставь только там, где они УСИЛИВАЮТ контент (цифра, парадокс, раскрытие, эмоция).
- Эффекты НЕ конкурируют: zoom и эмодзи могут совпадать по времени, sfx — отдельно.
- Hook = очень короткий текст-крючок (3-7 слов), отображается в первые 1.5 сек.
  Должен быть ИНТРИГОЙ, а не описанием. Не повторять субтитры.

Возвращай СТРОГО JSON БЕЗ markdown:
{
  "accents": [
    {"start": 5.2, "end": 6.1, "kind": "emphasis|insight|reveal|punchline|transition",
     "strength": 0.7, "word": "ключевое слово"}
  ],
  "emojis": [
    {"timestamp": 5.4, "duration": 1.2, "emoji": "🔥", "word": "...",
     "position": "top-center|right|left"}
  ],
  "sfx": [
    {"timestamp": 5.2, "kind": "whoosh|ding|pop|drum|applause|swoosh",
     "word": "...", "volume_db": -8}
  ],
  "hook": {"text": "89% делают это неправильно", "duration": 1.5}
}

kind для accents:
- emphasis: голосовой акцент / громкость / повтор
- insight: момент откровения / "вот фишка"
- reveal: раскрытие цифры / факта
- punchline: панчлайн / ирония / сильная фраза
- transition: смена темы / "но смотри"

emoji подбирай по содержанию:
- цифры/деньги → 💰📈💸🚀
- инсайт → 💡⚡🤯
- противоречие → 🤔😳
- успех → ✅🔥🎯
- факап → 😱⛔📉
"""


def _format_words_for_prompt(segments: list[Segment], clip_start: float, clip_end: float,
                             clip_title: str = "") -> str:
    """Формирует word-level транскрипт для LLM с таймкодами относительно клипа."""
    lines = []
    if clip_title:
        lines.append(f"Заголовок клипа: {clip_title}")
        lines.append("")
    lines.append("Слова с таймкодами (секунды от 0):")
    for seg in segments:
        for w in (seg.words or []):
            if w.end < clip_start or w.start > clip_end:
                continue
            rel_start = max(0.0, w.start - clip_start)
            if rel_start > clip_end - clip_start:
                continue
            lines.append(f"[{rel_start:5.2f}] {w.text}")
    return "\n".join(lines)


def _extract_json_object(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?", "", raw, flags=re.MULTILINE).strip()
    raw = re.sub(r"```$", "", raw, flags=re.MULTILINE).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start:end + 1]
    return raw


def plan_effects(
    *,
    segments: list[Segment],
    clip_start: float,
    clip_end: float,
    clip_title: str = "",
    enable_zoom: bool = True,
    enable_emoji: bool = True,
    enable_sfx: bool = False,
    enable_hook: bool = True,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> EffectsPlan:
    """Один LLM-запрос → план всех эффектов для одного клипа.

    Включённые эффекты определяют что мы берём из ответа. LLM всё равно генерит
    весь план (для согласованности), но мы фильтруем под включённые флаги.
    """
    clip_dur = clip_end - clip_start
    user = _format_words_for_prompt(segments, clip_start, clip_end, clip_title)
    user += f"\n\nДлительность клипа: {clip_dur:.1f} сек.\nВерни JSON."

    prov = get_provider(provider or default_provider())
    if not model:
        try:
            model = prov.model_for_tier("low") or None
        except Exception:
            model = None

    resp = prov.generate(
        system=SYSTEM_DIRECTOR, user=user,
        max_tokens=1500, response_json=True, model=model,
    )

    raw = _extract_json_object(resp.text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return EffectsPlan()

    plan = EffectsPlan()

    if enable_zoom:
        for a in (data.get("accents") or [])[:6]:
            try:
                plan.accents.append(Accent(
                    start=float(a["start"]),
                    end=float(a.get("end", a["start"] + 0.6)),
                    kind=a.get("kind", "emphasis"),
                    strength=max(0.3, min(1.0, float(a.get("strength", 0.6)))),
                    word=a.get("word", ""),
                ))
            except (KeyError, ValueError, TypeError):
                continue

    if enable_emoji:
        for e in (data.get("emojis") or [])[:5]:
            try:
                plan.emojis.append(EmojiCue(
                    timestamp=float(e["timestamp"]),
                    duration=float(e.get("duration", 1.2)),
                    emoji=str(e.get("emoji", "🔥"))[:8],
                    word=e.get("word", ""),
                    position=e.get("position", "top-center"),
                ))
            except (KeyError, ValueError, TypeError):
                continue

    if enable_sfx:
        for s in (data.get("sfx") or [])[:4]:
            try:
                plan.sfx.append(SfxCue(
                    timestamp=float(s["timestamp"]),
                    kind=s.get("kind", "ding"),
                    word=s.get("word", ""),
                    volume_db=float(s.get("volume_db", -8.0)),
                ))
            except (KeyError, ValueError, TypeError):
                continue

    if enable_hook:
        h = data.get("hook")
        if h and h.get("text"):
            plan.hook = HookOverlay(
                text=str(h["text"])[:60],
                duration=float(h.get("duration", 1.5)),
            )

    return plan
