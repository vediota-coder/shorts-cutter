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
        target_alpha: float = 0.18,     # вход EMA — после median'а (0.30 → 0.18: спокойнее реакция)
        alpha: float = 0.12,            # ускорение камеры (0.14 → 0.12)
        damping: float = 0.78,          # инерция — для плавных движений (0.74 → 0.78)
        deadband_px: float = 70.0,      # «комфортная зона» — нечувствительно к покачиванию (50 → 70)
        max_velocity_px: float = 22.0,  # верхняя планка скорости (24 → 22)
        catch_up_threshold: float = 250.0,  # ⭐ 600 → 250: при резких сменах ракурса/cut снапаем мгновенно
        median_window: int = 15,        # ⭐ 15 ≈ 0.5с@30fps (было 9 = 0.3с) — гасит колебания спикера
        h_alpha: float = 0.06,          # ⭐ EMA на crop_h — медленный, чтобы зум не пилил
        h_change_threshold_ratio: float = 0.04,  # ⭐ deadband по высоте: <4% изменения игнорим
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

    def stitch_from(self, other: "DampedFollower") -> None:
        """Перенять state соседнего follower'а — anti-jump при смене track_id.

        Копируем cx/cy/vx/vy/ch и буферы медианы, чтобы новая «камера» продолжила
        ровно с того места, где была старая, без скачка (включая высоту кропа).
        """
        if other.cx is None:
            return
        self.cx, self.cy = other.cx, other.cy
        self.tx, self.ty = other.tx, other.ty
        self.vx, self.vy = other.vx * 0.5, other.vy * 0.5  # часть скорости теряем
        self._buf_x = list(other._buf_x)[-self._win:]
        self._buf_y = list(other._buf_y)[-self._win:]
        # ⭐ переносим и сглаженную высоту, чтобы зум не дёргался при смене трека
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


