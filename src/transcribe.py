"""Транскрипция с авто-выбором бэкенда под железо.

Бэкенды:
- mlx          — Apple Silicon (M1/M2/M3/M4), MLX + Neural Engine. ~30x realtime.
- faster-cuda  — NVIDIA GPU. ~50x realtime на 4090.
- faster-cpu   — CPU fallback. faster-whisper int8 + greedy. ~5-15x realtime.
"""
from __future__ import annotations

import functools
import platform
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Literal, Optional


# Кэш для mlx_whisper.load_model — иначе модель 1.4 GB перегружается на каждый job.
# Патчим один раз при импорте модуля; ключ кэша = (path_or_hf_repo, dtype, ...).
try:
    from mlx_whisper import load_models as _mlx_load_models
    if not hasattr(_mlx_load_models.load_model, "cache_info"):
        _mlx_load_models.load_model = functools.lru_cache(maxsize=4)(
            _mlx_load_models.load_model
        )
except Exception:
    pass


ProgressFn = Callable[[float, str], None]
BackendName = Literal["groq", "mlx", "faster-cuda", "faster-cpu"]


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word]


@dataclass
class BackendInfo:
    name: BackendName
    device: str
    suggested_model: str
    note: str


def detect_backend() -> BackendInfo:
    """Определяет лучший бэкенд для текущей машины."""
    # 1. Groq Whisper API — самый быстрый вариант (~300× realtime, $0.006/мин).
    #    Включается явно через GROQ_API_KEY — даже если ключ есть, по умолчанию
    #    используется локальный backend, чтобы не тратить деньги случайно.
    #    Чтобы предпочесть groq: ставится EXCELLA_TRANSCRIBE_BACKEND=groq.
    import os as _os
    if _os.environ.get("EXCELLA_TRANSCRIBE_BACKEND") == "groq":
        if _os.environ.get("GROQ_API_KEY"):
            try:
                import groq  # noqa: F401
                return BackendInfo(
                    name="groq",
                    device="Groq Cloud (whisper-large-v3-turbo)",
                    suggested_model="whisper-large-v3-turbo",
                    note="Groq API, ~300× realtime, $0.006/мин",
                )
            except ImportError:
                pass

    # 2. macOS Apple Silicon → MLX (~30× realtime, локально, бесплатно)
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        try:
            import mlx_whisper  # noqa: F401
            return BackendInfo(
                name="mlx",
                device="Apple Neural Engine + GPU",
                suggested_model="mlx-community/whisper-large-v3-turbo",
                note="MLX, ~30x realtime",
            )
        except ImportError:
            pass

    # NVIDIA CUDA
    try:
        import torch
        if torch.cuda.is_available():
            gpu = torch.cuda.get_device_name(0)
            return BackendInfo(
                name="faster-cuda",
                device=f"CUDA: {gpu}",
                suggested_model="large-v3-turbo",
                note="faster-whisper GPU float16",
            )
    except ImportError:
        pass

    # CPU fallback
    return BackendInfo(
        name="faster-cpu",
        device=f"CPU ({platform.processor() or platform.machine()})",
        suggested_model="small",
        note="faster-whisper int8 greedy — компромисс скорость/качество",
    )


# ─────────────────────────── бэкенды ───────────────────────────

# Groq лимит на файл: 25 MB. Audio 16kHz mono ≈ 32 KB/s → 25 MB ≈ 13 минут.
# Чанкуем на 10-минутные куски для запаса.
_GROQ_CHUNK_MINUTES = 10.0
_GROQ_MAX_FILE_MB = 25


