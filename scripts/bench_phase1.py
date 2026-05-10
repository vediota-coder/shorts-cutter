"""Микро-бенчмарк Phase 1: analyze_video с/без time_ranges.

Запуск: .venv/bin/python scripts/bench_phase1.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.smart_reframe.pipeline import analyze_video  # noqa: E402

VIDEO = Path(__file__).resolve().parent.parent / "jobs/0430fc76ff9a/downloads/_2msdFKRS_c.mp4"


def progress_factory(label):
    last = [-1.0]

    def cb(pct, msg):
        # лог каждые ~10%
        if pct - last[0] >= 9.5 or pct >= 99:
            print(f"    {label} [{pct:5.1f}%] {msg}")
            last[0] = pct
    return cb


def main():
    if not VIDEO.exists():
        print(f"ERROR: {VIDEO} не найден")
        sys.exit(1)

    size_mb = VIDEO.stat().st_size // 1024 // 1024
    import subprocess
    duration = float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(VIDEO),
    ], text=True).strip())

    print(f"Видео: {VIDEO.name}, {size_mb} MB, {duration:.1f}с")
    print()

    # Test 1: без time_ranges (старое поведение)
    print("=" * 60)
    print("Test 1: analyze_video БЕЗ time_ranges (baseline)")
    print("=" * 60)
    t0 = time.monotonic()
    a_full = analyze_video(VIDEO, on_progress=progress_factory("baseline"))
    t1 = time.monotonic() - t0
    print(f"  → tracks: faces={len(a_full.tracks)} persons={len(a_full.person_tracks)} "
          f"screens={len(a_full.screens)} cuts={len(a_full.cuts)}")
    print(f"  → ВРЕМЯ: {t1:.1f}с")
    print()

    # Test 2: с time_ranges = ~17% видео (30с из 180с)
    half = duration / 2
    ranges = [(half - 15.0, half + 15.0)]
    coverage = sum(e - s for s, e in ranges) / duration * 100
    print("=" * 60)
    print(f"Test 2: analyze_video С time_ranges={ranges} ({coverage:.0f}% видео)")
    print("=" * 60)
    t0 = time.monotonic()
    a_clip = analyze_video(VIDEO, on_progress=progress_factory("ranges"), time_ranges=ranges)
    t2 = time.monotonic() - t0
    print(f"  → tracks: faces={len(a_clip.tracks)} persons={len(a_clip.person_tracks)} "
          f"screens={len(a_clip.screens)} cuts={len(a_clip.cuts)}")
    print(f"  → ВРЕМЯ: {t2:.1f}с")
    print()

    print("=" * 60)
    print("РЕЗУЛЬТАТЫ")
    print("=" * 60)
    print(f"  Test 1 (full):   {t1:6.1f}с")
    print(f"  Test 2 (ranges): {t2:6.1f}с (cover {coverage:.0f}%)")
    if t2 > 0:
        print(f"  Ускорение:       {t1/t2:.2f}×")
    print()
    print("ожидание: при coverage ~17% AI-inference падает в ~6×, "
          "общее время analyze падает в 3-5× (декодирование остаётся одинаковым)")


if __name__ == "__main__":
    main()
