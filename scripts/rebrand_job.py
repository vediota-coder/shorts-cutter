"""Накладывает брендинг (watermark + bottom strip + CTA) на готовые mp4 job'а.

Зачем: если `apply_brand` упал во время основного pipeline (типичная причина —
запущенный uvicorn держит в памяти устаревший байткод branding.py после правок,
либо несовместимая ffmpeg-версия), финальные мастер-файлы остаются без бренда.
Скрипт перечитывает branding.py с диска (свежий код), накладывает бренд на каждый
master-файл и пересоздаёт варианты ниже master_h.

Атомарная замена через .rebrand.tmp.mp4 → os.replace, так что параллельные
загрузки файлов через web не порвутся.

Запуск:
    .venv/bin/python scripts/rebrand_job.py <job_id> [--brand excella] [--cta none]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.branding import apply_brand, load_brand
from src.render import variants_below, transcode


def _master_label(files: dict[str, str]) -> str:
    """Лейбл с самой большой высотой (1080p > 720p > 480p > 1056p ...).

    Лейбл может быть произвольным (e.g. 1056p), поэтому сортируем по числу в нём.
    """
    def height(label: str) -> int:
        digits = "".join(ch for ch in label if ch.isdigit())
        return int(digits) if digits else 0
    return max(files, key=height)


def _video_height(path: Path) -> int:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return int(r.stdout.strip())


def rebrand_clip(out_dir: Path, clip: dict, *, brand_override: str | None, cta_override: str | None) -> None:
    files = clip.get("files") or {}
    if not files:
        print(f"[{clip['index']}] нет files, пропуск")
        return

    brand_name = brand_override or clip.get("brand")
    cta_name = cta_override or clip.get("cta")
    if not brand_name:
        print(f"[{clip['index']}] нет brand, пропуск")
        return
    tpl = load_brand(brand_name)

    master_lbl = _master_label(files)
    master_path = out_dir / files[master_lbl]
    if not master_path.exists():
        print(f"[{clip['index']}] master {master_path.name} не найден, пропуск")
        return

    title = (clip.get("title") or "")[:50]
    print(f"[{clip['index']}] {title} → {master_lbl}", flush=True)

    tmp = master_path.with_suffix(".rebrand.tmp.mp4")
    try:
        apply_brand(master_path, tmp, tpl, cta_key=cta_name, skip_face_overlay=True)
    except subprocess.CalledProcessError as ex:
        tmp.unlink(missing_ok=True)
        # печатаем stderr ffmpeg, чтобы видеть реальную причину
        err = ex.stderr.decode("utf-8", "replace") if ex.stderr else ""
        print(f"  FAIL apply_brand: {err.splitlines()[-3:] if err else ex}")
        return
    tmp.replace(master_path)

    mh = _video_height(master_path)
    for vlabel, (vw, vh) in variants_below(mh).items():
        if vlabel not in files:
            continue
        vpath = out_dir / files[vlabel]
        vtmp = vpath.with_suffix(".rebrand.tmp.mp4")
        try:
            transcode(master_path, vtmp, vw, vh)
        except subprocess.CalledProcessError as ex:
            vtmp.unlink(missing_ok=True)
            print(f"  FAIL transcode {vlabel}: {ex}")
            continue
        vtmp.replace(vpath)
        print(f"  ok variant {vlabel}")
    print(f"  ok master {master_lbl}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id")
    ap.add_argument("--brand", default=None)
    ap.add_argument("--cta", default=None)
    ap.add_argument("--only", type=int, default=None, help="rebrand только клип с таким index")
    args = ap.parse_args()

    job_dir = ROOT / "jobs" / args.job_id
    if not job_dir.exists():
        print(f"job {args.job_id} не найден", file=sys.stderr)
        return 1

    state = json.loads((job_dir / "state.json").read_text())
    clips = state.get("clips") or []
    if not clips:
        print("в state.json нет клипов", file=sys.stderr)
        return 1

    out_dir = job_dir / "output"
    for c in clips:
        if args.only and c.get("index") != args.only:
            continue
        rebrand_clip(out_dir, c, brand_override=args.brand, cta_override=args.cta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
