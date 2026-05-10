"""Бэкфилл хештегов в description у уже опубликованных YouTube-шортсов.

Раньше youtube.upload_video передавал хештеги только в snippet.tags
(невидимое поисковое поле), а не в description (где они становятся
кликабельными и влияют на Shorts-алгоритм). Этот скрипт проходит по
jobs/*/state.json, берёт meta_hashtags[youtube] для каждого clip с
publications.youtube.video_id и дописывает их в description через
videos.update.

Использование:
    python -m scripts.backfill_youtube_hashtags                # dry-run
    python -m scripts.backfill_youtube_hashtags --apply         # реально обновляет
    python -m scripts.backfill_youtube_hashtags --apply --job <ID>  # один job
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.publish import youtube as yt  # noqa: E402


def iter_published(jobs_dir: Path, only_job: str | None = None):
    for job_dir in sorted(jobs_dir.iterdir()):
        if not job_dir.is_dir():
            continue
        if only_job and job_dir.name != only_job:
            continue
        state_path = job_dir / "state.json"
        if not state_path.exists():
            continue
        try:
            state = json.loads(state_path.read_text())
        except json.JSONDecodeError:
            continue
        for clip in state.get("clips", []):
            pubs = clip.get("publications") or {}
            ytpub = pubs.get("youtube") or {}
            video_id = ytpub.get("video_id")
            if not video_id:
                continue
            tags = (clip.get("meta_hashtags") or {}).get("youtube") or []
            if not tags:
                continue
            yield job_dir.name, clip, video_id, tags


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                   help="Реально вызвать videos.update (без флага — только dry-run)")
    ap.add_argument("--job", help="Обработать только один job по ID")
    ap.add_argument("--jobs-dir", default=str(ROOT / "jobs"))
    args = ap.parse_args()

    jobs_dir = Path(args.jobs_dir)
    if not jobs_dir.exists():
        print(f"jobs dir не найден: {jobs_dir}", file=sys.stderr)
        return 2

    seen = updated = skipped = failed = 0
    for job_id, clip, video_id, tags in iter_published(jobs_dir, args.job):
        seen += 1
        brand = clip.get("brand", "excella")
        try:
            current = yt.get_snippet(brand, video_id)
        except Exception as e:
            print(f"[{job_id} / {video_id}] FAIL get_snippet: {e}")
            failed += 1
            continue
        if not current:
            print(f"[{job_id} / {video_id}] видео недоступно (удалено?), пропуск")
            skipped += 1
            continue
        cur_desc = current.get("description", "")
        new_desc = yt.inject_hashtags(cur_desc, tags)
        if new_desc == cur_desc.rstrip():
            print(f"[{job_id} / {video_id}] хештеги уже в description, пропуск")
            skipped += 1
            continue
        if not args.apply:
            added = [t for t in tags
                    if (t if t.startswith('#') else '#' + t).lower() not in cur_desc.lower()]
            print(f"[{job_id} / {video_id}] DRY-RUN +{len(added)} хештегов: {' '.join(added)}")
            updated += 1
            continue
        try:
            yt.update_description(brand=brand, video_id=video_id, description=new_desc)
            print(f"[{job_id} / {video_id}] OK обновлено")
            updated += 1
        except Exception as e:
            print(f"[{job_id} / {video_id}] FAIL update: {e}")
            failed += 1

    print(f"\nИтого: видим {seen}, обновлено/к обновлению {updated}, "
          f"пропущено {skipped}, ошибок {failed}")
    if not args.apply:
        print("Это был dry-run. Запусти с --apply, чтобы реально обновить.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
