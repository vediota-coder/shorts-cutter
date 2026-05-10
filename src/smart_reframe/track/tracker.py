"""IoU-tracker: склеивает детекции в треки по пересечению bbox'ов между кадрами."""
from __future__ import annotations

from typing import Iterable

from ..types import BBox, FaceDetection, FaceTrack


class IoUTracker:
    """Простой online-tracker.

    Для каждой новой пачки детекций (один кадр) ищем для каждой матч в активных
    треках: bbox с максимальным IoU > threshold. Если нет — заводим новый трек.
    Треки, не видевшие детекций > max_missing_frames, переходят в архив.
    """

    def __init__(self, iou_threshold: float = 0.3, max_missing_frames: int = 30):
        self.iou_threshold = iou_threshold
        self.max_missing_frames = max_missing_frames
        self._tracks: list[FaceTrack] = []
        self._next_id = 0
        # последний кадр, в котором track был замечен
        self._last_seen: dict[int, int] = {}

    def update(self, frame_idx: int, detections: list[FaceDetection]) -> None:
        # активные треки = те, что замечены в последние max_missing_frames кадров
        active_ids = [
            t.track_id for t in self._tracks
            if frame_idx - self._last_seen.get(t.track_id, -1) <= self.max_missing_frames
        ]
        active_tracks = [t for t in self._tracks if t.track_id in active_ids]

        unmatched_dets = list(detections)
        # жадный матч: берём пары (track, det) с максимальным IoU, пока есть кандидаты
        while unmatched_dets and active_tracks:
            best_iou = 0.0
            best_pair: tuple[FaceTrack, FaceDetection] | None = None
            for t in active_tracks:
                last_bbox = self._last_bbox(t)
                if last_bbox is None:
                    continue
                for d in unmatched_dets:
                    iou = last_bbox.iou(d.bbox)
                    if iou > best_iou:
                        best_iou = iou
                        best_pair = (t, d)
            if best_pair is None or best_iou < self.iou_threshold:
                break
            t, d = best_pair
            t.detections.append(d)
            self._last_seen[t.track_id] = frame_idx
            unmatched_dets.remove(d)
            active_tracks.remove(t)

        # неприсвоенные детекции → новые треки
        for d in unmatched_dets:
            t = FaceTrack(track_id=self._next_id, detections=[d])
            self._tracks.append(t)
            self._last_seen[self._next_id] = frame_idx
            self._next_id += 1

    def _last_bbox(self, track: FaceTrack) -> BBox | None:
        if not track.detections:
            return None
        return max(track.detections, key=lambda d: d.frame_idx).bbox

    def tracks(self) -> list[FaceTrack]:
        """Все треки (включая короткие). Фильтр по длине — снаружи."""
        return list(self._tracks)


def filter_short_tracks(tracks: Iterable[FaceTrack], min_frames: int = 5) -> list[FaceTrack]:
    """Убирает «мусорные» треки длиной меньше N кадров (флипы детектора)."""
    return [t for t in tracks if len(t.detections) >= min_frames]
