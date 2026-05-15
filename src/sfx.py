"""Sound FX overlay на акцентах (cuts, speech-onsets).

Использует уже существующую SmartAnalysis (cuts, asd_per_frame, lip_motion_energy)
из analysis.pkl — никакой новой детекции. SFX-файлы лежат в audio_library/sfx/.

Паттерн mix через ffmpeg amix+adelay — тот же что в src/music.py для add_music,
но с N коротких SFX-файлов, каждый со своей задержкой.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal


SFXType = Literal["cut", "speech_onset"]


SFX_DIR = Path(__file__).parent.parent / "audio_library" / "sfx"


# Дефолтные пресеты громкости и звуков для разных стилей
STYLE_PRESETS = {
    "subtle": {
        "cut":           {"file": "swoosh.wav", "volume": 0.30},
        "speech_onset":  {"file": "pop.wav",    "volume": 0.25},
        "min_gap_sec":   1.5,
    },
    "energetic": {
        "cut":           {"file": "whoosh.wav", "volume": 0.55},
        "speech_onset":  {"file": "ding.wav",   "volume": 0.50},
        "min_gap_sec":   0.8,
    },
}


def compute_sfx_timings(
    analysis,
    clip_start: float,
    clip_end: float,
    *,
    enable_cuts: bool = True,
    enable_speech_onset: bool = True,
    speech_pause_threshold: float = 0.8,
    min_gap_sec: float = 1.0,
) -> list[tuple[float, SFXType]]:
    """Возвращает [(t_in_clip_sec, type), ...] отсортированные по времени.

    - cut: каждый frame_idx из analysis.cuts, попадающий в окно клипа
    - speech_onset: переход asd_per_frame от -1 к ≥0 после паузы > threshold
    Соседние SFX ближе чем min_gap_sec — отбрасываются (оставляем первый).
    """
    fps = analysis.meta.fps if analysis else 25.0
    timings: list[tuple[float, SFXType]] = []

    cs_f = int(clip_start * fps)
    ce_f = int(clip_end * fps)
    dur = clip_end - clip_start

    if enable_cuts and getattr(analysis, "cuts", None):
        for cut_f in analysis.cuts:
            if cs_f < cut_f < ce_f:
                t = (cut_f - cs_f) / fps
                # не клеим SFX в первые 0.3 и последние 0.3 сек — звук обрежется
                if 0.3 <= t <= dur - 0.3:
                    timings.append((t, "cut"))

    if enable_speech_onset and getattr(analysis, "asd_per_frame", None):
        asd = analysis.asd_per_frame
        sorted_frames = sorted(f for f in asd.keys() if cs_f <= f <= ce_f)
        prev_speaker_f: int | None = None
        for f in sorted_frames:
            spk = asd.get(f, -1)
            if spk < 0:
                continue
            if prev_speaker_f is None or (f - prev_speaker_f) / fps > speech_pause_threshold:
                t = (f - cs_f) / fps
                if 0.3 <= t <= dur - 0.3:
                    timings.append((t, "speech_onset"))
            prev_speaker_f = f

    timings.sort(key=lambda x: x[0])

    # дедуп: убираем близкие соседи
    out: list[tuple[float, SFXType]] = []
    last_t = -1.0
    for t, typ in timings:
        if t - last_t < min_gap_sec:
            continue
        out.append((t, typ))
        last_t = t
    return out


def add_sfx(
    base_video: Path,
    out_path: Path,
    timings: list[tuple[float, SFXType]],
    *,
    style: str = "subtle",
    sfx_dir: Path = SFX_DIR,
) -> Path:
    """Накладывает SFX-стинги на аудиодорожку. Видео не трогает (-c:v copy)."""
    preset = STYLE_PRESETS.get(style) or STYLE_PRESETS["subtle"]

    if not timings:
        # нечего вставлять — просто копируем
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(base_video), "-c", "copy", str(out_path)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return out_path

    # собираем -i флаги для каждого SFX файла
    inputs = ["-i", str(base_video)]
    sfx_filters: list[str] = []
    mix_labels: list[str] = ["[0:a]"]
    for i, (t, typ) in enumerate(timings, start=1):
        cfg = preset.get(typ) or preset["cut"]
        sfx_path = sfx_dir / cfg["file"]
        if not sfx_path.exists():
            continue
        inputs += ["-i", str(sfx_path)]
        delay_ms = int(t * 1000)
        # adelay=Xms|Xms (для stereo); volume; разные label'ы
        sfx_filters.append(
            f"[{i}:a]adelay={delay_ms}|{delay_ms},volume={cfg['volume']:.2f}[s{i}]"
        )
        mix_labels.append(f"[s{i}]")

    if not sfx_filters:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(base_video), "-c", "copy", str(out_path)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return out_path

    n_streams = len(mix_labels)
    full_filter = (
        ";".join(sfx_filters) + ";"
        + "".join(mix_labels)
        + f"amix=inputs={n_streams}:dropout_transition=0:normalize=0[a]"
    )
    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", full_filter,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return out_path
