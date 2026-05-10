"""Детекция склеек (cuts) — резких смен кадра.

Алгоритм: гистограммная разница между соседними кадрами. Если diff > threshold —
это cut. Используется чтобы:
1. Сбрасывать EMA-сглаживание в renderer'е (иначе кроп «уползает» при смене ракурса)
2. Не сшивать face track'и через cut (новый ракурс — новый track для того же человека)
3. В scene classifier: cut = принудительная граница сегмента
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np


def detect_cuts(
    video_path: Path,
    sample_every: int = 1,
    diff_threshold: float = 0.4,   # 0..1, больше = меньше cut'ов
    on_progress: Optional[Callable[[float, str], None]] = None,
    time_ranges: Optional[list[tuple[float, float]]] = None,
) -> list[int]:
    """Возвращает список frame_idx где обнаружен cut (новый кадр сильно отличается).

    time_ranges — если задано, гистограммы считаются только для кадров в этих
    диапазонах (секунды). prev_hist сбрасывается при выходе из range, чтобы
    не получить ложный cut на стыке двух раздельных интервалов.
    """
    cap = cv2.VideoCapture(str(video_path))
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    frame_ranges = (
        [(int(s * fps), int(e * fps)) for s, e in time_ranges]
        if time_ranges else None
    )

    cuts: list[int] = []
    prev_hist: Optional[np.ndarray] = None
    in_range_prev = True
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        in_range = (
            frame_ranges is None
            or any(s <= idx <= e for s, e in frame_ranges)
        )
        if not in_range:
            if in_range_prev:
                # вышли из range — забываем предыдущую гистограмму
                prev_hist = None
            in_range_prev = False
            idx += 1
            continue
        in_range_prev = True
        if idx % sample_every == 0:
            small = cv2.resize(frame, (160, 90))
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
            cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
            if prev_hist is not None:
                d = 1.0 - cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                if d > diff_threshold:
                    cuts.append(idx)
            prev_hist = hist
        idx += 1
        if on_progress and n_frames > 0 and idx % 240 == 0:
            on_progress(min(99.0, idx / n_frames * 100), f"cuts: {idx}/{n_frames}, найдено {len(cuts)}")

    cap.release()
    return cuts
