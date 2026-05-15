"""Web-side стилизация субтитров, выведенная из того же `SubTemplate`,
что используется в `write_ass`.

Цель: WYSIWYG-превью в браузере, которое визуально совпадает с реальным
ASS-burned видео. Раньше превью описывалось хардкоженным CSS в styles.css —
оно расходилось с burn'ом и быстро устаревало при правках шаблонов.

Эндпоинт `GET /subtitle-templates/{key}/preview-style?target_h=1920` возвращает
JSON-структуру, описанную в `template_to_web_style`. Web-компонент `SubtitlePreview`
рендерит span/div с inline styles из этого JSON.

Все размеры — в пикселях для указанного `target_h` (по умолч. 1920). В чипах
селектора потребитель делает CSS transform: scale(...) к высоте чипа.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .subtitles import PRESETS, SubTemplate


def _hex_to_rgba(hex_color: str, alpha255: int = 0) -> str:
    """#RRGGBB + ASS-style alpha (0=opaque, 255=transparent) → CSS rgba()."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    a = max(0.0, min(1.0, 1.0 - alpha255 / 255.0))
    return f"rgba({r}, {g}, {b}, {a:.3f})"


def _outline_text_shadow(color: str, width: int) -> str:
    """Эмуляция ASS outline через CSS text-shadow stack — кольцо вокруг текста.

    8 направлений × `width` пикселей дают сплошной outline без webkit-text-stroke
    (который не поддерживается одновременно с цветной заливкой кириллицы в Safari).
    """
    if width <= 0:
        return ""
    parts: list[str] = []
    # bigger widths need denser stack — one shadow per pixel step
    steps = max(1, width)
    for s in range(1, steps + 1):
        for dx, dy in (
            (-s, -s), (0, -s), (s, -s),
            (-s,  0),          (s,  0),
            (-s,  s), (0,  s), (s,  s),
        ):
            parts.append(f"{dx}px {dy}px 0 {color}")
    return ", ".join(parts)


def _drop_shadow(color: str, offset: int, blur: int = 0) -> str:
    if offset <= 0 and blur <= 0:
        return ""
    return f"{offset}px {offset}px {blur}px {color}"


def _scale_for_target(target_h: int) -> tuple[float, float]:
    """Те же формулы, что в `write_ass` — нельзя расходиться, иначе превью != burn."""
    if target_h >= 1280:
        text_scale = target_h / 1920
    elif target_h >= 720:
        text_scale = (target_h / 1920) * 1.5
    else:
        text_scale = (target_h / 1920) * 2.2
    geom_scale = target_h / 1920
    return text_scale, geom_scale


def template_to_web_style(template: SubTemplate, target_h: int = 1920) -> dict[str, Any]:
    """Возвращает CSS-ready JSON-описание стиля субтитра для target_h.

    Web-компонент применяет это inline-стилями к span'у. Размеры — в реальных
    пикселях того разрешения, в которое будет рендериться видео; превью-чип
    масштабирует через `transform: scale(chip_h / target_h)`.
    """
    text_scale, geom_scale = _scale_for_target(target_h)
    size_px = max(14, int(round(template.size * text_scale)))
    outline_px = max(1, int(round(template.outline * text_scale))) if template.outline else 0
    shadow_px = max(0, int(round(template.shadow * text_scale))) if template.shadow else 0
    margin_v_px = max(20, int(round(template.margin_v * geom_scale)))
    letter_spacing_px = int(round(template.letter_spacing * text_scale)) if template.letter_spacing else 0
    pill_pad_x_px = int(round(template.pill_padding_x * text_scale)) if template.pill_bg else 0
    pill_pad_y_px = int(round(template.pill_padding_y * text_scale)) if template.pill_bg else 0

    # ── background box (ASS BorderStyle=3) ──
    background: dict[str, Any] | None = None
    if template.border_style == 3 and not template.pill_bg:
        # opaque box: outline в этом режиме = padding бокса
        box_pad = max(4, int(round(template.outline * text_scale)))
        background = {
            "color": _hex_to_rgba(template.back_color, template.back_alpha),
            "paddingX": box_pad,
            "paddingY": max(2, box_pad // 2),
            "borderRadius": max(0, int(round(template.back_blur * text_scale))) if template.back_blur else 0,
        }
    elif template.pill_bg:
        # настоящая капсула (border-radius=999px при pill_radius_pct=50)
        # ASS pill_radius_pct = % от высоты бокса; >40 → "капсула"
        radius = 9999 if template.pill_radius_pct >= 40 else int(round(size_px * template.pill_radius_pct / 100))
        background = {
            "color": _hex_to_rgba(template.back_color, template.back_alpha),
            "paddingX": pill_pad_x_px,
            "paddingY": pill_pad_y_px,
            "borderRadius": radius,
        }

    # ── outline + shadow → CSS text-shadow stack ──
    text_shadow_parts: list[str] = []
    if outline_px > 0 and template.border_style != 3:
        ts = _outline_text_shadow(template.outline_color, outline_px)
        if ts:
            text_shadow_parts.append(ts)
    if shadow_px > 0:
        # ASS shadow color = outline_color (по умолчанию) — даём drop с opacity 0.6
        drop_color = "rgba(0,0,0,0.55)"
        text_shadow_parts.append(_drop_shadow(drop_color, shadow_px, max(2, shadow_px)))

    return {
        "key": template.name,  # пользовательское имя стиля (не key)
        "fontFamily": template.font,
        "fontSize": size_px,
        "fontWeight": 700 if template.bold else 400,
        "fontStyle": "italic" if template.italic else "normal",
        "color": template.color,
        "letterSpacing": letter_spacing_px,
        "uppercase": template.uppercase,
        "lineHeight": 1.18,
        "marginV": margin_v_px,
        "marginLR": max(20, int(round(target_h * 9 / 16 * 0.04))),
        "outline": {
            "color": template.outline_color,
            "width": outline_px,
        },
        "shadow": {
            "color": "rgba(0,0,0,0.55)",
            "offset": shadow_px,
            "blur": max(2, shadow_px) if shadow_px else 0,
        },
        "textShadow": ", ".join([p for p in text_shadow_parts if p]),
        "background": background,
        "highlight": {
            "color": template.highlight,
            "scale": template.highlight_scale,
            "use": template.use_highlight,
        },
        "accent": {
            "color": template.accent_color,
            "scale": template.accent_scale,
        },
        "popIn": template.pop_in,
        "progressiveFill": template.progressive_fill,
        "chromaCycle": list(template.chroma_cycle) if template.chroma_cycle else [],
        "wordsPerChunk": template.words_per_chunk,
        "chunkAdvance": template.chunk_advance,
        "maxCharsPerLine": template.max_chars_per_line,
        "minChunkDuration": template.min_chunk_duration,
        "minWordDuration": template.min_word_duration,
        "minCps": template.min_cps,
        "autoCapitalize": template.auto_capitalize,
        # геометрия канваса для превью — потребитель использует чтобы вычислить scale
        "canvas": {
            "targetH": target_h,
            "targetW": int(round(target_h * 9 / 16)),
        },
        # сырой preset для отладки
        "preset": asdict(template),
    }


def template_to_web_style_by_name(name: str, target_h: int = 1920) -> dict[str, Any]:
    if name not in PRESETS:
        raise KeyError(name)
    return template_to_web_style(PRESETS[name], target_h=target_h)
