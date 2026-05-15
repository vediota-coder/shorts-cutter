"""ASS-субтитры с шаблонами под разные стили шортсов.

Базовые шаблоны:
- karaoke    — TikTok-стиль с per-word подсветкой, 3 слова окном
- block      — целые фразы появляются разом, без подсветки (легко читать)
- minimal    — небольшой белый текст, 5-6 слов разом
- neon       — киберпанк/неон стиль, яркий, для геймерского контента
- telegram   — компактный, многострочный, как в TG video transcripts
- big_white  — крупный белый, без подсветки, для подкастов

Pro-шаблоны (используют accent_keywords из EffectsPlan):
- submagic   — Hormozi-style: UPPERCASE bold, акцент-слова жёлтым+scale
- captions   — Wrapbox: чёрный полупрозрачный бокс под текстом, акцент жёлтым
- podcast_pro— clean: тонкий sans, 4-5 слов, мягкий цветной акцент

Каждый шаблон управляет:
- размером шрифта (с учётом ширины кадра)
- цветом, подсветкой, обводкой, фоновым боксом
- кол-вом слов на экране одновременно
- темпом смены (karaoke vs block)
- авто-переводом строки по символам
- UPPERCASE / pop-in / accent highlights
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .transcribe import Segment, Word


TemplateName = Literal[
    "karaoke", "block", "minimal", "neon", "telegram", "big_white",
    "submagic", "captions", "podcast_pro",
    "beast", "karaoke_fill", "highlight_box", "bubble", "chroma",
]

# Safe-area для платформ: минимальный margin_v в координатах 1920-высоты,
# чтобы субтитры не залезали под нижний UI (caption bar + кнопки).
# Замерено по живым видео: TikTok ~480px нижнего UI, Reels ~470, YT Shorts ~360.
SafeArea = Literal["none", "tiktok", "youtube_shorts", "reels"]
_SAFE_AREA_MIN_MARGIN_V_AT_1920 = {
    "none": 0,
    "tiktok": 500,
    "youtube_shorts": 380,
    "reels": 470,
}


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


def _ass_color_alpha(rgb: str, alpha: int) -> str:
    """#RRGGBB + alpha[0-255] → ASS &HAABBGGRR. alpha=0 непрозрачно, 255 невидимо."""
    rgb = rgb.lstrip("#")
    r, g, b = rgb[0:2], rgb[2:4], rgb[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _escape(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\\", "/")


def _strip_ass_tags(s: str) -> str:
    """Убирает ASS override tags {\\...} из строки — для оценки длины текста."""
    return re.sub(r"\{[^}]*\}", "", s).replace(r"\N", "\n")


def _pill_shape_cmd(width: int, height: int, radius: int) -> str:
    """ASS \\p draw-commands для капсулы. Координаты от (0,0) = top-left.

    Используется с \\an7\\pos(top_left_x, top_left_y) — libass с \\p1
    игнорирует \\an5 для центрирования shape, поэтому проще использовать
    top-left anchor и явно сдвигать \\pos.
    """
    w = max(2, int(width))
    h = max(2, int(height))
    r = max(1, min(int(radius), w // 2, h // 2))
    c = max(1, int(round(0.5523 * r)))
    return (
        f"m {r} 0 "
        f"l {w-r} 0 "
        f"b {w-r+c} 0 {w} {r-c} {w} {r} "
        f"l {w} {h-r} "
        f"b {w} {h-r+c} {w-r+c} {h} {w-r} {h} "
        f"l {r} {h} "
        f"b {r-c} {h} 0 {h-r+c} 0 {h-r} "
        f"l 0 {r} "
        f"b 0 {r-c} {r-c} 0 {r} 0"
    )


def _estimate_text_pixels(text: str, font_size: int, *, char_w_ratio: float = 0.58, line_h_ratio: float = 1.18) -> tuple[int, int]:
    """Грубая оценка ширины/высоты ASS-текста в пикселях. Игнорирует override tags."""
    clean = _strip_ass_tags(text)
    lines = clean.split("\n")
    max_len = max((len(l) for l in lines), default=1)
    n_lines = max(1, len(lines))
    w = int(round(max_len * font_size * char_w_ratio))
    h = int(round(n_lines * font_size * line_h_ratio))
    return w, h


_PUNCT_RE = re.compile(r"[^\wа-яёА-ЯЁ]+", re.UNICODE)


def _norm_word(s: str) -> str:
    return _PUNCT_RE.sub("", s).lower()


@dataclass
class AccentKeyword:
    """Слово, которое нужно выделить особым цветом/scale в субтитрах.

    КООРДИНАТЫ: start/end должны быть в clip-relative секундах (0..clip_dur),
    как и Accent из EffectsPlan. Это удобно для пост-генерации: план уже
    в clip-relative, и проще не путаться.

    Time-based матчинг: слово whisper'а считается accent'ом если его интервал
    пересекается с [start,end] (с tolerance 100мс) и нормализованный текст
    совпадает. Если text пустой — матч только по интервалу.
    """
    start: float
    end: float
    word: str = ""
    color: str = "#FFE600"
    scale: int = 110  # %% — увеличение per-word


@dataclass
class SubTemplate:
    name: str
    font: str = "Helvetica Neue"
    size: int = 56
    bold: bool = True
    italic: bool = False
    color: str = "#FFFFFF"
    highlight: str = "#FFE600"
    outline_color: str = "#000000"
    back_color: str = "#000000"     # цвет фонового бокса (BorderStyle=3)
    back_alpha: int = 128            # 0=непрозрачно, 255=прозрачно
    border_style: int = 1            # 1=outline+shadow, 3=opaque box
    outline: int = 4
    shadow: int = 2
    margin_v: int = 280
    words_per_chunk: int = 3
    chunk_advance: int = 1     # 1 = karaoke (сдвиг по слову), N = block (по N слов)
    max_chars_per_line: int = 22  # авто-перевод строки
    use_highlight: bool = True
    min_chunk_duration: float = 0.6  # минимум секунд на чанк (для читаемости)
    highlight_scale: int = 105   # %% (95 = меньше, 105 = чуть крупнее)
    uppercase: bool = False        # ВЕСЬ текст в верхнем регистре (Hormozi)
    pop_in: bool = False           # короткая scale-pulse анимация на новом слове
    accent_color: str = "#FFE600"  # цвет для accent_keywords (override per-keyword)
    accent_scale: int = 115        # scale для accent_keywords
    letter_spacing: int = 0        # ASS \fsp
    # ── читаемость / тайминг ─────────────────────────────────────────
    min_cps: float = 17.0          # max chars-per-second; чанк продлевается если слишком быстрый
    min_word_duration: float = 0.12 # короткие whisper-слова (например, "и", "а") расширяются
    auto_capitalize: bool = True   # капитализировать первое слово чанка после паузы >0.5s
    progressive_fill: bool = False # ASS \k-тег: цветная заливка слева-направо (CapCut karaoke)
    chroma_cycle: tuple[str, ...] = ()  # циклические цвета per-word (Opus ChromaClips)
    # ── имитация скруглённых углов для пузыря (BorderStyle=3) через ASS \blur ──
    # ASS не поддерживает border-radius напрямую. Этот параметр размывает outline,
    # что визуально создаёт мягкие, "круглые" углы pill-фона. 0 = прямые углы.
    back_blur: float = 0.0
    # ── НАСТОЯЩИЕ round-corners через ASS \p1 (Bezier-shape под текстом) ──
    # При pill_bg=True перед каждой репликой рисуется pill-rectangle из ASS draw
    # commands в слое 0, а текст — в слое 1. ASS-нативно, без PNG-overlay.
    # back_color + back_alpha = цвет/прозрачность pill. pill_radius_pct — радиус
    # как % от высоты бокса (50% = идеальный полукруг = "капсула").
    pill_bg: bool = False
    pill_radius_pct: int = 50    # 50 = классическая капсула; 20 = просто скруглённые углы
    pill_padding_x: int = 24     # доп. горизонтальный paddings для текста (px при 1920h)
    pill_padding_y: int = 12     # вертикальный paddings


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
    # ─── pro-шаблоны ─────────────────────────────────────────────────
    "submagic": SubTemplate(
        name="⚡ Submagic (Hormozi)",
        font="Helvetica Neue", size=62, bold=True,
        color="#FFFFFF", highlight="#FFFFFF",
        outline_color="#000000", outline=6, shadow=0,
        margin_v=420, words_per_chunk=3, chunk_advance=1,
        max_chars_per_line=18, use_highlight=False,
        min_chunk_duration=0.3,
        uppercase=True, pop_in=True,
        accent_color="#FFE600", accent_scale=118,
        letter_spacing=2,
    ),
    "captions": SubTemplate(
        name="📦 Captions (Wrapbox)",
        font="Helvetica Neue", size=50, bold=True,
        color="#FFFFFF", highlight="#FFFFFF",
        outline_color="#000000",
        back_color="#000000", back_alpha=80,
        border_style=3,                # opaque box behind text
        outline=14, shadow=0,          # outline тут = padding бокса
        margin_v=380, words_per_chunk=4, chunk_advance=4,
        max_chars_per_line=22, use_highlight=False,
        min_chunk_duration=0.8,
        uppercase=False, pop_in=False,
        accent_color="#FFE600", accent_scale=105,
    ),
    "podcast_pro": SubTemplate(
        name="🎙 Podcast Pro",
        font="Helvetica Neue", size=46, bold=False,
        color="#FFFFFF", highlight="#FFFFFF",
        outline_color="#000000", outline=3, shadow=1,
        margin_v=220, words_per_chunk=5, chunk_advance=5,
        max_chars_per_line=28, use_highlight=False,
        min_chunk_duration=1.2,
        uppercase=False, pop_in=False,
        accent_color="#5BB6FF", accent_scale=104,
    ),
    # ─── pro-шаблоны (доп.) ─────────────────────────────────────────
    "beast": SubTemplate(
        # MrBeast: жёлтые ALL CAPS + красный акцент. Толстая чёрная обводка.
        name="🦁 Beast (MrBeast)",
        font="Helvetica Neue", size=64, bold=True,
        color="#FFE600", highlight="#FFE600",
        outline_color="#000000", outline=7, shadow=2,
        margin_v=400, words_per_chunk=3, chunk_advance=1,
        max_chars_per_line=18, use_highlight=False,
        min_chunk_duration=0.3,
        uppercase=True, pop_in=True,
        accent_color="#FF2E2E", accent_scale=118,
        letter_spacing=2,
    ),
    "karaoke_fill": SubTemplate(
        # CapCut karaoke: progressive fill через \k tag.
        name="🎶 Karaoke Fill (CapCut)",
        font="Helvetica Neue", size=58, bold=True,
        color="#FFFFFF", highlight="#C6FF3D",
        outline_color="#000000", outline=4, shadow=2,
        margin_v=320, words_per_chunk=4, chunk_advance=4,
        max_chars_per_line=24, use_highlight=False,
        min_chunk_duration=0.8,
        uppercase=False, pop_in=False,
        accent_color="#FFE600", accent_scale=108,
        progressive_fill=True,
    ),
    "highlight_box": SubTemplate(
        # Veed: подложка под активным словом (накладывается через \3c+\bord).
        name="🔆 Highlight Box (Veed)",
        font="Helvetica Neue", size=56, bold=True,
        color="#FFFFFF", highlight="#C6FF3D",
        outline_color="#000000", outline=3, shadow=1,
        margin_v=340, words_per_chunk=3, chunk_advance=1,
        max_chars_per_line=22, use_highlight=True,
        min_chunk_duration=0.4,
        uppercase=False, pop_in=False,
        accent_color="#FF6B9D", accent_scale=112,
        highlight_scale=104,
    ),
    "bubble": SubTemplate(
        # Klap: белая КАПСУЛА под каждым словом с настоящими круглыми углами.
        # Рендерится через ASS \p1 Bezier-shape, не через opaque box.
        name="💬 Bubble (Klap)",
        font="Helvetica Neue", size=50, bold=True,
        color="#000000", highlight="#000000",
        outline_color="#000000", back_color="#FFFFFF", back_alpha=0,
        border_style=1, outline=0, shadow=4,        # no opaque box, shadow для drop
        pill_bg=True, pill_radius_pct=50,           # настоящая капсула
        pill_padding_x=28, pill_padding_y=14,
        margin_v=360, words_per_chunk=3, chunk_advance=1,
        max_chars_per_line=20, use_highlight=False,
        min_chunk_duration=0.35,
        uppercase=False, pop_in=True,
        accent_color="#FF2E2E", accent_scale=110,
    ),
    "chroma": SubTemplate(
        # Opus ChromaClips: per-word reveal с цикличными цветами.
        name="🌈 Chroma (Opus)",
        font="Helvetica Neue", size=60, bold=True,
        color="#FFFFFF", highlight="#FFFFFF",
        outline_color="#000000", outline=5, shadow=2,
        margin_v=380, words_per_chunk=2, chunk_advance=1,
        max_chars_per_line=18, use_highlight=False,
        min_chunk_duration=0.3,
        uppercase=True, pop_in=True,
        accent_color="#C6FF3D", accent_scale=115,
        letter_spacing=1,
        chroma_cycle=("#C6FF3D", "#FF6B9D", "#FFE600", "#5BB6FF"),
    ),
}

DEFAULT_TEMPLATE: TemplateName = "block"


# ─────────────────────────── алгоритм генерации ───────────────────────────


def _wrap_words_paired(visible: list[str], formatted: list[str], max_chars: int) -> str:
    """Раскладка слов на 1-2 строки через \\N. Длину строки меряем по `visible`
    (без ASS-кодов), а собираем результат из `formatted` (с подсветкой и пр.)."""
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


def _smooth_words(words: list[Word], min_dur: float) -> list[Word]:
    """Расширяет слишком короткие слова до min_dur, не залезая на следующее.

    Whisper иногда выдаёт ws = we = X для коротких союзов — субтитр мигает
    на 1 кадр. Делаем длительность хотя бы min_dur секунд, ограничивая
    концом по началу следующего слова.
    """
    if not words:
        return words
    out: list[Word] = []
    for i, w in enumerate(words):
        next_start = words[i + 1].start if i + 1 < len(words) else None
        dur = max(w.end - w.start, 0.0)
        if dur < min_dur:
            target_end = w.start + min_dur
            if next_start is not None:
                target_end = min(target_end, next_start)
            new_end = max(w.end, target_end)
        else:
            new_end = w.end
        out.append(Word(w.start, new_end, w.text))
    return out


def _strip_ass_tags(s: str) -> str:
    """Убирает {…} override-блоки и \\N для подсчёта visible-длины."""
    s = re.sub(r"\{[^}]*\}", "", s)
    s = s.replace(r"\N", " ").replace(r"\n", " ")
    return s


def _apply_cps_min_duration(
    visible_text: str, ev_start: float, ev_end: float,
    next_event_start: float | None, min_cps: float, min_chunk: float,
    gap: float = 0.04,
) -> float:
    """Возвращает скорректированный ev_end так, чтобы был CPS-budget на чтение,
    но не залезая на next_event_start (с минимальным gap)."""
    chars = len(_strip_ass_tags(visible_text).strip())
    if chars <= 0:
        return ev_end
    needed = max(min_chunk, chars / max(1.0, min_cps))
    target = ev_start + needed
    if next_event_start is not None:
        target = min(target, next_event_start - gap)
    return max(ev_end, target)


def _smart_caps(words: list[Word], pause_threshold: float = 0.5) -> set[int]:
    """Возвращает множество индексов слов, которые надо капитализировать —
    первое слово клипа и любое после паузы >pause_threshold."""
    caps: set[int] = set()
    if not words:
        return caps
    caps.add(0)
    for i in range(1, len(words)):
        gap = words[i].start - words[i - 1].end
        if gap > pause_threshold:
            caps.add(i)
    return caps


def _match_accent(
    word: Word, accents: list[AccentKeyword],
) -> AccentKeyword | None:
    """Ищет accent-keyword, чей интервал пересекается со словом и текст совпадает.

    Обе стороны — clip-relative (0..clip_dur).
    """
    if not accents:
        return None
    w_norm = _norm_word(word.text)
    for a in accents:
        # пересечение интервалов с допуском 100мс
        if word.end < a.start - 0.1 or word.start > a.end + 0.1:
            continue
        if a.word and _norm_word(a.word) != w_norm:
            continue
        return a
    return None


def _format_word(
    text: str, *, color: str | None = None, scale: int | None = None,
    pop_in: bool = False, bold_off: bool = False,
) -> str:
    """Оборачивает слово в ASS-override. color = "&H00BBGGRR&", scale = %%.

    pop_in добавляет короткую scale-pulse анимацию (0→150мс).
    """
    tags: list[str] = []
    if color is not None:
        tags.append(r"\c" + color.rstrip("&") + "&")
    if scale is not None:
        if pop_in:
            # стартует чуть меньше → пульсирует до scale за 150мс
            base = max(60, scale - 25)
            tags.append(rf"\fscx{base}\fscy{base}")
            tags.append(rf"\t(0,150,\fscx{scale}\fscy{scale})")
        else:
            tags.append(rf"\fscx{scale}\fscy{scale}")
    elif pop_in:
        tags.append(r"\fscx80\fscy80")
        tags.append(r"\t(0,150,\fscx100\fscy100)")
    if bold_off:
        tags.append(r"\b0")
    if not tags:
        return text
    return "{" + "".join(tags) + "}" + text + r"{\r}"


def write_ass(
    segments: list[Segment],
    start: float,
    end: float,
    out: Path,
    target_w: int = 1080,
    target_h: int = 1920,
    template: TemplateName | SubTemplate = DEFAULT_TEMPLATE,
    accent_keywords: list[AccentKeyword] | None = None,
    safe_area: SafeArea = "none",
) -> Path:
    """Генерирует ASS-субтитры по выбранному шаблону.

    accent_keywords — слова из LLM EffectsPlan с эмоциональным акцентом;
    они подсвечиваются индивидуальным цветом/scale поверх обычной стилизации.
    Координаты accent_keywords — в исходном видео, не clip-relative.

    Размер шрифта/обводки/теней автоматически масштабируется под target_h
    чтобы текст оставался читаемым на маленьких разрешениях.
    """
    style = PRESETS[template] if isinstance(template, str) else template
    accents = accent_keywords or []

    # ⭐ ДВЕ разные шкалы:
    # - text_scale: для шрифта/обводки/теней (с боустом для мелких видео)
    # - geom_scale: для margin_v — линейно по высоте, иначе текст уезжает в центр
    if target_h >= 1280:
        text_scale = target_h / 1920
    elif target_h >= 720:
        text_scale = (target_h / 1920) * 1.5
    else:
        text_scale = (target_h / 1920) * 2.2
    geom_scale = target_h / 1920

    actual_size = max(14, int(round(style.size * text_scale)))
    actual_outline = max(1, int(round(style.outline * text_scale)))
    actual_shadow = max(0, int(round(style.shadow * text_scale)))
    actual_margin_v = max(20, int(round(style.margin_v * geom_scale)))
    actual_margin_lr = max(20, int(round(target_w * 0.04)))

    # ⭐ Safe-area: платформенный UI снизу не должен накрывать субтитры.
    # margin_v увеличивается до минимума под платформу (если меньше).
    sa_min_at_1920 = _SAFE_AREA_MIN_MARGIN_V_AT_1920.get(safe_area, 0)
    if sa_min_at_1920 > 0:
        sa_min = int(round(sa_min_at_1920 * geom_scale))
        actual_margin_v = max(actual_margin_v, sa_min)

    # ⭐ Auto-fit ширины: текст не должен вылезать за пределы кадра.
    # Эмпирически средняя ширина символа ≈ font_size * (0.58 bold / 0.50 regular)
    # с учётом UPPERCASE буст и letter_spacing.
    char_w_factor = 0.62 if style.bold else 0.52
    if style.uppercase:
        char_w_factor *= 1.05
    avg_char_w = actual_size * char_w_factor + style.letter_spacing
    # для box-стиля outline съедает горизонтали (padding бокса)
    box_pad = 2 * actual_outline if style.border_style == 3 else 0
    avail_px = max(80, target_w - 2 * actual_margin_lr - box_pad - 10)
    fit_capacity = max(6, int(avail_px / max(1, avg_char_w)))
    effective_max_chars = min(style.max_chars_per_line, fit_capacity)

    primary = _ass_color(style.color)
    outline = _ass_color(style.outline_color)
    back = _ass_color_alpha(style.back_color, style.back_alpha)
    bold_flag = -1 if style.bold else 0
    italic_flag = -1 if style.italic else 0

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {target_w}
PlayResY: {target_h}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.font},{actual_size},{primary},&H000000FF,{outline},{back},{bold_flag},{italic_flag},0,0,100,100,{style.letter_spacing},0,{style.border_style},{actual_outline},{actual_shadow},2,{actual_margin_lr},{actual_margin_lr},{actual_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    words = _gather_words(segments, start, end)
    if not words:
        out.write_text(header, encoding="utf-8")
        return out

    # ⭐ сглаживание слишком коротких слов — иначе субтитр мигает на 1 кадр
    words = _smooth_words(words, style.min_word_duration)

    # Pre-compute accent matches per word (clip-relative)
    accent_for: dict[int, AccentKeyword] = {}
    for idx, w in enumerate(words):
        m = _match_accent(w, accents)
        if m is not None:
            accent_for[idx] = m

    # ⭐ капитализация первого слова после паузы (для не-UPPERCASE стилей)
    caps_idx: set[int] = (
        _smart_caps(words) if (style.auto_capitalize and not style.uppercase) else set()
    )

    highlight_color = _ass_color(style.highlight)
    accent_color_default = _ass_color(style.accent_color)
    # blur-префикс для имитации round corners на box-стилях (ASS не имеет border-radius)
    blur_prefix = (f"{{\\blur{style.back_blur:g}}}" if style.back_blur and style.back_blur > 0 else "")

    # ─── pill background через ASS \p1 — настоящие round corners ───
    pill_color_ass = _ass_color(style.back_color)
    pill_alpha = f"&H{style.back_alpha:02X}&"
    pill_pad_x = max(2, int(round(style.pill_padding_x * text_scale)))
    pill_pad_y = max(2, int(round(style.pill_padding_y * text_scale)))

    def _emit_pill_event(text_with_overrides: str, ev_start: float, ev_end: float) -> str | None:
        """Возвращает Dialogue line для pill-фона под этой репликой, или None."""
        if not style.pill_bg:
            return None
        tw, th = _estimate_text_pixels(text_with_overrides, actual_size)
        box_w = tw + 2 * pill_pad_x
        box_h = th + 2 * pill_pad_y
        radius = max(2, int(round(box_h * style.pill_radius_pct / 100 / 2)))
        shape = _pill_shape_cmd(box_w, box_h, radius)
        # ⭐ shape coords от top-left (0,0). \an7\pos(left, top) → libass рисует
        # shape точно от \pos позиции. Текст использует \an2 (default), bottom-center.
        # Text bottom y = target_h - actual_margin_v.
        # Pill bottom y = text bottom - tiny offset (просвет под текстом убираем).
        text_bottom_y = target_h - actual_margin_v
        pill_top_y = text_bottom_y - box_h
        pill_left_x = (target_w - box_w) // 2
        override = (
            f"{{\\an7\\pos({pill_left_x},{pill_top_y})\\bord0\\shad0\\1c{pill_color_ass}\\1a{pill_alpha}\\p1}}"
            f"{shape}"
            f"{{\\p0}}"
        )
        return f"Dialogue: 0,{_ass_time(ev_start)},{_ass_time(ev_end)},Default,,0,0,0,,{override}"

    def display_text(t: str, idx: int) -> str:
        if style.uppercase:
            return t.upper()
        if idx in caps_idx and t and t[0].islower():
            return t[0].upper() + t[1:]
        return t

    events: list[str] = []

    if style.use_highlight and style.chunk_advance == 1:
        # ── karaoke-режим: окно из words_per_chunk слов, активное подсвечено ──
        n = style.words_per_chunk
        for i, w in enumerate(words):
            win_start = max(0, i - n // 2)
            win_end = min(len(words), win_start + n)
            if win_end - win_start < n:
                win_start = max(0, win_end - n)
            chunk = words[win_start:win_end]

            visible: list[str] = []
            formatted: list[str] = []
            for j, ww in enumerate(chunk):
                actual = win_start + j
                t_disp = display_text(_escape(ww.text), actual)
                visible.append(t_disp)
                acc = accent_for.get(actual)
                if acc is not None:
                    col = _ass_color(acc.color)
                    formatted.append(_format_word(
                        t_disp, color=col, scale=acc.scale, pop_in=style.pop_in,
                    ))
                elif actual == i:
                    formatted.append(_format_word(
                        t_disp, color=highlight_color, scale=style.highlight_scale,
                        pop_in=style.pop_in,
                    ))
                else:
                    formatted.append(t_disp)

            text = _wrap_words_paired(visible, formatted, effective_max_chars)
            ev_start = w.start
            next_start = words[i + 1].start if i + 1 < len(words) else None
            ev_end = next_start if next_start is not None else w.end + 0.3
            # ⭐ CPS: гарантируем что для прочтения хватит времени, не залезая
            # на следующее событие (с min gap 30мс).
            ev_end = _apply_cps_min_duration(
                text, ev_start, ev_end, next_start,
                min_cps=style.min_cps, min_chunk=style.min_chunk_duration / 3,
            )
            pill = _emit_pill_event(text, ev_start, ev_end)
            if pill: events.append(pill)
            events.append(f"Dialogue: 1,{_ass_time(ev_start)},{_ass_time(ev_end)},Default,,0,0,0,,{blur_prefix}{text}")
    elif style.chunk_advance == 1:
        # ── per-word reveal без highlight активного слова (Submagic-style) ──
        # Окно из words_per_chunk, акценты подсвечены, остальные — обычным цветом.
        n = style.words_per_chunk
        for i, w in enumerate(words):
            win_start = max(0, i - n // 2)
            win_end = min(len(words), win_start + n)
            if win_end - win_start < n:
                win_start = max(0, win_end - n)
            chunk = words[win_start:win_end]

            visible: list[str] = []
            formatted: list[str] = []
            for j, ww in enumerate(chunk):
                actual = win_start + j
                t_disp = display_text(_escape(ww.text), actual)
                visible.append(t_disp)
                acc = accent_for.get(actual)
                # pop_in применяется только к слову, которое только что появилось
                # (актуальному i-му индексу)
                pop = style.pop_in and actual == i
                if acc is not None:
                    col = _ass_color(acc.color or style.accent_color)
                    sc = acc.scale or style.accent_scale
                    formatted.append(_format_word(
                        t_disp, color=col, scale=sc, pop_in=pop,
                    ))
                elif actual == i and style.chroma_cycle:
                    # ChromaClips: активное слово получает цвет из цикла
                    cyc = style.chroma_cycle
                    col = _ass_color(cyc[actual % len(cyc)])
                    formatted.append(_format_word(
                        t_disp, color=col, scale=style.accent_scale, pop_in=pop,
                    ))
                elif pop:
                    formatted.append(_format_word(t_disp, pop_in=True))
                else:
                    formatted.append(t_disp)

            text = _wrap_words_paired(visible, formatted, effective_max_chars)
            ev_start = w.start
            next_start = words[i + 1].start if i + 1 < len(words) else None
            ev_end = next_start if next_start is not None else w.end + 0.3
            ev_end = _apply_cps_min_duration(
                text, ev_start, ev_end, next_start,
                min_cps=style.min_cps, min_chunk=style.min_chunk_duration / 3,
            )
            pill = _emit_pill_event(text, ev_start, ev_end)
            if pill: events.append(pill)
            events.append(f"Dialogue: 1,{_ass_time(ev_start)},{_ass_time(ev_end)},Default,,0,0,0,,{blur_prefix}{text}")
    elif style.progressive_fill:
        # ── CapCut karaoke fill: один Dialogue на чанк, \k-теги на каждом слове ──
        # PrimaryColour = highlight (filled), SecondaryColour = base color (unfilled).
        # \k<cs> — слово остаётся в secondary <cs> сантисек, потом → primary.
        adv = max(1, style.chunk_advance)
        primary_fill = _ass_color(style.highlight)
        secondary_fill = _ass_color(style.color)
        i = 0
        while i < len(words):
            chunk = words[i:i + style.words_per_chunk]
            if not chunk:
                break
            ev_start = chunk[0].start
            next_i = i + adv
            next_start = words[next_i].start if next_i < len(words) else None
            ev_end = next_start if next_start is not None else chunk[-1].end + 0.3

            visible = [display_text(_escape(w.text), i + k) for k, w in enumerate(chunk)]
            # \k-длительности per-word в центисекундах
            ks: list[int] = []
            for k, ww in enumerate(chunk):
                # длительность слова в этом событии (clipped к ev_end если нужно)
                w_end_clipped = min(ww.end, ev_end)
                dur_s = max(0.0, w_end_clipped - ww.start)
                ks.append(max(1, int(round(dur_s * 100))))
            formatted = []
            for k, vis in enumerate(visible):
                acc = accent_for.get(i + k)
                if acc is not None:
                    col = _ass_color(acc.color or style.accent_color)
                    formatted.append(
                        r"{\k" + str(ks[k]) + r"\1c" + col.rstrip("&") + r"&}" + vis + r"{\1c" + primary_fill.rstrip("&") + r"&}"
                    )
                else:
                    formatted.append(r"{\k" + str(ks[k]) + r"}" + vis)
            # стартовый override: задаём primary/secondary
            prefix = (
                r"{\1c" + primary_fill.rstrip("&") + r"&\2c" + secondary_fill.rstrip("&") + r"&}"
            )
            body = _wrap_words_paired(visible, formatted, effective_max_chars)
            text = prefix + body
            ev_end = _apply_cps_min_duration(
                text, ev_start, ev_end, next_start,
                min_cps=style.min_cps, min_chunk=style.min_chunk_duration,
            )
            pill = _emit_pill_event(text, ev_start, ev_end)
            if pill: events.append(pill)
            events.append(f"Dialogue: 1,{_ass_time(ev_start)},{_ass_time(ev_end)},Default,,0,0,0,,{blur_prefix}{text}")
            i += adv
    else:
        # ── block-режим: чанки по chunk_advance слов появляются целиком ──
        adv = max(1, style.chunk_advance)
        i = 0
        while i < len(words):
            chunk = words[i:i + style.words_per_chunk]
            if not chunk:
                break
            ev_start = chunk[0].start
            next_i = i + adv
            next_start = words[next_i].start if next_i < len(words) else None
            ev_end = next_start if next_start is not None else chunk[-1].end + 0.3

            visible = [display_text(_escape(w.text), i + k) for k, w in enumerate(chunk)]
            formatted: list[str] = []
            for k, ww in enumerate(chunk):
                t_disp = visible[k]
                acc = accent_for.get(i + k)
                if acc is not None:
                    col = _ass_color(acc.color or style.accent_color)
                    sc = acc.scale or style.accent_scale
                    formatted.append(_format_word(t_disp, color=col, scale=sc))
                elif style.use_highlight and k == 0:
                    formatted.append(_format_word(t_disp, color=_ass_color(style.highlight)))
                else:
                    formatted.append(t_disp)
            text = _wrap_words_paired(visible, formatted, effective_max_chars)
            ev_end = _apply_cps_min_duration(
                text, ev_start, ev_end, next_start,
                min_cps=style.min_cps, min_chunk=style.min_chunk_duration,
            )
            pill = _emit_pill_event(text, ev_start, ev_end)
            if pill: events.append(pill)
            events.append(f"Dialogue: 1,{_ass_time(ev_start)},{_ass_time(ev_end)},Default,,0,0,0,,{blur_prefix}{text}")
            i += adv

    out.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return out
