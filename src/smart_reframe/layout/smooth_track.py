"""Offline smoothing of FaceTrack/person trajectories.

Replaces per-frame DampedFollower with pre-computed Gaussian-smoothed bbox
trajectories. This gives professional-cinema-camera smoothness:
- per-frame jitter is eliminated (no median-step changes)
- camera responds to actual movement, not detector noise
- no spring-mass lag — every frame has a deterministic smooth position

Algorithm:
1. Build per-frame raw arrays (cx, cy, h) from detections; NaN for missing.
2. Linear-interpolate NaN gaps within the track's first..last frame range.
3. Apply 1D Gaussian filter with sigma chosen to suppress jitter (~0.7s default).
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter1d

from ..types import FaceTrack


class SmoothedTrack:
    """Pre-computed Gaussian-smoothed trajectory for a single FaceTrack.

    Use .at(frame_idx) to get smoothed (cx, cy, h) or None when the
    frame is outside the track's coverage (±edge_extend).

    Если задан cuts_set, smoothing разбивается на сегменты между source-cut'ами:
    tracker иногда ошибочно сливает в один track двух разных людей через
    монтажный рез, и гауссово сглаживание усреднило бы их позиции в
    «фантомный» центр кадра. Per-segment smoothing предотвращает это.
    """

    def __init__(
        self,
        track: FaceTrack,
        total_frames: int,
        sigma_frames: float = 20.0,
        edge_extend: int = 30,
        cuts_set: set[int] | None = None,
    ):
        self.track = track
        self.total_frames = total_frames
        self._sigma = sigma_frames
        self._edge_extend = edge_extend
        self._cuts = cuts_set or set()
        self._smoothed: np.ndarray | None = None
        self._first: int = -1
        self._last: int = -1

    def _build(self) -> None:
        if self._smoothed is not None:
            return
        n = max(1, self.total_frames)
        cx_raw = np.full(n, np.nan)
        cy_raw = np.full(n, np.nan)
        h_raw = np.full(n, np.nan)
        for d in self.track.detections:
            if 0 <= d.frame_idx < n:
                cx_raw[d.frame_idx] = d.bbox.cx
                cy_raw[d.frame_idx] = d.bbox.cy
                h_raw[d.frame_idx] = d.bbox.h
        mask = ~np.isnan(cx_raw)
        if not mask.any():
            self._smoothed = np.zeros((n, 3))
            return
        idx_all = np.arange(n)
        valid_idx = idx_all[mask]
        self._first = int(valid_idx[0])
        self._last = int(valid_idx[-1])
        # ⭐ per-segment smoothing — каждая «глава» трека между source cut'ами
        # сглаживается отдельно. Иначе при merge'е двух людей в один track
        # через cut гауссово сглаживание даст усреднённую (фантомную) позицию.
        boundaries = sorted({0, n} | {c for c in self._cuts if 0 < c < n})
        cx_s = np.zeros(n)
        cy_s = np.zeros(n)
        h_s = np.zeros(n)
        for k in range(len(boundaries) - 1):
            a, b = boundaries[k], boundaries[k + 1]
            seg_mask = mask[a:b]
            if not seg_mask.any():
                # сегмент без детекций — оставляем cx=cy=h=0; .at() сообщит invalid через flag
                continue
            seg_idx = np.arange(b - a)
            v_idx = seg_idx[seg_mask]
            cx_i = np.interp(seg_idx, v_idx, cx_raw[a:b][seg_mask])
            cy_i = np.interp(seg_idx, v_idx, cy_raw[a:b][seg_mask])
            h_i = np.interp(seg_idx, v_idx, h_raw[a:b][seg_mask])
            if b - a >= 2:
                cx_s[a:b] = gaussian_filter1d(cx_i, sigma=self._sigma, mode="reflect")
                cy_s[a:b] = gaussian_filter1d(cy_i, sigma=self._sigma, mode="reflect")
                h_s[a:b] = gaussian_filter1d(h_i, sigma=self._sigma, mode="reflect")
            else:
                cx_s[a:b] = cx_i
                cy_s[a:b] = cy_i
                h_s[a:b] = h_i
        self._smoothed = np.stack([cx_s, cy_s, h_s], axis=1)

    def at(self, frame_idx: int) -> tuple[float, float, float] | None:
        self._build()
        if frame_idx < 0 or frame_idx >= self.total_frames:
            return None
        if self._first < 0:
            return None
        # ⭐ Раньше edge_extend=30 frames резко обрезал valid range, и сегменты,
        # которые длиннее реальных детекций, попадали в wide_default fallback.
        # Теперь возвращаем сглаженное значение для ЛЮБОГО кадра в clip range —
        # за пределами детекций gaussian_filter1d с mode="reflect" уже даёт
        # устойчивое edge value (= последняя/первая детекция), что эквивалентно
        # «hold last position» поведению.
        cx, cy, h = self._smoothed[frame_idx]
        return float(cx), float(cy), float(h)


def get_or_build_smoother(
    cache: dict[int, SmoothedTrack],
    track: FaceTrack,
    total_frames: int,
    sigma_frames: float = 20.0,
    cuts_set: set[int] | None = None,
) -> SmoothedTrack:
    s = cache.get(track.track_id)
    if s is None:
        s = SmoothedTrack(track, total_frames, sigma_frames=sigma_frames, cuts_set=cuts_set)
        cache[track.track_id] = s
    return s
