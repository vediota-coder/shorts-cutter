"""Скачивание видео с YouTube / VK / VK Video через yt-dlp.

Особенности устойчивости:
- автоматический resume (сохраняем .part-файлы)
- много retries на сетевые таймауты (YouTube часто троттлит)
- большой socket_timeout
- cookies-from-browser для обхода троттлинга (опционально)
- максимальная высота настраивается (1080/720/480)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import yt_dlp


ProgressFn = Callable[[float, str], None]


SUPPORTED_PATTERNS = [
    r"(youtube\.com|youtu\.be)",
    r"(vk\.com/video|vkvideo\.ru|vk\.ru/video)",
]


@dataclass
class DownloadResult:
    path: Path
    title: str
    duration: float
    source: str


def detect_source(url: str) -> str:
    if re.search(SUPPORTED_PATTERNS[0], url):
        return "youtube"
    if re.search(SUPPORTED_PATTERNS[1], url):
        return "vk"
    raise ValueError(f"Неподдерживаемый URL: {url}. Поддерживаются YouTube и VK Video.")


def download(
    url: str,
    out_dir: Path,
    on_progress: Optional[ProgressFn] = None,
    *,
    max_height: int = 1080,
    cookies_from_browser: Optional[str] = None,  # "chrome" | "safari" | "firefox" | None
) -> DownloadResult:
    source = detect_source(url)
    out_dir.mkdir(parents=True, exist_ok=True)

    def _hook(d: dict) -> None:
        if on_progress is None:
            return
        st = d.get("status")
        if st == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            pct = (done / total * 100) if total else 0
            mb_done = done / 1_000_000
            mb_total = total / 1_000_000 if total else 0
            speed = (d.get("speed") or 0) / 1_000_000
            retry = d.get("retry") or 0
            tag = f" (retry {retry})" if retry else ""
            on_progress(min(99, pct), f"{mb_done:.1f}/{mb_total:.1f} MB · {speed:.1f} MB/s{tag}")
        elif st == "finished":
            on_progress(100, "склейка ffmpeg…")
        elif st == "error":
            on_progress(0, "ошибка скачивания, ретраим…")

    opts = {
        # ⚠ без [ext=mp4] чтобы не отсечь webm/av1 — merge_output_format всё равно даст mp4.
        # Без явного player_client — yt-dlp сам подберёт; android урезан до 360p Google'ом,
        # а tv_embedded удалён из свежих yt-dlp.
        "format": (
            f"bestvideo[height<={max_height}]+bestaudio/"
            f"best[height<={max_height}]/best"
        ),
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_hook],
        # ── устойчивость к таймаутам YouTube ──
        "retries": 10,             # общие ретраи
        "fragment_retries": 10,    # для DASH-фрагментов
        "file_access_retries": 5,
        "socket_timeout": 60,      # больше дефолтных 20с
        "continuedl": True,        # resume с .part
        "concurrent_fragment_downloads": 4,  # параллельно качаем фрагменты
    }
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)

    def _do_download(opts: dict):
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return info, Path(ydl.prepare_filename(info)).with_suffix(".mp4")

    try:
        info, path = _do_download(opts)
    except Exception as e:
        msg = str(e).lower()
        # cookies из браузера не нашлись или не разблокированы — пробуем без них
        if cookies_from_browser and (
            "cookies database" in msg or "could not find" in msg
            or "couldn't read cookies" in msg or "not unlocked" in msg
        ):
            if on_progress:
                on_progress(0, f"⚠ cookies {cookies_from_browser} не доступны, продолжаю без них")
            opts.pop("cookiesfrombrowser", None)
            info, path = _do_download(opts)
        else:
            raise

    return DownloadResult(
        path=path,
        title=info.get("title", "untitled"),
        duration=float(info.get("duration", 0)),
        source=source,
    )


if __name__ == "__main__":
    import sys
    res = download(sys.argv[1], Path("downloads"))
    print(f"{res.source}: {res.title} ({res.duration:.0f}s) → {res.path}")
