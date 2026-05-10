"""analyze_video_streaming: один проход cv2.VideoCapture для всех детекторов.

Раньше: 4 независимых детектора, каждый открывает VideoCapture и читает все кадры.
На длинных видео это 4× декодирования + 4× memory pressure от буферов.

Теперь: один цикл, на каждом кадре все нужные детекторы (по своему sample_every)
получают этот кадр. Декодирование 1×, общая RAM ниже, скорость выше.

Включается через `EXCELLA_STREAMING_ANALYZE=1` или параметром `streaming=True`
в `analyze_video()`. По умолчанию OFF — сохраняем старое поведение для безопасности.
"""
from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Callable, Optional

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    FaceDetector,
    FaceDetectorOptions,
    RunningMode,
)

from .detect.faces import MODEL_PATH, MODEL_URL
from .detect.persons import YOLO_PERSON_CLASS
from .detect.screens import (
    YOLO_DEVICE,
    YOLO_IMGSZ,
    _DROP_CLASSES,
    _YOLO_SCREEN_CLASSES,
    _heuristic_screens,
    _load_yolo,
)
from .track.tracker import IoUTracker, filter_short_tracks
from .types import BBox, FaceDetection, FaceTrack, ScreenRegion, ScreenType, VideoMeta


ProgressFn = Callable[[float, str], None]


def _ensure_face_model() -> Path:
    if MODEL_PATH.exists() and MODEL_PATH.stat().st_size > 100_000:
        return MODEL_PATH
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    return MODEL_PATH


# sample_every для каждого детектора (как в оригинальных detect_*.py).
# 1 = каждый кадр, 2 = каждый 2-й и т.д.
SAMPLE_FACES = 2
SAMPLE_PERSONS = 3
SAMPLE_SCREENS = 6
SAMPLE_CUTS = 1

# YOLO confidence порог (был дублирован в persons.py и screens.py).
YOLO_PERSON_CONF = 0.5
YOLO_SCREEN_CONF = 0.4
YOLO_SCREEN_IOU = 0.5

# IoUTracker config — те же значения что в оригиналах.
FACE_IOU_THRESHOLD = 0.3
PERSON_IOU_THRESHOLD = 0.3

# Cuts: гистограммная разница порог.
CUTS_DIFF_THRESHOLD = 0.4


