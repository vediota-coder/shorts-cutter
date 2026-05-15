"""Перерендерить master-файлы клипов job-а с обновлённым scenes.json
(после правок в classifier). Обходит restyle, который использует кэш silent.mp4.

Шаги для каждого клипа:
  1. render_smart(...) → новый silent.mp4 (с обновлённым smart-reframe)
  2. write_ass(...) + mux_audio_and_subs → master с субтитрами + аудио
  3. transcode → 480p вариант
  4. apply_brand если есть бренд → бернит лого

Usage:
    .venv/bin/python scripts/rerender_clips_with_new_scenes.py <job_id>
"""
from __future__ import annotations

import json
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.smart_reframe import build_scenes, render_smart
from src.smart_reframe.types import SceneSegment
from src.subtitles import write_ass
from src.transcribe import Segment, Word
from src.render import mux_audio_and_subs, transcode, variants_below
from src.branding import load_brand, apply_brand
import pickle


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: rerender_clips_with_new_scenes.py <job_id>", file=sys.stderr)
        return 1
    job_id = sys.argv[1]
    job_dir = ROOT / "jobs" / job_id
    if not job_dir.exists():
        print(f"job {job_id} не найден", file=sys.stderr)
        return 1

    state = json.loads((job_dir / "state.json").read_text())
    analysis = pickle.loads((job_dir / "analysis.pkl").read_bytes())

    # Speech segments + words из segments.json
    seg_raw = json.loads((job_dir / "segments.json").read_text())
    speech = [(s["start"], s["end"]) for s in seg_raw]
    words = []
    for s in seg_raw:
        for w in s.get("words", []):
            words.append((w["start"], w["text"]))
    full_segments = [
        Segment(s["start"], s["end"], s["text"],
                [Word(w["start"], w["end"], w["text"]) for w in s.get("words", [])])
        for s in seg_raw
    ]

    # Re-build scenes (применяет новый classifier)
    print(f"[{job_id}] build_scenes...", flush=True)
    scenes_full = build_scenes(analysis, speech, words)

    out_dir = job_dir / "output"
    cache_dir = out_dir / "_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    dl_dir = job_dir / "downloads"

    for clip in state.get("clips", []):
        idx = clip["index"]
        slug = clip.get("slug")
        src_basename = clip.get("src_basename")
        cs, ce = clip["start"], clip["end"]
        if not slug or not src_basename:
            print(f"[{idx}] skip — нет slug/src_basename")
            continue
        src_path = dl_dir / src_basename
        if not src_path.exists():
            print(f"[{idx}] skip — нет {src_path}")
            continue

        # Сегменты для клипа в clip-relative time
        clip_scenes: list[SceneSegment] = []
        for s in scenes_full:
            if s.end <= cs or s.start >= ce:
                continue
            clip_scenes.append(SceneSegment(
                start=max(0.0, s.start - cs),
                end=min(ce, s.end) - cs,
                layout=s.layout,
                primary_face_id=s.primary_face_id,
                primary_screen_idx=s.primary_screen_idx,
                secondary_face_id=s.secondary_face_id,
                confidence=s.confidence, reason=s.reason, overridden=s.overridden,
            ))
        if not clip_scenes:
            clip_scenes = [SceneSegment(0, ce - cs, "wide_default")]

        # Размер мастера определяем по существующему файлу
        files = clip.get("files", {})
        master_label = next((k for k in ("1056p", "1080p", "720p") if k in files), None)
        if master_label:
            target_h = int(master_label.rstrip("p"))
        else:
            target_h = 1056
        target_w = (target_h * 9 // 16) // 2 * 2

        silent = cache_dir / f"{slug}.silent.mp4"
        print(f"[{idx}] render_smart {target_w}x{target_h}...", flush=True)
        render_smart(
            video_path=src_path,
            analysis=analysis,
            segments=clip_scenes,
            out_path=silent,
            start=cs, end=ce,
            target_w=target_w, target_h=target_h,
        )

        # Subtitles
        subs_path = cache_dir / f"{slug}.ass"
        write_ass(full_segments, cs, ce, subs_path,
                  target_w=target_w, target_h=target_h,
                  template=clip.get("sub_template", "block"))

        # Master
        master_filename = files.get(master_label, f"{slug}-{master_label}.mp4")
        master_path = out_dir / master_filename
        print(f"[{idx}] mux → {master_filename}", flush=True)
        mux_audio_and_subs(silent, src_path, subs_path, cs, ce, master_path)

        # Optional: бренд (без apply_brand если не сконфигурирован)
        brand_name = clip.get("brand")
        if brand_name:
            try:
                brand = load_brand(brand_name)
                if brand:
                    branded = out_dir / f"{slug}-{master_label}.brand.mp4"
                    apply_brand(master_path, branded, brand)
                    branded.replace(master_path)
                    print(f"[{idx}] brand applied")
            except Exception as e:
                print(f"[{idx}] brand fail: {e}")

        # 480p variant
        variants = variants_below(target_h)
        for label, (vw, vh) in variants.items():
            if label == master_label or vh >= target_h:
                continue
            variant = out_dir / f"{slug}-{label}.mp4"
            print(f"[{idx}] transcode {label}...", flush=True)
            transcode(master_path, variant, vw, vh)
            files[label] = variant.name
        files[master_label] = master_path.name

    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
