# FAQ

## Это правда бесплатно?

Да. Free forever, без подписок и trial periods. Подробнее — [Лицензия](licensing.md).

## Почему регистрация по email?

Чтобы:

1. Знать сколько у нас активных пользователей
2. Слать security advisories при критических багах
3. Привязать лицензию к конкретной машине → не позволяет одному человеку
   запустить 1000 копий и устроить ботнет
4. На будущее — если добавим white-label tier за деньги

Email никому не передаётся. Можно использовать `you+excella@gmail.com`.

## Можно ли убрать лого excella в углу?

Нет, в community tier нельзя. Это часть бренд-protection (см. [Лицензия](licensing.md)).

Если очень хочется — напишите в support@excella.ru, обсудим white-label tier.

## Поддерживается ли GPU?

| GPU | Стадии с GPU |
|---|---|
| Apple M1/M2/M3/M4 (MPS) | YOLO detection ✓, mlx-whisper transcription ✓ |
| NVIDIA (CUDA) | YOLO detection ✓, faster-whisper transcription ✓ |
| AMD (ROCm) | пока нет, в планах |
| Intel iGPU / Arc | работает CPU fallback |
| Docker (Linux VM на Mac) | только CPU |

## Какие LLM поддерживаются для picker'а?

- `claude-code` (default, через CLI, без API key)
- `anthropic` (нужен `ANTHROPIC_API_KEY`)
- `openai` (нужен `OPENAI_API_KEY`)
- `gemini` (нужен `GEMINI_API_KEY`)
- `gemini-cli` (через gemini CLI)
- `codex` (через codex CLI)

Все провайдеры конфигурируются через web UI / API.

## Сколько места на диске?

| Файл | Размер |
|---|---|
| Docker image | ~3.5 GB |
| Native app | ~500 MB |
| Whisper модели (lazy download) | 1–3 GB (зависит от размера модели) |
| MediaPipe модели | 50 MB |
| YOLO веса | 5 MB |
| LR-ASD веса | 13 MB |
| **На пустую установку** | **~5 GB** |
| **На рабочую установку с обработанными видео** | зависит от объёма jobs/ |

Один job на 30-минутном видео даёт ~500 MB–1 GB временных файлов
(downloads + cache + outputs).

## Как удалить старые job'ы?

```bash
# просмотр
du -sh ~/.excella/jobs/* | sort -h

# удалить старше 30 дней
find ~/.excella/jobs -maxdepth 1 -type d -mtime +30 -exec rm -rf {} \;

# или интерактивно через UI
http://localhost:8000/jobs → удалить кнопкой
```

## Можно ли запустить на сервере без GUI?

Да, это и есть основной use case. Headless Linux:

```bash
# Через Docker
ssh server
curl -fsSL https://get.excella.ru/install.sh | bash
excella init --email you@company.com
excella start
# проксируйте 8000 через nginx с auth
```

Web UI работает по HTTP. Для production обязательно ставьте за reverse proxy
с TLS и basic-auth.

## Почему именно YouTube как источник?

Технически работает любой URL который умеет yt-dlp:
- YouTube (включая Shorts, Live)
- VK Видео
- Instagram (reels, posts)
- TikTok
- Twitter/X
- Twitch (vod)
- ~1900 других сайтов

Также можно загружать локальные файлы (drag-and-drop в UI).

## Контент-ID, монетизация YouTube — это не нарушение?

excella shorts-cutter не публикует за вас. Вы сами решаете куда заливать
получившиеся клипы. **Использование чужого контента без лицензии** — это
ваша ответственность. Используйте только своё видео или контент с
permissive лицензией.

## Что делать если YouTube требует cookie?

```bash
# через UI: настройки → "Использовать cookies из браузера"
# через API:
curl -X POST localhost:8000/jobs \
  -F "url=..." \
  -F "download_cookies_browser=chrome"
```

yt-dlp прочитает cookies из браузера и использует их при скачивании.

## Где найти исходники?

Public repo: [github.com/excella/shorts-cutter](https://github.com/excella/shorts-cutter)

Закрытые компоненты (`brand_kernel/_kernel.pyx`, RSA private key,
master_secret) находятся в private repo и vault — не публикуются.
В public repo вы видите готовый бинарь `_kernel.so`.

## Я нашёл security-баг. Куда сообщить?

[GitHub Security Advisories](https://github.com/excella/shorts-cutter/security/advisories/new)
или security@excella.ru. Мы отвечаем в течение 48 часов.

## Можно использовать в России?

Да, продукт self-hosted работает offline (после регистрации). Регистрация
требует одного запроса на registration.excella.ru — если он недоступен,
есть offline-вариант (см. [Troubleshooting](troubleshooting.md#registration)).
