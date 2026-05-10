"""Фоновая музыка для клипов через ffmpeg amix + sidechain compression (ducking).

Хранилище: audio_library/<filename>.mp3 — пользователь загружает свои треки.
Ducking: голос автоматически снижает громкость музыки на -15dB через sidechaincompress.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


AUDIO_LIB = Path(__file__).parent.parent / "audio_library"


def list_tracks() -> list[dict]:
    AUDIO_LIB.mkdir(exist_ok=True)
    out = []
    for p in sorted(AUDIO_LIB.iterdir()):
        if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg"):
            out.append({
                "name": p.name,
                "size_kb": p.stat().st_size // 1024,
            })
    return out


def add_music(
    base_video: Path,
    music_path: Path,
    out_path: Path,
    music_volume: float = 0.15,   # 0..1, обычно 0.1-0.2 для подложки
    duck: bool = True,            # снижать музыку когда есть голос
    fade_in: float = 0.5,
    fade_out: float = 0.8,
) -> Path:
    """Накладывает музыку на видео-аудио. С duck=True — sidechain compression."""
    # длительность исходника
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(base_video)],
        capture_output=True, text=True, check=True,
    )
    duration = float(probe.stdout.strip())

    # фильтры для музыки: volume + fade in/out
    music_filter = (
        f"[1:a]volume={music_volume},"
        f"afade=t=in:st=0:d={fade_in},"
        f"afade=t=out:st={max(0.0, duration - fade_out)}:d={fade_out},"
        f"atrim=0:{duration},asetpts=PTS-STARTPTS[mus]"
    )

    if duck:
        # voice (0:a) контролирует sidechain — когда есть голос, музыка глушится
        full_filter = (
            f"{music_filter};"
            f"[mus][0:a]sidechaincompress=threshold=0.01:ratio=8:attack=20:release=300[ducked];"
            f"[ducked][0:a]amix=inputs=2:duration=first:dropout_transition=0[a]"
        )
    else:
        full_filter = (
            f"{music_filter};"
            f"[mus][0:a]amix=inputs=2:duration=first:dropout_transition=0[a]"
        )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(base_video),
        "-stream_loop", "-1", "-i", str(music_path),
        "-filter_complex", full_filter,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return out_path
