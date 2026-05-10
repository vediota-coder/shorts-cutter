# REST API

`http://localhost:8000` (или ваш host).

## Создание job'а

```http
POST /jobs
Content-Type: multipart/form-data

url=https://www.youtube.com/watch?v=...     # ИЛИ file=...
file=@local_video.mp4                        # ИЛИ url=...
max_clips=8                                  # default 8
whisper_model=medium                         # tiny|base|small|medium|large-v3
sub_template=block                           # block|karaoke|...
brand=excella                                # имя brand template
cta=demo                                     # ключ из cta_presets
llm_provider=                                # claude-code|anthropic|openai|gemini
llm_model=                                   # модель внутри провайдера
download_max_height=1080                     # YT macao 1080p
download_cookies_browser=                    # chrome|firefox|safari
output_size=native                           # native|1080p|720p|480p
voiceover=false                              # включить ElevenLabs voiceover
voiceover_engine=library                     # library|clone
voiceover_mode=duck                          # duck|replace
voiceover_voice=                             # ID голоса ElevenLabs
voiceover_model=eleven_v3                    # модель TTS
voiceover_target_lang=ru                     # язык переозвучки
picker_extra=                                # extra-инструкции для LLM picker'а
```

**Response 200:**
```json
{"job_id": "0f9f3f888b28"}
```

## Статус job'а

```http
GET /jobs/{job_id}
```

**Response 200:**
```json
{
  "id": "0f9f3f888b28",
  "status": "running",          // queued | running | done | error
  "stage": "analyze",           // download|transcribe|pick|analyze|render|meta|done
  "progress": 35.4,
  "log": [
    {"stage": "transcribe", "progress": 76, "msg": "MLX обрабатывает...", "eta_s": 14}
  ],
  "clips": [
    {
      "title": "3 уровня дохода: ...",
      "files": {
        "1056p": "01-3-уровня-...-1056p.mp4",
        "480p": "01-3-уровня-...-480p.mp4"
      },
      "meta_descriptions": {"youtube": "...", "instagram": "...", "vk": "..."},
      "meta_hashtags": {"youtube": ["..."], ...}
    }
  ],
  "error": null,
  "title": "...",
  "source_url": "https://..."
}
```

## Список всех job'ов

```http
GET /jobs?limit=30
```

Возвращает массив объектов вида выше, сортировка от новых к старым.

## Stream события через WebSocket

```javascript
const ws = new WebSocket("ws://localhost:8000/jobs/abc123/stream")
ws.onmessage = e => {
  const event = JSON.parse(e.data)
  // {stage, progress, msg, eta_s} или {stage:"done", clips:[...]}
}
```

WebSocket закрывается после `done` или `error`.

## Удалить job

```http
DELETE /jobs/{job_id}
```

Удаляет state + все output файлы.

## Brand templates

```http
GET /brands                               # список
GET /brands/{name}                        # один
POST /brands                              # создать
PATCH /brands/{name}                      # частичное обновление
DELETE /brands/{name}
```

Body для POST/PATCH — JSON с полями BrandTemplate (см. [Конфигурация](configuration.md)).

## Subtitle templates

```http
GET /subtitle-templates
GET /subtitle-templates/{key}
POST /subtitle-templates
PATCH /subtitle-templates/{key}
POST /subtitle-templates/{key}/reset
```

## Прочие endpoint'ы

```http
GET /backend                              # backend info (whisper, ffmpeg version)
GET /llm/providers                        # список доступных LLM
GET /prompts                              # список prompt'ов
POST /prompts/{name}                      # обновить prompt
GET /jobs/{id}/clips/{i}/publish/youtube  # опубликовать в YouTube
GET /jobs/{id}/clips/{i}/uniquify         # уникализировать клип (защита от ContentID)
POST /jobs/{id}/clips/{i}/thumbnails/generate
POST /jobs/{id}/clips/{i}/add-music
```

Подробнее — Swagger UI на `http://localhost:8000/docs`.

## Idempotency

POST /jobs не идемпотентен (каждый POST = новый `job_id`). Если хотите
переиспользовать analysis — сделайте rebrand-job через
`scripts/rebrand_job.py {job_id}`.

## Rate limit

В community-tier лимита нет. Через Semaphore идёт 2 параллельных pipeline'а
по умолчанию (override через `MAX_CONCURRENT_JOBS` env).

## Коды ошибок

| HTTP | Что |
|---|---|
| 200 | OK |
| 400 | Невалидный запрос (нет url/file, неизвестный brand, etc) |
| 404 | job_id не найден |
| 422 | Невалидный body (Pydantic) |
| 429 | (registration server) Превышен лимит регистраций per email |
| 500 | Внутренняя ошибка — смотрите stderr/logs uvicorn |
