"""Pipeline для импорта YouTube-канала в контент-план.
- yt-dlp → метаданные
- категоризация по ключевым словам + темам из формы
- youtube-transcript-api → транскрипции топ-N
- LLM → рерайты для топ-N под список продуктов пользователя
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Optional

# Глобальный state одного активного job (MVP — один в один момент времени)
IMPORT_JOB: dict = {
    "status": "idle",        # idle | running | done | error
    "step": "",              # человекочитаемая текущая фаза
    "progress": 0,           # 0..100
    "log": [],               # массив строк
    "result": None,          # сводка
    "started_at": 0,
    "finished_at": 0,
}

_LOCK = asyncio.Lock()


def _log(msg: str):
    IMPORT_JOB["log"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")
    if len(IMPORT_JOB["log"]) > 500:
        IMPORT_JOB["log"] = IMPORT_JOB["log"][-500:]


def _progress(p: int, step: str = ""):
    IMPORT_JOB["progress"] = max(0, min(100, p))
    if step:
        IMPORT_JOB["step"] = step


# ---------- yt-dlp ----------

def _parse_channel(url: str) -> list[dict]:
    """Выгружает метаданные shorts из yt-dlp."""
    if "/shorts" not in url and not url.endswith("/shorts/"):
        url = url.rstrip("/") + "/shorts"

    try:
        proc = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--dump-json", url],
            capture_output=True, text=True, timeout=600
        )
    except FileNotFoundError:
        raise RuntimeError("yt-dlp не установлен. Установи: brew install yt-dlp")
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp ошибка: {proc.stderr[:500]}")

    videos = []
    for line in proc.stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            v = json.loads(line)
            videos.append({
                "id": v["id"],
                "title": v.get("title", ""),
                "url": v.get("url", f"https://www.youtube.com/shorts/{v['id']}"),
                "view_count": v.get("view_count") or 0,
                "thumbnail": f"https://i.ytimg.com/vi/{v['id']}/hq720.jpg",
            })
        except Exception:
            continue
    return videos


# ---------- категоризация ----------

DEFAULT_KEYWORDS = {
    "b2b_sales": [r"\bb2b\b", r"корпоратив", r"крупн.{0,5} клиент", r"отдел продаж", r"переговор",
                  r"sales", r"менеджер.{0,5} прода"],
    "avito": [r"авито", r"avito", r"объявлен", r"маркетплейс"],
    "cold_outreach": [r"холодн.{0,5}", r"cold (call|email|outreach)", r"email", r"рассылк"],
    "youtube_content": [r"youtube", r"ютуб", r"контент", r"content", r"shorts", r"шортс", r"подкаст", r"блог"],
    "ai_automation": [r"\bai\b", r"\bии\b", r"chatgpt", r"gpt", r"искусственн", r"нейросет",
                      r"автоматизац", r"\bcrm\b", r"бот"],
    "high_ticket": [r"больш.{0,5} чек", r"high.?ticket", r"премиум", r"миллион", r"\d+\s?млн"],
    "hiring_team": [r"найм", r"hiring", r"recruit", r"\bhr\b", r"команд", r"team", r"сотрудник"],
    "mindset_motivation": [r"мотивац", r"мышлен", r"mindset", r"страх", r"успех", r"цел[иь]"],
    "money_cases": [r"\d+\s?(млн|m|тыс|k)", r"выручк", r"прибыль", r"кейс", r"case"],
    "strategy_business": [r"бизнес", r"business", r"стратеги", r"масштаб", r"рост\b", r"ниша"],
    "marketing_traffic": [r"маркетинг", r"marketing", r"таргет", r"реклам", r"трафик", r"лид", r"воронк"],
}

NAMES = {
    "b2b_sales": "B2B продажи",
    "avito": "Авито",
    "cold_outreach": "Холодные продажи / Email outreach",
    "youtube_content": "YouTube / Контент",
    "ai_automation": "AI / Автоматизация",
    "high_ticket": "Большой чек",
    "hiring_team": "Найм / Команда",
    "mindset_motivation": "Мышление / Мотивация",
    "money_cases": "Кейсы / Цифры",
    "strategy_business": "Стратегия / Бизнес",
    "marketing_traffic": "Маркетинг / Трафик",
    "other": "Другое",
}


def _categorize(videos: list[dict]) -> dict:
    for v in videos:
        t = v["title"].lower()
        tags = []
        for cat, patterns in DEFAULT_KEYWORDS.items():
            for p in patterns:
                if re.search(p, t):
                    tags.append(cat)
                    break
        if not tags:
            tags = ["other"]
        v["categories"] = tags

    videos.sort(key=lambda x: -x["view_count"])
    top_n = max(1, int(len(videos) * 0.2))
    threshold = videos[top_n - 1]["view_count"]
    for v in videos:
        v["is_viral"] = v["view_count"] >= threshold

    cat_count = Counter()
    viral_count = Counter()
    for v in videos:
        for c in v["categories"]:
            cat_count[c] += 1
            if v["is_viral"]:
                viral_count[c] += 1

    return {
        "total": len(videos),
        "viral_threshold": threshold,
        "viral_count": sum(1 for v in videos if v["is_viral"]),
        "categories": NAMES,
        "stats": {"by_category": dict(cat_count), "viral_by_category": dict(viral_count)},
        "videos": videos,
    }


# ---------- транскрипции через youtube-transcript-api ----------

def _fetch_transcripts(videos: list[dict], top_n: int, transcripts_dir: Path) -> int:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import (
            TranscriptsDisabled, NoTranscriptFound, VideoUnavailable, CouldNotRetrieveTranscript
        )
    except ImportError:
        _log("youtube-transcript-api не установлен. Пропускаю транскрипции.")
        return 0

    transcripts_dir.mkdir(parents=True, exist_ok=True)
    api = YouTubeTranscriptApi()
    target = videos[:top_n]
    ok = 0
    skip_errors = (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable, CouldNotRetrieveTranscript)
    for i, v in enumerate(target):
        vid = v["id"]
        out = transcripts_dir / f"{vid}.json"
        if out.exists():
            ok += 1
            continue
        try:
            t = api.fetch(vid, languages=["ru", "en"])
            text = " ".join(s.text for s in t.snippets).strip()
            if text:
                out.write_text(json.dumps({
                    "video_id": vid, "title": v["title"], "url": v["url"],
                    "view_count": v["view_count"], "text": text,
                }, ensure_ascii=False))
                ok += 1
        except skip_errors:
            pass
        except Exception as e:
            _log(f"  err {vid}: {type(e).__name__}")
        if (i + 1) % 10 == 0:
            _progress(40 + int(40 * (i + 1) / len(target)), f"Транскрипции {i+1}/{len(target)}")
    return ok


# ---------- whisper fallback (stream: качаем аудио → транскрибируем → удаляем) ----------

def _whisper_fallback(videos: list[dict], top_n: int, transcripts_dir: Path,
                      on_progress_cb=None) -> int:
    """Для каждого шортса в топ-N без существующего транскрипта:
    - качаем только аудио через yt-dlp (~300KB-1MB)
    - транскрибируем через whisper (MLX/Groq/faster)
    - сохраняем .json, удаляем аудио
    Память не растёт — один файл в момент времени.
    """
    try:
        from src.transcribe import transcribe, detect_backend
    except Exception as e:
        _log(f"Whisper-модуль недоступен: {e}")
        return 0

    info = detect_backend()
    _log(f"Whisper backend: {info.name} · {info.device}")

    transcripts_dir.mkdir(parents=True, exist_ok=True)
    target = videos[:top_n]
    pending = [v for v in target if not (transcripts_dir / f"{v['id']}.json").exists()]
    if not pending:
        _log("Нет шортсов для whisper-fallback (все уже с транскрипциями)")
        return 0
    _log(f"Whisper-fallback: будет обработано {len(pending)} шортсов")

    ok = 0
    with tempfile.TemporaryDirectory(prefix="cp_whisper_") as tmpdir:
        tmp = Path(tmpdir)
        for i, v in enumerate(pending):
            vid = v["id"]
            url = v["url"]
            audio_path = tmp / f"{vid}.m4a"

            # 1. Качаем только аудио
            try:
                proc = subprocess.run(
                    ["yt-dlp", "-x", "--audio-format", "m4a", "--audio-quality", "9",
                     "--no-playlist", "--quiet", "--no-warnings",
                     "-o", str(audio_path).replace(".m4a", ".%(ext)s"), url],
                    capture_output=True, text=True, timeout=120
                )
                # yt-dlp может сохранить с другим расширением — ищем что появилось
                got = list(tmp.glob(f"{vid}.*"))
                if not got:
                    _log(f"  yt-dlp не дал аудио для {vid}")
                    continue
                audio_path = got[0]
            except Exception as e:
                _log(f"  yt-dlp err {vid}: {type(e).__name__}")
                continue

            # 2. Транскрибируем
            try:
                segments = transcribe(audio_path, model_size="auto")
                text = " ".join(s.text.strip() for s in segments if s.text).strip()
            except Exception as e:
                _log(f"  whisper err {vid}: {type(e).__name__}: {str(e)[:200]}")
                audio_path.unlink(missing_ok=True)
                continue

            # 3. Сохраняем + удаляем аудио
            audio_path.unlink(missing_ok=True)

            if text:
                out = transcripts_dir / f"{vid}.json"
                out.write_text(json.dumps({
                    "video_id": vid, "title": v["title"], "url": v["url"],
                    "view_count": v["view_count"], "text": text,
                    "source": "whisper",
                }, ensure_ascii=False))
                ok += 1

            if (i + 1) % 5 == 0 or i == len(pending) - 1:
                _progress(60 + int(20 * (i + 1) / len(pending)), f"Whisper {i+1}/{len(pending)}")
                _log(f"  [{i+1}/{len(pending)}] ok={ok}")
    return ok


# ---------- рерайты через LLM ----------

REWRITE_SYSTEM = """Ты — копирайтер шортсов под спикера-предпринимателя.
Тебе дают оригинал шортса другого автора и:
- сферу спикера (его продукты),
- его архетип/тон.

