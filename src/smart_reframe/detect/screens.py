"""Детекция экранов / ноутбуков / телевизоров / досок / слайдов в кадре.

Двухслойный подход:
1. YOLOv8n — даёт нам реальные объекты (tv, laptop, book) с MS COCO. Лёгкая, быстрая.
2. Эвристика поверх — крупный прямоугольный регион с однородной заливкой,
   который НЕ перекрывается с лицами и достаточно большой → потенциальный
   слайд / доска / IDE-окно. Помечаем как "screen" даже если YOLO промолчал.

OCR (наличие текста) — добавлю позже; пока возвращаем has_text=False для всех.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from ..types import BBox, ScreenRegion, ScreenType


ProgressFn = Callable[[float, str], None]


# COCO classes, которые мы трактуем как «экран»
_YOLO_SCREEN_CLASSES = {
    62: "tv",       # tv
    63: "laptop",   # laptop
    73: "book",     # book — иногда детектится как «слайд»
    67: "screen",   # cell phone — обычно НЕ нужен, отключим ниже
}
_DROP_CLASSES = {67}  # cell phone и тд


def _detect_yolo_device() -> str:
    """Выбираем device для YOLO один раз: MPS на Apple Silicon, CUDA на NVIDIA, CPU иначе."""
    try:
        import torch
        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda:0"
    except Exception:
        pass
    return "cpu"


YOLO_DEVICE = _detect_yolo_device()
# imgsz=480 на M4 даёт 2-3× ускорение vs дефолтных 640 при сохранении точности
# для person/screen/laptop детекции (объекты крупные, не нужно высокое разрешение)
YOLO_IMGSZ = 480


def _load_yolo():
    """Lazy-load YOLO. Пробуем YOLO26 (январь 2026, NMS-free, +43% CPU),
    fallback на YOLO11 если ещё не вышел в нужной форме, потом v8."""
    global _yolo
    if "_yolo" in globals() and _yolo is not None:
        return _yolo
    from ultralytics import YOLO
    # порядок: новейший → стабильный → совместимый
    for weights in ("yolo26n.pt", "yolo11n.pt", "yolov8n.pt"):
        try:
            _yolo = YOLO(weights)
            return _yolo
        except Exception:
            continue
    raise RuntimeError("Не удалось загрузить YOLO веса")


def _heuristic_screens(frame: np.ndarray, exclude: list[BBox]) -> list[tuple[BBox, ScreenType]]:
    """Ищем большие прямоугольные регионы с однородной/контрастной заливкой.

    Простой пайплайн:
    - Convert grayscale + adaptiveThreshold → бинаризация
    - Морфология (закрытие) — соединяем мелкие области в «куски»
    - Контуры → прямоугольные → достаточно большие → bbox

    Это даёт «слайды/IDE/доски» когда YOLO их не нашёл.
    """
    h, w = frame.shape[:2]
    max_area = 0.65 * h * w
    out: list[tuple[BBox, ScreenType]] = []

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)

    # whiteboard: порог 190 + min 8% — ловит флипчарт/маркерную доску в студии
    _, light = cv2.threshold(gray, 190, 255, cv2.THRESH_BINARY)
    # code/IDE: тёмные регионы, более строгий min_area
    _, dark = cv2.threshold(gray, 35, 255, cv2.THRESH_BINARY_INV)

    for mask, kind, min_area in (
        (light, "whiteboard", 0.08 * h * w),  # 8% — флипчарт частично перекрытый
        (dark, "code", 0.15 * h * w),          # 15% — IDE/тёмный экран крупный
    ):
        kernel = np.ones((9, 9), np.uint8)
        closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            x, y, ww, hh = cv2.boundingRect(cnt)
            area = ww * hh
            if area < min_area or area > max_area:
                continue
            # «прямоугольность»: площадь контура / площадь bbox
            cnt_area = cv2.contourArea(cnt)
            if cnt_area / max(area, 1) < 0.7:  # было 0.5 — строже
                continue
            # ⭐ внутри регион должен быть «контент» — края (текст, формулы, графика)
            roi_edges = edges[y:y + hh, x:x + ww]
            if roi_edges.size == 0:
                continue
            edge_density = roi_edges.mean() / 255.0
            if edge_density < 0.02:  # пустая заливка → не доска, а просто фон
                continue
            bbox = BBox(x=x, y=y, w=ww, h=hh)
            # пересечение с лицами — пропускаем (лицо не должно лежать в screen)
            if any(bbox.iou(f) > 0.2 for f in exclude):
                continue
            # слишком вытянутые в одну сторону — мусор
            ar = ww / max(hh, 1)
            if ar > 4 or ar < 0.25:  # было 6 / 0.15 — строже
                continue
            out.append((bbox, kind))  # type: ignore[arg-type]
    return out


def detect_screens(
    video_path: Path,
    face_bboxes_per_frame: dict[int, list[BBox]] | None = None,
    sample_every: int = 6,
    on_progress: Optional[ProgressFn] = None,
    time_ranges: Optional[list[tuple[float, float]]] = None,
) -> list[ScreenRegion]:
    """Детектит ScreenRegion на каждом sample_every-м кадре.

    face_bboxes_per_frame — для подавления ложных срабатываний на областях с лицами.
    time_ranges — если задано, YOLO+эвристика только для кадров в этих
    временных диапазонах (секунды).
    """
    cap = cv2.VideoCapture(str(video_path))
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    frame_ranges = (
        [(int(s * fps), int(e * fps)) for s, e in time_ranges]
        if time_ranges else None
    )

    if on_progress:
        on_progress(1, "загружаю YOLOv8n")
    yolo = _load_yolo()

    out: list[ScreenRegion] = []
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % sample_every == 0 and (
            frame_ranges is None
            or any(s <= idx <= e for s, e in frame_ranges)
        ):
            face_bboxes = (face_bboxes_per_frame or {}).get(idx, [])

            # 1. YOLO
            results = yolo.predict(
                frame, verbose=False, conf=0.4, iou=0.5,
                device=YOLO_DEVICE, imgsz=YOLO_IMGSZ,
            )
            for r in results:
                if r.boxes is None:
                    continue
                for b, c in zip(r.boxes.xyxy.cpu().numpy(),
                                r.boxes.cls.cpu().numpy().astype(int)):
                    if int(c) in _DROP_CLASSES or int(c) not in _YOLO_SCREEN_CLASSES:
                        continue
                    x1, y1, x2, y2 = b
                    bbox = BBox(x=float(x1), y=float(y1),
                                w=float(x2 - x1), h=float(y2 - y1))
                    if any(bbox.iou(f) > 0.5 for f in face_bboxes):
                        continue
                    kind: ScreenType = _YOLO_SCREEN_CLASSES[int(c)]  # type: ignore[assignment]
                    out.append(ScreenRegion(
                        frame_idx=idx, bbox=bbox, type=kind, confidence=0.8,
                    ))

            # 2. Эвристика на «слайды» / «коды» / «доски»
            for bbox, kind in _heuristic_screens(frame, exclude=face_bboxes):
                out.append(ScreenRegion(
                    frame_idx=idx, bbox=bbox, type=kind, confidence=0.5,
                ))
        idx += 1
        if on_progress and n_frames > 0 and idx % 60 == 0:
            pct = min(99.0, idx / n_frames * 100)
            on_progress(pct, f"кадр {idx}/{n_frames}")

    cap.release()
    return out
