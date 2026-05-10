"""Person detection через YOLOv8 + IoU-tracking + связь с face tracks.

Зачем нужно: face detection не находит человека если:
- спина к камере
- профиль (>45° поворот головы)
- слишком далеко (>3-4 м для BlazeFace short_range)
- лицо в тени / частично перекрыто

Person detector работает на форме тела целиком → детектит в любой ориентации.
Если лицо ВНУТРИ person bbox — связываем их (один человек, есть face_id).
Если лицо НЕ найдено — кадрируем по person bbox (средний план «head & shoulders»).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import cv2

from ..track.tracker import IoUTracker, filter_short_tracks
from ..types import BBox, FaceDetection, FaceTrack
from .screens import YOLO_DEVICE, YOLO_IMGSZ, _load_yolo  # переиспользуем загрузчик


YOLO_PERSON_CLASS = 0  # COCO class 0 = person


def detect_persons(
    video_path: Path,
    sample_every: int = 3,
    min_confidence: float = 0.5,
    on_progress: Optional[Callable[[float, str], None]] = None,
    time_ranges: Optional[list[tuple[float, float]]] = None,
) -> list[FaceTrack]:
    """Возвращает «псевдо-FaceTrack'и» где bbox — это person bbox целиком.

    Используем тот же тип FaceTrack чтобы scene classifier работал единообразно.
    Для отличия — track_id начинается с 1000 (face track'и обычно 0..N).

    time_ranges — если задано, YOLO inference вызывается только для кадров,
    попадающих в эти временные интервалы (секунды). Декодирование идёт
    по всему видео (cv2.VideoCapture последовательный).
    """
    yolo = _load_yolo()
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    frame_ranges = (
        [(int(s * fps), int(e * fps)) for s, e in time_ranges]
        if time_ranges else None
    )

    tracker = IoUTracker(iou_threshold=0.3, max_missing_frames=int(fps * 1.5))
    tracker._next_id = 1000  # отличаем person tracks от face tracks

    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % sample_every == 0 and (
            frame_ranges is None
            or any(s <= idx <= e for s, e in frame_ranges)
        ):
            results = yolo.predict(
                frame, verbose=False, conf=min_confidence,
                classes=[YOLO_PERSON_CLASS],
                device=YOLO_DEVICE, imgsz=YOLO_IMGSZ,
            )
            detections: list[FaceDetection] = []
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
                    detections.append(FaceDetection(
                        frame_idx=idx, bbox=bbox, confidence=float(conf),
                    ))
            tracker.update(idx, detections)
        idx += 1
        if on_progress and n_frames > 0 and idx % 60 == 0:
            pct = min(99.0, idx / n_frames * 100)
            on_progress(pct, f"person кадр {idx}/{n_frames}")

    cap.release()
    # 25 кадров (~1с) — на длинном видео YOLO ловит много короткоживущих ложных детекций
    return filter_short_tracks(tracker.tracks(), min_frames=25)


def link_face_to_person(
    face_tracks: list[FaceTrack], person_tracks: list[FaceTrack],
    iou_min: float = 0.05,
) -> dict[int, int]:
    """Возвращает {face_track_id: person_track_id} — для каждого face найдём person."""
    out: dict[int, int] = {}
    for face_track in face_tracks:
        # для каждого face трека ищем person с максимальным средним IoU
        best_pid = -1
        best_score = 0.0
        for person_track in person_tracks:
            scores: list[float] = []
            for fd in face_track.detections:
                pbbox = person_track.bbox_at(fd.frame_idx)
                if pbbox is None:
                    continue
                # face должна быть ВНУТРИ person bbox (содержание, не пересечение)
                contained = (
                    pbbox.x <= fd.bbox.cx <= pbbox.x2
                    and pbbox.y <= fd.bbox.cy <= pbbox.y2
                )
                if contained:
                    scores.append(1.0)
                else:
                    scores.append(fd.bbox.iou(pbbox))
            if scores:
                avg = sum(scores) / len(scores)
                if avg > best_score and avg >= iou_min:
                    best_score = avg
                    best_pid = person_track.track_id
        if best_pid >= 0:
            out[face_track.track_id] = best_pid
    return out
