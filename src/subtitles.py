"""ASS-субтитры с шаблонами под разные стили шортсов.

Шаблоны:
- karaoke    — TikTok-стиль с per-word подсветкой, 3 слова окном
- block      — целые фразы появляются разом, без подсветки (легко читать)
- minimal    — небольшой белый текст, 5-6 слов разом
- neon       — киберпанк/неон стиль, яркий, для геймерского контента
- telegram   — компактный, многострочный, как в TG video transcripts
- big_white  — крупный белый, без подсветки, для подкастов

Каждый шаблон управляет:
- размером шрифта (с учётом ширины кадра)
- цветом, подсветкой, обводкой
- кол-вом слов на экране одновременно
- темпом смены (karaoke vs block)
- авто-переводом строки по символам
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .transcribe import Segment, Word


TemplateName = Literal["karaoke", "block", "minimal", "neon", "telegram", "big_white"]


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _ass_color(rgb: str) -> str:
    """#RRGGBB → ASS &HBBGGRR&."""
    rgb = rgb.lstrip("#")
    r, g, b = rgb[0:2], rgb[2:4], rgb[4:6]
    return f"&H00{b}{g}{r}&".upper()


def _escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\\", "/")


@dataclass
class SubTemplate:
    name: str
    font: str = "Helvetica Neue"
    size: int = 56
    bold: bool = True
    color: str = "#FFFFFF"
    highlight: str = "#FFE600"
    outline_color: str = "#000000"
    outline: int = 4
    shadow: int = 2
    margin_v: int = 280
    words_per_chunk: int = 3
    chunk_advance: int = 1     # 1 = karaoke (сдвиг по слову), N = block (по N слов)
    max_chars_per_line: int = 22  # авто-перевод строки
    use_highlight: bool = True
    min_chunk_duration: float = 0.6  # минимум секунд на чанк (для читаемости)
    highlight_scale: int = 105   # %% (95 = меньше, 105 = чуть крупнее)


PRESETS: dict[TemplateName, SubTemplate] = {
    "karaoke": SubTemplate(
        name="🎤 Karaoke (TikTok)",
        font="Helvetica Neue", size=58, bold=True,
        color="#FFFFFF", highlight="#FFE600",
        outline=4, shadow=2, margin_v=300,
        words_per_chunk=3, chunk_advance=1,
        max_chars_per_line=32, use_highlight=True,
        highlight_scale=110, min_chunk_duration=0.4,
    ),
    "block": SubTemplate(
        name="📦 Block (фразы)",
        font="Helvetica Neue", size=56, bold=True,
        color="#FFFFFF", highlight="#FFFFFF",
        outline=4, shadow=2, margin_v=320,
        words_per_chunk=3, chunk_advance=3,
        max_chars_per_line=34, use_highlight=False,
        min_chunk_duration=0.9,
    ),
    "minimal": SubTemplate(
        name="✏️ Minimal",
        font="Helvetica Neue", size=44, bold=False,
        color="#FFFFFF", highlight="#FFFFFF",
        outline=3, shadow=1, margin_v=240,
        words_per_chunk=3, chunk_advance=3,
        max_chars_per_line=36, use_highlight=False,
        min_chunk_duration=1.0,
    ),
    "neon": SubTemplate(
        name="🌈 Neon",
        font="Helvetica Neue", size=64, bold=True,
        color="#00FFFF", highlight="#FF00FF",
        outline_color="#1A0033", outline=5, shadow=3,
        margin_v=300, words_per_chunk=3, chunk_advance=1,
        max_chars_per_line=30, use_highlight=True,
        highlight_scale=115, min_chunk_duration=0.4,
    ),
    "telegram": SubTemplate(
        name="✈️ Telegram",
        font="Helvetica Neue", size=42, bold=False,
        color="#FFFFFF", highlight="#5BB6FF",
        outline_color="#000000", outline=2, shadow=1,
        margin_v=180, words_per_chunk=6, chunk_advance=3,
        max_chars_per_line=38, use_highlight=False,
        min_chunk_duration=1.3,
    ),
    "big_white": SubTemplate(
        name="⚪ Big White",
        font="Helvetica Neue", size=66, bold=True,
        color="#FFFFFF", highlight="#FFFFFF",
        outline=5, shadow=3, margin_v=300,
        words_per_chunk=2, chunk_advance=2,
        max_chars_per_line=26, use_highlight=False,
        min_chunk_duration=0.7,
    ),
}

DEFAULT_TEMPLATE: TemplateName = "block"


# ─────────────────────────── алгоритм генерации ───────────────────────────


def _wrap_words(words: list[str], max_chars: int) -> str:
    """Раскладываем слова на 1-2 строки через \\N исходя из max_chars per line."""
    return _wrap_words_paired(words, words, max_chars)


def _wrap_words_paired(visible: list[str], formatted: list[str], max_chars: int) -> str:
    """То же что _wrap_words, но длину строки меряем по `visible` (без ASS-кодов),
    а собираем результат из `formatted` (с подсветкой и пр.)."""
    lines: list[list[str]] = [[]]
    cur_len = 0
    for vis, fmt in zip(visible, formatted):
        wl = len(vis)
        if cur_len + wl + (1 if lines[-1] else 0) > max_chars and lines[-1]:
            lines.append([fmt])
            cur_len = wl
        else:
            lines[-1].append(fmt)
            cur_len += wl + (1 if cur_len > 0 else 0)
    return r"\N".join(" ".join(line) for line in lines)


