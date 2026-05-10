"""F4: Hook overlay — текст-крючок в первые 1.5 сек.

Отдельный жирный текст поверх видео в первые секунды. Цель — поймать swipe-через,
дать причину досмотреть. Контрастный фон + лёгкий fade-in.

Размещаем по центру верхней трети (не пересекается с субтитрами внизу
и не перекрывает face overlay в углах).

Текст подаётся через textfile=, чтобы не экранировать спецсимволы (%, :, '
и др. ломают text=). textfile создаётся apply.py во временной папке.
"""
from __future__ import annotations

import platform
from pathlib import Path

from .types import HookOverlay


# системные шрифты для drawtext
_FONT_CANDIDATES = {
    "Darwin": [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
    ],
    "Linux": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    ],
    "Windows": [
        "C:/Windows/Fonts/arialbd.ttf",
    ],
}


def _font_path() -> str | None:
    for c in _FONT_CANDIDATES.get(platform.system(), []):
        if Path(c).exists():
            return c
    return None


def _escape_filter_path(s: str) -> str:
    """Экранирует путь к файлу для filter_complex (двоеточие, бэкслеши)."""
    s = s.replace("\\", "/")
    s = s.replace(":", r"\:")
    s = s.replace("'", r"\'")
    return s


def build_hook_filter(
    hook: HookOverlay | None, target_w: int, target_h: int,
    base_label: str = "[v]",
    *, textfile_path: Path | None = None,
) -> tuple[str, str, list[Path]]:
    """Возвращает (filter_str, out_label, tempfiles_to_create).

    tempfiles_to_create — список (Path, content) на самом деле возвращаем как
    список Path; контент (hook.text) apply.py запишет до запуска ffmpeg.

    Если hook нет → ('', base_label, []).

    Использует textfile= для drawtext, чтобы не экранировать % : ' [ ] и т.п.
    """
    if not hook or not hook.text.strip():
        return "", base_label, []

    if textfile_path is None:
        # вызывающий должен передать путь — без него работать не можем
        return "", base_label, []

    raw_text = hook.text.strip().upper()

    font = _font_path()
    fontfile_part = f"fontfile='{font}':" if font else ""

    # размеры: подбираем fontsize так, чтобы текст влез в ~85% ширины.
    # средняя ширина uppercase-символа в Arial Bold ≈ 0.62 * fontsize.
    char_w_factor = 0.62
    n_chars = max(8, len(raw_text))
    box_pad_x = int(target_w * 0.025)
    max_text_w = int(target_w * 0.85) - 2 * box_pad_x
    max_fs_by_width = int(max_text_w / (n_chars * char_w_factor))
    max_fs_by_height = int(target_h * 0.045)
    fontsize = max(20, min(max_fs_by_width, max_fs_by_height))
    y_pos = int(target_h * 0.18)

    fade_in = max(0.05, hook.fade_in)
    fade_out = max(0.05, hook.fade_out)
    end_t = hook.duration

    # alpha expression: 0 → 1 за fade_in, 1 на середине, 1 → 0 за fade_out
    alpha_expr = (
        f"if(lt(t,{fade_in:.2f}),"
        f"t/{fade_in:.2f},"
        f"if(lt(t,{end_t - fade_out:.2f}),1,"
        f"max(0,({end_t:.2f}-t)/{fade_out:.2f})))"
    )

    tf_escaped = _escape_filter_path(str(textfile_path))

    out_label = "[v_hook]"
    f = (
        f"{base_label}drawtext="
        f"{fontfile_part}"
        f"textfile='{tf_escaped}':"
        f"expansion=none:"  # КРИТИЧНО: иначе % в тексте → "Stray %" → текст не печатается
        f"fontsize={fontsize}:"
        f"fontcolor=white:"
        f"x=(w-text_w)/2:y={y_pos}:"
        f"box=1:boxcolor=black@0.78:boxborderw={box_pad_x}:"
        f"borderw=3:bordercolor=black:"
        f"alpha='{alpha_expr}':"
        f"enable='lte(t,{end_t:.2f})'"
        f"{out_label}"
    )
    # apply.py создаст textfile с raw_text
    return f, out_label, [textfile_path]


def write_hook_textfile(path: Path, hook: HookOverlay) -> None:
    """Записывает текст хука в файл для drawtext textfile=."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(hook.text.strip().upper(), encoding="utf-8")
