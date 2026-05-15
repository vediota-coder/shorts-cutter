"""Alignment script (что хотел сказать) ↔ whisper-output (что произнёс).

Применение: после записи в суфлёре у нас есть:
- script — текст из суфлёра (reference)
- transcript — Whisper-сегменты с тайм-кодами слов (actual)

Нужно построить KEEP-ranges (start/end секунды) для ffmpeg-concat:
выкинуть оговорки/"ээ"/повторы/паузы, оставить произнесённый script.

Алгоритм:
1. Нормализуем оба в список (token, t_start, t_end) — у script тайм-кодов нет.
2. difflib.SequenceMatcher находит matching_blocks — непрерывные совпадения.
3. Каждый блок → range (whisper-слово-start, whisper-слово-end).
4. Маленькие зазоры между блоками (<300ms) объединяем, чтобы не было щёлков.
5. Расширяем границы по обе стороны: 100ms padding для естественности.

Бонусы:
- Если script-фраза повторена в whisper несколько раз — SequenceMatcher выбирает
  тот вариант, который в сумме даёт лучшее покрытие. Обычно это последний дубль.
- "Лишние" слова whisper (между matching blocks) автоматически выкидываются.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable


# знаки препинания и кавычки, которые игнорируем при сравнении
_PUNCT_RE = re.compile(r"[^\w\sёЁ]+", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def _normalize_word(w: str) -> str:
    w = w.lower().strip()
    w = _PUNCT_RE.sub("", w)
    w = _SPACE_RE.sub(" ", w).strip()
    # 'ё' трактуем как 'е' — Whisper их часто путает
    w = w.replace("ё", "е")
    return w


def script_to_words(script: str) -> list[str]:
    """Разбивает script на нормализованные слова, выкидывает теги [хук]/[зацеп] и т.п."""
    s = re.sub(r"\[[^\]]+\]", "", script)  # убираем [хук], [зацеп] и т.п.
    raw = s.split()
    out = []
    for w in raw:
        n = _normalize_word(w)
        if n:
            out.append(n)
    return out


@dataclass
class WhisperWord:
    text: str
    start: float
    end: float


def transcript_to_words(segments) -> list[WhisperWord]:
    """Из whisper-сегментов вытаскивает плоский список слов с тайм-кодами.
    Принимает list[Segment] из src/transcribe.py (с полем .words)."""
    out: list[WhisperWord] = []
    for seg in segments:
        words = getattr(seg, "words", None) or []
        if not words:
            # если whisper не дал word-level, фоллбэк: всё сегмент = одно слово
            n = _normalize_word(getattr(seg, "text", ""))
            if n:
                out.append(WhisperWord(text=n, start=seg.start, end=seg.end))
            continue
        for w in words:
            n = _normalize_word(w.text)
            if n:
                out.append(WhisperWord(text=n, start=w.start, end=w.end))
    return out


@dataclass
class KeepRange:
    start: float
    end: float
    script_start_idx: int  # индекс первого слова script в этом блоке
    script_end_idx: int    # индекс последнего слова + 1
    whisper_start_idx: int
    whisper_end_idx: int


def align(
    script_words: list[str],
    whisper_words: list[WhisperWord],
    *,
    pad_before: float = 0.20,
    pad_after: float = 0.25,
    merge_gap: float = 2.0,   # ≤2 сек — паузы сохраняем (естественная речь)
    min_block_len: int = 1,
) -> list[KeepRange]:
    """Находит keep-ranges для ffmpeg-concat.

    pad_before / pad_after — добавляем по краям каждого блока (естественность дыхания)
    merge_gap — если зазор между двумя блоками меньше, объединяем (не делаем cut)
    min_block_len — выкидываем блоки длиной <N слов (шумовое совпадение)
    """
    if not script_words or not whisper_words:
        return []

    whisper_tokens = [w.text for w in whisper_words]
    matcher = SequenceMatcher(a=script_words, b=whisper_tokens, autojunk=False)
    blocks = matcher.get_matching_blocks()  # (a_start, b_start, size), последний (la, lb, 0)

    ranges: list[KeepRange] = []
    for a, b, size in blocks:
        if size < min_block_len:
            continue
        if size == 0:
            continue
        ws = whisper_words[b]
        we = whisper_words[b + size - 1]
        ranges.append(KeepRange(
            start=max(0.0, ws.start - pad_before),
            end=we.end + pad_after,
            script_start_idx=a,
            script_end_idx=a + size,
            whisper_start_idx=b,
            whisper_end_idx=b + size,
        ))

    # объединяем перекрытия и маленькие зазоры
    ranges.sort(key=lambda r: r.start)
    merged: list[KeepRange] = []
    for r in ranges:
        if merged and r.start - merged[-1].end <= merge_gap:
            prev = merged[-1]
            merged[-1] = KeepRange(
                start=prev.start,
                end=max(prev.end, r.end),
                script_start_idx=min(prev.script_start_idx, r.script_start_idx),
                script_end_idx=max(prev.script_end_idx, r.script_end_idx),
                whisper_start_idx=min(prev.whisper_start_idx, r.whisper_start_idx),
                whisper_end_idx=max(prev.whisper_end_idx, r.whisper_end_idx),
            )
        else:
            merged.append(r)
    return merged


def coverage(script_words: list[str], ranges: list[KeepRange]) -> float:
    """Доля script-слов покрытых найденными ranges (0..1)."""
    if not script_words:
        return 0.0
    covered = set()
    for r in ranges:
        for i in range(r.script_start_idx, r.script_end_idx):
            covered.add(i)
    return len(covered) / len(script_words)


def build_render_segments(
    script: str,
    whisper_words: list[WhisperWord],
    ranges: list[KeepRange],
):
    """Возвращает list[Segment] для shorts-cutter write_ass. Использует РЕАЛЬНЫЕ
    тайм-коды whisper-слов (после вычитания cut_offset), а текст берётся из script
    (без ошибок распознавания). Группирует слова в фразы по пунктуации.
    """
    from .transcribe import Segment, Word
    raw_tokens = re.findall(r"\S+", re.sub(r"\[[^\]]+\]", "", script))
    if not raw_tokens or not whisper_words or not ranges:
        return []

    # offset для перевода тайм-кодов исходника в координаты вырезанного видео
    def to_cut(t: float) -> float:
        cut_offset = 0.0
        last_end = 0.0
        for r in ranges:
            if t < r.start:
                return max(0.0, t - cut_offset - max(0.0, r.start - last_end))
            cut_offset += max(0.0, r.start - last_end)
            if t <= r.end:
                return t - cut_offset
            last_end = r.end
        # за пределами последнего range — клампим к концу
        last_r = ranges[-1]
        return last_r.end - cut_offset

    # для каждого matching block у нас есть mapping script[a..a+size] → whisper[b..b+size]
    # построим точные тайм-коды для каждого script-токена
    script_w = script_to_words(script)
    word_times: list[tuple[float, float]] = [(-1.0, -1.0)] * len(script_w)
    for r in ranges:
        size = r.script_end_idx - r.script_start_idx
        for i in range(size):
            si = r.script_start_idx + i
            wi = r.whisper_start_idx + i
            if 0 <= si < len(word_times) and 0 <= wi < len(whisper_words):
                ww = whisper_words[wi]
                word_times[si] = (to_cut(ww.start), to_cut(ww.end))

    # заполняем непокрытые слова интерполяцией между соседними
    last_t = 0.0
    for i, (s, e) in enumerate(word_times):
        if s < 0:
            # ищем ближайшее заполненное справа
            j = i + 1
            while j < len(word_times) and word_times[j][0] < 0:
                j += 1
            if j < len(word_times):
                # линейная интерполяция
                next_s = word_times[j][0]
                span = (next_s - last_t) / (j - i + 1)
                word_times[i] = (last_t + span * (1), last_t + span * (1.5))
            else:
                word_times[i] = (last_t + 0.3, last_t + 0.6)
        last_t = word_times[i][1]

    # склеиваем raw_tokens (script) с тайм-кодами и текст
    if len(raw_tokens) != len(script_w):
        raw_tokens = script_w

    # группируем слова в Segment по пунктуации или по N слов
    segments = []
    cur_words: list[Word] = []
    cur_text_tokens: list[str] = []
    PHRASE_END = re.compile(r"[.!?…]\s*$")
    MAX_WORDS_PER_SEGMENT = 6

    for tok, (s, e) in zip(raw_tokens, word_times):
        cur_words.append(Word(start=s, end=e, text=tok))
        cur_text_tokens.append(tok)
        end_of_phrase = PHRASE_END.search(tok) is not None
        if end_of_phrase or len(cur_words) >= MAX_WORDS_PER_SEGMENT:
            seg_start = cur_words[0].start
            seg_end = cur_words[-1].end
            segments.append(Segment(start=seg_start, end=seg_end, text=" ".join(cur_text_tokens), words=cur_words))
            cur_words = []
            cur_text_tokens = []
    if cur_words:
        seg_start = cur_words[0].start
        seg_end = cur_words[-1].end
        segments.append(Segment(start=seg_start, end=seg_end, text=" ".join(cur_text_tokens), words=cur_words))

    return segments


def build_subtitle_cues(
    script: str,
    whisper_words: list[WhisperWord],
    ranges: list[KeepRange],
    *,
    cps: float = 18.0,    # символов в секунду для оценки длительности куска
    max_chars: int = 36,  # макс. символов в одной строке субтитра
) -> list[dict]:
    """Строит cues для субтитров: используем slова script (без ошибок whisper)
    с тайм-кодами от whisper-выравнивания.

    На выходе: [{start, end, text}] где start/end — в координатах УЖЕ ОБРЕЗАННОГО видео.
    """
    # word-level cues
    script_w = script_to_words(script)
    if not script_w:
        return []

    # привязываем каждое слово script к тайм-коду whisper через ranges
    # offset — сколько секунд срезано до текущего range
    cues_raw = []  # (script_idx, t_in_cut)
    cut_offset = 0.0  # секунд cumулятивно вырезано до начала текущего range
    last_end = 0.0
    for r in ranges:
        cut_offset += max(0.0, r.start - last_end)
        # для каждого слова script в этом range:
        for ai in range(r.script_start_idx, r.script_end_idx):
            # ищем соответствующее whisper-слово (приблизительно — пропорционально)
            block_size = max(1, r.script_end_idx - r.script_start_idx)
            rel = (ai - r.script_start_idx) / block_size
            t_orig = r.start + rel * (r.end - r.start)
            t_cut = t_orig - cut_offset
            cues_raw.append((ai, t_cut))
        last_end = r.end

    # склеиваем в строки по max_chars
    cues: list[dict] = []
    if not cues_raw:
        return cues
    # восстанавливаем «сырое» слово из script (с регистром и пунктуацией) — простой токенайз
    raw_tokens = re.findall(r"\S+", re.sub(r"\[[^\]]+\]", "", script))
    if len(raw_tokens) != len(script_w):
        raw_tokens = script_w  # фоллбэк

    line_words = []
    line_start = cues_raw[0][1]
    for (idx, t), tok in zip(cues_raw, raw_tokens):
        candidate = (" ".join(line_words) + " " + tok).strip()
        if len(candidate) > max_chars and line_words:
            line_end = t
            cues.append({"start": line_start, "end": line_end, "text": " ".join(line_words)})
            line_words = [tok]
            line_start = t
        else:
            line_words.append(tok)
    if line_words:
        # последний cue: end = последний known t + оценка длительности
        last_t = cues_raw[-1][1]
        est_dur = max(0.5, len(" ".join(line_words)) / cps)
        cues.append({"start": line_start, "end": last_t + est_dur, "text": " ".join(line_words)})

    return cues
