"""F1: Auto-zoom on emphasis.

Каждый accent → плавный bell-curve пульс zoom'а. Кадр увеличивается на N% и
плавно возвращается. Используем scale с per-frame eval + crop центра.

Формула:
    zoom(t) = 1 + sum_for_each_accent[ amp * exp(-((t - center) / sigma)^2) ]

Это гауссиан, который даёт плавный пик в центре акцента и быстрый спад. Sigma
выбирается так, чтобы пик был ~80% длительности accent'а.
"""
from __future__ import annotations

from .types import Accent


MAX_ZOOM_DEFAULT = 0.10  # +10% максимум
MIN_SIGMA = 0.25         # минимальная "ширина" пика, сек


def build_zoom_filter(
    accents: list[Accent], target_w: int, target_h: int,
    *, max_zoom: float = MAX_ZOOM_DEFAULT,
) -> str | None:
    """Строит ffmpeg-фильтр для micro-zoom.

    Возвращает строку фильтра вида "scale=...,crop=W:H" или None если acentов нет.
    Применяется к видеопотоку (не к аудио).
    """
    if not accents:
        return None

    pulses = []
    for a in accents:
        center = (a.start + a.end) / 2
        # sigma ~ половина длительности, но не меньше MIN_SIGMA
        dur = max(0.3, a.end - a.start)
        sigma = max(MIN_SIGMA, dur / 2.2)
        amp = max_zoom * max(0.3, min(1.0, a.strength))
        pulses.append(f"{amp:.4f}*exp(-((t-{center:.2f})/{sigma:.3f})^2)")

    zoom_expr = "1+" + "+".join(pulses)

    # scale per-frame upsizes картинку, crop вырезает центр target_w x target_h.
    # eval=frame заставляет scale пересчитывать каждый кадр (без него — один раз).
    # flags=bicubic — гладкая интерполяция. Bilinear артефактит на резких лицах.
    return (
        f"scale=w='iw*({zoom_expr})':h='ih*({zoom_expr})':eval=frame:flags=bicubic,"
        f"crop={target_w}:{target_h}:(in_w-{target_w})/2:(in_h-{target_h})/2"
    )
