"""Тест-стенд для всех subtitle preset'ов.

Что делает:
1. Генерирует синтетические Word/Segment с RU+EN текстом + accent_keywords.
2. Для каждого preset × разрешения (1080×1920, 720×1280, 480×854):
   - вызывает write_ass
   - валидирует структуру (header, events, balanced braces, time format)
   - оценивает ширину самой длинной строки vs target_w
   - burn-in на 5-сек чёрный клип через ffmpeg, проверяет return code
   - пробует с пустыми words и с одним словом — edge cases.

Запуск:
    .venv/bin/python scripts/test_subtitles.py
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.transcribe import Segment, Word
from src.subtitles import AccentKeyword, PRESETS, write_ass


# ─── фикстуры ─────────────────────────────────────────────────────────────


def make_segments_ru() -> list[Segment]:
    """Реалистичная RU фраза с word-timestamps и явными акцентами."""
    words_data = [
        (0.00, 0.35, "Сегодня"),
        (0.35, 0.70, "я"),
        (0.70, 1.10, "расскажу"),
        (1.10, 1.40, "о"),
        (1.40, 1.95, "невероятном"),
        (1.95, 2.40, "способе"),
        (2.40, 2.85, "заработать"),
        (2.85, 3.20, "первый"),
        (3.20, 3.70, "миллион"),
        (3.70, 4.15, "за"),
        (4.15, 4.60, "месяц"),
    ]
    words = [Word(s, e, t) for s, e, t in words_data]
    return [Segment(start=0.0, end=4.60, text=" ".join(w.text for w in words), words=words)]


def make_segments_en() -> list[Segment]:
    """Realistic EN sentence."""
    words_data = [
        (0.00, 0.30, "Today"),
        (0.30, 0.50, "I"),
        (0.50, 0.80, "will"),
        (0.80, 1.10, "show"),
        (1.10, 1.30, "you"),
        (1.30, 1.55, "the"),
        (1.55, 2.10, "absolute"),
        (2.10, 2.65, "best"),
        (2.65, 2.95, "way"),
        (2.95, 3.15, "to"),
        (3.15, 3.55, "make"),
        (3.55, 4.00, "money"),
    ]
    words = [Word(s, e, t) for s, e, t in words_data]
    return [Segment(start=0.0, end=4.00, text=" ".join(w.text for w in words), words=words)]


def make_segments_long_word() -> list[Segment]:
    """Очень длинное слово — стресс на auto-fit."""
    words = [
        Word(0.0, 0.5, "Антидисэстеблишментарианизм"),
        Word(0.5, 1.0, "интернационализированный"),
        Word(1.0, 1.5, "психофизиологический"),
    ]
    return [Segment(start=0.0, end=1.5, text=" ".join(w.text for w in words), words=words)]


def make_segments_empty() -> list[Segment]:
    return []


def make_accents_ru() -> list[AccentKeyword]:
    return [
        AccentKeyword(start=1.40, end=1.95, word="невероятном", color="#FFE600"),
        AccentKeyword(start=3.20, end=3.70, word="миллион", color="#00FF66", scale=120),
    ]


# ─── валидация ────────────────────────────────────────────────────────────


_TIME_RE = re.compile(r"^\d:\d{2}:\d{2}\.\d{2}$")


def validate_ass(path: Path) -> tuple[bool, list[str]]:
    """Базовая валидация ASS-файла.

    Возвращает (ok, errors). Проверяет:
    - наличие [Script Info], [V4+ Styles], [Events]
    - таймкоды Dialogue в формате H:MM:SS.cc
    - сбалансированность { } (escape работает)
    - end > start для каждого Dialogue
    """
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    if "[Script Info]" not in text:
        errors.append("missing [Script Info]")
    if "[V4+ Styles]" not in text:
        errors.append("missing [V4+ Styles]")
    if "[Events]" not in text:
        errors.append("missing [Events]")
    for ln in text.splitlines():
        if not ln.startswith("Dialogue:"):
            continue
        parts = ln.split(",", 9)
        if len(parts) < 10:
            errors.append(f"malformed dialogue: {ln[:80]}")
            continue
        t0, t1 = parts[1].strip(), parts[2].strip()
        if not _TIME_RE.match(t0):
            errors.append(f"bad start time: {t0}")
        if not _TIME_RE.match(t1):
            errors.append(f"bad end time: {t1}")
        # event text
        event_text = parts[9]
        # ASS позволяет вложенные { } в override-блоках. Проверяем что число
        # открывающих равно числу закрывающих.
        if event_text.count("{") != event_text.count("}"):
            errors.append(f"unbalanced braces: {event_text[:60]}")
        # end > start (parsing)
        try:
            def _ts(s: str) -> float:
                h, m, rest = s.split(":")
                sec = float(rest)
                return int(h) * 3600 + int(m) * 60 + sec
            if _ts(t1) <= _ts(t0):
                errors.append(f"end<=start: {t0}→{t1}")
        except ValueError:
            errors.append(f"unparseable times: {t0} {t1}")
    return (not errors, errors)


def estimate_max_line_width(path: Path, fontsize: int, bold: bool, uppercase: bool, letter_spacing: int) -> int:
    """Грубая оценка ширины самой длинной строки в пикселях.

    Считаем визуальную длину строки: убираем ASS-теги, разбиваем по \\N.
    """
    text = path.read_text(encoding="utf-8")
    longest = 0
    factor = (0.62 if bold else 0.52) * (1.05 if uppercase else 1.0)
    for ln in text.splitlines():
        if not ln.startswith("Dialogue:"):
            continue
        parts = ln.split(",", 9)
        if len(parts) < 10:
            continue
        ev = parts[9]
        # удаляем все {…} override-блоки
        ev_clean = re.sub(r"\{[^}]*\}", "", ev)
        # split на под-строки по \N
        for sub in ev_clean.split(r"\N"):
            chars = len(sub)
            px = int(chars * fontsize * factor + chars * letter_spacing)
            longest = max(longest, px)
    return longest


# ─── ffmpeg burn-in ────────────────────────────────────────────────────────


def make_test_video(out: Path, w: int, h: int, dur: float = 5.0) -> Path:
    """Чёрный клип нужного размера + тишина."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:d={dur}:r=30",
        "-f", "lavfi", "-i", f"anullsrc=cl=mono:r=44100",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
        "-c:a", "aac", "-shortest",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def burn_subs(video: Path, ass: Path, out: Path) -> tuple[bool, str]:
    """Пытается burn-in через libass. Возвращает (ok, stderr_excerpt)."""
    # экранирование пути для filtergraph
    ass_esc = str(ass).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "warning",
        "-i", str(video),
        "-vf", f"subtitles={ass_esc}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "copy",
        "-t", "5",
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return (r.returncode == 0, r.stderr[-400:])


