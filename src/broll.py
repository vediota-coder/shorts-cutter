"""B-roll вставки через Pexels API.

Пайплайн:
1. По транскрипту клипа Claude выбирает 1-3 ключевых слова → Pexels.
2. Для каждого слова находим короткое (5-15с) вертикальное видео.
3. Скачиваем во временный файл.
4. Вставляем в клип как overlay 1.5-2.5с поверх видео (аудио оригинала остаётся).
   Момент вставки — там, где спикер произносит «вот», «посмотрите», «здесь»,
   или просто в смысловой паузе посередине.

Хранилище: jobs/<id>/_broll/<clip>_<keyword>.mp4
"""
from __future__ import annotations

import os
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import requests


PEXELS_API = "https://api.pexels.com/videos/search"


@dataclass
class BRollCandidate:
    keyword: str
    pexels_id: int
    url: str             # прямой mp4 URL
    duration: float
    width: int
    height: int
    preview_url: str = ""


def search_pexels(api_key: str, query: str, per_page: int = 5,
                  prefer_vertical: bool = True) -> list[BRollCandidate]:
    if not api_key:
        raise RuntimeError("Pexels API key не установлен")
    r = requests.get(
        PEXELS_API,
        params={
            "query": query, "per_page": per_page,
            "orientation": "portrait" if prefer_vertical else "landscape",
            "size": "medium",
        },
        headers={"Authorization": api_key}, timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    out: list[BRollCandidate] = []
    for v in data.get("videos", []):
        # выбираем mp4 файл с разумным разрешением
        best = None
        for vf in v.get("video_files", []):
            if vf.get("file_type") == "video/mp4" and vf.get("width", 0) >= 720:
                if not best or vf.get("width", 0) < best["width"]:
                    best = vf
        if not best:
            continue
        out.append(BRollCandidate(
            keyword=query,
            pexels_id=v["id"],
            url=best["link"],
            duration=float(v.get("duration", 0) or 0),
            width=int(best.get("width", 0) or 0),
            height=int(best.get("height", 0) or 0),
            preview_url=v.get("image", ""),
        ))
    return out


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dest)
    return dest


def insert_broll_overlay(
    base_video: Path,
    broll_video: Path,
    out_path: Path,
    insert_at: float,
    duration: float = 2.0,
) -> Path:
    """Вставляет broll как overlay на base_video с insert_at на duration секунд.

    Аудио base_video сохраняется. Broll масштабируется под размер base.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", str(base_video),
        "-i", str(broll_video),
        "-filter_complex",
        f"[1:v]scale=iw:ih,setpts=PTS-STARTPTS[brl];"
        f"[0:v][brl]overlay=enable='between(t,{insert_at},{insert_at + duration})':"
        f"x=(W-w)/2:y=(H-h)/2[v]",
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "copy",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return out_path


SETTINGS_FILE = Path(__file__).parent.parent / ".env"


def load_pexels_key() -> str:
    if not SETTINGS_FILE.exists():
        return ""
    for line in SETTINGS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("PEXELS_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("PEXELS_API_KEY", "")