def _transcribe_groq(
    video_path: Path, model_name: str, language: str | None,
    on_progress: Optional[ProgressFn],
) -> list[Segment]:
    """Groq Whisper API. Чанкует видео >10 мин, отправляет batch'ами."""
    import groq

    client = groq.Groq()  # авточтение GROQ_API_KEY
    duration = _probe_duration(video_path)
    if on_progress:
        on_progress(2, f"Groq Whisper: видео {duration:.0f}с, model={model_name}")

    if duration <= _GROQ_CHUNK_MINUTES * 60:
        return _transcribe_groq_single(client, video_path, model_name, language,
                                        on_progress, duration)

    # chunked path
    target_chunk_s = _GROQ_CHUNK_MINUTES * 60.0
    splits = _silence_split_points(video_path, target_chunk_s)
    boundaries = [0.0] + splits + [duration]
    if len(boundaries) <= 2:
        boundaries = []
        t = 0.0
        while t < duration:
            boundaries.append(t)
            t += target_chunk_s
        boundaries.append(duration)
    chunks = list(zip(boundaries[:-1], boundaries[1:]))

    out_segments: list[Segment] = []
    tmp_dir = video_path.parent / f".groq_chunks_{video_path.stem}"
    tmp_dir.mkdir(exist_ok=True)
    try:
        for i, (cs, ce) in enumerate(chunks, 1):
            chunk_dur = ce - cs
            if on_progress:
                pct = 5 + 90 * (i - 1) / len(chunks)
                on_progress(pct, f"Groq чанк {i}/{len(chunks)}: {cs / 60:.1f}–{ce / 60:.1f} мин")
            wav = tmp_dir / f"chunk_{i:03d}.wav"
            _extract_audio_chunk(video_path, cs, ce, wav)

            t0 = time.monotonic()
            with wav.open("rb") as f:
                result = client.audio.transcriptions.create(
                    file=(wav.name, f),
                    model=model_name,
                    response_format="verbose_json",
                    language=language or "ru",
                    timestamp_granularities=["word", "segment"],
                )
            elapsed = time.monotonic() - t0
            speed = chunk_dur / elapsed if elapsed > 0 else 0
            if on_progress:
                pct = 5 + 90 * i / len(chunks)
                on_progress(pct, f"Groq чанк {i} готов · {elapsed:.0f}с ({speed:.1f}× realtime)")
            out_segments.extend(_groq_to_segments(result, cs))
            wav.unlink(missing_ok=True)
    finally:
        try:
            for f in tmp_dir.glob("*"):
                f.unlink()
            tmp_dir.rmdir()
        except OSError:
            pass

    if on_progress:
        on_progress(99, f"Groq готов · {len(out_segments)} сегментов")
    return out_segments


def _transcribe_groq_single(
    client, video_path: Path, model_name: str, language: str | None,
    on_progress: Optional[ProgressFn], duration: float,
) -> list[Segment]:
    """Один запрос к Groq для коротких видео."""
    # извлекаем audio в wav 16kHz mono — компактнее для лимита 25 MB
    wav_path = video_path.parent / f".groq_{video_path.stem}.wav"
    _extract_audio_chunk(video_path, 0.0, duration, wav_path)
    try:
        size_mb = wav_path.stat().st_size / 1024 / 1024
        if size_mb > _GROQ_MAX_FILE_MB:
            raise RuntimeError(
                f"audio {size_mb:.1f} MB > {_GROQ_MAX_FILE_MB} MB лимита Groq. "
                f"Снизьте качество или используйте chunking."
            )
        if on_progress:
            on_progress(20, f"отправляю в Groq ({size_mb:.1f} MB)…")
        t0 = time.monotonic()
        with wav_path.open("rb") as f:
            result = client.audio.transcriptions.create(
                file=(wav_path.name, f),
                model=model_name,
                response_format="verbose_json",
                language=language or "ru",
                timestamp_granularities=["word", "segment"],
            )
        elapsed = time.monotonic() - t0
        speed = duration / elapsed if elapsed > 0 else 0
        if on_progress:
            on_progress(95, f"Groq ответил: {elapsed:.1f}с ({speed:.0f}× realtime)")
        return _groq_to_segments(result, offset=0.0)
    finally:
        wav_path.unlink(missing_ok=True)


def _groq_to_segments(result, offset: float = 0.0) -> list[Segment]:
    """Конвертирует Groq verbose_json в наш список Segment."""
    out: list[Segment] = []
    # SDK groq возвращает Pydantic-модель: result.segments / result.words
    segments = getattr(result, "segments", None) or []
    # words опциональный, плоский список с timestamps
    words_all = getattr(result, "words", None) or []
    # бакет по segment'у на основе start/end
    for seg in segments:
        seg_start = float(seg.start) + offset
        seg_end = float(seg.end) + offset
        seg_text = (seg.text or "").strip()
        seg_words = [
            Word(start=float(w.start) + offset, end=float(w.end) + offset, text=w.word)
            for w in words_all
            if seg.start <= float(w.start) <= seg.end
        ]
        out.append(Segment(start=seg_start, end=seg_end, text=seg_text, words=seg_words))
    return out



