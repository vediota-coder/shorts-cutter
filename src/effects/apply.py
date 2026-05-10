"""Применение всех эффектов одним ffmpeg-pass.

Вход: уже отрендеренный клип (с субтитрами и аудио, без брендинга).
Выход: тот же клип + zoom + emoji + hook + sfx (если включены).

Архитектура:
- видео: scale-zoom → drawtext (hook) → overlay (emoji_1) → overlay (emoji_2) → ...
- аудио: original → amix(sfx_1, sfx_2, ...)

Все эффекты опциональны — если плана нет, функция возвращает входной файл без работы.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .emoji import build_emoji_overlay_filters
from .hook import build_hook_filter, write_hook_textfile
from .sfx import build_sfx_audio_filter, prepare_sfx_assets
from .types import EffectsPlan
from .zoom import build_zoom_filter


def apply_effects(
    *,
    input_video: Path,
    output_video: Path,
    plan: EffectsPlan,
    target_w: int,
    target_h: int,
    elevenlabs_api_key: str | None = None,
) -> Path:
    """Применяет EffectsPlan к входному видео. Если plan пустой — копирует in→out.

    Возвращает output_video.
    """
    if plan.is_empty():
        # быстрый shortcut: ничего не делать
        if input_video.resolve() != output_video.resolve():
            import shutil
            shutil.copy2(input_video, output_video)
        return output_video

    inputs: list[str] = [str(input_video)]
    extra_inputs: list[str] = []
    video_filters: list[str] = []
    audio_filters: list[str] = []

    cur_v = "[0:v]"
    cur_a = "[0:a]"

    # 1. Zoom (применяется ПЕРВЫМ, на сыром кадре)
    zoom_filter = build_zoom_filter(plan.accents, target_w, target_h)
    if zoom_filter:
        video_filters.append(f"{cur_v}{zoom_filter}[v_zoom]")
        cur_v = "[v_zoom]"

    # 2. Hook overlay (drawtext с textfile, чтобы не экранировать %, : и др.)
    hook_textfile = output_video.with_suffix(".hook.txt")
    if plan.hook and plan.hook.text.strip():
        write_hook_textfile(hook_textfile, plan.hook)
    hook_f, after_hook, _tf = build_hook_filter(
        plan.hook, target_w, target_h, base_label=cur_v,
        textfile_path=hook_textfile if plan.hook and plan.hook.text.strip() else None,
    )
    if hook_f:
        video_filters.append(hook_f)
        cur_v = after_hook

    # 3. Emoji overlays
    emoji_filters, emoji_inputs, after_emoji = build_emoji_overlay_filters(
        plan.emojis, target_w, target_h, base_label=cur_v,
    )
    if emoji_filters:
        # подставляем реальные input-индексы
        # extra_inputs пока не имеет sfx — emoji идут с offset 1 (после input_video=0)
        for i, ipath in enumerate(emoji_inputs):
            extra_inputs.append(ipath)
        # заменяем плейсхолдеры __EMOJI_i__ на реальные индексы
        # input_video=0, потом emoji_0=1, emoji_1=2, ...
        emoji_input_offset = 1  # после input_video
        for i in range(len(emoji_inputs)):
            actual_idx = emoji_input_offset + i
            for j, f in enumerate(emoji_filters):
                emoji_filters[j] = f.replace(f"__EMOJI_{i}__", str(actual_idx))
        video_filters.extend(emoji_filters)
        cur_v = after_emoji

    # 4. SFX audio mix
    sfx_assets = []
    if plan.sfx:
        sfx_assets = prepare_sfx_assets(plan.sfx, api_key=elevenlabs_api_key)
    sfx_input_offset = 1 + len(extra_inputs)  # после видео и эмодзи
    sfx_filters, sfx_inputs, final_a = build_sfx_audio_filter(
        sfx_assets, main_audio_label=cur_a,
        base_input_offset=sfx_input_offset,
    )
    if sfx_filters:
        extra_inputs.extend(sfx_inputs)
        audio_filters.extend(sfx_filters)
        cur_a = final_a

    # Финальные labels должны быть валидными (без [] вокруг "[v]" внутри map'а — ffmpeg сам обрабатывает)
    # ffmpeg map хочет "name", не "[name]"
    final_v_label = cur_v.strip("[]") if cur_v != "[0:v]" else "0:v"
    final_a_label = cur_a.strip("[]") if cur_a != "[0:a]" else "0:a"

    # Если ни один фильтр не дал нового label — нет эффектов вообще, повторный shortcut
    if final_v_label == "0:v" and final_a_label == "0:a":
        if input_video.resolve() != output_video.resolve():
            import shutil
            shutil.copy2(input_video, output_video)
        return output_video

    # собираем ffmpeg
    cmd = ["ffmpeg", "-y", "-i", inputs[0]]
    for ip in extra_inputs:
        cmd.extend(["-i", ip])

    fc = ";".join(video_filters + audio_filters)
    cmd.extend([
        "-filter_complex", fc,
        "-map", f"[{final_v_label}]" if final_v_label != "0:v" else "0:v",
        "-map", f"[{final_a_label}]" if final_a_label != "0:a" else "0:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-shortest",
        str(output_video),
    ])

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        # эффекты не критичны — если упали, возвращаем оригинал
        debug_path = output_video.with_suffix(".effects.log")
        try:
            debug_path.write_text(
                f"CMD: {' '.join(cmd)}\n\nSTDERR:\n{proc.stderr}\n",
                encoding="utf-8",
            )
        except Exception:
            pass
        if input_video.resolve() != output_video.resolve():
            import shutil
            shutil.copy2(input_video, output_video)
    # cleanup tempfile хука (если был создан)
    try:
        if hook_textfile.exists():
            hook_textfile.unlink()
    except Exception:
        pass
    return output_video


def write_plan_json(plan: EffectsPlan, path: Path) -> None:
    """Сохраняет план эффектов рядом с клипом — для дебага и retry без LLM."""
    import json
    path.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))


def load_plan_json(path: Path) -> EffectsPlan | None:
    """Восстанавливает план из JSON, если он есть. Возвращает None при ошибке."""
    if not path.exists():
        return None
    import json
    from .types import Accent, EmojiCue, HookOverlay, SfxCue
    try:
        d = json.loads(path.read_text())
    except Exception:
        return None
    plan = EffectsPlan()
    for a in d.get("accents") or []:
        plan.accents.append(Accent(**a))
    for e in d.get("emojis") or []:
        plan.emojis.append(EmojiCue(**e))
    for s in d.get("sfx") or []:
        plan.sfx.append(SfxCue(**s))
    if d.get("hook"):
        plan.hook = HookOverlay(**d["hook"])
    return plan