def get_or_create_follower(
    ctx: "RenderCtx",
    track_id: int,
    frame_idx: int,
    seed_x: float,
    seed_y: float,
    *,
    deadband_px: float | None = None,
    max_velocity_px: float | None = None,
    stitch_window_frames: int = 30,   # ⭐ 15 → 30 (1с@30fps): больше шансов подцепить соседа
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
            f.stitch_from(ctx.face_followers[best_tid])
        ctx.face_followers[track_id] = f

    ctx.follower_last_seen[track_id] = frame_idx
    return f


# ─────────────────────────── layout renderers ───────────────────────────


def _render_face_crop(frame: np.ndarray, track: FaceTrack, frame_idx: int, ctx: RenderCtx,
                     padding_ratio: float = 1.6) -> np.ndarray:
    """Закадровка по лицу с padding'ом, headroom rule (лицо в верхней трети)
    и safe margin от краёв исходного кадра.

    crop_h сглажен через follower.smooth_h() — иначе zoom пилит на per-frame
    шуме MediaPipe-детектора (bbox.h гуляет ±5-10% даже на неподвижной голове).
    """
    raw_bbox = _bbox_at(track, frame_idx)
    bbox = raw_bbox or BBox(
        ctx.meta.src_w / 2 - 50, ctx.meta.src_h / 2 - 60, 100, 120,
    )
    import os as _os
    if _os.environ.get("SR_TRACE") == "1":
        kind = "face" if raw_bbox else "DEFAULT"
        print(f"[face_crop] f={frame_idx} fid={track.track_id} bbox_kind={kind} "
              f"bbox(cx={bbox.cx:.0f},cy={bbox.cy:.0f},w={bbox.w:.0f},h={bbox.h:.0f})", flush=True)

    follower = get_or_create_follower(
        ctx, track.track_id, frame_idx, bbox.cx, bbox.cy,
    )

    # ⭐ хотим показать голову+плечи+грудь: ~4.5× высоты лица под 9:16,
    # но сглаживаем target высоту через EMA, чтобы избавиться от zoom-yoyo
    raw_target_h = bbox.h * 4.5
    raw_target_h = max(raw_target_h, ctx.target_h // 3)  # минимальный зум
    raw_target_h = min(raw_target_h, ctx.meta.src_h)
    crop_h = int(round(follower.smooth_h(raw_target_h)))
    crop_h = max(1, min(crop_h, ctx.meta.src_h))
    crop_w = int(round(crop_h * 9 / 16))
    crop_w = min(crop_w, ctx.meta.src_w)

    # ⭐ headroom: лицо в ВЕРХНЕЙ трети кропа → центр кропа НИЖЕ лица.
    # y растёт вниз, потому центр = bbox.cy + (crop_h * 0.18 - bbox.h * 0.5)
    # это ставит верх лба примерно на 12% высоты кропа от верха.
    target_cx = bbox.cx
    target_cy = bbox.cy + crop_h * 0.18 - bbox.h * 0.5

    # ⭐ safe margin: если лицо у края исходника, не зажимаем кроп слишком жёстко.
    # Гарантируем что bbox остаётся в горизонтально-центральной 80% полосе кропа.
    half_w = crop_w / 2
    safe_x_min = bbox.cx - crop_w * 0.4
    safe_x_max = bbox.cx + crop_w * 0.4
    target_cx = max(safe_x_min + half_w, min(safe_x_max + half_w - crop_w, target_cx))
    # вертикально — лицо должно быть выше центра, но не выпадать из кропа
    half_h = crop_h / 2
    safe_y_min = bbox.cy - crop_h * 0.35  # лицо может быть на 35% выше центра, но не выше
    safe_y_max = bbox.cy + crop_h * 0.10  # вниз почти не сдвигаем
    target_cy = max(safe_y_min, min(safe_y_max, target_cy))

    cx, cy = follower.update(target_cx, target_cy)
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
    no_recent_face = _bbox_at(track, frame_idx) is None  # search_window=6 default
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
    cx, cy = ctx.screen_ema.update(bbox.cx, bbox.cy)
    # вертикальный кроп под 9:16, охватывающий экран целиком
    crop_h = int(min(ctx.meta.src_h, max(bbox.h * 1.05, ctx.meta.src_h * 0.95)))
    crop_w = int(round(crop_h * 9 / 16))
    crop_w = min(crop_w, ctx.meta.src_w)

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
    bbox = _bbox_at(person_track, frame_idx, search_window=12)
    if bbox is None:
        return _render_wide_default(frame, seg, frame_idx, ctx)

    follower = get_or_create_follower(
        ctx, seg.primary_face_id, frame_idx, bbox.cx, bbox.cy,
        deadband_px=ctx.deadband_px * 1.5,  # person_close — крупный план, можно деаднее
    )

    # ⭐ при создании нового follower'а (первая person_close после cut'а) пре-заполняем
    # _buf_h медианой bbox.h из СЛЕДУЮЩИХ 10 кадров person track'а. Это убирает
    # zoom-out на 0.4с после cut'а: первый bbox YOLO часто транзитный и больше
    # стабильного значения, без lookahead'а ch инициализируется на этом выбросе.
    if follower.ch is None and not follower._buf_h:
        person_track = next(
            (p for p in (ctx.tracks_persons or []) if p.track_id == seg.primary_face_id),
            None,
        )
        if person_track is not None:
            future_hs = sorted(
                d.bbox.h for d in person_track.detections
                if frame_idx <= d.frame_idx <= frame_idx + 30
            )[:10]
            if len(future_hs) >= 3:
                # медиана будущих 10 кадров — устойчива к выбросу первого кадра
                lookahead_h = future_hs[len(future_hs) // 2]
                lookahead_target = max(lookahead_h * 1.15, ctx.meta.src_h * 0.6)
                lookahead_target = min(lookahead_target, ctx.meta.src_h)
                # пре-заполняем буфер медианой → smooth_h первый вызов вернёт стабильную ch
                for _ in range(min(5, follower._win)):
                    follower._buf_h.append(lookahead_target)
                follower.ch = lookahead_target

    # ⭐ сглаженная высота, иначе на дрожащем YOLO-bbox персоны зум прыгает
    raw_target_h = max(bbox.h * 1.15, ctx.meta.src_h * 0.6)
    raw_target_h = min(raw_target_h, ctx.meta.src_h)
    crop_h = int(round(follower.smooth_h(raw_target_h)))
    crop_h = max(1, min(crop_h, ctx.meta.src_h))
    crop_w = int(round(crop_h * 9 / 16))
    crop_w = min(crop_w, ctx.meta.src_w)

    # ⭐ ИЩЕМ РЕАЛЬНОЕ ЛИЦО на этом кадре через MediaPipe с пониженным conf=0.25.
    # YOLO body bbox.cx часто не совпадает с позицией головы (рука/плечо расширяет bbox).
    # MediaPipe в wide-shot подкаста при conf=0.25 находит лица, которые основной
    # пайплайн (conf=0.5) пропускает. Это ЕДИНСТВЕННЫЙ надёжный способ центрироваться
    # на голове, а не на торсе.
    face_pos = _detect_face_low_conf(frame, ctx, bbox)
    if face_pos is not None:
        cx = face_pos[0]
        cy = face_pos[1] + bbox.h * 0.20  # cy чуть ниже лица (плечи в кадре)
        cy_source = "mediapipe"
    else:
        cx = bbox.cx
        cy = bbox.y + bbox.h * 0.45
        cy_source = "bbox"

    target_cx_pre = cx
    cx, cy = follower.update(cx, cy)
    import os as _os
    if _os.environ.get("SR_TRACE") == "1":
        print(f"[person_close] f={frame_idx} pid={seg.primary_face_id} "
              f"src={cy_source} bbox.h={bbox.h:.0f} raw_target_h={raw_target_h:.0f} "
              f"smooth_h={crop_h} ch={follower.ch} bbox.cx={bbox.cx:.0f} "
              f"target_cx={target_cx_pre:.0f} follower_cx={cx:.0f} crop_w={crop_w}", flush=True)
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

    last_seg_layout: Optional[LayoutType] = None
    cuts_set = set(cuts or [])
    total = max(1, end_f - start_f)

    for i, fi in enumerate(range(start_f, end_f)):
        ok, frame = cap.read()
        if not ok:
            break
        t_in_clip = (fi - start_f) / fps  # время от начала вырезанного клипа
        seg = find_segment(t_in_clip)

        # ⭐ только на cut'ах (смена ракурса камеры) сбрасываем follower'ы — иначе
        # camera 0.5с догоняет новую позицию субъекта (при cut близких ракурсов
        # bbox.cx делает скачок 300+px, и плавный follow раздражает).
        # На смене сегмента (тот же ракурс) НЕ ресетим — иначе видимый рывок при
        # переключении speaker_close ↔ active_speaker_close на том же лице.
        if fi in cuts_set:
            ctx.face_followers.clear()
            ctx.screen_ema = EMA2D()

        if seg.layout != last_seg_layout:
            ctx.screen_ema = EMA2D()
            last_seg_layout = seg.layout

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
