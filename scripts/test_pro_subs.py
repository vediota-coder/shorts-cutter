"""Тестовый скрипт: применяет новые pro-шаблоны субтитров (submagic/captions/podcast_pro)
+ per-word highlights из EffectsPlan + новые zoom-punch и emoji pop-in
к одному клипу job'а.

Использует существующие cache-артефакты (silent_face.mp4 + ass + segments.json + effects.json),
чтобы не дёргать LLM/ASD/face_detect.

Запуск:
    .venv/bin/python scripts/test_pro_subs.py <job_id> <clip_index> [--template submagic]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.transcribe import Segment, Word
from src.subtitles import write_ass, AccentKeyword, PRESETS, TemplateName
from src.effects import apply_effects
from src.effects.apply import load_plan_json


def load_segments(path: Path) -> list[Segment]:
    raw = json.loads(path.read_text())
    return [
        Segment(start=s["start"], end=s["end"], text=s["text"],
                words=[Word(w["start"], w["end"], w["text"]) for w in s.get("words", [])])
        for s in raw
    ]


def slugify(s: str) -> str:
    """Минимальный соответствующий pipeline-у slug. Не идеален, но для теста ок."""
    import re
    s = s.lower()
    s = re.sub(r"[^\w\sа-яёА-ЯЁ-]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s[:40]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id")
    ap.add_argument("clip_index", type=int)
    ap.add_argument("--template", default="submagic", choices=list(PRESETS.keys()))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    job_dir = ROOT / "jobs" / args.job_id
    state = json.loads((job_dir / "state.json").read_text())
    clip = next((c for c in state["clips"] if c["index"] == args.clip_index), None)
    if clip is None:
        print(f"clip {args.clip_index} не найден", file=sys.stderr)
        return 1

    cache = job_dir / "output" / "_cache"
    # ищем slug по index — как в pipeline.py: f"{i:02d}-{slugify(clip.title)}"
    slug = None
    for f in cache.glob(f"{args.clip_index:02d}-*.silent_face.mp4"):
        slug = f.name[:-len(".silent_face.mp4")]
        break
    if slug is None:
        print(f"silent_face.mp4 для клипа {args.clip_index} не найден в _cache", file=sys.stderr)
        return 1
    print(f"clip: #{args.clip_index} {clip['title'][:60]}")
    print(f"slug: {slug}")
    print(f"template: {args.template}")

    silent_face = cache / f"{slug}.silent_face.mp4"
    src_video = job_dir / "downloads" / clip["src_basename"]
    segments = load_segments(job_dir / "segments.json")
    plan_path = cache / f"{slug}.effects.json"
    plan = load_plan_json(plan_path)
    if plan is None:
        print(f"effects.json не найден — нужен для accent_keywords. Запусти /regenerate-effects сначала.",
              file=sys.stderr)
        return 1
    print(f"plan: {len(plan.accents)} accents, {len(plan.emojis)} emojis, hook={'+' if plan.hook else '-'}")

    # размеры мастера
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(silent_face)],
        capture_output=True, text=True, check=True,
    )
    target_w, target_h = map(int, probe.stdout.strip().split(","))

    # ⭐ accent_keywords из плана
    accent_kws = [
        AccentKeyword(start=a.start, end=a.end, word=a.word, color="#FFE600")
        for a in plan.accents
    ]
    print(f"accent_kws: {[(round(a.start, 2), a.word) for a in accent_kws]}")

    # 1) Генерируем новый ASS с pro-шаблоном + accent highlights
    test_ass = Path(f"/tmp/test_{args.template}_{args.clip_index}.ass")
    write_ass(
        segments, clip["start"], clip["end"], test_ass,
        target_w=target_w, target_h=target_h,
        template=args.template, accent_keywords=accent_kws,
    )
    print(f"ass written: {test_ass} ({test_ass.stat().st_size} bytes)")

    # 2) Mux audio + burn new subs над silent_face
    duration = clip["end"] - clip["start"]
    subs_path_esc = str(test_ass).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    with_subs = Path(f"/tmp/test_{args.template}_{args.clip_index}.subs.mp4")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(silent_face),
        "-ss", str(clip["start"]), "-t", f"{duration:.3f}", "-i", str(src_video),
        "-vf", f"subtitles={subs_path_esc}",
        "-map", "0:v:0", "-map", "1:a:0?",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-shortest",
        str(with_subs),
    ]
    subprocess.run(cmd, check=True, stderr=subprocess.PIPE)
    print(f"subs burned: {with_subs} ({with_subs.stat().st_size} bytes)")

    # 3) Apply effects (zoom-punch + pop-in emoji + hook)
    out = Path(args.out) if args.out else Path(f"/tmp/test_{args.template}_{args.clip_index}_full.mp4")
    apply_effects(input_video=with_subs, output_video=out, plan=plan,
                  target_w=target_w, target_h=target_h)
    print(f"final: {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
