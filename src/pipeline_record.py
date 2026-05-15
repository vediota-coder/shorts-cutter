"""Mini-pipeline для видео, записанных в Telepromter.

Отличается от src/pipeline.py:
- НЕТ скачивания/picker'а (у нас уже один готовый клип)
- ЕСТЬ alignment между сценарием (что хотели сказать) и whisper (что произнесли)
- Cut по KEEP-ranges из alignment'а
- Субтитры по сценарию (не по whisper — без ошибок распознавания)

Использует существующие модули:
- transcribe.transcribe — Whisper MLX/Groq/faster
- subtitles.write_ass — ASS-субтитры
- branding.* — лого/цвета
- effects.* — опционально zoom/emoji/hook
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Optional

from .transcribe import transcribe, Segment, Word
from .subtitles import write_ass, DEFAULT_TEMPLATE, AccentKeyword
from .branding import load_brand, apply_brand, list_brands
from .seo import stamp_metadata, SEOData
from .effects import apply_effects, plan_effects, write_plan_json
from .align import (
    script_to_words, transcript_to_words, align, build_render_segments, coverage
)


# Глобальный реестр job'ов обработки записи (in-memory; для prod добавить персист)
RECORD_JOBS: dict[str, dict] = {}


def _log(job_id: str, msg: str):
    if job_id not in RECORD_JOBS:
        return
    RECORD_JOBS[job_id].setdefault("log", []).append(f"[{time.strftime('%H:%M:%S')}] {msg}")
    if len(RECORD_JOBS[job_id]["log"]) > 200:
        RECORD_JOBS[job_id]["log"] = RECORD_JOBS[job_id]["log"][-200:]


def _set_progress(job_id: str, pct: int, step: str = ""):
    if job_id not in RECORD_JOBS:
        return
    RECORD_JOBS[job_id]["progress"] = max(0, min(100, pct))
    if step:
        RECORD_JOBS[job_id]["step"] = step


def _ffmpeg_cut_concat(src: Path, ranges: list, out: Path) -> Path:
    """Cut input по списку KeepRange + concat через ffmpeg filter_complex.
    Каждый range = (start, end) в секундах исходника.
    """
    if not ranges:
        # просто копируем
        shutil.copy2(src, out)
        return out

    # один range — простой ss + to + copy
    if len(ranges) == 1:
        r = ranges[0]
        proc = subprocess.run([
            "ffmpeg", "-y", "-ss", f"{r.start:.3f}", "-to", f"{r.end:.3f}",
            "-i", str(src), "-c", "copy", str(out)
        ], capture_output=True, text=True)
        if proc.returncode != 0:
            # fallback с перекодировкой
            proc = subprocess.run([
                "ffmpeg", "-y", "-ss", f"{r.start:.3f}", "-to", f"{r.end:.3f}",
                "-i", str(src), "-c:v", "libx264", "-c:a", "aac", "-preset", "veryfast", str(out)
            ], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg cut failed: {proc.stderr[:500]}")
        return out

    # несколько ranges — concat через filter_complex
    inputs = []
    parts_v = []
    parts_a = []
    for i, r in enumerate(ranges):
        parts_v.append(f"[0:v]trim=start={r.start:.3f}:end={r.end:.3f},setpts=PTS-STARTPTS[v{i}]")
        parts_a.append(f"[0:a]atrim=start={r.start:.3f}:end={r.end:.3f},asetpts=PTS-STARTPTS[a{i}]")
    concat_v = "".join(f"[v{i}]" for i in range(len(ranges))) + f"concat=n={len(ranges)}:v=1:a=0[vout]"
    concat_a = "".join(f"[a{i}]" for i in range(len(ranges))) + f"concat=n={len(ranges)}:v=0:a=1[aout]"
    filter_complex = ";".join(parts_v + parts_a + [concat_v, concat_a])

    proc = subprocess.run([
        "ffmpeg", "-y", "-i", str(src),
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-c:a", "aac", "-preset", "veryfast",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(out)
    ], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed: {proc.stderr[-800:]}")
    return out


def _burn_ass(src: Path, ass_path: Path, out: Path) -> Path:
    """Прожигает ASS-субтитры (как делает render.py shorts-cutter)."""
    # для ffmpeg subtitles filter: escape двоеточий и обратных слешей в Windows-стиле
    ass_escaped = str(ass_path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    proc = subprocess.run([
        "ffmpeg", "-y", "-i", str(src),
        "-vf", f"subtitles='{ass_escaped}'",
        "-c:a", "copy", "-c:v", "libx264", "-preset", "veryfast",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(out)
    ], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg ASS burn failed: {proc.stderr[-1000:]}")
    return out


def ass_segments_for_plan(script: str, whisper_words, ranges) -> list:
    """Возвращает build_render_segments — это и есть нужный формат для plan_effects."""
    return build_render_segments(script, whisper_words, ranges)


def _probe_dimensions(path: Path) -> tuple[int, int]:
    """Возвращает (width, height) видео через ffprobe."""
    try:
        proc = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0",
            str(path)
        ], capture_output=True, text=True, timeout=15)
        w, h = proc.stdout.strip().split("x")
        return int(w), int(h)
    except Exception:
        return 1080, 1920


@dataclass
class RecordOptions:
    auto_cut: bool = True
    subtitles: bool = True
    brand: str = "excella"
    apply_brand: bool = True
    cta_key: str = ""           # имя CTA-пресета из бренда; "" = без CTA
    # job-уровень: выкл отдельные элементы бренда БЕЗ изменения сохранённого пресета
    apply_watermark: bool = True
    apply_face: bool = True
    apply_bottom_strip: bool = True
    effects: bool = False
    effects_zoom: bool = True
    effects_emoji: bool = True
    effects_hook: bool = False     # hook overlay в начале — для записанного шортса часто избыточно
    effects_sfx: bool = False      # требует ELEVENLABS_API_KEY
    effects_provider: str = ""     # пустой = автодефолт LLM
    subtitle_template: str = "block"  # из src/subtitles.py PRESETS
    # SEO-метаданные зашиваются в MP4 после рендера
    meta_title: str = ""
    meta_description: str = ""
    meta_tags: list = field(default_factory=list)


async def process_record(
    *,
    video_path: Path,
    script: str,
    options: RecordOptions,
    jobs_dir: Path,
    job_id: str,
):
    """Обработка записанного шортса. Делает синхронные ffmpeg-вызовы через to_thread."""
    RECORD_JOBS[job_id] = {
        "id": job_id,
        "status": "running",
        "step": "Старт",
        "progress": 0,
        "log": [],
        "result": None,
        "started_at": time.time(),
    }
    work = jobs_dir / job_id
    work.mkdir(parents=True, exist_ok=True)

    try:
        _log(job_id, f"Видео: {video_path.name} · {video_path.stat().st_size // 1024} KB")
        _set_progress(job_id, 5, "Транскрипция через Whisper…")
        segments = await asyncio.to_thread(transcribe, video_path, model_size="auto")
        _log(job_id, f"Whisper: {len(segments)} сегментов")

        # alignment
        _set_progress(job_id, 35, "Сопоставление сценария и записи…")
        sw = script_to_words(script)
        ww = transcript_to_words(segments)
        _log(job_id, f"Script: {len(sw)} слов · Whisper: {len(ww)} слов")

        ranges = align(sw, ww) if options.auto_cut else [
            # без cut — оставляем всё одним range от 0 до конца
        ]
        if not options.auto_cut:
            duration = ww[-1].end if ww else 0
            from .align import KeepRange
            ranges = [KeepRange(start=0, end=duration + 1.0, script_start_idx=0,
                                script_end_idx=len(sw), whisper_start_idx=0, whisper_end_idx=len(ww))]
        cov = coverage(sw, ranges)
        _log(job_id, f"Найдено {len(ranges)} KEEP-segments · покрытие {cov*100:.0f}%")
        for i, r in enumerate(ranges):
            _log(job_id, f"  KEEP[{i+1}] {r.start:.2f}–{r.end:.2f} ({r.end-r.start:.1f}с)")

        # cut+concat
        _set_progress(job_id, 50, "Нарезка ffmpeg…")
        cut_path = work / "cut.mp4"
        await asyncio.to_thread(_ffmpeg_cut_concat, video_path, ranges, cut_path)
        _log(job_id, f"Cut: {cut_path.stat().st_size // 1024} KB")

        # Effects plan через LLM (если включены эффекты) — для accent-подсветки в субтитрах + zoom/emoji
        effects_plan = None
        cut_duration = sum(r.end - r.start for r in ranges)
        if options.effects:
            _set_progress(job_id, 70, "План эффектов (LLM)…")
            try:
                effects_plan = await asyncio.to_thread(
                    plan_effects,
                    segments=ass_segments_for_plan(script, ww, ranges),
                    clip_start=0.0, clip_end=cut_duration,
                    clip_title=script.split("\n")[0][:80] if script else "shorts",
                    enable_zoom=options.effects_zoom,
                    enable_emoji=options.effects_emoji,
                    enable_sfx=options.effects_sfx,
                    enable_hook=options.effects_hook,
                    provider=options.effects_provider or None,
                )
                write_plan_json(effects_plan, work / "effects.json")
                acc = len(effects_plan.accents) if effects_plan else 0
                em = len(effects_plan.emojis) if effects_plan else 0
                _log(job_id, f"Effects plan: accents={acc} emojis={em} hook={'+' if effects_plan and effects_plan.hook else '-'}")
            except Exception as e:
                _log(job_id, f"Effects plan FAIL: {type(e).__name__}: {str(e)[:200]}")
                effects_plan = None

        # subtitles через готовый shorts-cutter write_ass (с accent_keywords из effects_plan)
        final_path = cut_path
        if options.subtitles:
            _set_progress(job_id, 75, "Субтитры (ASS-шаблон)…")
            ass_segments = build_render_segments(script, ww, ranges)
            _log(job_id, f"Segments: {len(ass_segments)} · template={options.subtitle_template}")
            for i, s in enumerate(ass_segments[:3]):
                _log(job_id, f"  seg[{i}] {s.start:.2f}-{s.end:.2f} '{s.text[:40]}'")
            ass_path = work / "subs.ass"
            target_w, target_h = await asyncio.to_thread(_probe_dimensions, cut_path)
            accent_kws = []
            if effects_plan:
                for a in effects_plan.accents:
                    accent_kws.append(AccentKeyword(start=a.start, end=a.end, word=a.word))
            await asyncio.to_thread(
                write_ass,
                ass_segments, 0.0, cut_duration, ass_path,
                target_w=target_w, target_h=target_h,
                template=options.subtitle_template,
                accent_keywords=accent_kws or None, safe_area="none",
            )
            sub_path = work / "with_subs.mp4"
            await asyncio.to_thread(_burn_ass, cut_path, ass_path, sub_path)
            final_path = sub_path
            _log(job_id, f"Subs OK: {sub_path.stat().st_size // 1024} KB ({target_w}×{target_h})")

        # Apply effects (zoom + emoji + hook + sfx) поверх готового видео с субтитрами
        if options.effects and effects_plan and not effects_plan.is_empty():
            _set_progress(job_id, 86, "Эффекты (zoom/emoji/hook)…")
            try:
                fx_path = work / "with_fx.mp4"
                target_w, target_h = await asyncio.to_thread(_probe_dimensions, final_path)
                import os
                eleven_key = os.environ.get("ELEVENLABS_API_KEY") if options.effects_sfx else None
                await asyncio.to_thread(
                    apply_effects,
                    input_video=final_path, output_video=fx_path,
                    plan=effects_plan, target_w=target_w, target_h=target_h,
                    elevenlabs_api_key=eleven_key,
                )
                final_path = fx_path
                _log(job_id, f"FX OK: {fx_path.stat().st_size // 1024} KB")
            except Exception as e:
                _log(job_id, f"FX SKIPPED: {type(e).__name__}: {str(e)[:200]}")

        # SEO метаданные в MP4 (читают YouTube, Google и др.) — через src/seo.py
        if options.meta_title or options.meta_description or options.meta_tags:
            _set_progress(job_id, 92, "Метаданные в MP4…")
            try:
                meta_path = work / "with_meta.mp4"
                seo = SEOData(
                    title=options.meta_title,
                    description=options.meta_description,
                    tags=list(options.meta_tags or []),
                )
                await asyncio.to_thread(
                    stamp_metadata, final_path, meta_path,
                    seo=seo, artist=options.brand or "",
                )
                final_path = meta_path
                _log(job_id, f"Meta зашиты: title='{seo.title[:40]}…' tags={len(seo.tags)}")
            except Exception as e:
                _log(job_id, f"Meta SKIPPED: {type(e).__name__}: {str(e)[:200]}")

        # branding (логотип + face overlay + bottom strip + опц. CTA)
        if options.apply_brand and options.brand:
            _set_progress(job_id, 90, f"Брендинг ({options.brand})…")
            try:
                tpl = await asyncio.to_thread(load_brand, options.brand)
                # job-уровневые override: отключаем отдельные элементы, не трогая bd
                disabled = []
                if not options.apply_watermark:
                    tpl.watermark_path = None
                    disabled.append("watermark")
                if not options.apply_face:
                    tpl.face_overlay_path = None
                    disabled.append("face")
                if not options.apply_bottom_strip:
                    tpl.bottom_strip = None
                    disabled.append("bottom_strip")
                if disabled:
                    _log(job_id, f"Override OFF: {', '.join(disabled)}")
                branded_path = work / "with_brand.mp4"
                target_w, target_h = await asyncio.to_thread(_probe_dimensions, final_path)
                await asyncio.to_thread(
                    apply_brand, final_path, branded_path, tpl,
                    options.cta_key or None, target_w, target_h
                )
                final_path = branded_path
                _log(job_id, f"Brand OK: {branded_path.stat().st_size // 1024} KB")
            except Exception as e:
                _log(job_id, f"Brand SKIPPED: {type(e).__name__}: {str(e)[:200]}")

        _set_progress(job_id, 100, "Готово")
        RECORD_JOBS[job_id]["status"] = "done"
        RECORD_JOBS[job_id]["result"] = {
            "final_path": str(final_path),
            "filename": final_path.name,
            "size_kb": final_path.stat().st_size // 1024,
            "ranges": [{"start": r.start, "end": r.end} for r in ranges],
            "coverage": round(cov, 3),
        }
        _log(job_id, f"DONE: {final_path.name}")
    except Exception as e:
        RECORD_JOBS[job_id]["status"] = "error"
        RECORD_JOBS[job_id]["step"] = f"Ошибка: {type(e).__name__}: {str(e)[:300]}"
        _log(job_id, f"ERROR {type(e).__name__}: {e}")
    finally:
        RECORD_JOBS[job_id]["finished_at"] = time.time()