# Кэш WhisperModel — переиспользуем между задачами, чтобы не грузить
# 1.5 GB веса на каждый job. Ключ: (model_size, device, compute_type).
_FASTER_WHISPER_CACHE: dict[tuple[str, str, str], object] = {}
_FASTER_WHISPER_LOCK = threading.Lock()


def _get_faster_whisper_model(model_size: str, device: str, compute_type: str):
    key = (model_size, device, compute_type)
    cached = _FASTER_WHISPER_CACHE.get(key)
    if cached is not None:
        return cached
    with _FASTER_WHISPER_LOCK:
        cached = _FASTER_WHISPER_CACHE.get(key)
        if cached is not None:
            return cached
        from faster_whisper import WhisperModel
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        _FASTER_WHISPER_CACHE[key] = model
        return model


def _transcribe_faster_whisper(
    video_path: Path, model_size: str, language: str | None,
    device: str, compute_type: str, beam_size: int,
    on_progress: Optional[ProgressFn],
) -> list[Segment]:
    cached = (model_size, device, compute_type) in _FASTER_WHISPER_CACHE
    if on_progress:
        msg = (
            f"модель {model_size} уже в памяти ({device}/{compute_type})"
            if cached
            else f"загружаю модель {model_size} ({device}/{compute_type})"
        )
        on_progress(1, msg)
    model = _get_faster_whisper_model(model_size, device, compute_type)
    segments_iter, info = model.transcribe(
        str(video_path),
        language=language,
        word_timestamps=True,
        vad_filter=True,
        beam_size=beam_size,
    )
    total = float(getattr(info, "duration", 0) or 0)
    out: list[Segment] = []
    for seg in segments_iter:
        words = [Word(w.start, w.end, w.word) for w in (seg.words or [])]
        out.append(Segment(seg.start, seg.end, seg.text.strip(), words))
        if on_progress and total > 0:
            pct = min(99.0, seg.end / total * 100)
            on_progress(pct, f"{seg.end:.0f}с из {total:.0f}с · {len(out)} сегм.")
    return out


def _probe_duration(video_path: Path) -> float:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
            stderr=subprocess.DEVNULL, timeout=10,
        )
        return float(out.strip())
    except Exception:
        return 0.0


def _silence_split_points(video_path: Path, target_chunk_s: float) -> list[float]:
    """Находит точки тишины через ffmpeg silencedetect и возвращает список offset'ов
    (в секундах от начала), близких к кратным target_chunk_s.

    Возвращает список разделителей. Если тишин не нашлось — пустой список.
    """
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats",
        "-i", str(video_path),
        "-af", "silencedetect=noise=-30dB:d=0.5",
        "-f", "null", "-",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except Exception:
        return []
    silences: list[float] = []
    for line in (r.stderr or "").splitlines():
        # ищем "silence_end: <secs> | silence_duration: ..."
        if "silence_end:" in line:
            try:
                t = float(line.split("silence_end:")[1].split("|")[0].strip())
                silences.append(t)
            except (ValueError, IndexError):
                continue
    if not silences:
        return []

    # выбираем разделители около кратных target_chunk_s
    duration = _probe_duration(video_path)
    splits: list[float] = []
    target = target_chunk_s
    while target < duration - target_chunk_s * 0.3:
        # ближайшая тишина в окне ±20% от target
        window = target_chunk_s * 0.4
        candidates = [s for s in silences if abs(s - target) <= window]
        if candidates:
            best = min(candidates, key=lambda s: abs(s - target))
            if not splits or best - splits[-1] >= target_chunk_s * 0.4:
                splits.append(best)
        target += target_chunk_s
    return splits


