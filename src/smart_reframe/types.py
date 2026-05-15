"""Базовые типы для smart_reframe pipeline.

Поток данных:
    видео + аудио → detect (faces, screens) → asd (active speaker)
                  → scene classifier → layout per segment
                  → renderer per layout → final clip

Все таймстемпы в секундах от начала исходника.
Все bbox — пиксели в координатах исходника (src_w × src_h).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

# ─────────────────────────── низкоуровневые ───────────────────────────


@dataclass(frozen=True)
class BBox:
    """Прямоугольник в пикселях исходного кадра."""
    x: float  # left
    y: float  # top
    w: float
    h: float

    @property
    def x2(self) -> float: return self.x + self.w

    @property
    def y2(self) -> float: return self.y + self.h

    @property
    def cx(self) -> float: return self.x + self.w / 2

    @property
    def cy(self) -> float: return self.y + self.h / 2

    @property
    def area(self) -> float: return self.w * self.h

    def iou(self, other: "BBox") -> float:
        """Intersection over Union, [0..1]."""
        ix1 = max(self.x, other.x)
        iy1 = max(self.y, other.y)
        ix2 = min(self.x2, other.x2)
        iy2 = min(self.y2, other.y2)
        iw = max(0.0, ix2 - ix1)
        ih = max(0.0, iy2 - iy1)
        inter = iw * ih
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0


# ─────────────────────────── детекции ───────────────────────────


@dataclass
class FaceDetection:
    """Лицо в одном кадре."""
    frame_idx: int
    bbox: BBox
    confidence: float = 1.0


@dataclass
class FaceTrack:
    """Лицо, прослеженное по кадрам (один человек)."""
    track_id: int
    detections: list[FaceDetection] = field(default_factory=list)
    speaking_prob: dict[int, float] = field(default_factory=dict)  # frame_idx -> prob

    def bbox_at(self, frame_idx: int, search_window: int = 0) -> Optional[BBox]:
        """Bbox в данном кадре (или ближайшей детекции в ±search_window) или None."""
        best = None
        best_d = 10 ** 9
        for d in self.detections:
            delta = abs(d.frame_idx - frame_idx)
            if delta <= max(search_window, 0) and delta < best_d:
                best = d
                best_d = delta
        return best.bbox if best else None

    def first_frame(self) -> int:
        return min((d.frame_idx for d in self.detections), default=-1)

    def last_frame(self) -> int:
        return max((d.frame_idx for d in self.detections), default=-1)


ScreenType = Literal["screen", "laptop", "tv", "whiteboard", "code", "slide"]


@dataclass
class ScreenRegion:
    """Экран/доска/слайд в одном кадре."""
    frame_idx: int
    bbox: BBox
    type: ScreenType
    confidence: float = 1.0
    has_text: bool = False  # детектирован ли текст внутри (OCR)


# ─────────────────────────── сцены и layout'ы ───────────────────────────


LayoutType = Literal[
    "speaker_close",          # 1 лицо крупно
    "active_speaker_close",   # выбран активный из нескольких лиц
    "person_close",           # человек целиком (когда лица не видно: спина, профиль, далеко)
    "screen_full",            # экран/слайд на полный кадр
    "pip_speaker_screen",     # лицо в углу + экран на основе
    "wide_group",             # широкий план группы
    "wide_default",           # центр кадра без зума
    "split_screen",           # 2 лица бок о бок
]


@dataclass
class SceneSegment:
    """Решение что показывать на отрезке времени.

    Один сегмент = один layout. Сегменты не перекрываются.
    Между соседними сегментами рендерер делает плавный переход (~0.5с blend).
    """
    start: float  # сек от начала клипа
    end: float
    layout: LayoutType
    primary_face_id: Optional[int] = None  # для speaker_*
    primary_screen_idx: Optional[int] = None  # индекс ScreenRegion в кадре start
    secondary_face_id: Optional[int] = None  # для split_screen / pip
    confidence: float = 1.0
    reason: str = ""  # для дебага: почему этот layout
    overridden: bool = False  # пришёл из user corrections


@dataclass
class FrameProbe:
    """Снимок состояния одного кадра — вход для scene classifier'а."""
    frame_idx: int
    timestamp: float
    faces: list[tuple[int, BBox]]  # [(track_id, bbox), ...]
    screens: list[ScreenRegion]
    audio_energy: float = 0.0  # RMS от 0 до 1
    is_speech: bool = False    # из VAD whisper'а
    active_speaker_id: Optional[int] = None  # track_id
    deictic_in_transcript: bool = False  # «вот», «здесь» — указывает на экран


# ─────────────────────────── метаданные исходника ───────────────────────────


@dataclass
class VideoMeta:
    src_w: int
    src_h: int
    fps: float
    n_frames: int
    duration: float

    @property
    def crop_h(self) -> int:
        return self.src_h

    @property
    def crop_w_for_9_16(self) -> int:
        # окно для классического speaker_close 9:16 на полную высоту
        w = int(round(self.src_h * 9 / 16))
        return min(w, self.src_w)

    @property
    def is_vertical(self) -> bool:
        """Уже вертикальное видео (близко к 9:16)? Тогда reframe не нужен."""
        if self.src_h <= 0 or self.src_w <= 0:
            return False
        ar = self.src_w / self.src_h
        return ar <= 0.65  # ~9:16 = 0.5625; всё что вертикальнее 0.65 считаем "уже шортс"

    @property
    def is_square(self) -> bool:
        if self.src_h <= 0 or self.src_w <= 0:
            return False
        ar = self.src_w / self.src_h
        return 0.85 <= ar <= 1.15


# ─────────────────────────── корекции ───────────────────────────


@dataclass
class FrameCorrection:
    """Ручная коррекция от пользователя в редакторе."""
    frame_range: tuple[int, int]  # [from, to)
    layout: LayoutType
    primary_face_id: Optional[int] = None
    primary_screen_idx: Optional[int] = None
    note: str = ""
