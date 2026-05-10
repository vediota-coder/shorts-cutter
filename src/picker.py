"""Выбор топ-моментов: через любой LLM-провайдер (claude-code/anthropic/openai/gemini)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from .llm import default_provider, get_provider
from .prompts import load_prompt


_LEGACY_SYSTEM = """Ты — топовый продюсер вертикальных шортсов на 1М+ просмотров.
Знаешь что такое «wow-моменты» и виральные крючки. Видишь разницу между
«просто интересным фрагментом» и моментом, который остановит scroll.

Из транскрипта длинного видео выбери 5–10 САМЫХ СИЛЬНЫХ фрагментов 25–60 секунд.

Критерии виральности (выбирай ТОЛЬКО те, у которых ВСЕ 4 пункта):
1. Сильный hook в первые 3 секунды: парадокс, вопрос-провокация, неожиданный факт,
   контр-интуитивное утверждение, конкретная цифра/история. НЕ «итак, сегодня поговорим».
2. Законченная мысль: фрагмент должен иметь чёткое начало и финал, не обрубаться.
3. «Saveable / shareable»: контент, который зритель захочет сохранить или переслать.
   Например: «правило / приём / факт / история / разоблачение / конкретный совет».
4. Эмоциональный пик ИЛИ практическая ценность ИЛИ контент, который меняет картину мира.

ИЗБЕГАЙ:
- Контент-«воду» (общие рассуждения без конкретики)
- Привязки к конкретным событиям недавним (стареет быстро)
- Длинные истории без чёткого вывода

Заголовок (title) — не описание клипа, а ЦЕПЛЯЮЩИЙ заголовок для соцсетей,
6–10 слов, который содержит крючок (число / парадокс / boldness).

Возвращай СТРОГО JSON-массив (без markdown):
[{"start": "mm:ss", "end": "mm:ss", "title": "...", "hook": "первая фраза в клипе"}]
"""


@dataclass
class Clip:
    start: float
    end: float
    title: str
    hook: str


@dataclass
class PickResult:
    clips: list["Clip"]
    usage: dict = field(default_factory=dict)  # input_tokens / output_tokens / cost_usd / duration_ms / model


def _parse_timestamp(s) -> float:
    if isinstance(s, (int, float)):
        return float(s)
    parts = str(s).split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return float(s)


def _extract_json_array(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?", "", raw, flags=re.MULTILINE).strip()
    raw = re.sub(r"```$", "", raw, flags=re.MULTILINE).strip()
    # вытаскиваем самый внешний массив
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end != -1 and end > start:
        return raw[start:end + 1]
    return raw


def pick_clips_with_usage(
    transcript: str,
    max_clips: int = 8,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    tier: str = "high",   # ⭐ для picker по умолчанию используем topовую модель
    extra_instructions: str = "",  # ⭐ per-video override от пользователя
) -> PickResult:
    user_msg = (
        f"Транскрипт (формат [mm:ss] текст):\n\n{transcript}\n\n"
        f"Выбери до {max_clips} клипов. Возвращай только JSON-массив, без пояснений."
    )
    SYSTEM = load_prompt("picker")
    # ⭐ per-video инструкции от пользователя — приоритетное правило, добавляется в конец
    # системного промпта чтобы LLM учитывал его как override основных критериев.
    if extra_instructions and extra_instructions.strip():
        SYSTEM = (
            SYSTEM.rstrip()
            + "\n\n=== ВАЖНО — ИНСТРУКЦИЯ ОТ ПОЛЬЗОВАТЕЛЯ ДЛЯ ИМЕННО ЭТОГО ВИДЕО ===\n"
            + "Это приоритетное правило, которое УТОЧНЯЕТ или СУЖАЕТ критерии выше. "
            + "Если оно противоречит общим критериям — следуй ему. "
            + "Если оно задаёт тематический фильтр — выбирай ТОЛЬКО фрагменты, попадающие под фильтр.\n\n"
            + extra_instructions.strip()
            + "\n=== КОНЕЦ ИНСТРУКЦИИ ОТ ПОЛЬЗОВАТЕЛЯ ===\n"
        )
    prov = get_provider(provider or default_provider())
    # если модель не задана явно — берём «high» из tier-mapping провайдера
    if not model:
        try:
            model = prov.model_for_tier(tier) or None
        except Exception:
            model = None
    resp = prov.generate(
        system=SYSTEM, user=user_msg,
        max_tokens=3000, response_json=True, model=model,
    )

    raw = _extract_json_array(resp.text)
    data = json.loads(raw)
    clips: list[Clip] = []
    for c in data:
        start = _parse_timestamp(c["start"])
        end = _parse_timestamp(c["end"])
        # ⭐ жёсткий cap 60 сек: VK Klips и YouTube Shorts отрезают всё выше 60.
        # Reels допускает 90, но единый формат удобнее (один master под три платформы).
        MAX_DUR = 60.0
        if end - start > MAX_DUR:
            end = start + MAX_DUR
        clips.append(Clip(
            start=start, end=end,
            title=c.get("title", ""), hook=c.get("hook", ""),
        ))

    return PickResult(clips=clips, usage=resp.to_usage_dict())


def pick_clips(transcript: str, max_clips: int = 8, model: Optional[str] = None) -> list[Clip]:
    """Старая сигнатура для совместимости."""
    return pick_clips_with_usage(transcript, max_clips, model=model).clips
