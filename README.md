# shorts-cutter

Нарезка длинных видео на вертикальные шортсы с face tracking и автосубтитрами.

## Pipeline

1. **download** — `yt-dlp` качает источник (YouTube/файл)
2. **transcribe** — `faster-whisper` строит транскрипт с таймкодами (локально)
3. **pick** — Claude API выбирает 5-10 лучших моментов 30-60 сек по транскрипту
4. **reframe** — `mediapipe` детектит лица покадрово, сглаженный crop 9:16 идёт за спикером
5. **render** — `ffmpeg` режет, кропит, накладывает субтитры

## Структура

```
src/
  download.py      # yt-dlp обёртка
  transcribe.py    # faster-whisper
  picker.py        # Claude API: транскрипт → таймкоды клипов
  reframe.py       # mediapipe face tracking + smooth crop
  render.py        # ffmpeg: cut + crop + subtitles
  pipeline.py      # оркестратор
downloads/         # исходники (gitignored)
output/            # готовые шортсы (gitignored)
```

## Запуск

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg
# нужен установленный и залогиненный Claude Code CLI (`claude --version`)
```

**CLI:**
```bash
python -m src.pipeline --url "https://youtube.com/watch?v=..."
python -m src.pipeline --url "https://vk.com/video-12345_67890"
python -m src.pipeline --file ./my-video.mp4
```

**Веб-интерфейс:**
```bash
uvicorn web.app:app --reload --port 8000
# открыть http://localhost:8000
```

В вебе: вставляешь URL или загружаешь файл → видишь прогресс по этапам (download → transcribe → pick → track → render) → получаешь карточки с превью и кнопками скачивания в **1080p / 720p / 480p**.

## Стоимость

- Всё локально, кроме Claude API (~$0.01-0.05 за часовое видео через Haiku 4.5)
