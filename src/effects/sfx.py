"""F3: Sound effects через ElevenLabs Sound Effects API + локальный fallback.

API: POST https://api.elevenlabs.io/v1/sound-effects/generate
Если api_key отсутствует — генерируем синтетические SFX через ffmpeg lavfi
(audio_library/sfx/<kind>.wav). Это полный offline fallback.

Кэш ElevenLabs-генераций по prompt-тексту: одно и то же "ding" не пере-генерится.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from .types import SfxCue


CACHE_DIR = Path(__file__).parent.parent.parent / ".effects_cache" / "sfx"
LOCAL_SFX_DIR = Path(__file__).parent.parent.parent / "audio_library" / "sfx"
SFX_PROMPTS = {
    "whoosh": "fast camera whoosh swoosh transition, short, punchy",
    "swoosh": "soft air swoosh transition, smooth, short",
    "ding": "soft notification ding bell, short, single hit, modern UI",
    "pop": "cartoon pop bubble, very short, comedic, single hit",
    "drum": "single boom drum hit, deep impact, cinematic, no reverb tail",
    "applause": "short crowd applause cheer, 1.5 second, enthusiastic",
}
DEFAULT_DUR = 1.0


# Синтетические рецепты через ffmpeg lavfi — каждый kind собирается из
# простых синусов/шумов с envelope. Это не frenchforce, но узнаваемые акценты.
_LAVFI_RECIPES: dict[str, str] = {
    # ding: чистый высокий синус ~1500Hz с быстрым затуханием
    "ding": "sine=frequency=1500:duration=0.6,afade=t=out:st=0.05:d=0.55,volume=0.6",
    # pop: короткий низкий sine с резким cut
    "pop":  "sine=frequency=400:duration=0.12,afade=t=in:st=0:d=0.01,"
            "afade=t=out:st=0.04:d=0.08,volume=0.7",
    # whoosh: розовый шум с ramp-up и ramp-down
    "whoosh": "anoisesrc=color=pink:duration=0.5:amplitude=0.4,"
              "afade=t=in:st=0:d=0.15,afade=t=out:st=0.25:d=0.25",
    # swoosh: brown noise (низкочастотный) более мягкий чем whoosh
    "swoosh": "anoisesrc=color=brown:duration=0.6:amplitude=0.35,"
              "afade=t=in:st=0:d=0.2,afade=t=out:st=0.3:d=0.3",
    # drum: короткий низкочастотный sine 60Hz + click — bass-удар
    "drum": "sine=frequency=60:duration=0.4,afade=t=out:st=0.05:d=0.35,volume=0.9",
    # applause: короткий розовый шум с амплитудной модуляцией
    "applause": "anoisesrc=color=pink:duration=1.5:amplitude=0.5,"
                "afade=t=in:st=0:d=0.1,afade=t=out:st=1.2:d=0.3,volume=0.4",
}


def _ensure_local_sfx(kind: str) -> Path | None:
    """Возвращает путь к local <kind>.wav. Создаёт если нет."""
    LOCAL_SFX_DIR.mkdir(parents=True, exist_ok=True)
    out = LOCAL_SFX_DIR / f"{kind}.wav"
    if out.exists() and out.stat().st_size > 1000:
        return out
    recipe = _LAVFI_RECIPES.get(kind)
    if not recipe:
        return None
    try:
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", recipe,
            "-ac", "2", "-ar", "48000",
            str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not out.exists():
            return None
        return out
    except Exception:
        return None


def _cache_path(prompt: str, dur: float) -> Path:
    h = hashlib.sha1(f"{prompt}|{dur:.2f}".encode()).hexdigest()[:16]
    return CACHE_DIR / f"{h}.mp3"


def fetch_sfx_remote(prompt: str, duration: float = DEFAULT_DUR,
                    api_key: str | None = None) -> Path | None:
    """Тянет звук из ElevenLabs API. None если ключа нет или запрос упал."""
    if api_key is None:
        api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        return None

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = _cache_path(prompt, duration)
    if cached.exists() and cached.stat().st_size > 100:
        return cached

    try:
        import requests
    except ImportError:
        return None

    try:
        r = requests.post(
            "https://api.elevenlabs.io/v1/sound-effects/generate",
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json={
                "text": prompt,
                "duration_seconds": max(0.5, min(22, duration)),
                "prompt_influence": 0.4,
            },
            timeout=60,
        )
        if r.status_code != 200:
            return None
        cached.write_bytes(r.content)
        return cached
    except Exception:
        return None


def fetch_sfx(kind: str, api_key: str | None = None) -> Path | None:
    """Возвращает путь к sfx-файлу для kind.

    Стратегия:
    1) Если есть ELEVENLABS_API_KEY — пробуем тянуть из API (качественнее).
    2) Иначе фолбэк на локальный синтез через ffmpeg lavfi.
    """
    prompt = SFX_PROMPTS.get(kind, SFX_PROMPTS["ding"])
    if api_key is None:
        api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip() or None
    if api_key:
        remote = fetch_sfx_remote(prompt, duration=DEFAULT_DUR, api_key=api_key)
        if remote is not None:
            return remote
    return _ensure_local_sfx(kind)


def prepare_sfx_assets(sfx_cues: list[SfxCue], api_key: str | None = None) -> list[tuple[SfxCue, Path]]:
    """Заранее находит/генерит все sfx-файлы. Возвращает только успешные (cue, path).

    Если api_key None — используется только локальный fallback (синтетические SFX).
    """
    out: list[tuple[SfxCue, Path]] = []
    for cue in sfx_cues:
        path = fetch_sfx(cue.kind, api_key=api_key)
        if path is not None:
            out.append((cue, path))
    return out


def build_sfx_audio_filter(
    sfx_assets: list[tuple[SfxCue, Path]], main_audio_label: str = "[0:a]",
    *, base_input_offset: int,
) -> tuple[list[str], list[str], str]:
    """Собирает audio-filter chain: каждый sfx подмиксовывается на свой timestamp.

    Возвращает (filters, extra_inputs, final_audio_label).
    base_input_offset — индекс с которого начинаются sfx-входы (после видео + других).
    """
    if not sfx_assets:
        return [], [], main_audio_label

    extra_inputs: list[str] = []
    filters: list[str] = []
    mix_labels = [main_audio_label]

    for i, (cue, path) in enumerate(sfx_assets):
        extra_inputs.append(str(path))
        in_idx = base_input_offset + i
        delay_ms = int(cue.timestamp * 1000)
        # volume: db → linear amplitude
        amp = 10 ** (cue.volume_db / 20.0)
        sfx_label = f"[sfx{i}]"
        filters.append(
            f"[{in_idx}:a]adelay={delay_ms}|{delay_ms},"
            f"volume={amp:.4f},aformat=channel_layouts=stereo:sample_rates=48000"
            f"{sfx_label}"
        )
        mix_labels.append(sfx_label)

    final_label = "[a_out]"
    inputs_concat = "".join(mix_labels)
    filters.append(
        f"{inputs_concat}amix=inputs={len(mix_labels)}:dropout_transition=0:"
        f"normalize=0{final_label}"
    )
    return filters, extra_inputs, final_label
