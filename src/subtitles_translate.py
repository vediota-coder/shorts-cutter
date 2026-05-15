"""Перевод субтитров клипа на другой язык + ре-burn в master.

Не парсит ASS — работает на уровне Segment-объектов:
- берёт исходные segments (с word-таймингами)
- переводит Segment.text через src/llm/translate.py
- пересоздаёт word-тайминги равномерным распределением слов перевода
  по тому же [start, end] (паттерн из voiceover.translated_to_segments)
- передаёт в существующий write_ass для генерации ASS-файла

Никакого нового рендера/burn — endpoint в web/app.py использует существующие
mux_audio_and_subs + apply_brand.
"""
from __future__ import annotations

from typing import Callable, Optional

from .llm.translate import translate_strings
from .transcribe import Segment, Word


PROGRESS = Callable[[float, str], None]


def _noop(_p: float, _m: str) -> None:
    pass


def translate_segments(
    segments: list[Segment],
    *,
    source_lang: str,
    target_lang: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    on_progress: PROGRESS = _noop,
) -> list[Segment]:
    """Возвращает новый list[Segment] с переведённым текстом.

    Word-тайминги пересоздаются равномерным распределением слов перевода
    по интервалу исходного segment'а — это терпимо для отображения, т.к.
    каждый segment всё равно короткий (1-3 сек) и точный word-level sync
    после перевода невозможен (количество слов меняется).
    """
    if not segments:
        return []

    texts = [s.text for s in segments]
    translated = translate_strings(
        texts,
        source_lang=source_lang,
        target_lang=target_lang,
        provider=provider,
        model=model,
        on_progress=on_progress,
    )

    out: list[Segment] = []
    for src_seg, new_text in zip(segments, translated):
        words_str = (new_text or src_seg.text).strip().split()
        if not words_str:
            continue
        n = len(words_str)
        dur = max(0.05, src_seg.end - src_seg.start)
        per_word = dur / n
        words = [
            Word(
                start=src_seg.start + i * per_word,
                end=src_seg.start + (i + 1) * per_word,
                text=w,
            )
            for i, w in enumerate(words_str)
        ]
        out.append(Segment(
            start=src_seg.start,
            end=src_seg.end,
            text=" ".join(words_str),
            words=words,
        ))
    return out


SUPPORTED_LANGS = ("en", "pt-br", "es", "de", "fr", "it")
