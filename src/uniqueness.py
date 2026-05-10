"""Уникализация видео под платформы — ослабляет fingerprint-совпадение.

Применять можно к двум кейсам:
1. Свой контент перед публикацией в N платформах — алгоритмы IG/TT/VK ценят
   «оригинальность» и поощряют такие версии в reach.
2. Чужой контент с лицензией/разрешением (тоже ослабляет YouTube CID, но
   страйк всё равно возможен — это игра в кошки-мышки, не панацея).

Применяется ПОСЛЕ финального рендера (после CTA, бренда, B-roll, музыки).
Делает новый mp4 без вмешательства в исходный мастер.

Что меняет:
- audio: pitch shift cents, speed factor, EQ low/high, фоновый pink noise
- video: speed factor (синхронно с audio), цветокор (temp/sat/bright),
         lite blur по краям (vignette), mirror flip
- container: fps remap (24/25/30)
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


Platform = Literal["youtube", "instagram", "vk", "tiktok"]


@dataclass
class UniquenessConfig:
    pitch_cents: int = 0           # ±20-50 почти неслышимо (1 цент = 1/100 полутона)
    speed: float = 1.0             # 0.97-1.03 безопасно по восприятию
    color_temp: int = 0            # ±5..±10K
    saturation: float = 0.0        # ±0.05
    brightness: float = 0.0        # ±0.03
    contrast: float = 0.0          # ±0.05
    mirror: bool = False           # горизонтальное отражение
    fps_target: int = 0            # 0 = не менять
    audio_eq_low_db: float = 0.0   # сдвиг низов ±2 dB
    audio_eq_high_db: float = 0.0  # сдвиг верхов ±2 dB
    bg_noise_db: float = -55       # фоновый pink noise (-55 неслышно, ломает audio fingerprint)
    bg_noise_enabled: bool = False


PRESETS: dict[Platform, UniquenessConfig] = {
    "youtube": UniquenessConfig(
        # YouTube — самый строгий, минимально аккуратные изменения
        pitch_cents=0, speed=1.0,
        color_temp=0, saturation=0.0, brightness=0.0,
    ),
    "instagram": UniquenessConfig(
        # IG поощряет оригинальность — больше «отпечатка»
        pitch_cents=15, speed=1.02,
        color_temp=200, saturation=0.04, brightness=0.02,
        bg_noise_enabled=True, bg_noise_db=-55,
        audio_eq_high_db=0.5,
    ),
    "vk": UniquenessConfig(
        # VK самая лояльная — но ваше видео = ваше преимущество
        pitch_cents=-10, speed=0.99,
        color_temp=-150, saturation=0.02, brightness=-0.01,
        audio_eq_low_db=0.5,
    ),
    "tiktok": UniquenessConfig(
        # TikTok: подкручиваем skin, тёплый цвет, лёгкое ускорение
        pitch_cents=20, speed=1.03,
        color_temp=300, saturation=0.05, brightness=0.02, contrast=0.03,
        bg_noise_enabled=True, bg_noise_db=-55,
        audio_eq_high_db=1.0,
    ),
}


def _video_filters(cfg: UniquenessConfig, fps_in: float) -> list[str]:
    chain: list[str] = []
    # цветокор: eq=brightness=B:contrast=1+C:saturation=1+S
    eq_parts = []
    if cfg.brightness != 0:
        eq_parts.append(f"brightness={cfg.brightness:.3f}")
    if cfg.contrast != 0:
        eq_parts.append(f"contrast={1 + cfg.contrast:.3f}")
    if cfg.saturation != 0:
        eq_parts.append(f"saturation={1 + cfg.saturation:.3f}")
    if eq_parts:
        chain.append("eq=" + ":".join(eq_parts))
    # температура: colorbalance с лёгким сдвигом RG/BG
    if cfg.color_temp != 0:
        rs = cfg.color_temp / 5000.0  # нормализуем
        bs = -rs
        chain.append(f"colorbalance=rs={rs:.3f}:gs=0:bs={bs:.3f}")
    # mirror
    if cfg.mirror:
        chain.append("hflip")
    # speed (видео): setpts=PTS/speed
    if cfg.speed != 1.0:
        chain.append(f"setpts={1/cfg.speed:.5f}*PTS")
    # fps remap
    if cfg.fps_target and abs(cfg.fps_target - fps_in) > 0.5:
        chain.append(f"fps={cfg.fps_target}")
    return chain


def _audio_filters(cfg: UniquenessConfig) -> list[str]:
    chain: list[str] = []
    # speed (аудио): atempo (диапазон 0.5..2.0; для 0.97-1.03 — один атемпо)
    if cfg.speed != 1.0:
        chain.append(f"atempo={cfg.speed:.4f}")
    # pitch shift в центах: 1 cent = 2^(1/1200); используем asetrate+aresample
    if cfg.pitch_cents != 0:
        ratio = 2 ** (cfg.pitch_cents / 1200)
        chain.append(f"asetrate=44100*{ratio:.6f},aresample=44100,atempo={1/ratio:.6f}")
    # EQ
    if cfg.audio_eq_low_db != 0:
        chain.append(f"equalizer=f=120:t=q:w=1.5:g={cfg.audio_eq_low_db:.2f}")
    if cfg.audio_eq_high_db != 0:
        chain.append(f"equalizer=f=8000:t=q:w=1.5:g={cfg.audio_eq_high_db:.2f}")
    return chain


def apply_uniqueness(
    in_path: Path,
    out_path: Path,
    cfg: UniquenessConfig,
) -> Path:
    """Применяет uniqueness конфиг к видео через ffmpeg."""
    # пробное чтение fps
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate", "-of", "default=noprint_wrappers=1:nokey=1",
         str(in_path)],
        capture_output=True, text=True, check=True,
    )
    fr = probe.stdout.strip()
    try:
        num, den = fr.split("/")
        fps_in = float(num) / float(den)
    except Exception:
        fps_in = 30.0

    vfilters = _video_filters(cfg, fps_in)
    afilters = _audio_filters(cfg)

    cmd = ["ffmpeg", "-y", "-i", str(in_path)]
    extra_inputs = 0

    if cfg.bg_noise_enabled and cfg.bg_noise_db < -10:
        # генерируем pink noise параллельным input'ом
        cmd += ["-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.5"]
        extra_inputs += 1

    filter_parts: list[str] = []
    if vfilters:
        filter_parts.append(f"[0:v]{','.join(vfilters)}[v]")
    else:
        filter_parts.append("[0:v]copy[v]")

    if cfg.bg_noise_enabled and extra_inputs:
        # mix: исходное аудио + затушёванный pink noise
        bg_vol = 10 ** (cfg.bg_noise_db / 20.0)  # dB→amplitude
        if afilters:
            filter_parts.append(f"[0:a]{','.join(afilters)}[a0]")
        else:
            filter_parts.append("[0:a]anull[a0]")
        filter_parts.append(f"[1:a]volume={bg_vol:.5f}[a1]")
        filter_parts.append("[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[a]")
    elif afilters:
        filter_parts.append(f"[0:a]{','.join(afilters)}[a]")
    else:
        filter_parts.append("[0:a]anull[a]")

    cmd += [
        "-filter_complex", ";".join(filter_parts),
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return out_path


def apply_preset(in_path: Path, out_path: Path, platform: Platform) -> Path:
    if platform not in PRESETS:
        raise ValueError(f"Неизвестный пресет: {platform}")
    return apply_uniqueness(in_path, out_path, PRESETS[platform])
