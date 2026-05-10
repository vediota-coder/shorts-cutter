"""Smart reframe pipeline: оркестратор всех этапов.

    analyze_video(src) →
        SmartAnalysis(tracks, screens, asd_per_frame, meta)

    render_smart(src, analysis, segments, out, start, end) →
        out.mp4

Сегменты можно строить через build_scenes(analysis, transcript_segments).
Корекции применяются как override на сегменты перед рендером.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .asd import compute_lip_motion, active_speaker_per_frame_lip
from .asd import lr_asd as _lr_asd_mod
from .detect import (
    detect_cuts, detect_faces, detect_persons, detect_screens, link_face_to_person,
)
from .layout import render_clip
from .scene import classify_scenes, ClassifierConfig, DEFAULT_CONFIG
from .types import (
    BBox,
    FaceTrack,
    FrameCorrection,
    SceneSegment,
    ScreenRegion,
    VideoMeta,
)


ProgressFn = Callable[[float, str], None]


@dataclass
class SmartAnalysis:
    meta: VideoMeta
    tracks: list[FaceTrack]
    screens: list[ScreenRegion]
    asd_per_frame: dict[int, int]  # frame_idx → track_id (-1 если никто)
    lip_motion_energy: dict[int, dict[int, float]] = field(default_factory=dict)
    person_tracks: list[FaceTrack] = field(default_factory=list)  # YOLO person tracks
    face_to_person: dict[int, int] = field(default_factory=dict)   # face_id → person_id
    cuts: list[int] = field(default_factory=list)  # frame_idx где обнаружен cut


def analyze_video(
    video_path: Path,
    on_progress: Optional[ProgressFn] = None,
    time_ranges: Optional[list[tuple[float, float]]] = None,
    streaming: Optional[bool] = None,
) -> SmartAnalysis:
    """Полный анализ исходника: лица + экраны + активный спикер.

    time_ranges — если задано, AI-инференс выполняется только для кадров,
    попадающих в эти временные интервалы (в секундах).

    streaming — если True (или env EXCELLA_STREAMING_ANALYZE=1), все 4 детектора
    (faces, persons, screens, cuts) работают в едином цикле декодирования —
    1× cv2.VideoCapture вместо 4× (Phase 1 #5). Дефолт None → берётся из env.
    """
    import os as _os
    if streaming is None:
        streaming = _os.environ.get("EXCELLA_STREAMING_ANALYZE", "0") == "1"

    def stage_progress(stage: str, w0: float, w1: float):
        def emit(pct: float, msg: str):
            if on_progress:
                global_pct = w0 + (w1 - w0) * pct / 100.0
                on_progress(global_pct, f"{stage}: {msg}")
        return emit

    if streaming:
        from .streaming import analyze_video_streaming
        if on_progress:
            on_progress(0, "STREAMING: один проход для всех детекторов")
        tracks, persons, screens, cuts, meta = analyze_video_streaming(
            video_path, on_progress=stage_progress("stream", 0, 80),
            time_ranges=time_ranges,
        )
        face_to_person = link_face_to_person(tracks, persons)

        if meta.is_vertical:
            if on_progress:
                on_progress(100, f"исходник {meta.src_w}x{meta.src_h} (вертикальный) — reframe не нужен")
            return SmartAnalysis(
                meta=meta, tracks=tracks, screens=[],
                asd_per_frame={}, lip_motion_energy={},
                person_tracks=[], face_to_person={}, cuts=[],
            )

        if _lr_asd_mod._is_available():
            if on_progress:
                on_progress(80, "активный спикер (LR-ASD ML)")
            try:
                speaking_probs = _lr_asd_mod.predict_speaking_probs(
                    video_path, tracks, meta.fps,
                    on_progress=lambda pct, msg: stage_progress("lr_asd", 80, 95)(pct, msg)
                    if on_progress else None,
                )
                asd = _lr_asd_mod.active_speaker_per_frame(speaking_probs)
                energy = {}
            except Exception as e:
                if on_progress:
                    on_progress(80, f"⚠ LR-ASD ошибка ({e}), fallback на lip-motion")
                energy = compute_lip_motion(video_path, tracks)
                asd = active_speaker_per_frame_lip(energy, fps=meta.fps)
        else:
            if on_progress:
                on_progress(80, "активный спикер (lip motion fallback)")
            energy = compute_lip_motion(video_path, tracks)
            asd = active_speaker_per_frame_lip(energy, fps=meta.fps)

        if on_progress:
            on_progress(100, f"готово (streaming): {len(tracks)} лиц, "
                             f"{len(persons)} людей, {len(screens)} экранов, {len(cuts)} cut'ов")

        return SmartAnalysis(
            meta=meta, tracks=tracks, screens=screens,
            asd_per_frame=asd, lip_motion_energy=energy,
            person_tracks=persons, face_to_person=face_to_person,
            cuts=cuts,
        )

    # ── Legacy: 4 отдельных детектора (по умолчанию)
    if on_progress:
        on_progress(0, "детекция лиц")
    tracks, meta = detect_faces(
        video_path, on_progress=stage_progress("faces", 0, 25),
        time_ranges=time_ranges,
    )

    # ⭐ если исходник уже вертикальный — пропускаем тяжёлые шаги, считаем как pass-through
    if meta.is_vertical:
        if on_progress:
            on_progress(100, f"исходник уже {meta.src_w}x{meta.src_h} (вертикальный) — reframe не нужен")
        return SmartAnalysis(
            meta=meta, tracks=tracks, screens=[],
            asd_per_frame={}, lip_motion_energy={},
            person_tracks=[], face_to_person={}, cuts=[],
        )

    # bbox-индекс для подсказки screen-детектору
    face_by_frame: dict[int, list[BBox]] = {}
    for t in tracks:
        for d in t.detections:
            face_by_frame.setdefault(d.frame_idx, []).append(d.bbox)

    if on_progress:
        on_progress(25, "детекция людей (YOLO person)")
    persons = detect_persons(
        video_path, on_progress=stage_progress("persons", 25, 45),
        time_ranges=time_ranges,
    )
    face_to_person = link_face_to_person(tracks, persons)

    if on_progress:
        on_progress(45, "детекция экранов")
    screens = detect_screens(
        video_path, face_bboxes_per_frame=face_by_frame,
        on_progress=stage_progress("screens", 45, 70),
        time_ranges=time_ranges,
    )

    if on_progress:
        on_progress(70, "детекция склеек (cuts)")
    cuts = detect_cuts(
        video_path, on_progress=stage_progress("cuts", 70, 80),
        time_ranges=time_ranges,
    )

    # ⭐ ASD: пробуем LR-ASD (ML, точнее), fallback на lip-motion
    if _lr_asd_mod._is_available():
        if on_progress:
            on_progress(80, "активный спикер (LR-ASD ML)")
        try:
            speaking_probs = _lr_asd_mod.predict_speaking_probs(
                video_path, tracks, meta.fps,
                on_progress=lambda pct, msg: stage_progress("lr_asd", 80, 95)(pct, msg)
                if on_progress else None,
            )
            asd = _lr_asd_mod.active_speaker_per_frame(speaking_probs)
            energy = {}  # не нужен при ML-ASD
        except Exception as e:
            if on_progress:
                on_progress(80, f"⚠ LR-ASD ошибка ({e}), fallback на lip-motion")
            energy = compute_lip_motion(video_path, tracks)
            asd = active_speaker_per_frame_lip(energy, fps=meta.fps)
    else:
        if on_progress:
            on_progress(80, "активный спикер (lip motion fallback)")
        energy = compute_lip_motion(video_path, tracks)
        asd = active_speaker_per_frame_lip(energy, fps=meta.fps)

    if on_progress:
        on_progress(100,
            f"готово: {len(tracks)} лиц, {len(persons)} людей, "
            f"{len(screens)} экранов, {len(cuts)} cut'ов")

    return SmartAnalysis(
        meta=meta, tracks=tracks, screens=screens,
        asd_per_frame=asd, lip_motion_energy=energy,
        person_tracks=persons, face_to_person=face_to_person,
        cuts=cuts,
    )


def build_scenes(
    analysis: SmartAnalysis,
    speech_segments: list[tuple[float, float]],
    transcript_words: list[tuple[float, str]],
    cfg: ClassifierConfig = DEFAULT_CONFIG,
) -> list[SceneSegment]:
    """Строит SceneSegment'ы через rule-based classifier."""
    return classify_scenes(
        tracks=analysis.tracks,
        screens=analysis.screens,
        active_speaker_per_frame=analysis.asd_per_frame,
        speech_segments=speech_segments,
        transcript_words=transcript_words,
        meta=analysis.meta,
        cfg=cfg,
        persons=analysis.person_tracks,
        cuts=analysis.cuts,
        face_to_person=analysis.face_to_person,
    )


def apply_corrections(
    segments: list[SceneSegment],
    corrections: list[FrameCorrection],
    fps: float,
) -> list[SceneSegment]:
    """Применяет ручные коррекции — override на куски сегментов.

    Если коррекция перекрывает середину сегмента — сегмент режется на 2-3 части.
    """
    if not corrections:
        return segments

    out: list[SceneSegment] = []
    for seg in segments:
        seg_start_f = int(seg.start * fps)
        seg_end_f = int(seg.end * fps)
        # ищем все коррекции, которые попали в этот сегмент
        relevant = [c for c in corrections
                    if c.frame_range[0] < seg_end_f and c.frame_range[1] > seg_start_f]
        if not relevant:
            out.append(seg)
            continue

        # сортируем по началу
        relevant.sort(key=lambda c: c.frame_range[0])
        cursor_f = seg_start_f
        for c in relevant:
            cs, ce = c.frame_range
            cs = max(cs, seg_start_f)
            ce = min(ce, seg_end_f)
            if cursor_f < cs:
                out.append(SceneSegment(
                    start=cursor_f / fps, end=cs / fps,
                    layout=seg.layout, primary_face_id=seg.primary_face_id,
                    primary_screen_idx=seg.primary_screen_idx,
                ))
            out.append(SceneSegment(
                start=cs / fps, end=ce / fps,
                layout=c.layout,
                primary_face_id=c.primary_face_id,
                primary_screen_idx=c.primary_screen_idx,
                overridden=True, reason=c.note,
            ))
            cursor_f = ce
        if cursor_f < seg_end_f:
            out.append(SceneSegment(
                start=cursor_f / fps, end=seg_end_f / fps,
                layout=seg.layout, primary_face_id=seg.primary_face_id,
                primary_screen_idx=seg.primary_screen_idx,
            ))
    return out


def render_smart(
    *,
    video_path: Path,
    analysis: SmartAnalysis,
    segments: list[SceneSegment],
    out_path: Path,
    start: float = 0.0,
    end: Optional[float] = None,
    target_w: int = 1080,
    target_h: int = 1920,
    on_progress: Optional[ProgressFn] = None,
) -> Path:
    """Рендер клипа [start, end] с применением SceneSegment'ов."""
    return render_clip(
        video_path=video_path,
        segments=segments,
        tracks=analysis.tracks,
        screens=analysis.screens,
        meta=analysis.meta,
        out_path=out_path,
        start=start, end=end,
        target_w=target_w, target_h=target_h,
        on_progress=on_progress,
        person_tracks=analysis.person_tracks,
        cuts=analysis.cuts,
        face_to_person=analysis.face_to_person,
    )
