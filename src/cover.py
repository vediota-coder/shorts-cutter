"""Cover Designer: hook-overlay поверх postera.

Берёт уже сгенерированный thumbnail (frame из master с уже зашитым брендом)
и накладывает крупный текст-крючок (hook) на цветной подложке. Используется
как poster для YouTube/IG/VK при публикации и как превью в UI.

Использует ffmpeg drawtext + _escape_drawtext из branding.py — никакой своей
рисовалки. Шрифт/цвета берутся из BrandTemplate.cover_*.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from .branding import BrandTemplate, _escape_drawtext


def _wrap_text(text: str, max_chars_per_line: int) -> list[str]:
    """Простой word-wrap по словам с лимитом символов на строку.

    Возвращает список строк. Не добавляет hyphenation — длинное слово
    останется в своей строке как есть.
    """
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        if len(cur) + 1 + len(w) <= max_chars_per_line:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def render_cover(
    thumbnail_path: Path,
    hook_text: str,
    brand: BrandTemplate,
    out_path: Path,
    *,
    target_w: int = 1080,
    target_h: int = 1920,
    text_position: str = "top",  # "top" | "center" | "bottom"
) -> Path:
    """Накладывает hook-текст на постер. Возвращает out_path.

    - thumbnail_path: PNG из extract_thumbnails (любой размер, будет ресайз).
    - hook_text: 2-8 слов, авто-перенос на 2-3 строки.
    - brand: для font_family + accent/text colors.
    - target_w/target_h: размер итогового PNG (1080×1920 для Shorts).
    """
    if not thumbnail_path.exists():
        raise FileNotFoundError(f"thumbnail не найден: {thumbnail_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    text = (hook_text or "").strip().upper()
    if not text:
        # без текста — просто ресайзим thumbnail
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(thumbnail_path),
             "-vf", f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
                    f"crop={target_w}:{target_h}",
             str(out_path)],
            check=True, capture_output=True,
        )
        return out_path

    font = brand.cover_font_family or (brand.bottom_strip.font_family if brand.bottom_strip else None) \
        or "Helvetica Neue"
    accent = brand.cover_accent_color.lstrip("#")
    text_color = brand.cover_text_color.lstrip("#")

    # CHAR_W_RATIO — эмпирический множитель ширины глифа от font_size для
    # широких UPPERCASE шрифтов с кириллицей. 0.62 безопасно для большинства.
    CHAR_W_RATIO = 0.62
    side_margin = int(target_w * 0.05)
    block_w = target_w - side_margin * 2
    block_x = side_margin
    pad_x = int(target_w * 0.025)
    inner_w = block_w - pad_x * 2

    # auto-fit: подбираем максимальный fontsize, при котором самая длинная строка
    # помещается в inner_w. Стартуем с 9% высоты постера.
    base_font = max(48, int(target_h * 0.085))
    while base_font > 32:
        max_chars = max(6, int(inner_w / (base_font * CHAR_W_RATIO)))
        lines = _wrap_text(text, max_chars)
        longest = max((len(l) for l in lines), default=0)
        if longest * base_font * CHAR_W_RATIO <= inner_w and len(lines) <= 4:
            break
        base_font = int(base_font * 0.9)
    n_lines = len(lines)

    line_h = int(base_font * 1.15)
    pad_y = int(base_font * 0.35)
    block_h = n_lines * line_h + pad_y * 2

    # позиционирование блока
    v_margin = int(target_h * 0.05)
    if text_position == "top":
        block_top = v_margin
    elif text_position == "bottom":
        block_top = target_h - block_h - v_margin
    else:
        block_top = (target_h - block_h) // 2

    filters: list[str] = []
    # ресайз+crop постера до target_w×target_h
    filters.append(
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
        f"crop={target_w}:{target_h}"
    )
    # одна общая плашка под весь текстовый блок — без gap'ов между строками
    filters.append(
        f"drawbox=x={block_x}:y={block_top}:"
        f"w={block_w}:h={block_h}:"
        f"color=0x{accent}@1.0:t=fill"
    )
    # drawtext по строкам — центрируется в блоке
    text_top = block_top + pad_y
    for i, line in enumerate(lines):
        y = text_top + i * line_h
        filters.append(
            f"drawtext=text='{_escape_drawtext(line)}':"
            f"fontcolor=0x{text_color}:"
            f"fontsize={base_font}:"
            f"x=(w-text_w)/2:y={y}:"
            f"font='{font}':borderw=0"
        )

    vf = ",".join(filters)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(thumbnail_path),
         "-vf", vf, "-frames:v", "1",
         str(out_path)],
        check=True, capture_output=True,
    )
    return out_path
