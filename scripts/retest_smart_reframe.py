"""Перерендеривает один клип через smart_reframe с текущим кодом — для отладки
дёрганья камеры и зум-йо-йо без полного pipeline (без analyze, без TTS, без LLM).

Использует уже посчитанные analysis.pkl + segments.json из job'а.
Выход: /tmp/clip{N}_smartonly.mp4 (видео + аудио из источника, без субтитров/бренда).

Запуск:
    .venv/bin/python scripts/retest_smart_reframe.py <job_id> <clip_index>
        [--target-h 1056] [--out /tmp/foo.mp4]
"""
from __future__ import annotations

import argparse
import json
import pickle
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.smart_reframe import build_scenes, render_smart
from src.smart_reframe.types import SceneSegment


def load_whisper(segments_path: Path) -> tuple[list[tuple[float, float]], list[tuple[float, str]]]:
    """segments.json → (speech_segments, transcript_words)."""
    raw = json.loads(segments_path.read_text())
    speech = [(s["start"], s["end"]) for s in raw]
    words: list[tuple[float, str]] = []
    for s in raw:
        for w in s.get("words", []):
            words.append((w["start"], w["text"]))
    return speech, words


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id")
    ap.add_argument("clip_index", type=int)
    ap.add_argument("--target-h", type=int, default=1056)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    job_dir = ROOT / "jobs" / args.job_id
    if not job_dir.exists():
        print(f"job {args.job_id} не найден", file=sys.stderr)
        return 1

    state = json.loads((job_dir / "state.json").read_text())
    clip = next((c for c in state.get("clips", []) if c.get("index") == args.clip_index), None)
    if clip is None:
        print(f"clip {args.clip_index} не найден в state.json", file=sys.stderr)
        return 1

    src_path = job_dir / "downloads" / clip["src_basename"]
    if not src_path.exists():
        print(f"source {src_path} не найден", file=sys.stderr)
        return 1

    print(f"job:    {args.job_id}")
    print(f"clip:   #{clip['index']} {clip['title'][:60]}")
    print(f"range:  {clip['start']:.2f}..{clip['end']:.2f}  ({clip['end'] - clip['start']:.1f}s)")

    print("[1/4] загружаю analysis.pkl...", flush=True)
    with open(job_dir / "analysis.pkl", "rb") as f:
        analysis = pickle.load(f)
    print(f"      {len(analysis.tracks)} face tracks, {len(analysis.person_tracks)} persons, "
          f"{len(analysis.screens)} screens, {len(analysis.cuts)} cuts, fps={analysis.meta.fps:.2f}")

    print("[2/4] загружаю whisper segments...", flush=True)
    speech, words = load_whisper(job_dir / "segments.json")
    print(f"      {len(speech)} speech segments, {len(words)} words")

    print("[3/4] build_scenes (новый classifier)...", flush=True)
    scenes = build_scenes(analysis, speech, words)
    # сегменты для клипа: пересекающие [start, end] И сдвинутые в локальное
    # время [0, clip_duration] — render_clip ждёт именно clip-local time
    cs, ce = clip["start"], clip["end"]
    clip_scenes: list[SceneSegment] = []
    for s in scenes:
        if s.end <= cs or s.start >= ce:
            continue
        clip_scenes.append(SceneSegment(
            start=max(0.0, s.start - cs),
            end=min(ce, s.end) - cs,
            layout=s.layout,
            primary_face_id=s.primary_face_id,
            primary_screen_idx=s.primary_screen_idx,
            secondary_face_id=s.secondary_face_id,
            confidence=s.confidence,
            reason=s.reason,
            overridden=s.overridden,
        ))
    if not clip_scenes:
        clip_scenes = [SceneSegment(0, ce - cs, "wide_default")]
    layouts_count: dict[str, int] = {}
    for s in clip_scenes:
        layouts_count[s.layout] = layouts_count.get(s.layout, 0) + 1
    print(f"      всего сцен: {len(scenes)}, в клипе: {len(clip_scenes)} → {layouts_count}")
    for s in clip_scenes[:20]:
        print(f"        {s.start:.2f}..{s.end:.2f}  {s.layout}  fid={s.primary_face_id}  reason={s.reason}")

    target_h = args.target_h
    target_w = (target_h * 9 // 16) // 2 * 2  # чётный
    out_silent = Path(f"/tmp/clip{args.clip_index}_smartonly.silent.mp4")
    out_path = Path(args.out or f"/tmp/clip{args.clip_index}_smartonly.mp4")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[4/4] render_smart → {out_silent.name} ({target_w}x{target_h})...", flush=True)
    render_smart(
        video_path=src_path,
        analysis=analysis,
        segments=clip_scenes,
        out_path=out_silent,
        start=cs, end=ce,
        target_w=target_w, target_h=target_h,
        on_progress=lambda pct, msg: print(f"      {pct:.0f}% {msg}", flush=True) if int(pct) % 10 == 0 else None,
    )

    duration = ce - cs
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(out_silent),
        "-ss", str(cs), "-t", f"{duration:.3f}", "-i", str(src_path),
        "-map", "0:v:0", "-map", "1:a:0?",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)
    out_silent.unlink(missing_ok=True)
    print(f"\nготово: {out_path}  ({out_path.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
