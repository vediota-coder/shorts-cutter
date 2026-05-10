# Конфигурация

## Переменные окружения

Все настройки через env-переменные. В Docker задаются в `docker-compose.yml`,
для native — в `~/.excella/.env`.

| Переменная | Дефолт | Что делает |
|---|---|---|
| `MAX_CONCURRENT_JOBS` | `2` | Лимит параллельных pipeline'ов через Semaphore |
| `EXCELLA_STREAMING_ANALYZE` | `0` | `1` → один проход декодирования (на ~1.6× быстрее, но меньше тестировано) |
| `EXCELLA_DEV` | unset | `1` → отключает tamper detection (только для разработки) |
| `EXCELLA_CACHE_DIR` | `~/.excella/cache/analysis` | Глобальный кэш analysis.pkl |
| `ANTHROPIC_API_KEY` | (опц) | Для picker'а через Anthropic API. По умолчанию используется claude-code CLI |
| `OPENAI_API_KEY` | (опц) | Для picker'а через OpenAI |
| `GROQ_API_KEY` | (опц) | Для transcribe через Groq Whisper API (~300× realtime, $0.006/мин) |
| `EXCELLA_TRANSCRIBE_BACKEND` | unset | `groq` → использовать Groq если ключ есть. Иначе авто-выбор mlx/cuda/cpu |
| `ELEVENLABS_API_KEY` | (опц) | Для voiceover через ElevenLabs |
| `HF_TOKEN` | (опц) | Если HuggingFace модели требуют авторизации |
| `PEXELS_API_KEY` | (опц) | Для b-roll картинок через Pexels |

## Бренд-шаблоны

Brand template — это `branding/{name}.json` (или `.json.enc` если используется
brand_kernel). Поля:

```json
{
  "name": "excella",
  "lead_url": "https://excella.ru",
  "watermark_path": "_assets/excella.png",
  "watermark_position": "top-left",
  "watermark_opacity": 0.65,
  "watermark_scale": 0.15,
  "face_overlay_path": "_assets/excella.face.png",
  "face_overlay_position": "bottom-right",
  "face_overlay_scale": 0.34,
  "bottom_strip": {
    "text": "EXcella.ru",
    "color": "#C6FF3D",
    "bg_color": "#1E1B4B",
    "opacity": 0.55,
    "font_size": 40,
    "height": 172,
    "bold": true,
    "font_family": "Unbounded"
  },
  "cta_default": "demo",
  "cta_presets": {
    "demo": {
      "text": "Попробуй бесплатно",
      "duration": 3,
      "sub_text": "excella.ru"
    }
  }
}
```

!!! info "Self-hosted brand protection"
    Если у вас валидная лицензия excella, brand template приходит в
    зашифрованном виде (`branding/excella.json.enc`). Простая правка
    JSON блокнотом не работает — только ваше [white-label-tier]
    позволяет менять брендинг.

### Пути к ассетам

В JSON пути могут быть:
- **относительные** (`_assets/excella.png`) — резолвятся от `branding/`
- **абсолютные** (`/full/path/to/logo.png`) — оставляются как есть

Рекомендуется относительные — они переносимы между машинами.

## Transcription backend

| Backend | Когда использовать | Скорость | Цена |
|---|---|---|---|
| `groq` | Длинные видео, быстрая обработка | ~300× realtime | $0.006/мин |
| `mlx` (default на M-серии Apple) | Локально на Apple Silicon | ~30× realtime | бесплатно |
| `faster-cuda` (NVIDIA) | Локально с CUDA | ~50× realtime | бесплатно |
| `faster-cpu` (Linux/Win без GPU) | Fallback | ~5–15× realtime | бесплатно |

Чтобы включить Groq:
```bash
export GROQ_API_KEY=gsk_...
export EXCELLA_TRANSCRIBE_BACKEND=groq
```

!!! warning "Groq не активируется автоматически"
    Даже если `GROQ_API_KEY` установлен — backend Groq используется только
    при явном `EXCELLA_TRANSCRIBE_BACKEND=groq`. Это защита кошелька от
    случайных трат: можно держать ключ в .env для других целей не платя
    за каждое транскрибирование.

## Picker

Выбор лучших моментов делает LLM. По умолчанию используется `claude-code` CLI
(если установлен). Можно переключить:

```bash
# через web UI: настройки → LLM провайдер
# через API:
curl -X POST http://localhost:8000/jobs \
  -F "url=..." \
  -F "llm_provider=anthropic" \
  -F "llm_model=claude-opus-4-5"
```

## Voiceover

```bash
curl -X POST http://localhost:8000/jobs \
  -F "url=..." \
  -F "voiceover=true" \
  -F "voiceover_engine=library" \
  -F "voiceover_voice=EXAVITQu4vr4xnSDxMaL"
```

`voiceover_engine`:
- `library` — TTS через ElevenLabs (нужен `ELEVENLABS_API_KEY`)
- `clone` — клонирование голоса оригинала через ElevenLabs voice clone
- empty — без озвучки

## Субтитры

Стиль через `sub_template`:
- `block` (default) — крупные блоки слов
- `karaoke` — слова подсвечиваются по мере произнесения
- свой стиль через `POST /subtitle-templates`
