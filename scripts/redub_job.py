"""Перегенерирует RU-озвучку для готового job'а БЕЗ полного rerender.

Что делает:
1. Читает segments.json + state.json job'а.
2. Для каждого клипа: фильтрует whisper-сегменты, переводит EN→RU + emotion tags,
   синтезирует речь через ElevenLabs с заданным voice_id.
3. Заменяет аудио в существующих 1056p/480p mp4: original audio -20dB + RU dub +3dB.
4. Пишет резервные копии оригиналов как `*.en.bak.mp4`.

Запуск:
    .venv/bin/python scripts/redub_job.py 8dbdfef100ce \\
        --voice EXAVITQu4vr4xnSDxMaL \\
        --model eleven_v3
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from src.transcribe import Segment, Word
from src.voiceover import translate_segments_ru, build_dub_track


def load_clip_segments(segments_path: Path, clip_start: float, clip_end: float) -> list[Segment]:
    raw = json.loads(segments_path.read_text())
    out = []
    for s in raw:
        if s["end"] <= clip_start or s["start"] >= clip_end:
            continue
        words = [Word(w["start"], w["end"], w["text"]) for w in s.get("words", [])]
        out.append(Segment(s["start"], s["end"], s["text"], words))
    return out


def remux_with_dub(src_mp4: Path, dub_wav: Path, out_mp4: Path,
                   duck_db: float = -20.0, dub_boost: float = 1.4,
                   logo_path: Path | None = None,
                   logo_position: str = "top-right",
                   logo_scale: float = 0.18,
                   logo_opacity: float = 0.95) -> None:
    """src_mp4 audio -20dB + dub_wav +3dB + overlay лого → out_mp4.
    Если logo_path задан — видео ПЕРЕКОДИРУЕТСЯ (нужно для overlay).
    Если нет — видео копируется без re-encode.
    """
    duck_gain = f"volume={10 ** (duck_db / 20.0):.4f}"
    audio_fc = (
        f"[0:a]{duck_gain},aresample=48000:async=1[orig];"
        f"[1:a]volume={dub_boost},aresample=48000:async=1[dub];"
        f"[orig][dub]amix=inputs=2:dropout_transition=0:normalize=0[a]"
    )

    if logo_path is None or not logo_path.exists():
        cmd = [
            "ffmpeg", "-y",
            "-i", str(src_mp4),
            "-i", str(dub_wav),
            "-filter_complex", audio_fc,
            "-map", "0:v:0", "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            "-shortest",
            str(out_mp4),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return

    # с лого: нужен видеопроцессинг
    # probe target width — scale хочет фиксированное число (main_w работает только в overlay)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(src_mp4)],
        capture_output=True, text=True, check=True,
    )
    src_w_str, src_h_str = probe.stdout.strip().split(",")[:2]
    src_w = int(src_w_str)
    src_h = int(src_h_str)
    wm_w = max(60, int(src_w * logo_scale))
    margin = max(12, int(src_w * 0.025))
    pos_map = {
        "top-left":     f"x={margin}:y={margin}",
        "top-right":    f"x=W-w-{margin}:y={margin}",
        "bottom-left":  f"x={margin}:y=H-h-{margin}",
        "bottom-right": f"x=W-w-{margin}:y=H-h-{margin}",
    }
    pos = pos_map.get(logo_position, pos_map["top-right"])
    video_fc = (
        f"[2:v]scale={wm_w}:-1,format=rgba,colorkey=0x000000:0.15:0.05,"
        f"colorchannelmixer=aa={logo_opacity}[wm];"
        f"[0:v][wm]overlay={pos}[v]"
    )
    fc = audio_fc + ";" + video_fc
    cmd = [
        "ffmpeg", "-y",
        "-i", str(src_mp4),
        "-i", str(dub_wav),
        "-i", str(logo_path),
        "-filter_complex", fc,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-shortest",
        str(out_mp4),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("job_id")
    p.add_argument("--voice", default="EXAVITQu4vr4xnSDxMaL", help="ElevenLabs voice_id (default: Sarah)")
    p.add_argument("--model", default="eleven_v3")
    p.add_argument("--llm-model", default="claude-haiku-4-5")
    p.add_argument("--brand", default="excella", help="бренд для лого/позиции")
    p.add_argument("--no-logo", action="store_true", help="не накладывать лого")
    p.add_argument("--reuse-dub", action="store_true",
                   help="не делать перевод+TTS, использовать dub.wav из _redub/clip_NN/")
    args = p.parse_args()

    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        print("✗ ELEVENLABS_API_KEY не задан", file=sys.stderr)
        sys.exit(1)

    job_dir = ROOT / "jobs" / args.job_id
    if not job_dir.exists():
        print(f"✗ нет job {args.job_id}", file=sys.stderr)
        sys.exit(1)

    state = json.loads((job_dir / "state.json").read_text())
    segments_path = job_dir / "segments.json"
    clips = state.get("clips", [])
    if not clips:
        print("✗ нет клипов в state.json", file=sys.stderr)
        sys.exit(1)

    out_dir = job_dir / "output"
    work_root = out_dir / "_redub"
    work_root.mkdir(exist_ok=True)

    # лого из бренда
    logo_path = None
    logo_pos = "top-right"
    logo_scale = 0.18
    logo_opacity = 0.95
    if not args.no_logo:
        try:
            from src.branding import load_brand
            tpl = load_brand(args.brand)
            if tpl.watermark_path and Path(tpl.watermark_path).exists():
                logo_path = Path(tpl.watermark_path)
                logo_pos = tpl.watermark_position or "top-right"
                logo_scale = tpl.watermark_scale or 0.15
                logo_opacity = tpl.watermark_opacity or 0.95
                print(f"  [brand] лого: {logo_path.name} · {logo_pos} · scale={logo_scale} · opacity={logo_opacity}")
        except Exception as e:
            print(f"  ⚠ не загрузил brand '{args.brand}': {e} — без лого")

    print(f"▶ {len(clips)} клипов · voice={args.voice} · model={args.model}")
    print()

    for c in clips:
        idx = c.get("index")
        cs = float(c.get("start", 0))
        ce = float(c.get("end", 0))
        title = c.get("title", "")
        print(f"━━━ [{idx}/{len(clips)}] {title[:60]} ({cs:.1f}–{ce:.1f}с) ━━━")

        clip_work = work_root / f"clip_{idx:02d}"
        clip_work.mkdir(exist_ok=True)
        dub_wav = clip_work / "dub.wav"

        if args.reuse_dub and dub_wav.exists():
            print(f"  ↻ переиспользую {dub_wav.name}")
        else:
            segs = load_clip_segments(segments_path, cs, ce)
            print(f"  whisper: {len(segs)} сегм.")
            if not segs:
                print(f"  пропуск — нет речи в [{cs:.1f}, {ce:.1f}]")
                continue
            print("  → перевод EN→RU + emotion tags…")
            translated = translate_segments_ru(segs, emotion_tags=True, model=args.llm_model)
            for ts in translated[:3]:
                print(f"     [{ts.start - cs:.1f}] {ts.text_ru[:80]}")
            if len(translated) > 3:
                print(f"     … +{len(translated)-3}")

            print("  → TTS + сборка дубляжа…")
            try:
                build_dub_track(
                    translated,
                    clip_start=cs, clip_end=ce,
                    voice_id=args.voice, api_key=api_key,
                    model_id=args.model,
                    out_path=dub_wav, work_dir=clip_work / "parts",
                    on_progress=lambda p, m: print(f"     {p:5.0f}% {m}") if "TTS " in m or "собран" in m else None,
                )
            except Exception as e:
                print(f"  ✗ TTS FAILED: {e}")
                sys.exit(2)

        # проверка громкости — что дубляж реально озвучен
        r = subprocess.run(
            ["ffmpeg", "-i", str(dub_wav), "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True,
        )
        mean_lines = [l for l in r.stderr.splitlines() if "mean_volume" in l]
        mean_db = float(mean_lines[0].split(":")[-1].strip().replace(" dB", "")) if mean_lines else -91
        if mean_db < -50:
            print(f"  ✗ dub silent (mean={mean_db:.1f} dB) — TTS не вернул аудио")
            sys.exit(2)
        print(f"  ✓ dub mean_volume={mean_db:.1f} dB")

        # remux обоих разрешений
        for label, fname in (c.get("files") or {}).items():
            src = out_dir / fname
            if not src.exists():
                continue
            backup = src.with_suffix(".en.bak.mp4")
            tmp = src.with_suffix(".ru.tmp.mp4")
            if not backup.exists():
                shutil.copy2(src, backup)
            print(f"  → remux {label}: {fname}{' + лого' if logo_path else ''}")
            try:
                remux_with_dub(
                    src, dub_wav, tmp,
                    logo_path=logo_path,
                    logo_position=logo_pos,
                    logo_scale=logo_scale,
                    logo_opacity=logo_opacity,
                )
                tmp.replace(src)
            except subprocess.CalledProcessError as e:
                print(f"     ffmpeg fail: {e.stderr.decode()[:300]}")
                tmp.unlink(missing_ok=True)
        print()

    print(f"✅ готово · {len(clips)} клипов с RU озвучкой")
    print(f"   оригиналы EN сохранены как *.en.bak.mp4 рядом")


if __name__ == "__main__":
    main()
