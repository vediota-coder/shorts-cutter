"""Рендер layout'ов покадрово через OpenCV.

Каждый layout — функция (frame_bgr, ctx) → out_frame_bgr (target_w × target_h).
Пайплайн `render_clip` собирает per-frame решения и пишет видео через ffmpeg pipe
(libx264 yuv420p CRF 18) — это даёт корректные h264 без артефактов mp4v кодека.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from ..types import (
    BBox,
    FaceTrack,
    LayoutType,
    SceneSegment,
    ScreenRegion,
    VideoMeta,
)
from .smooth_track import SmoothedTrack, get_or_build_smoother


# ─────────────────────────── вспомогательное ───────────────────────────


def _crop_centered(frame: np.ndarray, cx: float, cy: float, crop_w: int, crop_h: int) -> np.ndarray:
    """Кроп фиксированного размера, центрированный на (cx, cy), с clamping в границы."""
    h, w = frame.shape[:2]
    x0 = int(round(cx - crop_w / 2))
    y0 = int(round(cy - crop_h / 2))
    x0 = max(0, min(w - crop_w, x0))
    y0 = max(0, min(h - crop_h, y0))
    return frame[y0:y0 + crop_h, x0:x0 + crop_w]


def _resize(img: np.ndarray, w: int, h: int) -> np.ndarray:
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_LANCZOS4)


def _bbox_at(track: FaceTrack, frame_idx: int, search_window: int = 6) -> Optional[BBox]:
    """Ближайшая детекция в окне ±search_window кадров."""
    best = None
    best_d = 10**9
    for det in track.detections:
        d = abs(det.frame_idx - frame_idx)
        if d < best_d and d <= search_window:
            best = det
            best_d = d
    return best.bbox if best else None


def _screen_at(screens: list[ScreenRegion], frame_idx: int, fps: float, win_sec: float = 0.5) -> Optional[ScreenRegion]:
    win = int(win_sec * fps)
    candidates = [s for s in screens if abs(s.frame_idx - frame_idx) <= win]
    if not candidates:
        # fallback: последняя whiteboard-детекция до текущего кадра
        # (человек повернулся к доске — она никуда не ушла, просто тело перекрыло)
        # только whiteboard, не code/intro-анимация которая даёт ложные bbox'ы
        past_wb = [s for s in screens if s.frame_idx < frame_idx and s.type == "whiteboard"]
        if past_wb:
            return max(past_wb, key=lambda s: s.frame_idx)
        return None
    return max(candidates, key=lambda s: s.bbox.area)


# ─────────────────────────── EMA-сглаживание ───────────────────────────


class EMA2D:
    """Экспоненциально-сглаженная 2D-точка для траектории центра кропа.

    Используется для лёгкого сглаживания screen detector'а. Для лица применяем DampedFollower."""

    def __init__(self, alpha: float = 0.15):
        self.alpha = alpha
        self.cx: Optional[float] = None
        self.cy: Optional[float] = None

    def update(self, x: float, y: float) -> tuple[float, float]:
        if self.cx is None:
            self.cx, self.cy = x, y
        else:
            self.cx = self.alpha * x + (1 - self.alpha) * self.cx
            self.cy = self.alpha * y + (1 - self.alpha) * self.cy
        return self.cx, self.cy

    def get(self, fallback: tuple[float, float]) -> tuple[float, float]:
        if self.cx is None:
            return fallback
        return self.cx, self.cy

    def reset(self) -> None:
        self.cx = None
        self.cy = None


