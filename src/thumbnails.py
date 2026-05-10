"""Auto-thumbnails: вытаскивает топ-3 кадра из клипа по качеству.

Метрики:
- резкость (Laplacian variance)
- яркость (mean L)
- наличие лица (mediapipe)
- центрированность лица
- улыбка (опционально, требует доп. модель)

Топ-3 по композитному score сохраняются как PNG.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    FaceDetector,
    FaceDetectorOptions,
    RunningMode,
)

from .smart_reframe.detect.faces import _ensure_model as _ensure_face_model


def _sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _brightness(frame: np.ndarray) -> float:
    return float(np.mean(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)[..., 2])) / 255.0


def _score_frame(
    frame: np.ndarray, face_count: int, face_centered: bool,
) -> float:
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    sharpness = min(1.0, _sharpness(gray) / 500.0)  # ~normalized
    brightness = _brightness(frame)
    bright_score = 1.0 - abs(brightness - 0.55) * 2.0  # лучше всего 0.55
    bright_score = max(0.0, bright_score)
    face_score = (1.0 if face_count == 1 else 0.6 if face_count == 2 else 0.3)
    if face_count == 0:
        face_score = 0.4  # не наказываем сильно — может быть фул-screen контент
    centered = 1.0 if face_centered else 0.7
    return 0.40 * sharpness + 0.20 * bright_score + 0.25 * face_score + 0.15 * centered


def extract_thumbnails(
    video_path: Path,
    out_dir: Path,
    n: int = 3,
    sample_every_sec: float = 0.5,
    skip_first_sec: float = 0.5,
    skip_last_sec: float = 0.5,
) -> list[Path]:
    """Возвращает пути к N лучшим кадрам, сохранённым как PNG."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = n_frames / fps if fps > 0 else 0
    if duration <= 0:
        cap.release()
        return []

    skip_start_f = int(skip_first_sec * fps)
    skip_end_f = max(0, n_frames - int(skip_last_sec * fps))
    step_f = max(1, int(sample_every_sec * fps))

    model_path = _ensure_face_model()
    detector_opts = FaceDetectorOptions(
        base_options=BaseOptions(model_asset_path=str(model_path)),
        running_mode=RunningMode.VIDEO,
        min_detection_confidence=0.5,
    )

    candidates: list[tuple[float, int, np.ndarray]] = []
    with FaceDetector.create_from_options(detector_opts) as det:
        for fi in range(skip_start_f, skip_end_f, step_f):
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ok, frame = cap.read()
            if not ok:
                continue
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            ts_ms = int(fi / fps * 1000)
            res = det.detect_for_video(mp_image, ts_ms)
            face_count = len(res.detections or [])
            face_centered = False
            if res.detections:
                bb = res.detections[0].bounding_box
                cx = bb.origin_x + bb.width / 2
                center_x = frame.shape[1] / 2
                face_centered = abs(cx - center_x) < frame.shape[1] * 0.2
            score = _score_frame(frame, face_count, face_centered)
            candidates.append((score, fi, frame))

    cap.release()
    if not candidates:
        return []
    # сортируем по score, убираем близкие по времени дубликаты
    candidates.sort(key=lambda x: -x[0])
    picked: list[tuple[float, int, np.ndarray]] = []
    for c in candidates:
        if any(abs(c[1] - p[1]) < int(2.0 * fps) for p in picked):
            continue
        picked.append(c)
        if len(picked) >= n:
            break

    out_paths: list[Path] = []
    for i, (score, fi, frame) in enumerate(picked, 1):
        p = out_dir / f"thumbnail_{i:02d}.png"
        cv2.imwrite(str(p), frame)
        out_paths.append(p)
    return out_paths
