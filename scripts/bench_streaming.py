"""Сравнение legacy vs streaming analyze_video.

Запуск: .venv/bin/python scripts/bench_streaming.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.smart_reframe.pipeline import analyze_video  # noqa: E402

VIDEO = Path(__file__).resolve().parent.parent / "jobs/0430fc76ff9a/downloads/_2msdFKRS_c.mp4"


def quiet_progress(label):
    last = [-10.0]

    def cb(pct, msg):
        if pct - last[0] >= 19.5 or pct >= 99:
            print(f"    {label} [{pct:5.1f}%] {msg}")
            last[0] = pct
    return cb


def main():
    if not VIDEO.exists():
        print(f"ERROR: {VIDEO} не найден")
        sys.exit(1)
    print(f"video: {VIDEO.name}, {VIDEO.stat().st_size // 1024 // 1024} MB")
    print()

    # Test A: legacy (4 detectors, 4 проходов)
    print("=" * 60)
    print("Test A: legacy (4 отдельных detect_*, 4 декодирования)")
    print("=" * 60)
    t0 = time.monotonic()
    a_legacy = analyze_video(VIDEO, on_progress=quiet_progress("legacy"), streaming=False)
    t_legacy = time.monotonic() - t0
    print(f"  → faces={len(a_legacy.tracks)} persons={len(a_legacy.person_tracks)} "
          f"screens={len(a_legacy.screens)} cuts={len(a_legacy.cuts)}")
    print(f"  → ВРЕМЯ: {t_legacy:.1f}с")
    print()

    # Test B: streaming (1 проход)
    print("=" * 60)
    print("Test B: streaming (один cv2.VideoCapture, все 4 детектора параллельно)")
    print("=" * 60)
    t0 = time.monotonic()
    a_stream = analyze_video(VIDEO, on_progress=quiet_progress("stream"), streaming=True)
    t_stream = time.monotonic() - t0
    print(f"  → faces={len(a_stream.tracks)} persons={len(a_stream.person_tracks)} "
          f"screens={len(a_stream.screens)} cuts={len(a_stream.cuts)}")
    print(f"  → ВРЕМЯ: {t_stream:.1f}с")
    print()

    print("=" * 60)
    print("РЕЗУЛЬТАТЫ")
    print("=" * 60)
    print(f"  Legacy:    {t_legacy:6.1f}с  faces={len(a_legacy.tracks)} pers={len(a_legacy.person_tracks)} scr={len(a_legacy.screens)} cuts={len(a_legacy.cuts)}")
    print(f"  Streaming: {t_stream:6.1f}с  faces={len(a_stream.tracks)} pers={len(a_stream.person_tracks)} scr={len(a_stream.screens)} cuts={len(a_stream.cuts)}")
    if t_stream > 0:
        print(f"  Ускорение: {t_legacy / t_stream:.2f}×")


if __name__ == "__main__":
    main()
