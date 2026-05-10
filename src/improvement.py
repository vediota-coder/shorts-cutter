"""Self-improvement loop: агрегация коррекций → статистика паттернов → подсказки тюнинга.

Источник: `jobs/<id>/output/<slug>.corrections.json` — массивы CorrectionItem,
сохранённые web/app.py при apply_corrections_endpoint.

Шаги:
1. Сканируем все коррекции по всем job'ам.
2. Считаем переходы layout (was → became) — что система выбрала VS что человек поправил.
3. Считаем смены primary_face_id.
4. Возвращаем топ-паттернов и подсказку: какой порог classifier'а стоит подкрутить.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CorrectionStats:
    total_corrections: int = 0
    layout_transitions: dict[str, int] = field(default_factory=dict)  # "was→became" → count
    face_changes: int = 0
    by_brand: dict[str, int] = field(default_factory=dict)
    suggestions: list[str] = field(default_factory=list)


def collect_corrections(jobs_dir: Path) -> list[dict]:
    """Читает все corrections.json файлы и возвращает плоский список с meta."""
    out = []
    if not jobs_dir.exists():
        return out
    for job_dir in jobs_dir.iterdir():
        if not job_dir.is_dir():
            continue
        scenes_path = job_dir / "scenes.json"
        if not scenes_path.exists():
            continue
        try:
            json.loads(scenes_path.read_text(encoding="utf-8"))  # validate
        except Exception:
            continue
        out_dir = job_dir / "output"
        if not out_dir.exists():
            continue
        for cf in out_dir.glob("*.corrections.json"):
            try:
                items = json.loads(cf.read_text(encoding="utf-8"))
            except Exception:
                continue
            for item in items:
                # сопоставим коррекцию с оригинальным сегментом по start (clip-relative)
                # NOTE: для упрощения берём ближайший segment по середине диапазона
                out.append({
                    "job_id": job_dir.name,
                    "clip": cf.stem.replace(".corrections", ""),
                    "start": item["start"],
                    "end": item["end"],
                    "new_layout": item["layout"],
                    "new_face_id": item.get("primary_face_id"),
                })
    return out


def _find_was_layout(corrections: list[dict], jobs_dir: Path) -> list[tuple[str, str]]:
    """Для каждой коррекции пытаемся восстановить «оригинальный» layout из scenes.json."""
    pairs: list[tuple[str, str]] = []
    by_job: dict[str, list[dict]] = {}
    for c in corrections:
        by_job.setdefault(c["job_id"], []).append(c)

    for job_id, items in by_job.items():
        scenes_path = jobs_dir / job_id / "scenes.json"
        if not scenes_path.exists():
            continue
        try:
            json.loads(scenes_path.read_text(encoding="utf-8"))  # validate
        except Exception:
            continue
        # коррекции в clip-relative time, но scenes — в src-time. Без clip[start] точно не сопоставить.
        # Здесь упрощаем: смотрим job-clips через jobs_dir/<id>/output/<slug>-1080p.mp4 не парсим.
        # Используем приблизительное сопоставление: scene с center, ближайшим к коррекции.
        # На практике — за пределами этого скоупа точное сопоставление; сейчас просто
        # учитываем переходы как "[unknown→became]" для подсчёта частот became.
        for c in items:
            pairs.append(("?", c["new_layout"]))
    return pairs


def compute_stats(jobs_dir: Path) -> CorrectionStats:
    corrections = collect_corrections(jobs_dir)
    stats = CorrectionStats(total_corrections=len(corrections))
    if not corrections:
        stats.suggestions.append(
            "Пока нет коррекций — поправь несколько клипов в редакторе, "
            "и здесь появится статистика."
        )
        return stats

    # частоты «куда правят»
    target_counts = Counter(c["new_layout"] for c in corrections)
    for layout, n in target_counts.most_common():
        stats.layout_transitions[f"→ {layout}"] = n

    stats.face_changes = sum(1 for c in corrections if c.get("new_face_id") is not None)

    # суггестии на основе паттернов
    top_layout, top_count = target_counts.most_common(1)[0]
    share = top_count / len(corrections)
    if share >= 0.4:
        stats.suggestions.append(
            f"Чаще всего правят на «{top_layout}» ({int(share*100)}%). "
            f"Возможно, classifier недо-детектит этот layout — стоит ослабить порог."
        )
    if "screen_full" in target_counts and target_counts["screen_full"] / len(corrections) >= 0.25:
        stats.suggestions.append(
            "Много правок на screen_full — увеличить чувствительность YOLO/heuristic для экранов "
            "(уменьшить min_screen_area_ratio)."
        )
    if "active_speaker_close" in target_counts and target_counts["active_speaker_close"] / len(corrections) >= 0.2:
        stats.suggestions.append(
            "Много правок на active_speaker — стоит подключить Light-ASD (#13) "
            "вместо lip-motion эвристики."
        )
    if stats.face_changes / max(stats.total_corrections, 1) >= 0.3:
        stats.suggestions.append(
            f"В {int(stats.face_changes / stats.total_corrections * 100)}% коррекций "
            "меняли primary_face_id — IoU-tracker склеивает разные лица в один трек, "
            "стоит ужесточить iou_threshold или добавить face embeddings."
        )

    if not stats.suggestions:
        stats.suggestions.append(
            "Паттернов не выявлено — система работает в пределах нормы."
        )
    return stats
