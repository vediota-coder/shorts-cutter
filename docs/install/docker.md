# Установка через Docker

Рекомендуемый способ. Один образ работает на macOS / Linux / Windows.

## Требования

- Docker Desktop 24+ (macOS/Windows) или Docker Engine 24+ (Linux)
- **Минимум 8 GB RAM выделено Docker'у** (Settings → Resources на Mac/Win)
- 20 GB свободного места на диске
- Интернет для первого запуска (скачивание моделей и образа)

!!! warning "Важно: память Docker"
    Docker Desktop по умолчанию выделяет 2 GB RAM. Pipeline требует **8+ GB**
    при пиковой нагрузке. Откройте Docker Desktop → Settings → Resources →
    Advanced и установите **Memory: 12 GB** (или больше).

## Quick install

```bash
curl -fsSL https://get.excella.ru/install.sh | bash
```

Скрипт скачает `docker-compose.yml`, регистрирует команду `excella`, создаёт
`~/.excella/`.

## Manual install

```bash
# 1. скачать docker-compose.yml
mkdir -p ~/.excella && cd ~/.excella
curl -O https://get.excella.ru/docker-compose.yml

# 2. поднять контейнер
docker compose pull
docker compose up -d

# 3. проверить
curl http://localhost:8000/jobs
```

## Структура volumes

Файлы которые «выживают» рестарт контейнера:

```
~/.excella/
├── jobs/             ← state каждой задачи + готовые клипы
├── downloads/        ← скачанные YouTube видео (можно чистить)
├── output/           ← финальные mp4 (то же что jobs/{id}/output/)
├── license.json      ← подписанная лицензия от excella init
├── license.sig       ← её RSA-подпись
└── assets/
    ├── excella.json.enc   ← зашифрованный brand template
    └── excella.png.enc    ← зашифрованное лого
```

## Команды

```bash
excella start          # docker compose up -d
excella stop           # docker compose stop
excella logs           # docker compose logs -f
excella update         # docker compose pull && up -d
excella status         # docker ps + health
```

## Что внутри образа

```dockerfile
# Stage 1: builder — собирает brand_kernel из .pyx → .so для Linux
# Stage 2: runtime — Python 3.13 + ffmpeg + opencv-headless + faster-whisper
# Размер итогового образа: ~3.5 GB
```

YOLO веса (yolo26n.pt) и LR-ASD модель — bundle в образе.
MediaPipe и Whisper модели скачиваются при первом старте (~1 GB) и
кэшируются в named volumes.

## Производительность в Docker

На macOS Docker работает в виртуализированной Linux-VM — это **в 1.5–2× медленнее
native**. Если важна скорость, особенно на Apple Silicon (M1–M4) — используйте
[нативную установку](native.md), там работает MLX (×30 на transcribe) и MPS
(×3 на YOLO).

В Docker всегда CPU fallback:

| Стадия | Native M4 (MPS) | Docker на M4 (CPU) |
|---|---|---|
| transcribe | ~10 с / мин видео | ~30 с / мин |
| analyze | 90 с / 3-мин видео | 180 с / 3-мин |
| render | 30 с / клип | 30 с / клип |

## Troubleshooting Docker

См. [Troubleshooting](../troubleshooting.md#docker).