def analyze_video_streaming(
    video_path: Path,
    on_progress: Optional[ProgressFn] = None,
    time_ranges: Optional[list[tuple[float, float]]] = None,
    min_face_confidence: float = 0.5,
) -> tuple[list[FaceTrack], list[FaceTrack], list[ScreenRegion], list[int], VideoMeta]:
    """Один проход по видео, все 4 детектора параллельно.

    Возвращает (face_tracks, person_tracks, screen_regions, cuts, meta) —
    те же типы что и старые detect_* функции, чтобы analyze_video мог
    собрать SmartAnalysis без изменений.
    """
    cap = cv2.VideoCapture(str(video_path))
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    meta = VideoMeta(
        src_w=src_w, src_h=src_h, fps=fps, n_frames=n_frames,
        duration=n_frames / fps if fps > 0 else 0.0,
    )

    frame_ranges: Optional[list[tuple[int, int]]] = (
        [(int(s * fps), int(e * fps)) for s, e in time_ranges]
        if time_ranges else None
    )

    # Init моделей и состояния.
    if on_progress:
        on_progress(1, "streaming: загружаю модели (face + YOLO)")
    face_model_path = _ensure_face_model()
    yolo = _load_yolo()

    face_options = FaceDetectorOptions(
        base_options=BaseOptions(model_asset_path=str(face_model_path)),
        running_mode=RunningMode.VIDEO,
        min_detection_confidence=min_face_confidence,
    )

    face_tracker = IoUTracker(
        iou_threshold=FACE_IOU_THRESHOLD,
        max_missing_frames=int(fps * 1.0),
    )
    person_tracker = IoUTracker(
        iou_threshold=PERSON_IOU_THRESHOLD,
        max_missing_frames=int(fps * 1.5),
    )
    person_tracker._next_id = 1000  # отличаем person tracks

    screens: list[ScreenRegion] = []
    cuts: list[int] = []
    prev_hist: Optional[np.ndarray] = None
    in_range_prev = True

    if on_progress:
        on_progress(2, "streaming: один проход по видео")

    with FaceDetector.create_from_options(face_options) as face_detector:
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
                # cuts сбрасывает prev_hist на стыке диапазонов
                if in_range_prev:
                    prev_hist = None
                in_range_prev = False
                idx += 1
                continue
            in_range_prev = True

            # ── 1. Faces (sample_every=2)
            face_dets_this_frame: list[FaceDetection] = []
            if idx % SAMPLE_FACES == 0:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                ts_ms = int(idx / fps * 1000)
                result = face_detector.detect_for_video(mp_image, ts_ms)
                for det in (result.detections or []):
                    bb = det.bounding_box
                    bbox = BBox(x=float(bb.origin_x), y=float(bb.origin_y),
                                w=float(bb.width), h=float(bb.height))
                    conf = (det.categories[0].score if det.categories else 1.0)
                    face_dets_this_frame.append(FaceDetection(
                        frame_idx=idx, bbox=bbox, confidence=float(conf),
                    ))
                face_tracker.update(idx, face_dets_this_frame)

            # ── 2. Persons (sample_every=3) — YOLO person
            if idx % SAMPLE_PERSONS == 0:
                results = yolo.predict(
                    frame, verbose=False, conf=YOLO_PERSON_CONF,
                    classes=[YOLO_PERSON_CLASS],
                    device=YOLO_DEVICE, imgsz=YOLO_IMGSZ,
                )
                pers_dets: list[FaceDetection] = []
                for r in results:
                    if r.boxes is None:
                        continue
                    for b, c, conf in zip(
                        r.boxes.xyxy.cpu().numpy(),
                        r.boxes.cls.cpu().numpy().astype(int),
                        r.boxes.conf.cpu().numpy(),
                    ):
                        if int(c) != YOLO_PERSON_CLASS:
                            continue
                        x1, y1, x2, y2 = b
                        bbox = BBox(x=float(x1), y=float(y1),
                                    w=float(x2 - x1), h=float(y2 - y1))
                        pers_dets.append(FaceDetection(
                            frame_idx=idx, bbox=bbox, confidence=float(conf),
                        ))
                person_tracker.update(idx, pers_dets)

            # ── 3. Screens (sample_every=6) — YOLO screen classes + heuristic
            if idx % SAMPLE_SCREENS == 0:
                # face_bboxes для подавления ложных screens на лицах.
                # Если faces НЕ работали на этом кадре (idx % 6 == 0 кратно 2 → faces работали),
                # face_bboxes возьмутся из face_dets_this_frame.
                face_bboxes_now = [d.bbox for d in face_dets_this_frame]

                yolo_results = yolo.predict(
                    frame, verbose=False, conf=YOLO_SCREEN_CONF, iou=YOLO_SCREEN_IOU,
                    device=YOLO_DEVICE, imgsz=YOLO_IMGSZ,
                )
                for r in yolo_results:
                    if r.boxes is None:
                        continue
                    for b, c in zip(
                        r.boxes.xyxy.cpu().numpy(),
                        r.boxes.cls.cpu().numpy().astype(int),
                    ):
                        if int(c) in _DROP_CLASSES or int(c) not in _YOLO_SCREEN_CLASSES:
                            continue
                        x1, y1, x2, y2 = b
                        bbox = BBox(x=float(x1), y=float(y1),
                                    w=float(x2 - x1), h=float(y2 - y1))
                        if any(bbox.iou(f) > 0.5 for f in face_bboxes_now):
                            continue
                        kind: ScreenType = _YOLO_SCREEN_CLASSES[int(c)]  # type: ignore[assignment]
                        screens.append(ScreenRegion(
                            frame_idx=idx, bbox=bbox, type=kind, confidence=0.8,
                        ))
                # Эвристика на «слайды» / «коды» / «доски»
                for bbox, kind in _heuristic_screens(frame, exclude=face_bboxes_now):
                    screens.append(ScreenRegion(
                        frame_idx=idx, bbox=bbox, type=kind, confidence=0.5,
                    ))

            # ── 4. Cuts (sample_every=1, every frame)
            if idx % SAMPLE_CUTS == 0:
                small = cv2.resize(frame, (160, 90))
                hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
                hist = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
                cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
                if prev_hist is not None:
                    d = 1.0 - cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                    if d > CUTS_DIFF_THRESHOLD:
                        cuts.append(idx)
                prev_hist = hist

            idx += 1
            if on_progress and n_frames > 0 and idx % 60 == 0:
                pct = min(99.0, idx / n_frames * 100)
                on_progress(pct, f"streaming: кадр {idx}/{n_frames}")

    cap.release()

    # finalize: filter_short_tracks (как в оригинальных detect_*).
    face_tracks = filter_short_tracks(face_tracker.tracks(), min_frames=15)
    person_tracks = filter_short_tracks(person_tracker.tracks(), min_frames=25)

    if on_progress:
        on_progress(100, f"streaming готов: {len(face_tracks)} лиц, "
                         f"{len(person_tracks)} людей, {len(screens)} экранов, {len(cuts)} cut'ов")

    return face_tracks, person_tracks, screens, cuts, meta