class DampedFollower:
    """Кинематика «следящей камеры»: ТРОЙНОЕ сглаживание.

    1. Median filter (окно median_window) по входу → убирает per-frame шум
       детектора без латентности EMA (median не «тянет хвост» на скачки).
    2. EMA по сглаженному медианой target.
    3. Deadband + инерционное преследование цели.
    4. На крупных скачках (> catch_up) — мгновенный снап.

    + Поддержка stitch_from(other) — копирует state соседнего follower'а
       при смене track_id (anti-jump на ID swap'ах).
    """

    def __init__(
        self,
        target_alpha: float = 0.14,     # 0.18 → 0.14: медленнее реагирует на шум детектора
        alpha: float = 0.09,            # 0.12 → 0.09: плавнее ускорение
        damping: float = 0.86,          # 0.78 → 0.86: больше демпфирования, меньше перелётов
        deadband_px: float = 90.0,      # 70 → 90: шире «зона покоя» — не реагируем на микро-движения
        max_velocity_px: float = 16.0,  # 22 → 16: медленнее максимум → меньше рывков
        catch_up_threshold: float = 200.0,  # 250 → 200: снапаем при меньшем расстоянии
        median_window: int = 15,
        h_alpha: float = 0.06,
        h_change_threshold_ratio: float = 0.04,
    ):
        self.target_alpha = target_alpha
        self.alpha = alpha
        self.damping = damping
        self.deadband = deadband_px
        self.max_v = max_velocity_px
        self.catch_up = catch_up_threshold
        self.cx: Optional[float] = None
        self.cy: Optional[float] = None
        self.tx: Optional[float] = None  # сглаженный target
        self.ty: Optional[float] = None
        self.vx: float = 0.0
        self.vy: float = 0.0
        # медианный буфер на input
        self._buf_x: list[float] = []
        self._buf_y: list[float] = []
        self._win = max(1, median_window)
        # ⭐ сглаживание высоты кропа — отдельный канал
        self.h_alpha = h_alpha
        self.h_threshold = h_change_threshold_ratio
        self.ch: Optional[float] = None      # сглаженная высота
        self._buf_h: list[float] = []

    def stitch_from(self, other: "DampedFollower",
                    seed_x: float | None = None, seed_y: float | None = None) -> None:
        """Перенять state соседнего follower'а при смене track_id.

        cx/cy/vx/vy — стартуем с позиции старого трека (без скачка камеры).
        _buf_x/_buf_y — ЗАПОЛНЯЕМ НОВОЙ позицией (seed), а не копируем старую:
        если старый буфер содержит значения прежнего лица, медиана будет «тянуть»
        камеру назад → видимые осцилляции первые ~15 кадров. Seed = bbox нового лица.
        """
        if other.cx is None:
            return
        self.cx, self.cy = other.cx, other.cy
        self.tx, self.ty = other.tx, other.ty
        self.vx, self.vy = other.vx * 0.3, other.vy * 0.3  # гасим скорость сильнее
        # заполняем буфер seed-позицией нового лица — медиана сразу указывает на цель
        sx = seed_x if seed_x is not None else other.cx
        sy = seed_y if seed_y is not None else other.cy
        self._buf_x = [sx] * self._win
        self._buf_y = [sy] * self._win
        self.ch = other.ch
        self._buf_h = list(other._buf_h)[-self._win:]

    def smooth_h(self, h_target: float) -> float:
        """Сглаживает целевую высоту кропа (median + EMA + deadband).

        Используется отдельно от update(x,y) — модули рендера передают raw
        bbox.h * padding и получают стабильную crop_h без zoom-yoyo.

        Warmup: пока буфер не заполнен (первые ~15 кадров после reset/cut),
        ch = mean(buffer). Это быстро гасит выбросы на первом кадре нового
        ракурса — иначе одна большая bbox.h на первом кадре зажимает зум на
        0.5+ секунды, видимо как медленный zoom-out.
        После заполнения буфера — стандартный median+EMA+deadband.
        """
        self._buf_h.append(h_target)
        if len(self._buf_h) > self._win:
            self._buf_h.pop(0)
        # ⭐ warmup: быстрый mean-based lock-on, иначе outlier на первом кадре после
        # cut'а заклинивает ch на ~10 кадров, видно как zoom-out 3%/0.3с.
        if len(self._buf_h) < self._win:
            self.ch = sum(self._buf_h) / len(self._buf_h)
            return self.ch
        sh = sorted(self._buf_h)
        h_med = sh[len(sh) // 2]
        if self.ch is None:
            self.ch = h_med
            return self.ch
        # deadband по высоте: маленькие колебания игнорим
        if abs(h_med - self.ch) / max(self.ch, 1.0) < self.h_threshold:
            return self.ch
        self.ch = self.h_alpha * h_med + (1 - self.h_alpha) * self.ch
        return self.ch

    def update(self, x: float, y: float) -> tuple[float, float]:
        # 1. Median filter — гасит шум детектора без латентности EMA
        self._buf_x.append(x)
        self._buf_y.append(y)
        if len(self._buf_x) > self._win:
            self._buf_x.pop(0)
            self._buf_y.pop(0)
        # быстрая median для ≤9 точек: sorted middle
        sx = sorted(self._buf_x)
        sy = sorted(self._buf_y)
        x = sx[len(sx) // 2]
        y = sy[len(sy) // 2]

        # 2. Сглаживаем target (input EMA) — мягкая дополнительная линза
        if self.tx is None:
            self.tx, self.ty = x, y
        else:
            self.tx = self.target_alpha * x + (1 - self.target_alpha) * self.tx
            self.ty = self.target_alpha * y + (1 - self.target_alpha) * self.ty

        if self.cx is None:
            self.cx, self.cy = self.tx, self.ty
            return self.cx, self.cy

        dx = self.tx - self.cx
        dy = self.ty - self.cy
        dist = (dx * dx + dy * dy) ** 0.5

        if dist < self.deadband:
            # цель «в покое» — гасим скорость
            self.vx *= 0.4
            self.vy *= 0.4
            return self.cx, self.cy

        if dist > self.catch_up:
            # резкий скачок (новый ракурс/cut) — мгновенный снап
            self.cx, self.cy = self.tx, self.ty
            self.vx = self.vy = 0.0
            return self.cx, self.cy

        # ускорение к цели + инерция
        ax = self.alpha * dx
        ay = self.alpha * dy
        self.vx = self.damping * self.vx + ax
        self.vy = self.damping * self.vy + ay

        v = (self.vx * self.vx + self.vy * self.vy) ** 0.5
        if v > self.max_v:
            sc = self.max_v / v
            self.vx *= sc
            self.vy *= sc

        self.cx += self.vx
        self.cy += self.vy
        return self.cx, self.cy

    def reset(self) -> None:
        self.cx = self.cy = None
        self.tx = self.ty = None
        self.vx = self.vy = 0.0
        self.ch = None
        self._buf_h = []


# ─────────────────────────── контекст рендера ───────────────────────────


@dataclass
class RenderCtx:
    meta: VideoMeta
    target_w: int
    target_h: int
    tracks: list[FaceTrack]
    screens: list[ScreenRegion]
    # дамптеры на лица — кинематика «следящей камеры», плавно но не отстаёт
    face_followers: dict[int, DampedFollower]   # track_id → follower
    screen_ema: EMA2D
    last_layout: Optional[LayoutType] = None
    tracks_persons: list[FaceTrack] = None  # YOLO person tracks (для person_close)
    # на крупных видео нужен бóльший deadband и max_v
    deadband_px: float = 35.0
    max_velocity_px: float = 18.0
    # ⭐ track stitching: при создании нового follower'а переиспользуем state
    # соседнего недавно живого follower'а если позиция близка → anti-jump на ID swap.
    follower_last_seen: dict[int, int] = None  # track_id → last frame_idx update'а
    follower_last_pos: dict[int, tuple[float, float]] = None  # track_id → (cx, cy)
    # ⭐ face_to_person: позволяет в person_close найти позицию головы из недавнего
    # speaker_close на ТОТ ЖЕ человек. Без этого в person_close camera центрируется
    # на bbox.cx (body center), а голова часто смещена → «пустота между телом и руками».
    face_to_person: dict[int, int] = None       # face_id → person_id
    last_face_pos_by_person: dict[int, tuple[int, float, float]] = None  # person_id → (frame_idx, cx, cy)
    # ⭐ low-conf MediaPipe face detector — для wide-shot, где основной детектор
    # с conf=0.5 не видит мелкие лица. Lazy init при первом обращении.
    _low_conf_face_detector: object = None
    # ⭐ cut frames для cut-aware fallback в _render_speaker_close: если между
    # последней детекцией face track'а и текущим кадром был cut → старая позиция
    # лица невалидна (новый ракурс), переключаемся на person_close.
    cuts_set: set = None
    # ⭐ offline trajectory smoothers — заменяют DampedFollower для face/person
    # cropping. Gaussian filter по всей траектории трека даёт cinema-camera
    # плавность: per-frame jitter полностью убран, лаг отсутствует
    # (значение каждого кадра предвычислено).
    face_smoothers: dict[int, SmoothedTrack] = None   # face track_id → smoother
    person_smoothers: dict[int, SmoothedTrack] = None # person track_id → smoother
    # ⭐ camera plan: pre-computed (cx, cy, crop_h) per frame после Gaussian
    # сглаживания через границы сегментов. Layout transitions
    # (speaker_close ↔ screen_full ↔ person_close) превращаются в плавный
    # zoom/pan вместо hard cut'ов.
    camera_plan: object = None  # CamPlan | None


def get_or_create_follower(
    ctx: "RenderCtx",
    track_id: int,
    frame_idx: int,
    seed_x: float,
    seed_y: float,
    *,
    deadband_px: float | None = None,
    max_velocity_px: float | None = None,
    stitch_window_frames: int = 90,   # ⭐ 30 → 90 (3с@30fps): покрывает gap'ы между треками до 1.5с
    stitch_radius_px: float = 350.0,  # ⭐ 200 → 350: face_cy и person_cy могут быть на 200+ px разнесены
) -> "DampedFollower":
    """Возвращает follower'а для track_id. Если новый — пытается перенять
    state соседнего follower'а с близкой last_pos в пределах N кадров.
    """
    if ctx.follower_last_seen is None:
        ctx.follower_last_seen = {}
    if ctx.follower_last_pos is None:
        ctx.follower_last_pos = {}

    f = ctx.face_followers.get(track_id)
    if f is None:
        f = DampedFollower(
            deadband_px=deadband_px if deadband_px is not None else ctx.deadband_px,
            max_velocity_px=max_velocity_px if max_velocity_px is not None else ctx.max_velocity_px,
        )
        # ищем недавно «потерянный» трек рядом с seed_x, seed_y
        best_tid = None
        best_dist = stitch_radius_px
        for prev_tid, prev_frame in ctx.follower_last_seen.items():
            if prev_tid == track_id:
                continue
            if frame_idx - prev_frame > stitch_window_frames:
                continue
            px, py = ctx.follower_last_pos.get(prev_tid, (0, 0))
            d = ((px - seed_x) ** 2 + (py - seed_y) ** 2) ** 0.5
            if d < best_dist:
                best_dist = d
                best_tid = prev_tid
        if best_tid is not None and best_tid in ctx.face_followers:
            f.stitch_from(ctx.face_followers[best_tid], seed_x=seed_x, seed_y=seed_y)
        ctx.face_followers[track_id] = f

    ctx.follower_last_seen[track_id] = frame_idx
    return f


# ─────────────────────────── layout renderers ───────────────────────────


def _render_face_crop(frame: np.ndarray, track: FaceTrack, frame_idx: int, ctx: RenderCtx,
                     padding_ratio: float = 1.6) -> np.ndarray:
    """Закадровка по лицу. Использует offline-smoothed траекторию (Gaussian sigma=20f).

    Никакого per-frame follower'а: значение каждого кадра предвычислено по всему треку,
    поэтому jitter полностью отсутствует и нет лага spring-mass'а.
    """
    if ctx.face_smoothers is None:
        ctx.face_smoothers = {}
    smoother = get_or_build_smoother(
        ctx.face_smoothers, track, ctx.meta.n_frames, sigma_frames=20.0,
        cuts_set=ctx.cuts_set,
    )
    smoothed = smoother.at(frame_idx)

    import os as _os
    if _os.environ.get("SR_TRACE") == "1":
        kind = "smoothed" if smoothed else "OUT_OF_RANGE"
        if smoothed:
            scx, scy, sh = smoothed
            print(f"[face_crop] f={frame_idx} fid={track.track_id} {kind} "
                  f"(cx={scx:.0f},cy={scy:.0f},h={sh:.0f})", flush=True)
        else:
            print(f"[face_crop] f={frame_idx} fid={track.track_id} {kind}", flush=True)

    if smoothed is None:
        # фолбэк: трек не покрывает этот кадр — wide_default безопаснее snap к центру
        return _render_wide_default(frame, SceneSegment(0, 0, "wide_default"), frame_idx, ctx)

    face_cx, face_cy, face_h = smoothed

    # ⭐ 3.5× face_h — голова+плечи; smoother уже сгладил h по всему треку, никакого EMA не надо
    crop_h = face_h * 3.5
    crop_h = max(crop_h, ctx.target_h // 3)
    crop_h = min(crop_h, ctx.meta.src_h)
    crop_h = int(round(crop_h))
    crop_w = int(round(crop_h * 9 / 16))
    crop_w = min(crop_w, ctx.meta.src_w)

    # headroom: лицо в верхней трети кропа → центр кропа ниже лица
    cx = face_cx
    cy = face_cy + crop_h * 0.18 - face_h * 0.5

    # safe margin: лицо не выпадает за 80% ширину кропа при близости к краю исходника
    half_w = crop_w / 2
    safe_x_min = face_cx - crop_w * 0.4
    safe_x_max = face_cx + crop_w * 0.4
    cx = max(safe_x_min + half_w, min(safe_x_max + half_w - crop_w, cx))
    safe_y_min = face_cy - crop_h * 0.35
    safe_y_max = face_cy + crop_h * 0.10
    cy = max(safe_y_min, min(safe_y_max, cy))

    if ctx.follower_last_pos is not None:
        ctx.follower_last_pos[track.track_id] = (cx, cy)

    crop = _crop_centered(frame, cx, cy, crop_w, crop_h)
    return _resize(crop, ctx.target_w, ctx.target_h)


def _render_speaker_close(frame: np.ndarray, seg: SceneSegment, frame_idx: int, ctx: RenderCtx) -> np.ndarray:
    track = next((t for t in ctx.tracks if t.track_id == seg.primary_face_id), None)
    if track is None:
        return _render_wide_default(frame, seg, frame_idx, ctx)
    # ⭐ cut-aware fallback: если между последней детекцией face track'а и текущим
    # кадром был cut, или в окне ±6 кадров детекции нет — рендерим как person_close
    # на привязанном person'е (там MediaPipe ищет реальную позицию лица).
    # Это закрывает дыру, где _merge_short_segments продлевает speaker_close на
    # пост-cut кадры с устаревшим bbox (стара позиция камеры на новой сцене).
    last_det = max(
        (d.frame_idx for d in track.detections if d.frame_idx <= frame_idx),
        default=-1,
    )
    cut_between = (
        last_det >= 0
        and ctx.cuts_set
        and any(last_det < c <= frame_idx for c in ctx.cuts_set)
    )
    no_recent_face = _bbox_at(track, frame_idx, search_window=30) is None  # ⭐ 6 → 30: 1с@30fps, меньше ложных person_close
    if (no_recent_face or cut_between) and ctx.face_to_person:
        pid = ctx.face_to_person.get(track.track_id)
        if pid is not None:
            person_track = next(
                (p for p in (ctx.tracks_persons or []) if p.track_id == pid), None,
            )
            if person_track and _bbox_at(person_track, frame_idx, search_window=12) is not None:
                fallback_seg = SceneSegment(
                    start=seg.start, end=seg.end, layout="person_close",
                    primary_face_id=pid,
                    reason=("face_lost" if no_recent_face else "cut_between") + "_fallback_to_person",
                )
                return _render_person_close(frame, fallback_seg, frame_idx, ctx)
    return _render_face_crop(frame, track, frame_idx, ctx)


def _render_active_speaker(frame: np.ndarray, seg: SceneSegment, frame_idx: int, ctx: RenderCtx) -> np.ndarray:
    return _render_speaker_close(frame, seg, frame_idx, ctx)


def _render_screen_full(frame: np.ndarray, seg: SceneSegment, frame_idx: int, ctx: RenderCtx) -> np.ndarray:
    screen = _screen_at(ctx.screens, frame_idx, ctx.meta.fps)
    if screen is None:
        return _render_wide_default(frame, seg, frame_idx, ctx)

    bbox = screen.bbox
    # вертикальный кроп под 9:16
    crop_h = int(min(ctx.meta.src_h, max(bbox.h * 1.05, ctx.meta.src_h * 0.95)))
    crop_w = int(round(crop_h * 9 / 16))
    crop_w = min(crop_w, ctx.meta.src_w)

    # если доска уже кропа — сдвигаем центр так, чтобы правый край доски
    # совпал с правым краем кропа, убирая тёмный фон справа
    raw_cx = bbox.cx
    if bbox.w < crop_w:
        slack = (crop_w - bbox.w) / 2
        raw_cx = bbox.cx - slack  # сдвиг влево — доска правым краем к краю кропа
        raw_cx = max(raw_cx, crop_w / 2)  # не уходим за левый край

    cx, cy = ctx.screen_ema.update(raw_cx, bbox.cy)
    crop = _crop_centered(frame, cx, cy, crop_w, crop_h)
    return _resize(crop, ctx.target_w, ctx.target_h)


def _render_wide_default(frame: np.ndarray, seg: SceneSegment, frame_idx: int, ctx: RenderCtx) -> np.ndarray:
    """Центральный кроп всего кадра под 9:16, без зума."""
    crop_h = ctx.meta.src_h
    crop_w = int(round(crop_h * 9 / 16))
    if crop_w > ctx.meta.src_w:
        crop_w = ctx.meta.src_w
        crop_h = int(round(crop_w * 16 / 9))
    cx = ctx.meta.src_w / 2
    cy = ctx.meta.src_h / 2
    crop = _crop_centered(frame, cx, cy, crop_w, crop_h)
    return _resize(crop, ctx.target_w, ctx.target_h)


def _render_wide_group(frame: np.ndarray, seg: SceneSegment, frame_idx: int, ctx: RenderCtx) -> np.ndarray:
    """Широкий план — центр между всеми лицами."""
    bboxes = [_bbox_at(t, frame_idx) for t in ctx.tracks]
    bboxes = [b for b in bboxes if b is not None]
    if not bboxes:
        return _render_wide_default(frame, seg, frame_idx, ctx)
    cx = sum(b.cx for b in bboxes) / len(bboxes)
    cy = sum(b.cy for b in bboxes) / len(bboxes)
    crop_h = ctx.meta.src_h
    crop_w = int(round(crop_h * 9 / 16))
    crop_w = min(crop_w, ctx.meta.src_w)
    crop = _crop_centered(frame, cx, cy, crop_w, crop_h)
    return _resize(crop, ctx.target_w, ctx.target_h)


def _render_split_screen(frame: np.ndarray, seg: SceneSegment, frame_idx: int, ctx: RenderCtx) -> np.ndarray:
    """Два лица бок о бок — верхняя/нижняя половины кадра 9:16."""
    a_track = next((t for t in ctx.tracks if t.track_id == seg.primary_face_id), None)
    b_track = next((t for t in ctx.tracks if t.track_id == seg.secondary_face_id), None)
    if a_track is None or b_track is None:
        return _render_wide_group(frame, seg, frame_idx, ctx)

    half_h = ctx.target_h // 2

    def crop_for_face(t: FaceTrack) -> np.ndarray:
        bbox = _bbox_at(t, frame_idx) or BBox(ctx.meta.src_w/2-50, ctx.meta.src_h/2-60, 100, 120)
        ch = int(min(ctx.meta.src_h, bbox.h * 3.5))
        cw = int(round(ch * 16 / 9))
        cw = min(cw, ctx.meta.src_w)
        # headroom для side_by_side тоже — лицо в верхней трети
        target_cy = bbox.cy + ch * 0.15 - bbox.h * 0.5
        follower = get_or_create_follower(ctx, t.track_id, frame_idx, bbox.cx, target_cy)
        cx, cy = follower.update(bbox.cx, target_cy)
        if ctx.follower_last_pos is not None:
            ctx.follower_last_pos[t.track_id] = (cx, cy)
        return _resize(_crop_centered(frame, cx, cy, cw, ch), ctx.target_w, half_h)

    out = np.zeros((ctx.target_h, ctx.target_w, 3), dtype=np.uint8)
    out[:half_h] = crop_for_face(a_track)
    out[half_h:] = crop_for_face(b_track)
    # тонкая разделительная линия
    cv2.line(out, (0, half_h), (ctx.target_w, half_h), (0, 0, 0), 4)
    return out


def _render_pip_speaker_screen(frame: np.ndarray, seg: SceneSegment, frame_idx: int, ctx: RenderCtx) -> np.ndarray:
    """Picture-in-Picture: экран — основа, лицо в правом нижнем углу."""
    base = _render_screen_full(frame, seg, frame_idx, ctx)

    track = next((t for t in ctx.tracks if t.track_id == seg.primary_face_id), None)
    if track is None:
        return base

    # лицо в виде кружка/квадрата 280×280 (для 1080×1920) в правом нижнем углу с отступом 60px
    pip_size = max(220, ctx.target_w // 4)
    pip_face = _render_face_crop(frame, track, frame_idx, ctx, padding_ratio=1.4)
    pip_face = _resize(pip_face, pip_size, pip_size)

    # белая обводка 6px + лёгкая тень
    bordered = cv2.copyMakeBorder(pip_face, 6, 6, 6, 6, cv2.BORDER_CONSTANT, value=(255, 255, 255))

    # позиция в base
    out = base.copy()
    margin = 60
    x = ctx.target_w - bordered.shape[1] - margin
    y = ctx.target_h - bordered.shape[0] - margin - 200  # выше субтитров
    bh, bw = bordered.shape[:2]

    # тень
    shadow = cv2.GaussianBlur(np.full((bh, bw, 3), 0, dtype=np.uint8), (21, 21), 8)
    sx, sy = x + 8, y + 8
    if 0 <= sx and sx + bw <= ctx.target_w and 0 <= sy and sy + bh <= ctx.target_h:
        roi = out[sy:sy + bh, sx:sx + bw]
        out[sy:sy + bh, sx:sx + bw] = cv2.addWeighted(roi, 0.7, shadow, 0.3, 0)

    out[y:y + bh, x:x + bw] = bordered
    return out


def _detect_face_low_conf(frame: np.ndarray, ctx: RenderCtx, near_bbox: BBox) -> tuple[float, float] | None:
    """Запускает MediaPipe Face Detection (conf=0.25) на текущем кадре.
    Возвращает (cx, cy) лица, ближайшего к ``near_bbox`` (если попадает в его границы).

    Для wide-shot подкаста это ловит лица, которые основной детектор с conf=0.5
    пропускает — body bbox YOLO ≠ position головы (плечи/руки расширяют bbox).
    """
    if ctx._low_conf_face_detector is None:
        try:
            import mediapipe as _mp
            from mediapipe.tasks.python import BaseOptions as _BO
            from mediapipe.tasks.python.vision import (
                FaceDetector as _FD, FaceDetectorOptions as _FDO, RunningMode as _RM,
            )
            from pathlib import Path as _P
            model_path = _P.home() / ".cache/mediapipe/blaze_face_short_range.tflite"
            if not model_path.exists():
                return None
            opts = _FDO(
                base_options=_BO(model_asset_path=str(model_path)),
                running_mode=_RM.IMAGE,
                min_detection_confidence=0.25,
            )
            ctx._low_conf_face_detector = _FD.create_from_options(opts)
        except Exception:
            ctx._low_conf_face_detector = False  # маркер «не работает»
            return None
    if ctx._low_conf_face_detector is False:
        return None
    try:
        import mediapipe as _mp
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_img = _mp.Image(image_format=_mp.ImageFormat.SRGB, data=rgb)
        res = ctx._low_conf_face_detector.detect(mp_img)
        if not res.detections:
            return None
        # ищем лицо В пределах near_bbox (горизонтально), и ближайшее к верху bbox
        best = None
        best_score = 0.0
        for d in res.detections:
            bb = d.bounding_box
            cx = bb.origin_x + bb.width / 2.0
            cy = bb.origin_y + bb.height / 2.0
            # ограничение: лицо должно быть В person bbox
            if cx < near_bbox.x or cx > near_bbox.x + near_bbox.w:
                continue
            if cy < near_bbox.y - 50 or cy > near_bbox.y + near_bbox.h * 0.5:
                continue  # лицо должно быть в верхней половине person bbox
            score = d.categories[0].score if d.categories else 0
            if score > best_score:
                best_score = score
                best = (cx, cy)
        return best
    except Exception:
        return None


def _render_person_close(frame: np.ndarray, seg: SceneSegment, frame_idx: int, ctx: RenderCtx) -> np.ndarray:
    """Кроп вокруг person'а (когда лица не видно: спина, профиль, далеко).

    Берём person bbox + добавляем padding сверху (чтобы голова не упиралась в верх).
    Стандарт middle-shot: высота = bbox.h * 1.1, центр чуть выше середины bbox.
    primary_face_id здесь хранит track_id person'а (см. classifier.py).
    """
    person_track = next(
        (t for t in (ctx.tracks_persons or []) if t.track_id == seg.primary_face_id),
        None,
    )
    if person_track is None:
        return _render_wide_default(frame, seg, frame_idx, ctx)

    if ctx.person_smoothers is None:
        ctx.person_smoothers = {}
    # для person'ов используем чуть бóльшую sigma — body bbox шумнее face bbox
    smoother = get_or_build_smoother(
        ctx.person_smoothers, person_track, ctx.meta.n_frames, sigma_frames=25.0,
        cuts_set=ctx.cuts_set,
    )
    smoothed = smoother.at(frame_idx)
    if smoothed is None:
        return _render_wide_default(frame, seg, frame_idx, ctx)

    person_cx, person_cy_unused, person_h = smoothed
    # y берём из smoothed центра bbox, h — сглажен по всему треку
    # для person_close хотим показать торс + голову → центр кропа чуть выше центра bbox

    # crop_h: 1.15× bbox.h, но не меньше 60% высоты исходника (middle-shot)
    raw_target_h = max(person_h * 1.15, ctx.meta.src_h * 0.6)
    raw_target_h = min(raw_target_h, ctx.meta.src_h)
    crop_h = int(round(raw_target_h))
    crop_h = max(1, min(crop_h, ctx.meta.src_h))
    crop_w = int(round(crop_h * 9 / 16))
    crop_w = min(crop_w, ctx.meta.src_w)

    # центрируем на голове: голова обычно в верхней четверти person bbox.
    # cy_top_quarter = person_cy_unused - person_h * 0.25 (верх плеч)
    # но это per-frame значение шумит — используем сглаженное смещение через bbox в кадре, если есть.
    raw_bbox = _bbox_at(person_track, frame_idx, search_window=12)
    if raw_bbox is not None:
        face_pos = _detect_face_low_conf(frame, ctx, raw_bbox)
    else:
        face_pos = None
    if face_pos is not None:
        # MediaPipe нашёл лицо → центрируемся на нём, x от smoothed (без шума)
        cy = face_pos[1] + person_h * 0.20
    else:
        # без MediaPipe: используем smoothed центр и подымаем камеру так,
        # чтобы голова была в верхней трети кропа
        cy = person_cy_unused - person_h * 0.15

    cx = person_cx

    import os as _os
    if _os.environ.get("SR_TRACE") == "1":
        print(f"[person_close] f={frame_idx} pid={seg.primary_face_id} "
              f"smoothed cx={cx:.0f} cy={cy:.0f} h={person_h:.0f} crop_h={crop_h}", flush=True)
    if ctx.follower_last_pos is not None:
        ctx.follower_last_pos[seg.primary_face_id] = (cx, cy)

    crop = _crop_centered(frame, cx, cy, crop_w, crop_h)
    return _resize(crop, ctx.target_w, ctx.target_h)


_LAYOUT_RENDERERS: dict[LayoutType, Callable] = {
    "speaker_close": _render_speaker_close,
    "active_speaker_close": _render_active_speaker,
    "person_close": _render_person_close,
    "screen_full": _render_screen_full,
    "pip_speaker_screen": _render_pip_speaker_screen,
    "wide_group": _render_wide_group,
    "wide_default": _render_wide_default,
    "split_screen": _render_split_screen,
}


# ─────────────────────────── camera plan ───────────────────────────


_SMOOTHABLE_LAYOUTS: set[LayoutType] = {
    "speaker_close", "active_speaker_close",
    "person_close", "screen_full",
    "wide_default", "wide_group",
}


@dataclass
class CamPlan:
    """Per-frame (cx, cy, crop_h) for the clip, Gaussian-smoothed across segment
    boundaries. Transitions speaker_close ↔ screen_full ↔ person_close become
    plавные zoom/pan вместо hard cut'ов.
    """
    cx: np.ndarray
    cy: np.ndarray
    crop_h: np.ndarray
    valid: np.ndarray
    start_f: int

    def get(self, frame_idx: int) -> Optional[tuple[float, float, int]]:
        i = frame_idx - self.start_f
        if i < 0 or i >= len(self.cx) or not self.valid[i]:
            return None
        return float(self.cx[i]), float(self.cy[i]), int(round(self.crop_h[i]))


def _track_has_recent_detection(
    track: FaceTrack, frame_idx: int, cuts_set: set, search_window: int = 15,
) -> bool:
    """Есть ли у трека детекция в окне ±search_window кадров, БЕЗ source-cut'а между.

    Если есть source cut между ближайшей детекцией и текущим кадром, значит
    в реальном видео случился монтажный рез, и положение лица «до» не валидно
    для кадров «после». В таком случае возвращаем False — пусть камера-план
    интерполирует между соседними сегментами или хард-cut'нется.
    """
    for d in track.detections:
        delta = abs(d.frame_idx - frame_idx)
        if delta > search_window:
            continue
        lo = min(d.frame_idx, frame_idx)
        hi = max(d.frame_idx, frame_idx)
        if cuts_set and any(lo < c <= hi for c in cuts_set):
            continue  # cut между ними → детекция невалидна для этого кадра
        return True
    return False


def _params_face_crop(track: FaceTrack, frame_idx: int, ctx: RenderCtx) -> Optional[tuple[float, float, float]]:
    # ⭐ если у трека нет детекции в ±15 кадрах (без source cut между) — позиция
    # ненадёжна, возвращаем None. В camera_plan такие кадры станут «дырами» в
    # своём cut-регионе и заполнятся либо соседними валидными значениями того же
    # региона, либо целиком регион будет невалиден.
    if not _track_has_recent_detection(track, frame_idx, ctx.cuts_set or set()):
        return None
    if ctx.face_smoothers is None:
        ctx.face_smoothers = {}
    smoother = get_or_build_smoother(
        ctx.face_smoothers, track, ctx.meta.n_frames, sigma_frames=20.0,
        cuts_set=ctx.cuts_set,
    )
    s = smoother.at(frame_idx)
    if s is None:
        return None
    face_cx, face_cy, face_h = s
    crop_h = max(face_h * 3.5, ctx.target_h // 3)
    crop_h = min(crop_h, ctx.meta.src_h)
    # cinema headroom: face_center at ~38-40% from top → desired cy below face_cy
    target_cy = face_cy - face_h * 0.5 + crop_h * 0.40
    # ⭐ hard guarantee: TOP OF HEAD (incl. hair ≈ face_cy - face_h*0.85) must sit
    # at least max(60px, 8%·crop_h) below crop_top. Иначе при smoothed-jitter лица
    # или растущем face_h на close-gesture макушка вылетает за верх кропа.
    headroom_px = max(60.0, crop_h * 0.08)
    cy_max = face_cy - face_h * 0.85 + crop_h / 2 - headroom_px
    cy = min(target_cy, cy_max)
    return face_cx, cy, crop_h


def _params_person_close(seg: SceneSegment, frame_idx: int, ctx: RenderCtx) -> Optional[tuple[float, float, float]]:
    person_track = next(
        (t for t in (ctx.tracks_persons or []) if t.track_id == seg.primary_face_id),
        None,
    )
    if person_track is None:
        return None
    if ctx.person_smoothers is None:
        ctx.person_smoothers = {}
    smoother = get_or_build_smoother(
        ctx.person_smoothers, person_track, ctx.meta.n_frames, sigma_frames=25.0,
        cuts_set=ctx.cuts_set,
    )
    s = smoother.at(frame_idx)
    if s is None:
        return None
    person_cx, person_cy, person_h = s
    crop_h = max(person_h * 1.15, ctx.meta.src_h * 0.6)
    crop_h = min(crop_h, ctx.meta.src_h)
    # голова в верхних 20-25% person bbox → head_y ≈ person_cy - person_h*0.30
    head_y = person_cy - person_h * 0.30
    target_cy = head_y + crop_h * 0.28
    # ⭐ hard headroom: TOP OF HAIR ≈ person_cy - person_h*0.50 должен быть
    # ≥ max(60px, 8%·crop_h) ниже crop_top. Иначе при росте person_h на близких
    # гестах макушка вылетает за верх кропа.
    headroom_px = max(60.0, crop_h * 0.08)
    cy_max = person_cy - person_h * 0.50 + crop_h / 2 - headroom_px
    cy = min(target_cy, cy_max)
    return person_cx, cy, crop_h


def _params_screen_full(frame_idx: int, ctx: RenderCtx) -> Optional[tuple[float, float, float]]:
    screen = _screen_at(ctx.screens, frame_idx, ctx.meta.fps)
    if screen is None:
        return None
    bbox = screen.bbox
    crop_h = min(ctx.meta.src_h, max(bbox.h * 1.05, ctx.meta.src_h * 0.95))
    crop_w = crop_h * 9 / 16
    raw_cx = bbox.cx
    if bbox.w < crop_w:
        slack = (crop_w - bbox.w) / 2
        raw_cx = max(bbox.cx - slack, crop_w / 2)
    return raw_cx, float(bbox.cy), crop_h


def _params_wide_default(ctx: RenderCtx) -> tuple[float, float, float]:
    return ctx.meta.src_w / 2, ctx.meta.src_h / 2, float(ctx.meta.src_h)


def _params_for_segment(seg: SceneSegment, frame_idx: int, ctx: RenderCtx) -> Optional[tuple[float, float, float]]:
    """Returns (cx, cy, crop_h) for a single-crop layout, or None.

    ⭐ None означает «нет надёжной позиции» — build_camera_plan пометит кадр
    invalid и rendering loop вызовет старый renderer (со всей его fallback-
    логикой через person_close / wide_default). РАНЬШЕ возвращали
    _params_wide_default — это давало центр кадра, где реального субъекта нет,
    и появлялись «пустые» frames с занавеской/столом.
    """
    if seg.layout in ("speaker_close", "active_speaker_close"):
        track = next((t for t in ctx.tracks if t.track_id == seg.primary_face_id), None)
        if track is not None:
            return _params_face_crop(track, frame_idx, ctx)
        return None
    if seg.layout == "person_close":
        return _params_person_close(seg, frame_idx, ctx)
    if seg.layout == "screen_full":
        return _params_screen_full(frame_idx, ctx)
    if seg.layout in ("wide_default", "wide_group"):
        return _params_wide_default(ctx)
    return None  # pip / split — выходят через старые рендеры


def _subject_key(seg: SceneSegment, ctx: RenderCtx) -> tuple:
    """Идентификатор «кого/что показываем» для сегмента.

    Используется чтобы понять, является ли переход seg→seg сменой субъекта.
    speaker_close pid=A → speaker_close pid=B (A≠B) = разные субъекты → hard cut.
    speaker_close pid=A → person_close pid=P, если face_to_person[A]==P → ТОТ ЖЕ
    человек, плавный transition. wide_*/screen_full — отдельные субъекты, но
    переход к/от них допускает плавный zoom (не hard cut).
    """
    lay = seg.layout
    pid = seg.primary_face_id
    if lay in ("speaker_close", "active_speaker_close"):
        # speaker идентифицируется лицом + соответствующим person'ом (если есть mapping)
        linked_person = (ctx.face_to_person or {}).get(pid) if pid is not None else None
        return ("speaker", pid, linked_person)
    if lay == "person_close":
        # person идентифицируется person_id + face которое к нему привязано
        face_to_person = ctx.face_to_person or {}
        linked_face = next((f for f, p in face_to_person.items() if p == pid), None)
        return ("person", pid, linked_face)
    if lay == "screen_full":
        return ("screen", seg.primary_screen_idx)
    return (lay,)


def _subjects_match(a: tuple, b: tuple) -> bool:
    """Совпадают ли два subject_key — учитываем cross-link face<->person."""
    if a == b:
        return True
    # speaker_close A ↔ person_close P, если P == face_to_person[A]
    if a[0] == "speaker" and b[0] == "person":
        # a = ("speaker", face_id, linked_person), b = ("person", person_id, linked_face)
        return a[2] is not None and a[2] == b[1]
    if a[0] == "person" and b[0] == "speaker":
        return b[2] is not None and b[2] == a[1]
    return False


def build_camera_plan(
    segments: list[SceneSegment],
    start_f: int,
    end_f: int,
    ctx: RenderCtx,
    sigma_frames: float = 8.0,
    cut_threshold_px: float = 250.0,
) -> CamPlan:
    """Pre-compute camera plan and smooth WITHIN contiguous regions.

    Cuts between разными субъектами НЕ сглаживаются — иначе при переключении
    speaker_close A → speaker_close B появляется «фантомный» кадр посередине,
    где камера зависла между двумя лицами с пустым curtain'ом по бокам.

    Две независимые сигнала для cut'а:
    1. Граница сегмента + изменение субъекта (face_id / person_id) →
       ВСЕГДА hard cut, даже если cx-delta < threshold (два спикера могут
       сидеть близко по центру кадра).
    2. Большая дельта cx/cy между соседними кадрами (>cut_threshold_px) —
       страховка на случай некорректной классификации.

    sigma_frames=8 (~0.27с @ 30fps) внутри региона → плавный zoom/pan между
    близкими layout'ами (speaker_close ↔ screen_full, speaker ↔ person того же
    человека). Между регионами — hard cut, как у редактора.
    """
    from scipy.ndimage import gaussian_filter1d

    n = max(0, end_f - start_f)
    cx_arr = np.zeros(n)
    cy_arr = np.zeros(n)
    h_arr = np.zeros(n)
    valid = np.zeros(n, dtype=bool)
    fps = ctx.meta.fps

    def find_segment(t: float) -> SceneSegment:
        for s in segments:
            if s.start <= t < s.end:
                return s
        return segments[-1] if segments else SceneSegment(0, 0, "wide_default")

    # per-frame seg + subject key
    seg_per_frame: list[SceneSegment] = []
    subject_per_frame: list[tuple] = []
    for i in range(n):
        fi = start_f + i
        t = i / fps
        seg = find_segment(t)
        seg_per_frame.append(seg)
        subject_per_frame.append(_subject_key(seg, ctx))
        params = _params_for_segment(seg, fi, ctx)
        if params is not None:
            cx_arr[i], cy_arr[i], h_arr[i] = params
            valid[i] = True

    if not valid.any():
        return CamPlan(cx_arr, cy_arr, h_arr, valid, start_f)

    # ⭐ детектим резы из ТРЁХ источников:
    # (a) граница сегмента + смена субъекта → ВСЕГДА hard cut
    # (b) source cut (cv2-detected scene change в исходнике) → ВСЕГДА hard cut
    # (c) большая дельта cx/cy между соседними valid-кадрами (страховка)
    cuts = {0, n}
    # (a) subject change at segment boundary
    for i in range(1, n):
        if not _subjects_match(subject_per_frame[i], subject_per_frame[i-1]):
            cuts.add(i)
    # (b) source cuts within window
    for c in (ctx.cuts_set or set()):
        rel = c - start_f
        if 0 < rel < n:
            cuts.add(rel)
    cuts_sorted = sorted(cuts)

    # interp+smooth ПО РЕГИОНАМ (между cut'ами), а не глобально — иначе invalid
    # frames на границе одного региона тянули бы валидные значения из соседнего.
    final_valid = np.zeros(n, dtype=bool)
    cx_s = np.zeros(n)
    cy_s = np.zeros(n)
    h_s = np.zeros(n)
    for k in range(len(cuts_sorted) - 1):
        a, b = cuts_sorted[k], cuts_sorted[k+1]
        if b <= a:
            continue
        region_valid = valid[a:b]
        if not region_valid.any():
            # весь регион без валидных кадров — оставляем invalid, рендер уйдёт в fallback layout
            continue
        r_idx = np.arange(b - a)
        v_idx = np.where(region_valid)[0]
        cx_r = np.interp(r_idx, v_idx, cx_arr[a:b][region_valid])
        cy_r = np.interp(r_idx, v_idx, cy_arr[a:b][region_valid])
        h_r = np.interp(r_idx, v_idx, h_arr[a:b][region_valid])
        # (c) safety: внутри региона тоже бывают большие скачки — режем ещё раз
        sub_cuts = [0]
        for j in range(1, b - a):
            d = max(abs(cx_r[j] - cx_r[j-1]), abs(cy_r[j] - cy_r[j-1]))
            if d > cut_threshold_px:
                sub_cuts.append(j)
        sub_cuts.append(b - a)
        for s_k in range(len(sub_cuts) - 1):
            sa, sb = sub_cuts[s_k], sub_cuts[s_k + 1]
            if sb - sa >= 2:
                cx_s[a + sa:a + sb] = gaussian_filter1d(cx_r[sa:sb], sigma=sigma_frames, mode="nearest")
                cy_s[a + sa:a + sb] = gaussian_filter1d(cy_r[sa:sb], sigma=sigma_frames, mode="nearest")
                h_s[a + sa:a + sb] = gaussian_filter1d(h_r[sa:sb], sigma=sigma_frames, mode="nearest")
            else:
                cx_s[a + sa:a + sb] = cx_r[sa:sb]
                cy_s[a + sa:a + sb] = cy_r[sa:sb]
                h_s[a + sa:a + sb] = h_r[sa:sb]
        final_valid[a:b] = True

    return CamPlan(cx_s, cy_s, h_s, final_valid, start_f)


def _render_from_plan(frame: np.ndarray, plan_params: tuple[float, float, int], ctx: RenderCtx) -> np.ndarray:
    cx, cy, crop_h = plan_params
    crop_h = max(1, min(crop_h, ctx.meta.src_h))
    crop_w = int(round(crop_h * 9 / 16))
    crop_w = min(crop_w, ctx.meta.src_w)
    crop = _crop_centered(frame, cx, cy, crop_w, crop_h)
    return _resize(crop, ctx.target_w, ctx.target_h)


# ─────────────────────────── публичный API ───────────────────────────


def render_clip(
    *,
    video_path: Path,
    segments: list[SceneSegment],
    tracks: list[FaceTrack],
    screens: list[ScreenRegion],
    meta: VideoMeta,
    out_path: Path,
    start: float = 0.0,
    end: Optional[float] = None,
    target_w: int = 1080,
    target_h: int = 1920,
    on_progress: Optional[Callable[[float, str], None]] = None,
    person_tracks: list[FaceTrack] = None,
    cuts: list[int] = None,
    face_to_person: dict[int, int] = None,
) -> Path:
    """Рендер клипа [start, end] с применением SceneSegment'ов через layout renderers."""
    end = end if end is not None else meta.duration
    fps = meta.fps

    cap = cv2.VideoCapture(str(video_path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(start * fps))

    # ⭐ ffmpeg pipe вместо mp4v — настоящий H.264 yuv420p без артефактов
    ff_cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{target_w}x{target_h}",
        "-pix_fmt", "bgr24",
        "-r", str(fps),
        "-i", "-",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out_path),
    ]
    ff = subprocess.Popen(ff_cmd, stdin=subprocess.PIPE)
    writer = None  # для совместимости с проверкой ниже

    # ⭐ deadband пропорционален размеру кадра, но не меньше «комфортного» порога:
    # большой deadband на низком разрешении предотвращает дёрганье на шумной детекции лиц.
    # max_velocity тоже пропорционален — иначе камера будет не успевать.
    # Подняли минимумы (40→70px, 20→22px), чтобы микро-движения головы спикера
    # не таскали камеру влево-вправо при разговоре.
    deadband = max(70, int(meta.src_w * 0.06))   # 6% ширины кадра, минимум 70px
    max_v = max(22, int(meta.src_w * 0.014))     # 1.4% ширины за кадр, минимум 22px

    ctx = RenderCtx(
        meta=meta,
        target_w=target_w, target_h=target_h,
        tracks=tracks, screens=screens,
        face_followers={}, screen_ema=EMA2D(),
        tracks_persons=person_tracks or [],
        deadband_px=deadband, max_velocity_px=max_v,
        face_to_person=face_to_person or {},
        last_face_pos_by_person={},
        cuts_set=set(cuts or []),
    )

    start_f = int(start * fps)
    end_f = int(end * fps)

    # быстрый поиск активного сегмента по времени
    def find_segment(t: float) -> SceneSegment:
        for s in segments:
            if s.start <= t < s.end:
                return s
        return segments[-1] if segments else SceneSegment(0, end - start, "wide_default")

    # ⭐ pre-pass: считаем (cx, cy, crop_h) для каждого кадра по сегменту, потом
    # Gaussian-сглаживаем через границы. Это превращает hard-cut между
    # speaker_close и screen_full в плавный zoom/pan за ~0.5с.
    ctx.camera_plan = build_camera_plan(segments, start_f, end_f, ctx, sigma_frames=8.0)

    last_seg_layout: Optional[LayoutType] = None
    cuts_set = set(cuts or [])
    total = max(1, end_f - start_f)

    for i, fi in enumerate(range(start_f, end_f)):
        ok, frame = cap.read()
        if not ok:
            break
        t_in_clip = (fi - start_f) / fps  # время от начала вырезанного клипа
        seg = find_segment(t_in_clip)

        # cut'ы больше не сбрасывают follower'ы — мы их не используем; камера plan
        # уже учитывает границы сегментов через smoothing
        if seg.layout != last_seg_layout:
            ctx.screen_ema = EMA2D()
            last_seg_layout = seg.layout

        # ⭐ smoothable layouts → используем сглаженный camera_plan;
        # special layouts (pip, split) — через старые рендеры
        plan_params = ctx.camera_plan.get(fi) if seg.layout in _SMOOTHABLE_LAYOUTS else None
        if plan_params is not None:
            out_frame = _render_from_plan(frame, plan_params, ctx)
        else:
            renderer = _LAYOUT_RENDERERS.get(seg.layout, _render_wide_default)
            out_frame = renderer(frame, seg, fi, ctx)
        # пишем сырые BGR байты в ffmpeg
        try:
            ff.stdin.write(out_frame.tobytes())
        except (BrokenPipeError, OSError):
            break

        if on_progress and i % 60 == 0:
            on_progress(min(99.0, i / total * 100), f"кадр {i}/{total} · {seg.layout}")

    try:
        ff.stdin.close()
    except Exception:
        pass
    ff.wait(timeout=120)
    cap.release()
    return out_path