def _extract_audio_chunk(video_path: Path, start: float, end: float, out_wav: Path) -> Path:
    """Вырезает [start,end] из видео в моно 16kHz wav (формат, который любит whisper)."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
        "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le",
        str(out_wav),
    ]
    subprocess.run(cmd, check=True)
    return out_wav


def _transcribe_mlx(
    video_path: Path, model_repo: str, language: str | None,
    on_progress: Optional[ProgressFn],
    chunk_minutes: float = 6.0,
    long_video_threshold_s: float = 600.0,
) -> list[Segment]:
    """MLX Whisper с chunking для длинных видео.

    Видео < long_video_threshold_s — один проход.
    Иначе — режется по тишине на куски ~chunk_minutes мин, каждый прогоняется отдельно,
    реальный прогресс по чанкам, сегменты склеиваются с offset'ом.
    """
    import mlx_whisper

    duration = _probe_duration(video_path)
    if duration <= long_video_threshold_s:
        return _transcribe_mlx_single(video_path, model_repo, language, on_progress, duration=duration)

    # ── chunked path ──
    if on_progress:
        on_progress(2, f"видео {duration / 60:.1f} мин — режу на чанки по {chunk_minutes:.0f} мин")

    target_chunk_s = chunk_minutes * 60.0
    splits = _silence_split_points(video_path, target_chunk_s)
    boundaries = [0.0] + splits + [duration]
    # фолбэк: тишин нет → режем по фикс. интервалу с overlap 2с (whisper стерпит)
    if len(boundaries) <= 2:
        boundaries = []
        t = 0.0
        while t < duration:
            boundaries.append(t)
            t += target_chunk_s
        boundaries.append(duration)

    chunks = list(zip(boundaries[:-1], boundaries[1:]))
    if on_progress:
        on_progress(3, f"чанков: {len(chunks)} (по тишине)" if splits else f"чанков: {len(chunks)} (фикс. интервалы)")

    out_segments: list[Segment] = []
    tmp_dir = video_path.parent / f".whisper_chunks_{video_path.stem}"
    tmp_dir.mkdir(exist_ok=True)

    try:
        for i, (cs, ce) in enumerate(chunks, 1):
            chunk_dur = ce - cs
            if on_progress:
                pct = 3 + 90 * (i - 1) / len(chunks)
                on_progress(pct, f"чанк {i}/{len(chunks)}: {cs / 60:.1f}–{ce / 60:.1f} мин ({chunk_dur:.0f}с)")

            wav = tmp_dir / f"chunk_{i:03d}.wav"
            _extract_audio_chunk(video_path, cs, ce, wav)

            t0 = time.monotonic()
            result = mlx_whisper.transcribe(
                str(wav),
                path_or_hf_repo=model_repo,
                word_timestamps=True,
                language=language,
            )
            elapsed = time.monotonic() - t0
            speed = chunk_dur / elapsed if elapsed > 0 else 0
            if on_progress:
                pct = 3 + 90 * i / len(chunks)
                on_progress(pct, f"чанк {i}/{len(chunks)} готов · {elapsed:.0f}с ({speed:.1f}× realtime)")

            for seg in result.get("segments", []):
                words = [
                    Word(w["start"] + cs, w["end"] + cs, w.get("word", w.get("text", "")))
                    for w in seg.get("words", [])
                ]
                out_segments.append(Segment(
                    seg["start"] + cs, seg["end"] + cs,
                    (seg.get("text") or "").strip(), words,
                ))
            wav.unlink(missing_ok=True)
    finally:
        # чистим temp-папку
        try:
            for f in tmp_dir.glob("*"):
                f.unlink()
            tmp_dir.rmdir()
        except OSError:
            pass

    if on_progress:
        on_progress(95, f"пост-обработка ({len(out_segments)} сегм.)")
    return out_segments


def _transcribe_mlx_single(
    video_path: Path, model_repo: str, language: str | None,
    on_progress: Optional[ProgressFn],
    duration: float = 0.0,
) -> list[Segment]:
    """Один проход MLX (для коротких видео)."""
    import mlx_whisper

    if not duration:
        duration = _probe_duration(video_path)
    if on_progress:
        on_progress(2, f"MLX считает (видео {duration:.0f}с)…" if duration else "MLX считает…")

    # реалистичный прогноз: ~6× realtime при word_timestamps на длинных видео
    expected_total = max(20.0, duration / 6.0) if duration else 60.0
    stop = threading.Event()

    def heartbeat():
        t0 = time.monotonic()
        nonlocal expected_total
        while not stop.wait(2.0):
            elapsed = time.monotonic() - t0
            # если перевалили за прогноз — растягиваем динамически (пусть прогресс не клампится в 94%)
            if elapsed > expected_total * 0.9:
                expected_total = elapsed * 1.5
            pct = min(93.0, 2.0 + 91.0 * elapsed / expected_total)
            if on_progress:
                eta = max(0, expected_total - elapsed)
                on_progress(pct, f"MLX обрабатывает · {elapsed:.0f}с (ETA ~{eta:.0f}с)")

    hb = threading.Thread(target=heartbeat, daemon=True)
    hb.start()
    try:
        result = mlx_whisper.transcribe(
            str(video_path),
            path_or_hf_repo=model_repo,
            word_timestamps=True,
            language=language,
        )
    finally:
        stop.set()
        hb.join(timeout=1.0)

    if on_progress:
        on_progress(95, "пост-обработка")

    out: list[Segment] = []
    for seg in result.get("segments", []):
        words = [
            Word(w["start"], w["end"], w.get("word", w.get("text", "")))
            for w in seg.get("words", [])
        ]
        out.append(Segment(seg["start"], seg["end"], (seg.get("text") or "").strip(), words))
    return out


# ─────────────────────────── публичный API ───────────────────────────

# human-readable имена → конкретные repo_id для MLX-бекенда.
# faster-whisper понимает голые имена сам (tiny/base/small/medium/large-v3),
# а MLX требует HF-репозиторий mlx-community/whisper-XXX.
_MLX_MODEL_MAP = {
    "tiny":             "mlx-community/whisper-tiny-mlx",
    "base":             "mlx-community/whisper-base-mlx",
    "small":            "mlx-community/whisper-small-mlx",
    "medium":           "mlx-community/whisper-medium-mlx",
    "large-v2":         "mlx-community/whisper-large-v2-mlx",
    "large-v3":         "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo":   "mlx-community/whisper-large-v3-turbo",
}


def _resolve_mlx_repo(model_size: str, fallback: str) -> str:
    if "/" in model_size:
        # уже HF-repo
        return model_size
    return _MLX_MODEL_MAP.get(model_size, fallback)


def transcribe(
    video_path: Path,
    model_size: str = "auto",
    language: str | None = None,
    on_progress: Optional[ProgressFn] = None,
    backend: Optional[BackendName] = None,
) -> list[Segment]:
    info = detect_backend()
    chosen = backend or info.name
    if on_progress:
        on_progress(1, f"бэкенд: {chosen} · {info.device}")

    if model_size == "auto":
        model_size = info.suggested_model

    if chosen == "groq":
        # для Groq model_size = "auto" → "whisper-large-v3-turbo".
        # Доступные у Groq: whisper-large-v3, whisper-large-v3-turbo, distil-whisper-large-v3-en.
        groq_model = model_size if model_size.startswith("whisper-") else "whisper-large-v3-turbo"
        return _transcribe_groq(video_path, groq_model, language, on_progress)

    if chosen == "mlx":
        repo = _resolve_mlx_repo(model_size, info.suggested_model)
        if on_progress:
            on_progress(1, f"MLX модель: {repo}")
        return _transcribe_mlx(video_path, repo, language, on_progress)
    if chosen == "faster-cuda":
        return _transcribe_faster_whisper(
            video_path, model_size, language,
            device="cuda", compute_type="float16", beam_size=5,
            on_progress=on_progress,
        )
    return _transcribe_faster_whisper(
        video_path, model_size, language,
        device="cpu", compute_type="int8", beam_size=1,
        on_progress=on_progress,
    )


def to_plain_transcript(segments: Iterable[Segment]) -> str:
    lines = []
    for s in segments:
        m, sec = divmod(int(s.start), 60)
        lines.append(f"[{m:02d}:{sec:02d}] {s.text}")
    return "\n".join(lines)
