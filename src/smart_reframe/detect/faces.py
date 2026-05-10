"""Детекция всех лиц в кадре через mediapipe Tasks API + tracking по IoU."""
from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Callable, Optional

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    FaceDetector,
    FaceDetectorOptions,
    RunningMode,
)

from ..track.tracker import IoUTracker, filter_short_tracks
from ..types import BBox, FaceDetection, FaceTrack, VideoMeta


ProgressFn = Callable[[float, str], None]

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
MODEL_PATH = Path.home() / ".cache" / "mediapipe" / "blaze_face_short_range.tflite"


def _ensure_model() -> Path:
    if MODEL_PATH.exists() and MODEL_PATH.stat().st_size > 100_000:
        return MODEL_PATH
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    return MODEL_PATH


def detect_faces(
    video_path: Path,
    sample_every: int = 2,
    min_confidence: float = 0.5,
    on_progress: Optional[ProgressFn] = None,
    time_ranges: Optional[list[tuple[float, float]]] = None,
) -> tuple[list[FaceTrack], VideoMeta]:
    """Прогон по видео с детекцией всех лиц + IoU-tracking → список FaceTrack.

    Возвращает только треки длиной ≥ 5 кадров (фильтр шума).
    time_ranges — если задано, MediaPipe inference только для кадров в этих
    диапазонах (секунды).
    """
    if on_progress:
        on_progress(1, "загружаю модель детектора лиц")
    model_path = _ensure_model()

    cap = cv2.VideoCapture(str(video_path))
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    meta = VideoMeta(
        src_w=src_w, src_h=src_h, fps=fps, n_frames=n_frames,
        duration=n_frames / fps if fps > 0 else 0.0,
    )

    frame_ranges = (
        [(int(s * fps), int(e * fps)) for s, e in time_ranges]
        if time_ranges else None
    )

    options = FaceDetectorOptions(
        base_options=BaseOptions(model_asset_path=str(model_path)),
        running_mode=RunningMode.VIDEO,
        min_detection_confidence=min_confidence,
    )

    tracker = IoUTracker(iou_threshold=0.3, max_missing_frames=int(fps * 1.0))

    with FaceDetector.create_from_options(options) as detector:
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % sample_every == 0 and (
                frame_ranges is None
                or any(s <= idx <= e for s, e in frame_ranges)
            ):
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                ts_ms = int(idx / fps * 1000)
                result = detector.detect_for_video(mp_image, ts_ms)

                detections: list[FaceDetection] = []
                for det in (result.detections or []):
                    bb = det.bounding_box
                    bbox = BBox(x=float(bb.origin_x), y=float(bb.origin_y),
                                w=float(bb.width), h=float(bb.height))
                    conf = (det.categories[0].score if det.categories else 1.0)
                    detections.append(FaceDetection(
                        frame_idx=idx, bbox=bbox, confidence=float(conf),
                    ))
                tracker.update(idx, detections)

            idx += 1
            if on_progress and n_frames > 0 and idx % 30 == 0:
                pct = min(99.0, idx / n_frames * 100)
                on_progress(pct, f"кадр {idx}/{n_frames}")

    cap.release()
    # 15 кадров (~0.6с при 25fps) — отсекает мерцающие ложные срабатывания BlazeFace
    tracks = filter_short_tracks(tracker.tracks(), min_frames=15)
    return tracks, meta
