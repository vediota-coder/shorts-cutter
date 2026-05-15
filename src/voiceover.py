"""RU-дубляж англоязычных видео: перевод сегментов + ElevenLabs TTS + сборка дорожки."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import urllib.request
import urllib.error

from .llm import default_provider, get_provider
from .transcribe import Segment


ELEVEN_API_BASE = "https://api.elevenlabs.io/v1"

# https://elevenlabs.io/docs/api-reference/text-to-speech (May 2026):
# eleven_multilingual_v2 — стабильный многоязычный, $120/1M симв
# eleven_v3              — самый эмоциональный/выразительный, RU отличный
# Для дубляжа берём v3 как качество-флагман (выбор пользователя).
# GA с февраля 2026, 70+ языков, audio tags для эмоций. Дефолт.
DEFAULT_TTS_MODEL = "eleven_v3"
# Модели, поддерживающие inline-теги [excited]/[whispers]/[sighs]/[laughs]/...
EMOTION_TAG_MODELS = {"eleven_v3"}

# Дефолтные voice_id из публичной библиотеки ElevenLabs.
# Пользователь может прописать свой через UI/CLI.
DEFAULT_VOICE_RU_FEMALE = "EXAVITQu4vr4xnSDxMaL"  # "Sarah" — нейтральный женский, хорошо звучит на RU
DEFAULT_VOICE_RU_MALE = "JBFqnCBsd6RMkjVDRZzb"    # "George" — спокойный мужской

PROGRESS = Callable[[float, str], None]


@dataclass
class TranslatedSegment:
    start: float
    end: float
    text_en: str
    text_ru: str


def _noop(_p: float, _m: str) -> None:
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Перевод
# ─────────────────────────────────────────────────────────────────────────────

_TRANSLATE_SYSTEM_BASE = """Ты — переводчик субтитров для дубляжа.

Тебе дают список сегментов с английским текстом и индексами.
Переведи КАЖДЫЙ сегмент на разговорный русский язык так, чтобы озвучка по длительности
совпадала с оригиналом (примерно столько же слогов).

Правила:
- Сохраняй смысл и тон, но используй естественный русский, не дословный.
- Не добавляй пояснений, не объединяй и не дроби сегменты.
- Если в оригинале короткое восклицание — перевод тоже короткий.
- Имена собственные — оставь как принято в русском.
- Для отдельных непереводимых терминов — оставь латиницей.

# ОЧЕНЬ ВАЖНО: числа и ударения для TTS

ElevenLabs не умеет правильно читать русские числа — пиши прописью:
- Цифры → словами: "1000" → "тысяча", "$45,000" → "сорок пять тысяч долларов",
  "2026" → "две тысячи двадцать шестой", "60%" → "шестьдесят процентов".
- Даты → словами с правильным падежом: "March 5" → "пятое марта".
- Дроби и проценты — словами: "1.5x" → "в полтора раза", "10%" → "десять процентов".

Расставляй УДАРЕНИЯ через символ ́ (combining acute, U+0301) над ударной гласной:
- ВСЕГДА для чисел прописью: "со́рок пя́ть ты́сяч до́лларов", "две́ ты́сячи два́дцать шесто́й".
- Для слов с неочевидным/частоошибочным ударением: "за́мок" vs "замо́к", "до́говор",
  "обеспе́чение", "звони́т", "красиве́е", "одновреме́нно".
- Для имён собственных где ударение могут перепутать: "Илья́", "Никола́й", "Ма́рия".
- Для иностранных слов в кириллической транскрипции: "Илон Ма́ск", "Я́нсен Ха́унг".

НЕ ставь ударения на каждое слово — только там где TTS реально может ошибиться.
Стандартные слова с очевидным ударением оставляй как есть."""

_TRANSLATE_SYSTEM_TAGS = """
# Эмоциональные теги (ElevenLabs v3 audio tags)
По смыслу оригинала добавляй inline-теги в квадратных скобках перед той фразой,
к которой они относятся. Используй только когда эмоция явно читается:

- [excited]   — эмоциональный подъём, восторг, важное откровение
- [whispers]  — тихое признание, секрет, интим
- [laughs]    — смех; вставляется как самостоятельный «звук» отдельной репликой
- [sighs]     — вздох, сомнение, разочарование
- [angry]     — злость, негодование
- [sarcastic] — сарказм, ирония
- [calmly]    — намеренно спокойный тон при эмоциональной теме