def _gather_words(segments: list[Segment], start: float, end: float) -> list[Word]:
    out: list[Word] = []
    for seg in segments:
        if seg.end < start or seg.start > end:
            continue
        for w in (seg.words or []):
            if w.end < start or w.start > end:
                continue
            ws = max(start, w.start) - start
            we = min(end, w.end) - start
            text = (w.text or "").strip()
            if not text:
                continue
            out.append(Word(ws, we, text))
    return out


def write_ass(
    segments: list[Segment],
    start: float,
    end: float,
    out: Path,
    target_w: int = 1080,
    target_h: int = 1920,
    template: TemplateName | SubTemplate = DEFAULT_TEMPLATE,
) -> Path:
    """Генерирует ASS-субтитры по выбранному шаблону.

    Размер шрифта/обводки/теней автоматически масштабируется под target_h
    чтобы текст оставался читаемым на маленьких разрешениях.
    """
    style = PRESETS[template] if isinstance(template, str) else template

    # ⭐ ДВЕ разные шкалы:
    # - text_scale: для шрифта/обводки/теней (с боустом для мелких видео — текст должен быть читаем)
    # - geom_scale: для margin_v — линейно по высоте, иначе текст уезжает в центр
    if target_h >= 1280:
        text_scale = target_h / 1920
    elif target_h >= 720:
        text_scale = (target_h / 1920) * 1.5
    else:
        text_scale = (target_h / 1920) * 2.2  # на 360p и ниже текст ОЧЕНЬ нужен крупный
    geom_scale = target_h / 1920  # без буста — иначе субтитры съедут в середину кадра

    actual_size = max(14, int(round(style.size * text_scale)))
    actual_outline = max(1, int(round(style.outline * text_scale)))
    actual_shadow = max(0, int(round(style.shadow * text_scale)))
    actual_margin_v = max(20, int(round(style.margin_v * geom_scale)))
    # ⭐ горизонтальные margin'ы ≈ 4% от ширины (вместо хардкода 80px),
    # чтобы libass не auto-wrap'ил длинные кириллические слова на узких видео
    actual_margin_lr = max(20, int(round(target_w * 0.04)))

    primary = _ass_color(style.color)
    highlight = _ass_color(style.highlight)
    outline = _ass_color(style.outline_color)
    bold_flag = -1 if style.bold else 0

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {target_w}
PlayResY: {target_h}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.font},{actual_size},{primary},&H000000FF,{outline},&H80000000,{bold_flag},0,0,0,100,100,0,0,1,{actual_outline},{actual_shadow},2,{actual_margin_lr},{actual_margin_lr},{actual_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    words = _gather_words(segments, start, end)
    if not words:
        out.write_text(header, encoding="utf-8")
        return out

    events: list[str] = []

    if style.use_highlight and style.chunk_advance == 1:
        # ── karaoke-режим: окно из words_per_chunk слов, активное подсвечено ──
        n = style.words_per_chunk
        for i, w in enumerate(words):
            # окно: пытаемся центрировать активное слово
            win_start = max(0, i - n // 2)
            win_end = min(len(words), win_start + n)
            if win_end - win_start < n:
                win_start = max(0, win_end - n)
            chunk = words[win_start:win_end]

            visible: list[str] = []
            formatted: list[str] = []
            for j, ww in enumerate(chunk):
                actual = win_start + j
                t = _escape(ww.text)
                visible.append(t)
                if actual == i:
                    formatted.append(
                        r"{\c" + highlight.rstrip("&") + r"&"
                        rf"\fscx{style.highlight_scale}\fscy{style.highlight_scale}" + r"}"
                        + t + r"{\r}"
                    )
                else:
                    formatted.append(t)

            text = _wrap_words_paired(visible, formatted, style.max_chars_per_line)
            ev_start = w.start
            next_start = words[i + 1].start if i + 1 < len(words) else None
            ev_end = next_start if next_start is not None else w.end + 0.3
            # min_chunk_duration НЕ должно тянуть за начало следующего слова —
            # иначе события перекрываются и субтитры «скачут»
            target_end = ev_start + style.min_chunk_duration / 3
            if next_start is not None:
                ev_end = max(ev_end, min(target_end, next_start))
            else:
                ev_end = max(ev_end, target_end)
            events.append(f"Dialogue: 0,{_ass_time(ev_start)},{_ass_time(ev_end)},Default,,0,0,0,,{text}")
    else:
        # ── block-режим: чанки по chunk_advance слов появляются целиком ──
        adv = max(1, style.chunk_advance)
        i = 0
        while i < len(words):
            chunk = words[i:i + style.words_per_chunk]
            if not chunk:
                break
            ev_start = chunk[0].start
            # конец чанка: либо начало следующего чанка (если есть), либо конец последнего слова
            next_i = i + adv
            next_start = words[next_i].start if next_i < len(words) else None
            ev_end = next_start if next_start is not None else chunk[-1].end + 0.3
            # min_chunk_duration НЕ должно тянуть за начало следующего чанка —
            # иначе субтитры перекрываются и «скачут»
            target_end = ev_start + style.min_chunk_duration
            if next_start is not None:
                ev_end = max(ev_end, min(target_end, next_start))
            else:
                ev_end = max(ev_end, target_end)

            visible = [_escape(w.text) for w in chunk]
            formatted = list(visible)
            # доп. подсветка первого слова, если шаблон требует (без анимации)
            if style.use_highlight and formatted:
                formatted[0] = (
                    r"{\c" + highlight.rstrip("&") + r"&}" + formatted[0] + r"{\r}"
                )
            text = _wrap_words_paired(visible, formatted, style.max_chars_per_line)
            events.append(f"Dialogue: 0,{_ass_time(ev_start)},{_ass_time(ev_end)},Default,,0,0,0,,{text}")
            i += adv

    out.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return out
