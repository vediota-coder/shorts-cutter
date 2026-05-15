"""Scene classifier: правило-основанный выбор layout'а на каждый сегмент.

Вход: для каждого момента времени имеем
- face_tracks (все лица с ID)
- screen_regions (детектированные экраны/доски)
- active_speaker_per_frame (из lip-motion или Light-ASD)
- transcript segments с word timestamps (из Whisper)

Выход: список SceneSegment'ов — кусков клипа с одним layout'ом каждый.
Соседние сегменты должны быть достаточно длинные (мин. 1.0 сек), чтобы
не было «дёргания» layout'ов.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..types import (
    FaceTrack,
    ScreenRegion,
    SceneSegment,
    LayoutType,
    VideoMeta,
)


# слова-указатели — спикер ссылается на визуальный материал
DEICTIC_WORDS = {
    "вот", "здесь", "тут", "смотрите", "посмотрим", "вот это", "этот",
    "эта", "видите", "видно", "обратите внимание", "слева", "справа",
    "сверху", "снизу", "наверху", "выше", "ниже", "там",
    # английские для смешанной речи
    "here", "this", "look", "see", "watch", "above", "below", "right here",
}


@dataclass
class ClassifierConfig:
    min_segment_sec: float = 2.0             # ⭐ 1.0 → 2.0: даёт камере «осесть» на спикере
    transition_blend_sec: float = 0.4
    pip_screen_min_area_ratio: float = 0.10  # экран должен занимать ≥10% кадра
    pip_face_min_area_ratio: float = 0.005   # ...а лицо ≥0.5%
    # ⭐ для случая n_faces==1 + big_screen: если лицо ≤ этого порога,
    # переключаемся в pip_speaker_screen вместо speaker_close (экран как
    # основной контент, лицо в углу — talking-head + screen-share).
    pip_face_max_for_screen_ratio: float = 0.06
    wide_threshold_faces: int = 4            # 4+ лиц → wide_group
    # ⭐ слияние соседних сегментов с одинаковым layout, но разным primary_face_id:
    # если суммарная длительность таких микро-кусков мала, выбираем доминирующий face_id.
    same_layout_merge_max_sec: float = 4.0   # если соседи короче этого — мерджим
    speaker_layouts_for_merge: tuple[str, ...] = ("speaker_close", "active_speaker_close")


DEFAULT_CONFIG = ClassifierConfig()


def _has_deictic(words_in_window: list[str]) -> bool:
    txt = " ".join(words_in_window).lower()
    return any(w in txt for w in DEICTIC_WORDS)


_CLASSIFY_SEARCH_WINDOW = 6  # кадров — совпадает с render.py _bbox_at default


def _faces_at_time(tracks: list[FaceTrack], frame_idx: int) -> list[tuple[int, "BBox"]]:  # noqa: F821
    out = []
    for t in tracks:
        b = t.bbox_at(frame_idx, search_window=_CLASSIFY_SEARCH_WINDOW)
        if b is not None:
            out.append((t.track_id, b))
    return out


def _persons_at_time(tracks: list[FaceTrack], frame_idx: int) -> list[tuple[int, "BBox"]]:  # noqa: F821
    out = []
    for t in tracks:
        b = t.bbox_at(frame_idx, search_window=_CLASSIFY_SEARCH_WINDOW)
        if b is not None:
            out.append((t.track_id, b))
    return out


def _screens_near(screens: list[ScreenRegion], frame_idx: int, fps: float, window_sec: float = 0.5) -> list[ScreenRegion]:
    win = int(window_sec * fps)
    return [s for s in screens if abs(s.frame_idx - frame_idx) <= win]


def _classify_frame(
    frame_idx: int,
    tracks: list[FaceTrack],
    screens: list[ScreenRegion],
    active_speaker: dict[int, int],
    deictic: bool,
    is_speech: bool,
    meta: VideoMeta,
    cfg: ClassifierConfig,
    persons: list[FaceTrack] = None,
    face_to_person: dict[int, int] = None,
    last_active_face_id: int | None = None,
) -> tuple[LayoutType, dict]:
    """Решение для одного кадра. Сегменты собираются позже из соседних одинаковых решений.

    ⭐ ``face_to_person`` + ``last_active_face_id`` — speaker continuity:
    когда лицо кратковременно теряется детектором, ``person_close`` выбирает
    person'а, привязанного к последнему активному speaker'у, а не самого
    большого по площади (иначе на подкастах кадр уезжает на хоста или в стол).
    """
    faces = _faces_at_time(tracks, frame_idx)
    n_faces = len(faces)
    persons_in_frame = _persons_at_time(persons or [], frame_idx)
    nearby_screens = _screens_near(screens, frame_idx, meta.fps)

    src_area = meta.src_w * meta.src_h
    big_screens = [s for s in nearby_screens if s.bbox.area / src_area >= cfg.pip_screen_min_area_ratio]
    big_screens.sort(key=lambda s: -s.bbox.area)

    asd_id = active_speaker.get(frame_idx, -1)

    extra: dict = {}

    # ── 0 лиц ──
    if n_faces == 0:
        # если текущее окно не дало экранов — смотрим назад 15с: человек повернулся к доске,
        # тело перекрывает её, но доска никуда не ушла
        if not big_screens and persons_in_frame:
            lookback = _screens_near(screens, frame_idx, meta.fps, window_sec=15.0)
            lb_big = [s for s in lookback if s.bbox.area / src_area >= cfg.pip_screen_min_area_ratio
                      and s.frame_idx <= frame_idx]  # только прошлые детекции
            lb_big.sort(key=lambda s: -s.frame_idx)  # самая последняя
            if lb_big:
                big_screens = [lb_big[0]]
                nearby_screens = lookback
        if big_screens:
            # ⭐ screen_full кропает 9:16 вокруг центра screen.bbox. Если PERSON
            # стоит так что его cx ВНЕ итогового crop_x range — screen_full
            # вырежет его за кадр. Эмулируем кроп классификатором и проверяем.
            screen = big_screens[0]
            sbb = screen.bbox
            # повторяем формулу из _render_screen_full
            crop_h_screen = min(meta.src_h, max(sbb.h * 1.05, meta.src_h * 0.95))
            crop_w_screen = crop_h_screen * 9 / 16
            crop_w_screen = min(crop_w_screen, meta.src_w)
            crop_cx = sbb.cx
            crop_x_min = crop_cx - crop_w_screen / 2
            crop_x_max = crop_cx + crop_w_screen / 2
            person_outside_screen = False
            for _pid, pbb in persons_in_frame:
                # face/head обычно в top 20% person bbox; head_top y ≈ pbb.y
                # если head_y выше screen_top на >20px, screen_full crop с
                # cy=sbb.cy всё равно растянется до full height (crop_h ~95% src_h),
                # но если crop_h меньше src_h, голова может оказаться за пределами.
                if pbb.y < sbb.y - 30 and crop_h_screen < meta.src_h * 0.95:
                    person_outside_screen = True
                    break
                # cx персоны вне горизонтального crop range — main case
                if pbb.cx < crop_x_min - 10 or pbb.cx > crop_x_max + 10:
                    person_outside_screen = True
                    break
            if person_outside_screen:
                extra["reason"] = "person_outside_screen_crop"
                return "wide_default", extra
            extra["primary_screen_idx"] = nearby_screens.index(big_screens[0])
            return "screen_full", extra
        # ⭐ если есть person'ы (YOLO нашёл человека без лица — спина/профиль/далеко) → person_close
        if persons_in_frame:
            if len(persons_in_frame) >= 4:
                return "wide_group", extra
            chosen_pid = None
            # 1) пробуем удержать недавно активного спикера через face_to_person
            if last_active_face_id is not None and face_to_person:
                linked_pid = face_to_person.get(last_active_face_id)
                if linked_pid is not None:
                    if any(pid == linked_pid for pid, _ in persons_in_frame):
                        chosen_pid = linked_pid
            # 2) фолбэк — самый большой по площади (старое поведение)
            if chosen_pid is None:
                persons_in_frame.sort(key=lambda x: -x[1].area)
                chosen_pid = persons_in_frame[0][0]
            extra["primary_face_id"] = chosen_pid  # переиспользуем поле — track_id person'а
            extra["reason"] = "person_no_face"
            return "person_close", extra
        return "wide_default", extra

    # ── 1 лицо ──
    if n_faces == 1:
        face_id, face_bbox = faces[0]
        # ⭐ talking-head + screen-share: если в кадре есть большой экран и лицо
        # сравнительно мелкое (≤6% площади), показываем PiP — экран на фон,
        # лицо в углу. Иначе старое поведение: speaker_close, экран игнорируется
        # (talking-head без демо).
        if big_screens:
            face_area_ratio = face_bbox.area / src_area
            if face_area_ratio <= cfg.pip_face_max_for_screen_ratio:
                extra["primary_face_id"] = face_id
                extra["primary_screen_idx"] = nearby_screens.index(big_screens[0])
                extra["reason"] = "screen_with_face_pip"
                return "pip_speaker_screen", extra
        # лицо видно → спикер крупно
        extra["primary_face_id"] = face_id
        return "speaker_close", extra

    # ── 2-3 лица ──
    if n_faces <= 3:
        if not is_speech:
            return "wide_group", extra
        # есть активный спикер из ASD
        if asd_id >= 0 and any(fid == asd_id for fid, _ in faces):
            extra["primary_face_id"] = asd_id
            # split_screen для интервью на 2 человека если оба «звучали недавно»
            if n_faces == 2:
                # пока без detection «второго недавнего спикера» → simple close на активном
                pass
            return "active_speaker_close", extra
        # ASD не определился — широкий план группы
        return "wide_group", extra

    # ── 4+ лица ──
    return "wide_group", extra


def classify_scenes(
    *,
    tracks: list[FaceTrack],
    screens: list[ScreenRegion],
    active_speaker_per_frame: dict[int, int],
    speech_segments: list[tuple[float, float]],
    transcript_words: list[tuple[float, str]],
    meta: VideoMeta,
    cfg: ClassifierConfig = DEFAULT_CONFIG,
    persons: list[FaceTrack] = None,
    cuts: list[int] = None,
    face_to_person: dict[int, int] = None,
) -> list[SceneSegment]:
    """Прогон по всем кадрам, склейка соседних одинаковых в SceneSegment'ы.

    ⭐ ``face_to_person`` пробрасывается в ``_classify_frame`` для speaker
    continuity: когда лицо теряется, ``person_close`` подхватывает того же
    физического человека, а не «самого большого».
    """
    if meta.n_frames <= 0:
        return []

    # быстрый поиск: «есть ли речь в этом кадре»
    def is_speech_at(t: float) -> bool:
        return any(s <= t <= e for s, e in speech_segments)

    # быстрый поиск: «есть ли deictic слово в окне ±0.5с»
    def deictic_at(t: float) -> bool:
        win = 0.5
        words = [w for ts, w in transcript_words if abs(ts - t) <= win]
        return _has_deictic(words)

    # классификация по кадрам (с шагом, не в каждом — быстрее)
    step = max(1, int(meta.fps / 5))  # 5 решений в секунду
    decisions: list[tuple[int, LayoutType, dict]] = []
    last_active_face_id: int | None = None  # ⭐ удержание спикера через провалы детекта
    for f in range(0, meta.n_frames, step):
        t = f / meta.fps if meta.fps > 0 else 0.0
        layout, extra = _classify_frame(
            frame_idx=f,
            tracks=tracks,
            screens=screens,
            active_speaker=active_speaker_per_frame,
            deictic=deictic_at(t),
            is_speech=is_speech_at(t),
            meta=meta,
            cfg=cfg,
            persons=persons,
            face_to_person=face_to_person,
            last_active_face_id=last_active_face_id,
        )
        # обновляем «последнего активного» только когда классификатор выбрал face-based layout
        if layout in ("speaker_close", "active_speaker_close") and extra.get("primary_face_id") is not None:
            last_active_face_id = extra["primary_face_id"]
        decisions.append((f, layout, extra))

    # склеиваем соседние одинаковые решения в сегменты, разрезая на cut'ах
    cuts_set = set(cuts or [])
    segments: list[SceneSegment] = []
    if not decisions:
        return segments

    cur_start_f, cur_layout, cur_extra = decisions[0]
    for i in range(1, len(decisions)):
        f, layout, extra = decisions[i]
        # cut между cur_start_f и f → принудительная граница на самом cut'е
        cut_in_range = any(cur_start_f < c <= f for c in cuts_set)
        if cut_in_range or layout != cur_layout or extra.get("primary_face_id") != cur_extra.get("primary_face_id"):
            # ⭐ если был cut — закрываем сегмент НА КАДРЕ CUT'А, не на следующем
            # decision-кадре. Иначе кадры между cut и decision рендерятся со старой
            # позицией камеры поверх новой сцены → видимый рывок.
            if cut_in_range:
                cut_f = min(c for c in cuts_set if cur_start_f < c <= f)
                seg_end_f = cut_f
                next_start_f = cut_f
            else:
                seg_end_f = f
                next_start_f = f
            seg = SceneSegment(
                start=cur_start_f / meta.fps,
                end=seg_end_f / meta.fps,
                layout=cur_layout,
                primary_face_id=cur_extra.get("primary_face_id"),
                primary_screen_idx=cur_extra.get("primary_screen_idx"),
                reason=cur_extra.get("reason", ""),
            )
            segments.append(seg)
            cur_start_f, cur_layout, cur_extra = next_start_f, layout, extra
    segments.append(SceneSegment(
        start=cur_start_f / meta.fps,
        end=meta.duration,
        layout=cur_layout,
        primary_face_id=cur_extra.get("primary_face_id"),
        primary_screen_idx=cur_extra.get("primary_screen_idx"),
    ))

    # ⭐ cut_times передаются в merger'ы — слияние не должно перешагивать cut'ы,
    # иначе face_id из предыдущего шота тянется в новый, и renderer удерживает
    # позицию лица, которого в кадре уже нет → «прыжки» камеры.
    cut_times = sorted({c / meta.fps for c in (cuts or [])})

    # фильтр: слишком короткие сегменты сливаем с соседями
    segments = _merge_short_segments(segments, cfg.min_segment_sec, cut_times)
    # ⭐ второй проход: соседи с тем же layout, но разным primary_face_id —
    # сливаем в один кусок с доминирующим face_id (по суммарной длительности).
    # Это убирает микро-перекидывание камеры между двумя спикерами.
    return _merge_same_layout_speakers(
        segments,
        layouts=cfg.speaker_layouts_for_merge,
        max_chunk_sec=cfg.same_layout_merge_max_sec,
        cut_times=cut_times,
    )


def _has_cut_between(start: float, end: float, cut_times: list[float]) -> bool:
    """True если между [start, end) есть source-cut (исключая сам start)."""
    return any(start < c < end for c in cut_times)


def _merge_short_segments(
    segments: list[SceneSegment], min_sec: float,
    cut_times: list[float] | None = None,
) -> list[SceneSegment]:
    """Сегменты короче min_sec поглощаются предыдущим только если совпадают
    (layout, face_id) И между ними нет source-cut.

    Раньше короткий сегмент поглощался безусловно — это тянуло face_id из
    предыдущего шота на новые кадры (после cut'а), и renderer удерживал
    позицию лица, которого в новом шоте уже нет → «прыжки» камеры.
    """
    cut_times = cut_times or []
    if not segments:
        return []
    out = [segments[0]]
    for seg in segments[1:]:
        prev = out[-1]
        seg_dur = seg.end - seg.start
        same_target = (
            prev.layout == seg.layout
            and prev.primary_face_id == seg.primary_face_id
        )
        cut_between = _has_cut_between(prev.end - 0.05, seg.start + 0.05, cut_times)
        if seg_dur < min_sec and same_target and not cut_between:
            out[-1] = SceneSegment(
                start=prev.start, end=seg.end, layout=prev.layout,
                primary_face_id=prev.primary_face_id,
                primary_screen_idx=prev.primary_screen_idx,
                reason=prev.reason,
            )
        else:
            out.append(seg)
    return out


def _merge_same_layout_speakers(
    segments: list[SceneSegment],
    layouts: tuple[str, ...],
    max_chunk_sec: float,
    cut_times: list[float] | None = None,
) -> list[SceneSegment]:
    """Сливает подряд идущие сегменты одного layout-а (из ``layouts``) с разным
    primary_face_id в один кусок с face_id, доминирующим по сумме длительностей.

    Срабатывает только когда каждый отдельный кусок короче max_chunk_sec —
    длинные «настоящие» переключения спикеров не трогаем. Дополнительно: cut
    в source видео блокирует слияние — после cut'а кадры визуально отличаются,
    нельзя удерживать face_id из старого шота.
    """
    cut_times = cut_times or []
    if not segments:
        return []
    out: list[SceneSegment] = []
    i = 0
    n = len(segments)
    while i < n:
        seg = segments[i]
        if seg.layout not in layouts:
            out.append(seg)
            i += 1
            continue
        # копим run одинакового layout'а ПОКА нет cut'а между соседями
        j = i
        run_max_dur = 0.0
        while j < n and segments[j].layout == seg.layout:
            if j > i and _has_cut_between(segments[j - 1].end - 0.05, segments[j].start + 0.05, cut_times):
                break
            d = segments[j].end - segments[j].start
            if d > run_max_dur:
                run_max_dur = d
            j += 1
        # если хоть один кусок длиннее порога — это «настоящее» переключение спикеров,
        # не сливаем (сольёт долгого спикера с коротким перебивщиком).
        if run_max_dur >= max_chunk_sec or j - i <= 1:
            out.extend(segments[i:j])
            i = j
            continue
        # доминирующий face_id по суммарной длительности
        weights: dict[int | None, float] = {}
        for k in range(i, j):
            fid = segments[k].primary_face_id
            weights[fid] = weights.get(fid, 0.0) + (segments[k].end - segments[k].start)
        dominant_fid = max(weights.items(), key=lambda kv: kv[1])[0]
        merged = SceneSegment(
            start=segments[i].start,
            end=segments[j - 1].end,
            layout=seg.layout,
            primary_face_id=dominant_fid,
            primary_screen_idx=segments[i].primary_screen_idx,
            reason=f"merged x{j - i} → fid={dominant_fid}",
        )
        out.append(merged)
        i = j
    return out
