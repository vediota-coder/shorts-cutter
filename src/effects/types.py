"""Общие dataclass'ы для эффектов клипа.

Все таймкоды хранятся в clip-relative координатах (от 0 до clip_dur),
не в координатах исходного длинного видео. Это упрощает рендер и кеш.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


AccentKind = Literal["emphasis", "insight", "reveal", "punchline", "transition"]
SfxKind = Literal["whoosh", "ding", "pop", "drum", "applause", "swoosh"]


@dataclass
class Accent:
    """Момент с эмоциональным/смысловым акцентом.

    strength: 0.0-1.0, сила эффекта. amplitude zoom'а скейлится по этому значению.
    """
    start: float
    end: float
    kind: AccentKind = "emphasis"
    strength: float = 0.6
    word: str = ""  # ключевое слово для дебага


@dataclass
class EmojiCue:
    """Эмодзи на акценте."""
    timestamp: float  # secs
    duration: float = 1.2
    emoji: str = "🔥"
    word: str = ""  # ключевое слово
    position: Literal["top-center", "right", "left"] = "top-center"


@dataclass
class SfxCue:
    """Звуковой эффект — точка в таймлайне аудио."""
    timestamp: float
    kind: SfxKind = "ding"
    word: str = ""
    volume_db: float = -8.0


@dataclass
class HookOverlay:
    """Текст-крючок в первые секунды клипа."""
    text: str = ""
    duration: float = 1.5
    fade_in: float = 0.15
    fade_out: float = 0.25


@dataclass
class EffectsPlan:
    """Полный план эффектов для одного клипа."""
    accents: list[Accent] = field(default_factory=list)
    emojis: list[EmojiCue] = field(default_factory=list)
    sfx: list[SfxCue] = field(default_factory=list)
    hook: HookOverlay | None = None

    def is_empty(self) -> bool:
        return (not self.accents and not self.emojis and not self.sfx
                and not (self.hook and self.hook.text))

    def to_dict(self) -> dict:
        return {
            "accents": [a.__dict__ for a in self.accents],
            "emojis": [e.__dict__ for e in self.emojis],
            "sfx": [s.__dict__ for s in self.sfx],
            "hook": self.hook.__dict__ if self.hook else None,
        }
