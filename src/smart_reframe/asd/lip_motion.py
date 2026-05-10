"""Lip-motion активный спикер: эвристика на основе межкадровой разницы губ.

Идея:
- Для каждого FaceTrack берём область рта (нижняя 1/3 bbox лица).
- В каждом кадре сэмплируем интенсивность пикселей, считаем разницу с предыдущим
  кадром этого трека → «энергия движения губ».
- В окне 0.5с складываем энергию → даёт оценку «насколько активны губы».
- Активный спикер = трек с максимальной энергией в данном кадре.

Точность: 70-85% на моноспикере и 2-3 чел в кадре с фронтальным ракурсом.
Не работает: профиль, маленькое/далёкое лицо, перекрытие рта рукой.
В таких случаях откатываемся на Light-ASD (ML-модель).
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from ..types import BBox, FaceTrack


def _mouth_roi(frame: np.ndarray, bbox: BBox) -> np.ndarray | None:
    """Вытаскиваем нижнюю треть лица (область рта)."""
    h, w = frame.shape[:2]
    x = int(max(0, bbox.x))
    y = int(max(0, bbox.y + bbox.h * 0.55))   # начинаем чуть ниже носа
    x2 = int(min(w, bbox.x2))
    y2 = int(min(h, bbox.y2))
    if x2 <= x or y2 <= y:
        return None
    crop = frame[y:y2, x:x2]
    if crop.size == 0:
        return None
    # стандартизуем размер чтобы трекать движение независимо от масштаба
    return cv2.resize(crop, (64, 32), interpolation=cv2.INTER_AREA)


def compute_lip_motion(
    video_path: Path,
    tracks: list[FaceTrack],
    sample_every: int = 2,
) -> dict[int, dict[int, float]]:
    """Возвращает {track_id: {frame_idx: motion_energy}}.

    motion_energy ∈ [0, 1] — нормализованная межкадровая разница пикселей рта.
    """
    energy: dict[int, dict[int, float]] = defaultdict(dict)
    prev_roi: dict[int, np.ndarray] = {}

    # индекс детекций по кадру для быстрого доступа
    by_frame: dict[int, list[tuple[int, BBox]]] = defaultdict(list)
    for t in tracks:
        for d in t.detections:
            by_frame[d.frame_idx].append((t.track_id, d.bbox))

    cap = cv2.VideoCapture(str(video_path))
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx in by_frame:
            for tid, bbox in by_frame[idx]:
                roi = _mouth_roi(frame, bbox)
                if roi is None:
                    continue
                gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).astype(np.int16)
                if tid in prev_roi:
                    diff = np.abs(gray - prev_roi[tid]).mean()
                    # нормализуем: 30 единиц разницы = «активная речь»
                    energy[tid][idx] = float(min(1.0, diff / 30.0))
                else:
                    energy[tid][idx] = 0.0
                prev_roi[tid] = gray
        idx += 1
    cap.release()
    return dict(energy)


def active_speaker_per_frame(
    energy: dict[int, dict[int, float]],
    fps: float,
    window_sec: float = 0.75,   # 0.5→0.75 — стабильнее на коротких паузах (вдохи, мычание)
) -> dict[int, int]:
    """Возвращает {frame_idx: track_id_активного_спикера}.

    На каждом кадре сравниваем суммарную энергию треков в окне ±window_sec.
    Если у всех нулевое движение — возвращаем -1 (никто не говорит).
    """
    if not energy:
        return {}
    win = int(window_sec * fps)
    all_frames = sorted({f for d in energy.values() for f in d.keys()})
    out: dict[int, int] = {}

    for f in all_frames:
        best_tid = -1
        best_e = 0.0
        for tid, frames_map in energy.items():
            local = sum(
                v for fr, v in frames_map.items()
                if abs(fr - f) <= win
            )
            if local > best_e:
                best_e = local
                best_tid = tid
        # порог: ниже него считаем «никто не говорит»
        if best_e > 0.5:
            out[f] = best_tid
        else:
            out[f] = -1
    return out
