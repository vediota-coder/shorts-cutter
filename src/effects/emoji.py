"""F2: Эмодзи на акцентах.

Подход: рендерим каждый уникальный эмодзи в PNG (через PIL + Apple Color Emoji
шрифт), кэшируем в .effects_cache/emoji/, накладываем через ffmpeg overlay
с pop-анимацией (scale 0→1→0.95 с easing).

PNG генерация однократная — на одном клипе уникальных эмодзи 2-3, на репозитории
их быстро становится <50 → кэш почти всегда тёплый.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

from .types import EmojiCue


CACHE_DIR = Path(__file__).parent.parent.parent / ".effects_cache" / "emoji"


def _emoji_font_path() -> str | None:
    """Находит цветной эмодзи-шрифт системы."""
    if platform.system() == "Darwin":
        p = "/System/Library/Fonts/Apple Color Emoji.ttc"
        if Path(p).exists():
            return p
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/noto-color-emoji/NotoColorEmoji.ttf",
        "C:/Windows/Fonts/seguiemj.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def _slug(emoji: str) -> str:
    """Стабильный slug для имени файла кэша (без эмодзи в названии файла)."""
    return "_".join(f"{ord(c):x}" for c in emoji)


def render_emoji_png(emoji: str, size: int = 256) -> Path | None:
    """Рендерит эмодзи в PNG. Использует pillow + системный emoji-шрифт.

    Если pillow нет или шрифта нет — возвращает None (эффект пропустится).
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = CACHE_DIR / f"{_slug(emoji)}_{size}.png"
    if out.exists():
        return out

    # Пробуем через PIL (если доступен)
    try:
        from PIL import Image, ImageDraw, ImageFont  # noqa
    except ImportError:
        return _render_via_ffmpeg_drawtext(emoji, size, out)

    font_path = _emoji_font_path()
    if not font_path:
        return None

    # Apple Color Emoji TTC поддерживает фиксированные размеры (160 на macOS).
    # Используем 160 для рендера, потом ресайз до size через PIL.
    try:
        if platform.system() == "Darwin":
            font = ImageFont.truetype(font_path, 160)
            img_size = 200
        else:
            font = ImageFont.truetype(font_path, size)
            img_size = size + 40

        img = Image.new("RGBA", (img_size, img_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # центрируем
        bbox = draw.textbbox((0, 0), emoji, font=font, embedded_color=True)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (img_size - tw) // 2 - bbox[0]
        y = (img_size - th) // 2 - bbox[1]
        draw.text((x, y), emoji, font=font, embedded_color=True)
        # тримим прозрачность и масштабируем до size
        bbox2 = img.getbbox()
        if bbox2:
            img = img.crop(bbox2)
        img = img.resize((size, size), Image.LANCZOS)
        img.save(out, "PNG")
        return out
    except Exception:
        return _render_via_ffmpeg_drawtext(emoji, size, out)


def _render_via_ffmpeg_drawtext(emoji: str, size: int, out: Path) -> Path | None:
    """Фолбэк: рендер эмодзи через ffmpeg drawtext.

    Не на всех ОС работает — Apple Color Emoji ffmpeg напрямую читает плохо.
    Возвращаем None если не получилось.
    """
    font_path = _emoji_font_path()
    if not font_path:
        return None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=black@0:s={size + 40}x{size + 40}:d=0.04",
            "-vf", (
                f"format=rgba,drawtext=fontfile='{font_path}':"
                f"text='{emoji}':fontsize={int(size * 0.85)}:"
                "x=(w-text_w)/2:y=(h-text_h)/2"
            ),
            "-frames:v", "1",
            str(tmp_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        shutil.move(str(tmp_path), str(out))
        return out
    except Exception:
        return None


def emoji_position_xy(position: str, target_w: int, target_h: int, sprite_w: int) -> tuple[str, str]:
    """Возвращает (x_expr, y_expr) для overlay на основе position.

    Поддерживается: top-center / top-right / top-left / right / left.
    Внизу не ставим — там обычно субтитры или CTA-плашка.
    """
    margin_y = int(target_h * 0.12)  # ~12% сверху
    margin_x = int(target_w * 0.05)
    if position == "top-right":
        return (f"W-w-{margin_x}", f"{margin_y}")
    if position == "top-left":
        return (f"{margin_x}", f"{margin_y}")
    if position == "right":
        return (f"W-w-{margin_x}", "(H-h)/2")
    if position == "left":
        return (f"{margin_x}", "(H-h)/2")
    return ("(W-w)/2", f"{margin_y}")


def build_emoji_overlay_filters(
    emojis: list[EmojiCue], target_w: int, target_h: int,
    base_label: str = "[v]",
    *, sprite_size: int = 220,
) -> tuple[list[str], list[str], str]:
    """Строит filter_complex chain для overlay'а эмодзи.

    Возвращает (filters, extra_inputs, final_label).
    extra_inputs — пути PNG-спрайтов, которые надо подать как -i.

    Pop-анимация:
      scale = sprite_size * (1 - exp(-3 * progress))   при progress < 0.4 (быстрый рост)
              sprite_size * (0.95 + 0.05 * cos(...))   потом небольшой bounce
      Упрощённо: используем enable + scale-tween через `if`.
      Поскольку overlay не поддерживает per-frame scale напрямую,
      каждый эмодзи получает свой scale-фильтр с фиксированным размером,
      а pop достигается через короткий fade-in (alpha tween).
    """
    if not emojis:
        return [], [], base_label

    extra_inputs: list[str] = []
    filters: list[str] = []
    cur = base_label

    target_sprite = int(target_h * 0.13)  # ~13% от высоты кадра

    for i, e in enumerate(emojis):
        png = render_emoji_png(e.emoji, size=sprite_size)
        if not png:
            continue
        extra_inputs.append(str(png))
        # input idx = текущая длина списка extra_inputs (после добавления),
        # но сам индекс будет проставлен позже в apply.py через {input_offset}.
        # Здесь используем плейсхолдер, который apply.py заменит.
        idx_placeholder = f"__EMOJI_{i}__"
        sprite_label = f"[em{i}]"
        # масштабируем PNG → target_sprite. loop=-1 превращает 1-кадровый PNG в
        # бесконечный поток, иначе fade и enable не работают за пределами 1/fps.
        # setpts=PTS-STARTPTS обнуляет таймстемпы (loop сбрасывает их в 0).
        filters.append(
            f"[{idx_placeholder}:v]loop=loop=-1:size=1:start=0,setpts=PTS-STARTPTS,"
            f"scale={target_sprite}:{target_sprite}:"
            f"force_original_aspect_ratio=decrease,format=rgba[em{i}_s]"
        )
        # fade-in/out через alpha
        fade_in = 0.15
        fade_out = 0.20
        end_t = e.timestamp + e.duration
        filters.append(
            f"[em{i}_s]fade=t=in:st={e.timestamp:.2f}:d={fade_in}:alpha=1,"
            f"fade=t=out:st={max(0, end_t - fade_out):.2f}:d={fade_out}:alpha=1"
            f"{sprite_label}"
        )
        x_expr, y_expr = emoji_position_xy(e.position, target_w, target_h, target_sprite)
        out_label = f"[v_em{i}]"
        filters.append(
            f"{cur}{sprite_label}overlay=x={x_expr}:y={y_expr}:"
            f"enable='between(t,{e.timestamp:.2f},{end_t:.2f})'"
            f"{out_label}"
        )
        cur = out_label

    return filters, extra_inputs, cur
