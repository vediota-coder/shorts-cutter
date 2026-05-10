"""Face tracking через mediapipe Tasks API → сглаженная траектория центра кропа 9:16."""
from __future__ import annotations

import urllib.request
from dataclasses import dataclass
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


ProgressFn = Callable[[float, str], None]


# BlazeFace full-range — лица до ~5 м, аналог model_selection=1 из старого API.
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
MODEL_PATH = Path.home() / ".cache" / "mediapipe" / "blaze_face_short_range.tflite"


def _ensure_model() -> Path:
    if MODEL_PATH.exists() and MODEL_PATH.stat().st_size > 100_000:
        return MODEL_PATH
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    return MODEL_PATH


@dataclass
class CropTrack:
    centers: list[tuple[float, float]]
    crop_w: int
    crop_h: int
    src_w: int
    src_h: int
    fps: float


def build_track(
    video_path: Path,
    ema_alpha: float = 0.08,
    sample_every: int = 2,
    on_progress: Optional[ProgressFn] = None,
) -> CropTrack:
    if on_progress:
        on_progress(1, "загружаю модель детектора лиц")
    model_path = _ensure_model()

    cap = cv2.VideoCapture(str(video_path))
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    crop_h = src_h
    crop_w = int(round(src_h * 9 / 16))
    if crop_w > src_w:
        crop_w = src_w
        crop_h = int(round(src_w * 16 / 9))

    options = FaceDetectorOptions(
        base_options=BaseOptions(model_asset_path=str(model_path)),
        running_mode=RunningMode.VIDEO,
        min_detection_confidence=0.5,
    )

    raw_x: list[float | None] = []
    raw_y: list[float | None] = []
    last_x: float | None = None
    last_y: float | None = None

    with FaceDetector.create_from_options(options) as detector:
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % sample_every == 0:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                ts_ms = int(idx / fps * 1000)
                result = detector.detect_for_video(mp_image, ts_ms)
                if result.detections:
                    best = max(result.detections, key=lambda d: d.bounding_box.width)
                    bb = best.bounding_box
                    last_x = bb.origin_x + bb.width / 2
                    last_y = bb.origin_y + bb.height / 2
            raw_x.append(last_x)
            raw_y.append(last_y)
            idx += 1
            if on_progress and n_frames > 0 and idx % 30 == 0:
                pct = min(99.0, idx / n_frames * 100)
                on_progress(pct, f"кадр {idx}/{n_frames}")
    cap.release()

    default_cx = src_w / 2
    default_cy = src_h / 2
    cx = next((v for v in raw_x if v is not None), default_cx)
    cy = next((v for v in raw_y if v is not None), default_cy)

    smoothed: list[tuple[float, float]] = []
    for rx, ry in zip(raw_x, raw_y):
        if rx is not None:
            cx = ema_alpha * rx + (1 - ema_alpha) * cx
        if ry is not None:
            cy = ema_alpha * ry + (1 - ema_alpha) * cy
        smoothed.append((cx, cy))

    if not smoothed:
        smoothed = [(default_cx, default_cy)] * max(n_frames, 1)

    return CropTrack(centers=smoothed, crop_w=crop_w, crop_h=crop_h, src_w=src_w, src_h=src_h, fps=fps)


def render_reframed(video_path: Path, track: CropTrack, out_path: Path,
                    start: float, end: float, target_w: int = 1080, target_h: int = 1920) -> Path:
    cap = cv2.VideoCapture(str(video_path))
    fps = track.fps
    start_f = int(start * fps)
    end_f = int(end * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_f)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_path), fourcc, fps, (target_w, target_h))

    half_w = track.crop_w // 2
    half_h = track.crop_h // 2

    for i in range(start_f, min(end_f, len(track.centers))):
        ok, frame = cap.read()
        if not ok:
            break
        cx, cy = track.centers[i]
        x0 = int(max(0, min(track.src_w - track.crop_w, cx - half_w)))
        y0 = int(max(0, min(track.src_h - track.crop_h, cy - half_h)))
        crop = frame[y0:y0 + track.crop_h, x0:x0 + track.crop_w]
        resized = cv2.resize(crop, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
        writer.write(resized)

    writer.release()
    cap.release()
    return out_path