Делаешь N рерайтов, по одному под каждый продукт. Каждый рерайт:
1. Сохраняет МЕХАНИКУ оригинального хука (парадокс / провокация / цитата клиента).
2. ИСТОРИЯ берётся из мира спикера (не пересказ оригинала).
3. Формула: ХУК (≤12 слов) → ЗАЦЕП → ПОВОРОТ → ЗАМОК.
4. Короткие фразы по одному выдоху, под живую речь.
5. Никакого пафоса, кочинг-штампов, «успешного успеха».

Ответ только в JSON формате:
{
  "rewrites": [
    {"product": "название продукта", "score": 1-5, "text": "[хук]\\n...[зацеп]\\n..."}
  ]
}
score — насколько органично механика оригинала ложится на этот продукт."""


def _generate_rewrites(videos: list[dict], top_n: int, transcripts_dir: Path,
                       products: list[str], topics: list[str], persona: str,
                       provider_name: str, model: Optional[str],
                       rewrites_path: Path):
    try:
        from src.llm.registry import get_provider
    except Exception as e:
        _log(f"LLM registry недоступен: {e}")
        return

    try:
        provider = get_provider(provider_name)
    except Exception as e:
        _log(f"Не удалось получить LLM-провайдер {provider_name}: {e}")
        return

    if not provider.is_configured():
        _log(f"LLM-провайдер {provider_name} не настроен (нет ключа).")
        return

    rewrites = {}
    if rewrites_path.exists():
        try:
            rewrites = json.loads(rewrites_path.read_text())
        except Exception:
            rewrites = {}

    target = [v for v in videos[:top_n] if (transcripts_dir / f"{v['id']}.json").exists()]
    if not target:
        _log("Нет транскрипций для генерации рерайтов.")
        return

    for i, v in enumerate(target):
        vid = v["id"]
        if vid in rewrites:
            continue
        try:
            t = json.loads((transcripts_dir / f"{vid}.json").read_text())
            text = t.get("text", "")
        except Exception:
            continue

        topics_block = ""
        if topics:
            topics_block = "Темы которые интересуют спикера в этом канале:\n" + "\n".join(f"- {t}" for t in topics) + "\n\n"

        user_prompt = (
            f"Персона и тон спикера:\n{persona}\n\n"
            f"{topics_block}"
            f"Продукты спикера (для каждого делаешь свою версию):\n"
            + "\n".join(f"- {p}" for p in products) +
            f"\n\nОригинал шортса (просмотры: {v['view_count']:,}):\n"
            f"Заголовок: {v['title']}\n"
            f"Текст: {text}\n\n"
            f"Сделай по одному рерайту под каждый из {len(products)} продуктов."
        )

        try:
            resp = provider.generate(
                system=REWRITE_SYSTEM,
                user=user_prompt,
                max_tokens=4000,
                response_json=True,
                model=model
            )
            data = json.loads(resp.text)
            rewrites[vid] = data.get("rewrites", [])
            rewrites_path.write_text(json.dumps(rewrites, ensure_ascii=False, indent=2))
        except Exception as e:
            _log(f"  rewrite err {vid}: {type(e).__name__}: {str(e)[:200]}")
            continue

        _progress(80 + int(20 * (i + 1) / len(target)), f"Рерайты {i+1}/{len(target)}")


# ---------- main pipeline ----------

async def run_import(
    channel_url: str,
    content_data: Path,
    top_n: int = 200,
    fetch_transcripts: bool = True,
    whisper_fallback: bool = False,
    generate_rewrites: bool = False,
    products: Optional[list[str]] = None,
    topics: Optional[list[str]] = None,
    persona: str = "",
    provider: str = "anthropic",
    model: Optional[str] = None,
):
    """Главный pipeline. Запускается в фоновой asyncio.task."""
    IMPORT_JOB.update({
        "status": "running", "step": "Старт", "progress": 0,
        "log": [], "result": None,
        "started_at": time.time(), "finished_at": 0,
    })
    try:
        _log(f"URL: {channel_url}")
        _progress(5, "Парсинг канала через yt-dlp…")
        videos = await asyncio.to_thread(_parse_channel, channel_url)
        _log(f"Найдено {len(videos)} шортсов")
        if not videos:
            raise RuntimeError("Пустой канал или yt-dlp вернул 0 видео")

        _progress(30, "Категоризация…")
        cat = await asyncio.to_thread(_categorize, videos)
        (content_data / "categorized.json").write_text(json.dumps(cat, ensure_ascii=False, indent=2))
        _log(f"Категорий: {len([c for c, n in cat['stats']['by_category'].items() if n])}, залетевших: {cat['viral_count']}")

        ok_transcripts = 0
        if fetch_transcripts:
            _progress(40, f"Транскрипции через YouTube subtitles (топ-{top_n})…")
            ok_transcripts = await asyncio.to_thread(
                _fetch_transcripts, cat["videos"], top_n, content_data / "transcripts"
            )
            _log(f"Скачано через subtitles: {ok_transcripts}")

        if whisper_fallback:
            _progress(60, "Whisper-fallback (stream аудио → транскрипт)…")
            ok_whisper = await asyncio.to_thread(
                _whisper_fallback, cat["videos"], top_n, content_data / "transcripts"
            )
            _log(f"Добавлено через whisper: {ok_whisper}")
            ok_transcripts += ok_whisper

        ok_rewrites = 0
        if generate_rewrites and products:
            _progress(80, "Генерация рерайтов через LLM…")
            await asyncio.to_thread(
                _generate_rewrites,
                cat["videos"], top_n, content_data / "transcripts",
                products, topics or [], persona, provider, model,
                content_data / "rewrites.json"
            )
            try:
                ok_rewrites = len(json.loads((content_data / "rewrites.json").read_text()))
            except Exception:
                pass

        _progress(100, "Готово")
        IMPORT_JOB["status"] = "done"
        IMPORT_JOB["result"] = {
            "total_videos": len(videos),
            "viral_count": cat["viral_count"],
            "transcripts": ok_transcripts,
            "rewrites": ok_rewrites,
        }
        _log(f"DONE: видео={len(videos)} транскрипций={ok_transcripts} рерайтов={ok_rewrites}")
    except Exception as e:
        IMPORT_JOB["status"] = "error"
        IMPORT_JOB["step"] = f"Ошибка: {e}"
        _log(f"ERROR: {type(e).__name__}: {e}")
    finally:
        IMPORT_JOB["finished_at"] = time.time()