Правила тегов:
- Не более 1-2 тегов на сегмент.
- Не лепи теги в каждый сегмент — только когда оригинал реально эмоционален.
- Тег ставится В НАЧАЛЕ фразы или в логической паузе: "[excited] Вот это да!"
- Не используй другие теги, кроме перечисленных.
"""

_TRANSLATE_FORMAT = """
Возвращай СТРОГО JSON в формате:
{"items": [{"i": 0, "ru": "..."}, {"i": 1, "ru": "..."}, ...]}
"""


def _build_translate_system(emotion_tags: bool) -> str:
    parts = [_TRANSLATE_SYSTEM_BASE]
    if emotion_tags:
        parts.append(_TRANSLATE_SYSTEM_TAGS)
    parts.append(_TRANSLATE_FORMAT)
    return "\n".join(parts)


def translate_segments_ru(
    segments: list[Segment],
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    batch_size: int = 80,
    emotion_tags: bool = False,
    on_progress: PROGRESS = _noop,
) -> list[TranslatedSegment]:
    """Переводит whisper-сегменты EN → RU батчами.

    emotion_tags=True — LLM добавит inline-теги [excited]/[whispers]/... для ElevenLabs v3.
    """
    prov_name = provider or default_provider()
    prov = get_provider(prov_name)
    system = _build_translate_system(emotion_tags)

    out: list[TranslatedSegment] = []
    total = len(segments)
    if total == 0:
        return out

    for batch_start in range(0, total, batch_size):
        batch = segments[batch_start:batch_start + batch_size]
        items = [{"i": batch_start + idx, "en": s.text} for idx, s in enumerate(batch)]
        user = json.dumps({"items": items}, ensure_ascii=False)
        on_progress(
            batch_start / total * 100,
            f"перевод {batch_start + 1}–{batch_start + len(batch)} из {total}",
        )
        resp = prov.generate(
            system=system, user=user,
            max_tokens=4000, response_json=True, model=model,
        )
        ru_by_i = _parse_translation(resp.text)
        for idx, seg in enumerate(batch):
            i = batch_start + idx
            ru = ru_by_i.get(i, "").strip() or seg.text  # фолбэк — оригинал
            out.append(TranslatedSegment(
                start=seg.start, end=seg.end, text_en=seg.text, text_ru=ru,
            ))
    on_progress(100, f"переведено {len(out)} сегментов")
    return out


def _parse_translation(text: str) -> dict[int, str]:
    """Dub-specific: достаёт {i: ru} из ответа LLM. Переиспользует общий парсер."""
    from .llm.translate import _parse_json_items
    return _parse_json_items(text, key="ru")


# ─────────────────────────────────────────────────────────────────────────────
# ElevenLabs TTS
# ─────────────────────────────────────────────────────────────────────────────


def _http_post(url: str, headers: dict, body: bytes, timeout: float = 120.0) -> tuple[bytes, str]:
    """Возвращает (body_bytes, content_type)."""
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), r.headers.get("content-type", "")
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"ElevenLabs HTTP {e.code}: {msg}") from None


def translated_to_segments(translated: list[TranslatedSegment]):
    """Делает list[transcribe.Segment] с RU-текстом и СИНТЕТИЧЕСКИМИ word-таймингами
    (равномерное распределение слов по [start, end]). Используется для генерации
    русских субтитров, когда оригинал был EN.
    """
    from .transcribe import Segment, Word
    out = []
    for ts in translated:
        # убираем ElevenLabs audio-теги [excited]/[whispers]/... из субтитров
        sub_text = re.sub(r"\[[a-zA-Zа-яА-Я ]+\]", "", ts.text_ru).strip()
        if not sub_text:
            continue
        words_str = sub_text.split()
        n = max(1, len(words_str))
        dur = max(0.05, ts.end - ts.start)
        per_word = dur / n
        words = []
        for i, w in enumerate(words_str):
            ws = ts.start + i * per_word
            we = ts.start + (i + 1) * per_word
            words.append(Word(ws, we, w))
        out.append(Segment(ts.start, ts.end, sub_text, words))
    return out


def apply_pronunciations(text: str, pronunciations: dict[str, str] | None) -> str:
    """Заменяет вхождения слов из словаря на их TTS-произношение.
    Регистронезависимо для поиска, но сохраняем регистр первой буквы оригинала.
    """
    if not pronunciations:
        return text
    out = text
    # сортируем по длине ключа убыв., чтобы 'GPT-4' заменилось до 'GPT'
    for src in sorted(pronunciations.keys(), key=len, reverse=True):
        dst = pronunciations[src]
        # word boundary через простой re (поддержка кириллицы важна — \b работает)
        pat = re.compile(r"(?<!\w)" + re.escape(src) + r"(?!\w)", re.IGNORECASE)
        out = pat.sub(dst, out)
    return out


def synthesize(
    text: str,
    *,
    voice_id: str,
    api_key: str,
    model_id: str = DEFAULT_TTS_MODEL,
    out_path: Path,
    stability: float = 0.5,
    similarity_boost: float = 0.75,
    speed: float = 1.0,
    pronunciations: dict[str, str] | None = None,
) -> Path:
    """Синтез одного фрагмента → MP3 файл."""
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY не задан")
    text = apply_pronunciations(text, pronunciations)
    url = f"{ELEVEN_API_BASE}/text-to-speech/{voice_id}?output_format=mp3_44100_128"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
            "speed": speed,
        },
    }
    audio, ctype = _http_post(url, headers, json.dumps(payload).encode("utf-8"))
    # ⭐ валидация: ElevenLabs при country block / proxy issue возвращает 200 с HTML.
    # Если не audio/mpeg — НЕ пишем в файл, явно фейлим запрос.
    if "audio" not in ctype.lower() or len(audio) < 200:
        snippet = audio[:200].decode("utf-8", errors="replace")
        raise RuntimeError(
            f"ElevenLabs TTS вернул не-аудио (content-type={ctype!r}, {len(audio)} байт). "
            f"Возможно VPN/proxy блок. Первые 200 байт: {snippet}"
        )
    out_path.write_bytes(audio)
    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# Сборка дубляж-дорожки для клипа
# ─────────────────────────────────────────────────────────────────────────────


def _ffprobe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip() or 0.0)


def _atempo_chain(speed: float) -> str:
    """ffmpeg atempo допускает [0.5, 100.0], рекомендуется ≤2.0 за фильтр.
    Для аккуратной растяжки/сжатия делаем цепочку.
    """
    speed = max(0.5, min(speed, 4.0))
    chain = []
    while speed > 2.0:
        chain.append("atempo=2.0")
        speed /= 2.0
    while speed < 0.5:
        chain.append("atempo=0.5")
        speed /= 0.5
    chain.append(f"atempo={speed:.4f}")
    return ",".join(chain)


def _fit_to_slot(
    src_mp3: Path, slot_dur: float, out_wav: Path,
    *,
    min_speed: float = 0.85,
    max_speed: float = 1.30,
) -> Path:
    """Подгоняем MP3 под slot_dur секунд:
    - tempo плавно в [min_speed, max_speed] — без рывков и мультяшности.
    - если за пределами — допускаем слегка хвост (silence pad) или мягкую truncation.
    Выход: 48k mono WAV ровно slot_dur секунд.
    """
    src_dur = _ffprobe_duration(src_mp3)
    if slot_dur <= 0.05:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
             "-t", f"{max(slot_dur, 0.01):.3f}", "-c:a", "pcm_s16le", str(out_wav)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return out_wav

    if src_dur <= 0:
        # фолбэк silence
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
             "-t", f"{slot_dur:.3f}", "-c:a", "pcm_s16le", str(out_wav)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return out_wav

    speed = max(min_speed, min(max_speed, src_dur / slot_dur))
    af = _atempo_chain(speed)
    cmd = [
        "ffmpeg", "-y", "-i", str(src_mp3),
        "-af", af,
        "-ar", "48000", "-ac", "1",
        "-c:a", "pcm_s16le",
        str(out_wav),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    real_dur = _ffprobe_duration(out_wav)

    # если после tempo всё равно длиннее слота → мягкая truncation (с fadeout 80мс)
    if real_dur > slot_dur + 0.05:
        cut = out_wav.with_suffix(".cut.wav")
        fade_start = max(0.0, slot_dur - 0.08)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(out_wav),
             "-af", f"afade=t=out:st={fade_start:.3f}:d=0.08",
             "-t", f"{slot_dur:.3f}",
             "-c:a", "pcm_s16le", str(cut)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        cut.replace(out_wav)
    # если короче — добиваем тишиной
    elif real_dur + 0.02 < slot_dur:
        padded = out_wav.with_suffix(".padded.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(out_wav),
             "-af", f"apad=whole_dur={slot_dur:.3f}",
             "-c:a", "pcm_s16le", str(padded)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        padded.replace(out_wav)
    return out_wav


def build_dub_track(
    translated: list[TranslatedSegment],
    clip_start: float,
    clip_end: float,
    *,
    voice_id: str,
    api_key: str,
    model_id: str = DEFAULT_TTS_MODEL,
    out_path: Path,
    work_dir: Path,
    pronunciations: dict[str, str] | None = None,
    on_progress: PROGRESS = _noop,
) -> Path:
    """Собирает WAV ровно длительности (clip_end - clip_start) секунд:
    каждый сегмент из translated, попадающий в [clip_start, clip_end],
    озвучивается ElevenLabs и кладётся в свой временной слот.
    Между сегментами — тишина.
    """
    duration = max(clip_end - clip_start, 0.1)
    work_dir.mkdir(parents=True, exist_ok=True)

    # 1) отбираем сегменты, перекрывающие клип, в локальных координатах
    raw = []
    for ts in translated:
        if ts.end <= clip_start or ts.start >= clip_end:
            continue
        local_start = max(0.0, ts.start - clip_start)
        local_end = min(duration, ts.end - clip_start)
        if local_end - local_start < 0.15:
            continue
        raw.append((local_start, local_end, ts.text_ru))
    raw.sort(key=lambda x: x[0])

    # 2) ⭐ группируем в ФРАЗЫ — соседние сегменты с паузой <0.5с склеиваются.
    # Один TTS-запрос на всю фразу даёт ровную интонацию и единый темп вместо
    # рваного «то быстро то медленно» по микро-сегментам.
    PHRASE_GAP = 0.5
    slots: list[tuple[float, float, str]] = []
    for s, e, txt in raw:
        if slots and s - slots[-1][1] < PHRASE_GAP:
            ps, pe, pt = slots[-1]
            slots[-1] = (ps, e, (pt + " " + txt).strip())
        else:
            slots.append((s, e, txt))

    if not slots:
        # нет речи в клипе — просто silent track
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
             "-t", f"{duration:.3f}", "-c:a", "pcm_s16le", str(out_path)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return out_path

    # синтезируем все фрагменты (mp3) + подгоняем под слот (wav)
    fitted_paths: list[tuple[float, float, Path]] = []
    total = len(slots)
    for idx, (s, e, txt) in enumerate(slots):
        on_progress(idx / total * 100, f"TTS {idx + 1}/{total}")
        slot_dur = e - s
        mp3_path = work_dir / f"seg_{idx:04d}.mp3"
        wav_path = work_dir / f"seg_{idx:04d}.wav"
        try:
            synthesize(
                txt, voice_id=voice_id, api_key=api_key,
                model_id=model_id, out_path=mp3_path,
                pronunciations=pronunciations,
            )
        except Exception as ex:
            # ⭐ quota_exceeded / unauthorized / country block → роняем весь dub,
            # чтобы pipeline понял что озвучка реально сломана, а не делал silence-stub.
            msg = str(ex).lower()
            # ⭐ хард-фейл на любую "не имеешь права" ошибку — чтобы не было silence-stub'ов
            HARD_FAIL_KEYWORDS = (
                "quota_exceeded", "unauthorized", "401", "402",
                "payment_required", "paid_plan_required",
                "не-аудио", "missing_permissions", "forbidden",
            )
            if any(k in msg for k in HARD_FAIL_KEYWORDS):
                raise
            # одиночный transient сбой (timeout, 5xx) — заменяем silence, идём дальше
            print(f"[voiceover] TTS transient fail seg={idx}: {ex}")
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                 "-t", f"{slot_dur:.3f}", "-c:a", "pcm_s16le", str(wav_path)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            _fit_to_slot(mp3_path, slot_dur, wav_path)
        fitted_paths.append((s, e, wav_path))

    # склейка: filter_complex — каждый фрагмент через adelay на нужный offset, потом amix
    inputs = []
    filters = []
    mix_labels = []
    for idx, (s, _e, p) in enumerate(fitted_paths):
        inputs.extend(["-i", str(p)])
        delay_ms = int(s * 1000)
        filters.append(f"[{idx}:a]adelay={delay_ms}|{delay_ms}[a{idx}]")
        mix_labels.append(f"[a{idx}]")
    n = len(fitted_paths)
    filters.append(
        "".join(mix_labels) +
        f"amix=inputs={n}:dropout_transition=0:normalize=0[mix]"
    )
    # пэддинг до точной длительности
    filters.append(f"[mix]apad=whole_dur={duration:.3f}[out]")
    fc = ";".join(filters)

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", fc,
        "-map", "[out]",
        "-t", f"{duration:.3f}",
        "-ar", "48000", "-ac", "1",
        "-c:a", "pcm_s16le",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    on_progress(100, f"дубляж собран ({duration:.1f}с, {total} реплик)")
    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# ElevenLabs Dubbing API — клонирует голос оригинала, сохраняет эмоции и тайминг
# ─────────────────────────────────────────────────────────────────────────────


def _http_get(url: str, headers: dict, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"ElevenLabs HTTP {e.code}: {msg}") from None


def _http_post_multipart(
    url: str, headers: dict, fields: dict,
    files: dict[str, tuple[str, bytes, str]] | None = None,
    timeout: float = 600.0,
) -> bytes:
    """Минимальная multipart/form-data реализация без зависимостей."""
    boundary = "----shortscutter" + os.urandom(8).hex()
    body = bytearray()
    for k, v in fields.items():
        if v is None:
            continue
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8")
    for k, (fname, data, ctype) in (files or {}).items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fname}\"\r\nContent-Type: {ctype}\r\n\r\n".encode("utf-8")
        body += data
        body += b"\r\n"
    body += f"--{boundary}--\r\n".encode("utf-8")
    h = dict(headers)
    h["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    h["Content-Length"] = str(len(body))
    payload, _ctype = _http_post(url, h, bytes(body), timeout=timeout)
    return payload


def dub_full_video(
    video_path: Path,
    *,
    api_key: str,
    target_lang: str = "ru",
    source_lang: str = "auto",
    num_speakers: int = 0,
    drop_background_audio: bool = False,
    out_path: Path,
    poll_every: float = 10.0,
    timeout_s: float = 3600.0,
    on_progress: PROGRESS = _noop,
) -> Path:
    """Полный дубляж видео через ElevenLabs Dubbing API.

    1) POST /v1/dubbing с файлом → получаем dubbing_id.
    2) Polling GET /v1/dubbing/{id} пока status="dubbed".
    3) GET /v1/dubbing/{id}/audio/{lang} → mp4 c озвучкой целевого языка.

    Возвращает Path к скачанному mp4. Голоса оригинальных спикеров клонируются,
    тайминг и эмоции сохраняются.
    """
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY не задан")

    on_progress(1, f"загрузка {video_path.name} → ElevenLabs Dubbing")
    headers = {"xi-api-key": api_key, "Accept": "application/json"}
    fields = {
        "target_lang": target_lang,
        "source_lang": source_lang,
        "mode": "automatic",
        "num_speakers": str(num_speakers),
        "drop_background_audio": "true" if drop_background_audio else "false",
        "watermark": "false",
    }
    files = {
        "file": (video_path.name, video_path.read_bytes(), "video/mp4"),
    }
    resp = _http_post_multipart(
        f"{ELEVEN_API_BASE}/dubbing", headers, fields, files,
    )
    meta = json.loads(resp.decode("utf-8"))
    dubbing_id = meta.get("dubbing_id")
    expected_dur = float(meta.get("expected_duration_sec") or 0)
    if not dubbing_id:
        raise RuntimeError(f"Dubbing API не вернул dubbing_id: {meta}")
    on_progress(5, f"job создан id={dubbing_id} (~{expected_dur:.0f}с обработки)")

    # polling
    started = time.monotonic()
    while True:
        if time.monotonic() - started > timeout_s:
            raise RuntimeError(f"Dubbing timeout ({timeout_s:.0f}с) для {dubbing_id}")
        time.sleep(poll_every)
        try:
            status_raw = _http_get(
                f"{ELEVEN_API_BASE}/dubbing/{dubbing_id}",
                headers={"xi-api-key": api_key, "Accept": "application/json"},
            )
        except RuntimeError as e:
            on_progress(50, f"polling: {e} (повтор)")
            continue
        st = json.loads(status_raw.decode("utf-8"))
        status = st.get("status", "")
        elapsed = time.monotonic() - started
        pct = min(95, 5 + (elapsed / max(expected_dur, 30)) * 90)
        on_progress(pct, f"status={status} ({int(elapsed)}с)")
        if status in ("dubbed", "succeeded", "complete"):
            break
        if status in ("failed", "error"):
            err = st.get("error") or "неизвестная ошибка"
            raise RuntimeError(f"Dubbing failed: {err}")

    on_progress(96, "скачиваю результат")
    audio = _http_get(
        f"{ELEVEN_API_BASE}/dubbing/{dubbing_id}/audio/{target_lang}",
        headers={"xi-api-key": api_key, "Accept": "application/octet-stream"},
        timeout=600.0,
    )
    out_path.write_bytes(audio)
    on_progress(100, f"готово: {out_path.name} ({len(audio) / 1024 / 1024:.1f} MB)")
    return out_path