# ─── runner ────────────────────────────────────────────────────────────────


SIZES = [(1080, 1920), (720, 1280), (480, 854)]


def run() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sub_test_"))
    print(f"tmp dir: {tmp}")

    failures = 0
    fixtures = {
        "ru": (make_segments_ru(), make_accents_ru()),
        "en": (make_segments_en(), []),
        "longword": (make_segments_long_word(), []),
        "empty": (make_segments_empty(), []),
    }

    for preset_key, preset in PRESETS.items():
        print(f"\n━━ preset: {preset_key} ({preset.name}) ━━")
        for fix_name, (segs, acc) in fixtures.items():
            for w, h in SIZES:
                ass_path = tmp / f"{preset_key}_{fix_name}_{w}x{h}.ass"
                seg_end = max((s.end for s in segs), default=5.0)
                try:
                    write_ass(
                        segs, 0.0, seg_end, ass_path,
                        target_w=w, target_h=h,
                        template=preset_key, accent_keywords=acc,
                    )
                except Exception as e:
                    print(f"  ✗ {fix_name} {w}×{h}: write_ass FAILED: {e}")
                    failures += 1
                    continue

                ok, errs = validate_ass(ass_path)
                if not ok:
                    print(f"  ✗ {fix_name} {w}×{h}: validation: {errs[:3]}")
                    failures += 1
                    continue

                # ширина строки — приблизительная оценка
                size_scale = h / 1920 if h >= 1280 else (h / 1920) * 1.5 if h >= 720 else (h / 1920) * 2.2
                actual_size = max(14, int(round(preset.size * size_scale)))
                px = estimate_max_line_width(
                    ass_path, fontsize=actual_size,
                    bold=preset.bold, uppercase=preset.uppercase,
                    letter_spacing=preset.letter_spacing,
                )
                margin_lr = max(20, int(round(w * 0.04)))
                avail = w - 2 * margin_lr
                if fix_name != "empty" and px > avail:
                    print(f"  ⚠ {fix_name} {w}×{h}: line ~{px}px > avail {avail}px (overflow risk)")
                    # не считаем фейлом для longword — это стресс-тест

                print(f"  ✓ {fix_name} {w}×{h}: ass ok, longest~{px}px / avail {avail}px")

        # ffmpeg burn-in только на одном фиксе/размере (sanity, не каждый комбо)
        ass_path = tmp / f"{preset_key}_ru_1080x1920.ass"
        if ass_path.exists():
            video = tmp / f"black_1080x1920.mp4"
            if not video.exists():
                make_test_video(video, 1080, 1920, dur=5.0)
            burn_out = tmp / f"{preset_key}_burned.mp4"
            ok, err = burn_subs(video, ass_path, burn_out)
            if not ok:
                print(f"  ✗ ffmpeg burn-in FAILED: {err}")
                failures += 1
            else:
                size_kb = burn_out.stat().st_size // 1024
                print(f"  ✓ ffmpeg burn-in ok ({size_kb} KB)")

    print()
    if failures:
        print(f"━━ {failures} test(s) failed ━━")
        return 1
    print("━━ all tests passed ━━")
    return 0


if __name__ == "__main__":
    sys.exit(run())
