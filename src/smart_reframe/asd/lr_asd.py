"""LR-ASD (Lightweight & Robust ASD, IJCV 2025) — ML active speaker detection.

Wrapper над репозиторием Junhua-Liao/LR-ASD. Использует pretrained веса 0.84M
параметров, работает на CPU/MPS (без CUDA). 94.5% mAP на AVA-ActiveSpeaker.

Поток:
1. Для каждого FaceTrack извлекаем 112×112 grayscale crops, синхронные по времени
2. Извлекаем MFCC из соответствующего аудио-окна (100 Hz, 13 коэффициентов)
3. Прогоняем через ASD_Model → per-frame speaking probability
4. Возвращаем dict {track_id: {frame_idx: prob}}
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import torch


# vendor LR-ASD path
_REPO_ROOT = Path(__file__).resolve().parents[3] / "vendor" / "LR-ASD"
_WEIGHTS = _REPO_ROOT / "weight" / "finetuning_TalkSet.model"


def _is_available() -> bool:
    return _REPO_ROOT.exists() and _WEIGHTS.exists()


def _device() -> torch.device:
    """Apple MPS если доступен, иначе CPU."""
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


_MODEL: Optional[torch.nn.Module] = None
_LOSS_AV: Optional[torch.nn.Module] = None
_MODEL_DEVICE: Optional[torch.device] = None


def _load_model() -> tuple[torch.nn.Module, torch.nn.Module]:
    """Грузит ASD_Model + lossAV.FC head из pretrained checkpoint."""
    global _MODEL, _LOSS_AV, _MODEL_DEVICE
    if _MODEL is not None and _LOSS_AV is not None:
        return _MODEL, _LOSS_AV

    if not _is_available():
        raise RuntimeError(
            "LR-ASD не клонирован. "
            "git clone https://github.com/Junhua-Liao/LR-ASD.git vendor/LR-ASD"
        )

    sys.path.insert(0, str(_REPO_ROOT))
    try:
        from model.Model import ASD_Model  # type: ignore[import-not-found]
        from loss import lossAV  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)

    device = _device()
    model = ASD_Model()
    loss_av = lossAV()  # nn.Linear(128, 2) внутри

    state = torch.load(str(_WEIGHTS), map_location=device, weights_only=False)
    # state_dict: keys "model.X" → ASD_Model, "lossAV.X" → lossAV head, "lossV.X" — visual-only
    model_state = {}
    lossav_state = {}
    for k, v in state.items():
        if k.startswith("model."):
            model_state[k[6:]] = v
        elif k.startswith("lossAV."):
            lossav_state[k[7:]] = v

    model.load_state_dict(model_state, strict=False)
    loss_av.load_state_dict(lossav_state, strict=False)
    model.eval(); loss_av.eval()
    model.to(device); loss_av.to(device)
    _MODEL = model
    _LOSS_AV = loss_av
    _MODEL_DEVICE = device
    return model, loss_av


def _crop_face(frame: np.ndarray, bb, target_size: int) -> Optional[np.ndarray]:
    """Квадратный grayscale crop 112×112 для одной детекции. None если слишком мелко."""
    cx = bb.cx
    cy = bb.cy
    size = max(bb.w, bb.h) * 1.4
    x1 = int(max(0, cx - size / 2))
    y1 = int(max(0, cy - size / 2))
    x2 = int(min(frame.shape[1], cx + size / 2))
    y2 = int(min(frame.shape[0], cy + size / 2))
    if x2 - x1 < 20 or y2 - y1 < 20:
        return None
    face = frame[y1:y2, x1:x2]
    gray = cv2.cvtColor(face, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, (target_size, target_size), interpolation=cv2.INTER_AREA)


def _extract_crops_for_all_tracks(
    video_path: Path, tracks, target_size: int = 112,
) -> dict[int, tuple[np.ndarray, list[int]]]:
    """Один проход по видео — собираем crops для ВСЕХ tracks одновременно.

    Раньше было N декодирований (по track) + random seek на каждую детекцию.
    Теперь: 1 декодирование, sequential read до max нужного frame_idx,
    cap.set(CAP_PROP_POS_FRAMES, first_idx) для пропуска начала.

    Возвращает {track_id: (crops_array, frame_indices)}.
    """
    # frame_idx → list[(track_id, bbox)]
    by_frame: dict[int, list[tuple[int, object]]] = {}
    for track in tracks:
        for det in track.detections:
            by_frame.setdefault(det.frame_idx, []).append((track.track_id, det.bbox))

    if not by_frame:
        return {}

    needed = sorted(by_frame.keys())
    first_idx = needed[0]
    max_idx = needed[-1]

    cap = cv2.VideoCapture(str(video_path))
    # пропускаем начало если первый нужный кадр далеко от начала
    if first_idx > 30:
        cap.set(cv2.CAP_PROP_POS_FRAMES, first_idx)
        idx = first_idx
    else:
        idx = 0

    track_crops: dict[int, list[np.ndarray]] = {}
    track_indices: dict[int, list[int]] = {}

    while idx <= max_idx:
        ok, frame = cap.read()
        if not ok:
            break
        if idx in by_frame:
            for tid, bbox in by_frame[idx]:
                gray = _crop_face(frame, bbox, target_size)
                if gray is None:
                    continue
                track_crops.setdefault(tid, []).append(gray)
                track_indices.setdefault(tid, []).append(idx)
        idx += 1
    cap.release()

    out: dict[int, tuple[np.ndarray, list[int]]] = {}
    for tid, crops in track_crops.items():
        out[tid] = (np.stack(crops, axis=0), track_indices[tid])
    return out


def _extract_audio_mfcc(video_path: Path, fps: float) -> np.ndarray:
    """Извлекает MFCC 13-dim @ 100 Hz через ffmpeg + python_speech_features."""
    import subprocess
    import tempfile
    try:
        from python_speech_features import mfcc
    except ImportError as e:
        raise RuntimeError(
            "python_speech_features не установлен. pip install python_speech_features scipy"
        ) from e
    from scipy.io import wavfile

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = Path(tmp.name)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path),
         "-ac", "1", "-ar", "16000", "-vn", str(wav_path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    sr, audio = wavfile.read(str(wav_path))
    wav_path.unlink(missing_ok=True)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = audio.astype(np.float32)
    feats = mfcc(audio, sr, numcep=13, winstep=0.010, winlen=0.025)
    return feats  # shape: (N_audio_frames, 13), 100 Hz


def predict_speaking_probs(
    video_path: Path,
    tracks,
    fps: float,
    on_progress=None,
) -> dict[int, dict[int, float]]:
    """Возвращает {track_id: {frame_idx: prob_speaking}}.

    fallback на пустой dict если LR-ASD недоступен.
    """
    if not _is_available():
        return {}
    try:
        model, loss_av = _load_model()
    except Exception as e:
        warnings.warn(f"LR-ASD недоступен: {e}")
        return {}

    device = _MODEL_DEVICE or _device()
    audio_mfcc = _extract_audio_mfcc(video_path, fps)
    out: dict[int, dict[int, float]] = {}
    n = max(1, len(tracks))

    # Один проход по видео для ВСЕХ tracks (раньше — N декодирований с random seek per detection).
    if on_progress:
        on_progress(0, f"LR-ASD: декодирую crops для {n} tracks")
    crops_by_track = _extract_crops_for_all_tracks(video_path, tracks)
    if on_progress:
        on_progress(20, f"LR-ASD: ML inference для {n} tracks")

    for ti, track in enumerate(tracks):
        if on_progress:
            on_progress(20 + ti / n * 80, f"LR-ASD: track {ti+1}/{n}")
        if track.track_id not in crops_by_track:
            continue
        crops, indices = crops_by_track[track.track_id]
        if len(crops) < 4:
            continue
        # синхронизируем аудио: 4 audio frames на 1 video frame (audio 100Hz, video ~25fps)
        audio_per_video = 4
        # для каждого детектированного кадра берём audio_mfcc[idx*4-2 : idx*4+2]
        frame_to_prob: dict[int, float] = {}
        # обрабатываем чанками по 100 кадров
        chunk = 100
        for i in range(0, len(crops), chunk):
            v_chunk = crops[i:i + chunk]
            ind_chunk = indices[i:i + chunk]
            T = len(v_chunk)
            # audio: для каждого video frame берём 4 audio frames; собираем 4*T mfcc
            audio_seq = []
            for fi in ind_chunk:
                aidx = int(fi * 100 / fps)
                start = max(0, aidx - 2)
                end = start + audio_per_video
                if end > len(audio_mfcc):
                    end = len(audio_mfcc)
                    start = max(0, end - audio_per_video)
                slice_ = audio_mfcc[start:end]
                if len(slice_) < audio_per_video:
                    pad = np.zeros((audio_per_video - len(slice_), audio_mfcc.shape[1]), dtype=np.float32)
                    slice_ = np.concatenate([slice_, pad], axis=0)
                audio_seq.append(slice_)
            audio_arr = np.stack(audio_seq, axis=0)  # (T, 4, 13)
            audio_arr = audio_arr.reshape(T * audio_per_video, 13).astype(np.float32)

            audio_t = torch.from_numpy(audio_arr).unsqueeze(0).to(device)  # (1, 4T, 13)
            visual_t = torch.from_numpy(np.stack(v_chunk, axis=0)).unsqueeze(0).float().to(device)  # (1, T, 112, 112)

            with torch.no_grad():
                outs_av, _ = model(audio_t, visual_t)
                # outs_av: (T, 128) — прогоняем через lossAV.FC → (T, 2) → softmax → P(speaking)
                logits = loss_av.FC(outs_av)  # (T, 2)
                probs_2 = torch.softmax(logits, dim=-1)
                probs = probs_2[:, 1].cpu().numpy()  # P(speaking)
                if len(probs) >= T:
                    probs = probs[:T]
                else:
                    probs = np.pad(probs, (0, T - len(probs)), mode="edge")

            for fi_idx, fi in enumerate(ind_chunk):
                frame_to_prob[fi] = float(probs[fi_idx])

        out[track.track_id] = frame_to_prob

    return out


def active_speaker_per_frame(
    speaking_probs: dict[int, dict[int, float]],
    threshold: float = 0.40,
    smooth_window: int = 30,         # ⭐ 18 → 30 (≈1с@30fps) — длиннее окно сглаживания probs
    min_advantage: float = 0.18,     # ⭐ 0.08 → 0.18 — top-1 должен заметнее отрываться от top-2
    sticky_frames: int = 15,         # ⭐ нужно ≥ N подряд кадров нового лидера, чтобы переключиться
) -> dict[int, int]:
    """Из per-track probs → {frame_idx: track_id_активного}.

    Стратегия:
    1. Сглаживаем probs скользящим окном smooth_window кадров
       (LR-ASD per-frame может прыгать — speech это слова с паузами).
    2. Для каждого кадра выбираем трек с максимальной сглаженной prob.
    3. Если max_p < threshold → -1 (никто не говорит, или не уверены).
    4. Если разница между топ-1 и топ-2 < min_advantage → -1
       (модели одинаково думают «оба молчат» или «оба говорят»).
    5. ⭐ Sticky speaker: чтобы переключиться с активного A на B, нужно ≥ sticky_frames
       подряд кадров где B — лидер. Иначе держим A. Это убирает микро-переключения
       при подхвате слов вторым человеком.
    """
    if not speaking_probs:
        return {}

    # сглаживаем
    smoothed: dict[int, dict[int, float]] = {}
    for tid, frames_map in speaking_probs.items():
        if not frames_map:
            continue
        sorted_frames = sorted(frames_map.keys())
        smoothed[tid] = {}
        for i, f in enumerate(sorted_frames):
            lo = max(0, i - smooth_window // 2)
            hi = min(len(sorted_frames), i + smooth_window // 2 + 1)
            window_vals = [frames_map[sorted_frames[j]] for j in range(lo, hi)]
            smoothed[tid][f] = sum(window_vals) / len(window_vals)

    all_frames: set[int] = set()
    for d in smoothed.values():
        all_frames.update(d.keys())

    # сначала строим «сырой» выбор лидера на каждом кадре
    raw: dict[int, int] = {}
    for f in sorted(all_frames):
        ranked: list[tuple[float, int]] = []
        for tid, frames_map in smoothed.items():
            p = frames_map.get(f, 0.0)
            ranked.append((p, tid))
        ranked.sort(reverse=True)
        if not ranked:
            raw[f] = -1
            continue
        top_p, top_tid = ranked[0]
        second_p = ranked[1][0] if len(ranked) > 1 else 0.0
        if top_p >= threshold and (top_p - second_p) >= min_advantage:
            raw[f] = top_tid
        else:
            raw[f] = -1

    # ⭐ sticky-speaker: переключаемся на нового лидера только если он удерживает
    # лидерство ≥ sticky_frames подряд. Иначе сохраняем текущего активного.
    out: dict[int, int] = {}
    current = -1
    candidate = -1
    candidate_run = 0
    for f in sorted(raw.keys()):
        leader = raw[f]
        if leader == current:
            candidate = -1
            candidate_run = 0
        elif leader == candidate:
            candidate_run += 1
            if candidate_run >= sticky_frames:
                current = candidate
                candidate = -1
                candidate_run = 0
        else:
            candidate = leader
            candidate_run = 1
        out[f] = current
    return out

