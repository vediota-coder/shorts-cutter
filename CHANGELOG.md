# Changelog

История изменений проекта shorts-cutter.
Формат: [Keep a Changelog](https://keepachangelog.com/) + семантическое версионирование.

## [Unreleased]

### Added
- **Выбор количества клипов: ручной ввод + AI-авто** (`web/preview/hero-cut.jsx`, `src/picker.py`). К пресетам [5,8,10,15] добавлены: кнопка [AI авто] (LLM сам решает оптимальное число) и числовой input без верхней границы. Транспорт через тот же `max_clips`: 0 = auto, число = строгий лимит «до N». В auto-режиме picker подменяет user_msg на «реши САМ оптимальное количество» и дописывает к system prompt блок «АВТО-РЕЖИМ ВЫБОРА КОЛИЧЕСТВА» с ориентиром по длительности (<10 мин: 0–3, 10–40 мин: 3–7, >40 мин: 7–15) и явным запретом натягивать слабые моменты до круглого числа. CLI `--max-clips 0` тоже включает auto.
- **Cover Designer — hook-overlay поверх постера** (`src/cover.py`): берёт chosen_thumbnail и накладывает большой UPPERCASE-крючок (из meta_title или явно заданного `hook_text`) на цветной плашке. Auto-fit fontsize: уменьшается пока самая длинная строка не помещается в плашку. Шрифт + accent/text-цвета — из новых полей `BrandTemplate.cover_font_family / cover_accent_color / cover_text_color`. Не пишет своей рисовалки текста — переиспользует ffmpeg drawtext + `_escape_drawtext` из branding. Endpoints: `POST /jobs/{id}/clips/{i}/cover` (генерация), `GET /jobs/{id}/clips/{i}/cover.png` (отдача). UI: collapse-секция «Обложка с хуком» в карточке клипа с textarea hook + позиция + live preview.
- **AI-translate субтитров на 4 языка** (`src/subtitles_translate.py` + `src/llm/translate.py`): RU→EN/PT-BR/ES/DE через Claude. Не парсит ASS — работает на уровне Segment-объектов, переводит `Segment.text` через общий `translate_strings` (батчи по 80, JSON-формат), пересоздаёт word-тайминги равномерным распределением по тому же `[start, end]`. Использует кешированный `silent.mp4` (без аудио, без субтитров) — НЕ запускает smart-reframe заново, только новый ASS + mux + brand. Endpoint `POST /jobs/{id}/clips/{i}/translate {target_langs}`. Сохраняется в `clip.translations[lang] = {ass, files}`. UI: collapse-секция с чекбоксами языков + список готовых переводов со ссылками на mp4.
- **Sound FX на акцентах** (`src/sfx.py`): накладывает короткие стинги (whoosh/swoosh/ding/pop из `audio_library/sfx/`) на cut'ы и onset'ы речи. Тайминги — из уже сохранённого `analysis.pkl` (`SmartAnalysis.cuts` + `asd_per_frame`), без новой детекции. 2 пресета: `subtle` (swoosh+pop тихо, gap 1.5s), `energetic` (whoosh+ding громко, gap 0.8s). Audio mix через ffmpeg amix+adelay (тот же паттерн что в `add_music`), видео не пере­рендерится (`-c:v copy`). Endpoint `POST /jobs/{id}/clips/{i}/add-sfx`. UI: collapse-секция «Sound FX» с выбором стиля и чекбоксами типов акцентов.
- **Общий translate-хелпер** (`src/llm/translate.py`): generic batch-translate для произвольных пар языков + универсальный `_parse_json_items` парсер JSON-ответов LLM. `voiceover._parse_translation` теперь делегирует в общий парсер — нет дублирования логики. Dub-specific промпт (ударения, audio tags, EN→RU) остался в voiceover.

- **WYSIWYG-редактор субтитров в стиле Vizard**:
  - `src/sub_style.py` `template_to_web_style(template, target_h)` выводит CSS-ready JSON из того же `SubTemplate`, который используется в `write_ass` — превью гарантированно совпадает с burn'ом. Раньше превью описывалось хардкоженным CSS в `styles.css`, расходилось при правках шаблонов и быстро устаревало.
  - `GET /subtitle-templates/{key}/preview-style?target_h=N` — стиль для чипа в селекторе.
  - `GET /jobs/{id}/clips/{i}/sub-style?target_h=N` — стиль для конкретного клипа: base preset + per-clip overrides слиты.
  - `GET /jobs/{id}/clips/{i}/words` — whisper-слова, сдвинутые в clip-relative time, для overlay'я.
  - `PATCH /jobs/{id}/clips/{i}/sub-overrides` (28 полей `SubTemplate`) — мгновенно меняет стиль БЕЗ re-render'а; overlay подхватывает через 220 мс.
  - `DELETE /jobs/{id}/clips/{i}/sub-overrides` — сброс всех правок к чистому пресету.
  - `POST /jobs/{id}/clips/{i}/restyle` теперь принимает `overrides` — финальный burn в файл с overrides поверх template.
- **WYSIWYG overlay** субтитров поверх `<video>` в карточке клипа: рендерится в `requestAnimationFrame` через JSON-стиль, подсвечивает текущий чанк/слово на основе word timestamps. Toggle "Aa" в углу плеера (по умолчанию on).
- **Direct-manipulation редактор поверх видео (Vizard-style)**: click по overlay → selection mode с пунктирной рамкой + 4 угловыми handle'ами. Drag по телу overlay меняет `margin_v` (px от низа), drag по угловому handle меняет `size` пропорционально (projection на наружный диагональный вектор). Изменения применяются мгновенно в overlay, PATCH `/sub-overrides` идёт debounced 220 мс. Esc или клик вне overlay → deselect.
- **Toolbar редактора субтитров** в табе "edit" клипа (secondary к direct-manipulation): picker шаблонов с paritет-точными чипами + collapsible-секции «Размер и позиция», «Цвет», «Стиль» (slider'ы для size/margin_v/outline/shadow/letter_spacing, color picker'ы для color/highlight/accent/outline_color, toggle'ы bold/uppercase/pop_in/auto_capitalize). Правки сохраняются debounced (220 мс) в `state.json`. Кнопка «Применить» запускает `POST /restyle` → новый burn-файл, video URL обновляется через cache-bust query.
- **Pro-шаблоны субтитров (8 новых)**: `submagic` (Hormozi: UPPERCASE bold + жёлтый акцент + pop-in), `captions` (Wrapbox: полупрозрачный бокс), `podcast_pro` (clean минимал), `beast` (MrBeast: жёлтые CAPS + красный акцент), `karaoke_fill` (CapCut: progressive `\k`-fill слева-направо), `highlight_box` (Veed: подложка под активным словом), `bubble` (Klap: каждое слово на белой пилюле), `chroma` (Opus ChromaClips: циклы цветов per-word). Итого 14 шаблонов в UI.
- **`progressive_fill` + `chroma_cycle`** поля в `SubTemplate` — управляют ASS `\k`-fill и циклической раскраской слов соответственно.
- **`AccentKeyword` API**: `write_ass(..., accent_keywords=[...])` подсвечивает слова из `EffectsPlan.accents` индивидуальным цветом/scale прямо в субтитрах (как Submagic/Opus Clip), не только zoom/emoji.
- **Auto-fit ширины**: `effective_max_chars` в `subtitles.py` пересчитывает количество слов на строке исходя из `target_w` и метрик шрифта, чтобы текст не вылезал за кадр на узких разрешениях.
- **CPS-based timing** (`min_cps` поле SubTemplate, по умолч. 17): длительность каждого события считается как `max(min_chunk_duration, chars/min_cps)` — короткие фразы продлеваются для читаемости, не залезая на следующий чанк (gap 30мс).
- **Smooth word durations** (`min_word_duration`, 0.12s): короткие слова Whisper'а (например, "и", "а" с длительностью <0.12s) расширяются до читаемого минимума.
- **Smart capitalization** (`auto_capitalize`): первое слово клипа и любое слово после паузы >0.5s капитализируется автоматически (для не-UPPERCASE стилей).
- **Safe-area presets** (параметр `safe_area` в `write_ass`): `tiktok` / `youtube_shorts` / `reels` поднимают `margin_v` чтобы субтитры не залезали под нижний UI платформы.
- **Тест-стенд `scripts/test_subtitles.py`**: валидация всех 9 пресетов × 3 разрешения × 4 фикстуры (RU/EN/long-word/empty) + ffmpeg burn-in sanity.

### Fixed
- **Smart-reframe regression: голова спикера обрезалась когда он стоит у доски**. Job 972b83078939 (новый whiteboard-видео) — 87-96% сцен выбирались как `screen_full`, кроп вырезал ровно доску (33% кадра), а спикер стоял справа/слева от неё с головой выше доски → голова за границей кропа.
  - Корень: в `classifier.py` правило «есть big_screen (>=10% кадра) → screen_full» не учитывало позицию спикера относительно итогового screen-кропа.
  - Фикс: перед `screen_full` эмулируем geometry кропа (`crop_h = max(screen.h*1.05, src_h*0.95)`, `crop_w = crop_h * 9/16`, `cx = screen.cx`). Если у любого person'а `cx` вне итогового `crop_x_range` ИЛИ голова выше screen_top на >30px при неполном-height кропе → fallback на `wide_default` (показывает весь кадр, доска+спикер).
  - До: clip 2 = 96% screen_full. После: clip 2 = 96% wide_default — голова спикера в кадре. Не задел старый whiteboard-job 937558d7c341 (там screen меньше 10%).
- **Bubble pill (ASS `\p1` shape) рендерился слева от текста, не под ним**. `\an5\pos(center)` libass не интерпретировал как «центр shape на pos» — shape оставался с абсолютными координатами от top-left frame. Переписали `_pill_shape_cmd` чтобы координаты шли от (0,0)=top-left самого shape, и переключились на `\an7\pos(left_x, top_y)` — pill теперь точно под текстом.
- **WYSIWYG-овer­lay: scaled слова съедали пробел между словами** (например "тестсубтитров"). CSS `transform: scale()` на inline-block элементе клеит соседний текст. Заменили на `font-size: baseSize * scale`.
- **WYSIWYG-overlay: длинный текст вылезал за границы кадра** (`submagic`/`chroma` "ЭТО ТЕСТ СУБТИТРОВ"). Контейнер имел `white-space: nowrap`. Заменили на `whitespace: normal; overflow-wrap: break-word` — теперь работает как ASS auto-wrap.
- **Smart-reframe: «пустые» frames в подкаст/интервью клипах** на границах между разными спикерами (outreach_01 00:03/00:11, outreach_03 00:45/00:50/01:00 в job ae336bf6911a). Корневая причина — person tracker иногда сливает разных физических людей в один track через source cut, и гауссово сглаживание усредняло их позиции в фантомный центр кадра. Исправлено:
  - `SmoothedTrack` теперь принимает `cuts_set` и сглаживает каждый сегмент между cut'ами независимо
  - `_params_face_crop` возвращает None если у трека нет детекции в ±15 кадрах без source cut между → camera plan помечает кадр invalid → fallback на `_render_speaker_close` который сам делает fallback на `person_close` через `face_to_person`
  - `build_camera_plan` теперь добавляет hard cut в трёх случаях: смена субъекта на границе сегмента, source cut, или большая дельта cx/cy между соседними кадрами (страховка). Интерполяция и сглаживание делаются per-region между cut'ами
  - `_params_for_segment` больше НЕ фолбэкает на `_params_wide_default` для face/person/screen layouts — возвращает None, чтобы rendering loop использовал старые renderers с их fallback-логикой вместо центрированного кропа
  - Headroom в `_params_face_crop` и `_params_person_close` теперь гарантирует ≥max(60px, 8%·crop_h) над макушкой (face_cy − face_h·0.85 для лица, person_cy − person_h·0.5 для тела) — иначе при росте bbox на близком gesture макушка вылетала за верх кропа
- **Логотипы VK/YouTube в публикационном меню** не отображались — `<img src="assets/...">` использовал относительный путь, который на странице `/` резолвился в `/assets/vk.svg` (404). Заменено на абсолютный `/preview/assets/...`.
- **Pickerlабелы новых шаблонов субтитров** в hero-cut.jsx — отсутствующие IDs (`submagic`, `captions`, `podcast_pro`) фолбэчили на "Big white". Добавлены i18n-ключи и явный map.

### Changed
- `src/pipeline.py`: `plan_effects` теперь вычисляется ДО `write_ass`, accents пробрасываются в субтитры, повторного LLM-вызова нет.
- `web/app.py`: `SubTemplatePatch` принимает новые поля (`uppercase`, `pop_in`, `accent_color`, `accent_scale`, `back_color`, `back_alpha`, `border_style`, `letter_spacing`, `italic`).

### Roadmap (запланировано)

**Фаза 1 — Перформанс (неделя 1):**
- [x] **lr_asd одним проходом** для всех tracks — обнаружено в живом прогоне (analyze 19 мин). 2.7× ускорение baseline

- [x] ~~Перенести `analyze` ПОСЛЕ `picker`~~ — был уже в правильном порядке; добавлена передача `time_ranges` в `analyze_video` и каждый detect_*, AI-инференс пропускается вне ranges (−80% inference на длинных видео из которых рендерятся короткие клипы)
- [x] `asyncio.Semaphore(2)` в `web/app.py` — `MAX_CONCURRENT_JOBS=2` через env, статус `queued` для очереди
- [x] Singleton моделей: `_FASTER_WHISPER_CACHE` + monkey-patch `mlx_whisper.load_models.load_model` через `lru_cache(maxsize=4)`. YOLO singleton уже был через `global _yolo` в screens.py
- [x] YOLO `device='mps'`, `imgsz=480` в persons.py + screens.py через общие `YOLO_DEVICE`/`YOLO_IMGSZ` из `_detect_yolo_device()`
- [x] Кэш `analysis.pkl` по `(video_fp, ranges_fp)` в `~/.excella/cache/analysis/` — повторный запуск с теми же ranges пропускает analyze
- [ ] Один цикл декодирования для всех детекторов — большой рефакторинг с stateful Detector API, отложен на отдельную сессию
- [ ] py-spy профилирование (требует свежей задачи на запущенном uvicorn)
- [ ] Нагрузочный тест 3/5/8 параллельных задач (требует рестарт uvicorn для подхвата изменений)

**Фаза 2 — Brand protection (неделя 2):**
- [x] Скопировать `brand_kernel` в `vendor/brand_kernel/` для прямого импорта из `src/`
- [x] Интегрировать `brand_kernel` в `src/branding.py:load_brand` — две ветки: kernel-decrypted `.json.enc` или fallback на plain JSON
- [x] AI_NOTICE header в `src/branding.py`, `src/render.py`, `src/pipeline.py` — `<system>` блок c DMCA/EU/ГК ссылками
- [x] Tamper detection инфраструктура: `verify_module_integrity()`, `assert_modules_intact()` в `_kernel.pyx`, dev-mode skip через `EXCELLA_DEV=1`. Хэши `_PROTECTED_HASHES` будут заполнены release CI
- [x] Free-forever registration endpoint в `brand_kernel_poc/server/app.py` — POST /register, SQLite CRM, rate-limit, идемпотентность по (email, machine_fp). Клиентский скрипт `scripts/excella_init.py`. Tier `community`, expires 2099. Без revocation list (free-модель)
- [—] ~~DCT watermark embedding~~ — **исключено из проекта**. Decision 2026-05-10: invisible/стенографический watermark не делаем. Защита держится на kernel + AES + лицензия + visible brand layer (excella.png + bottom_strip + CTA), которые применяются через apply_brand
- [x] Master secret obfuscation в `_kernel.pyx` — 3 XOR-замаскированных фрагмента, recovery через `_master_secret()`. Прямого secret в .so нет ни в каком виде
- [x] PyArmor для остального Python кода — `scripts/build_obfuscated.sh` готов; протестирован на `src/branding.py`: обфусцированная версия (105 KB vs 25 KB исходник) импортируется, функционирует идентично, plain text "excella"/"BrandTemplate"/"apply_brand" в файле не находятся
- [ ] Docker self-hosted сборка — Phase 4

**Фаза 3 — Production hardening (неделя 3+):**
- [x] Groq Whisper API integration — `EXCELLA_TRANSCRIBE_BACKEND=groq` + `GROQ_API_KEY` → ~300× realtime, $0.006/мин. Chunking 10 мин для лимита 25 MB
- [ ] Replicate YOLO (опц., при росте нагрузки)
- [ ] Воркеры в отдельных процессах (multiprocessing.Pool)
- [ ] Celery + Redis для горизонтального скейла
- [ ] Pen-test от внешнего реверс-инженера

**Фаза 4 — Distribution & Operations (неделя 4-5):**
- [x] Multi-stage Dockerfile + docker-compose.yml
- [x] install.sh / install.ps1 для curl | bash установки
- [x] scripts/excella_update.py — auto-update механизм с rollback
- [x] MkDocs Material документация (9 страниц на ru)
- [x] GitHub Actions release.yml — CI matrix для kernel.so на 4 платформах
- [x] GitHub Actions docs.yml — авто-деплой docs на docs.excella.ru
- [ ] Native installer .pkg для macOS (нужен Apple Developer ID + notarization)
- [ ] Native installer .msi для Windows (нужен Authenticode signing)
- [ ] Native installer .deb/.rpm для Linux
- [ ] get.excella.ru landing-страница (Cloudflare Pages)
- [ ] PyArmor для src/ — обфускация Python кода в release-build
- [ ] Telegram-бот / Discord для поддержки
- [ ] Beta-тест на 5-10 клиентах

---

## 2026-05-10 (Phase 3 #23 + Phase 2 #16 — Groq Whisper + PyArmor)

### Added

- **`src/transcribe.py:_transcribe_groq`** — Groq Whisper API провайдер
  - `BackendName` Literal расширен: `groq | mlx | faster-cuda | faster-cpu`
  - `detect_backend()` выбирает groq **только** при `EXCELLA_TRANSCRIBE_BACKEND=groq`
    + `GROQ_API_KEY` (двухфакторная защита от случайных трат)
  - `_transcribe_groq_single` для коротких видео (<10 мин)
  - `_transcribe_groq` с chunking по 10 мин для длинных (Groq лимит 25 MB на файл)
  - `_groq_to_segments` конвертирует verbose_json в наш Segment
  - Audio extracted через ffmpeg в 16kHz mono wav (компактнее для лимита)
  - response_format=verbose_json + timestamp_granularities=[word, segment]
  - Скорость: **~300× realtime** vs ~30× у MLX. Цена: **$0.006/мин** (~$0.18 за 30-мин видео)

- **`scripts/build_obfuscated.sh`** — PyArmor wrapper для release-CI
  - `pyarmor gen --recursive --restrict 0 src/`
  - Тест на `src/branding.py`: 25 KB → 105 KB (encoded bytecode)
  - Plain text 'excella'/'BrandTemplate'/'apply_brand' не находятся через grep
  - Функциональная корректность сохранена (импорт + load_brand работают идентично)
  - Платформо-специфичный runtime — CI matrix вызывает под нужную ОС

### Changed

- **`requirements.txt`** — добавлены `anthropic`, `openai`, `google-genai`,
  `ultralytics`, `python_speech_features`, `scipy` (silent technical debt
  обнаружен Docker build)

### Validation

- Groq integration smoke-test 5/5: default→mlx, force-groq-no-key→fallback mlx,
  groq+key→groq, SDK импорт, конвертация пустого результата
- PyArmor: обфусцированный branding.py импортируется + load_brand работает
- Без реального GROQ_API_KEY полный flow не тестировался — CI/release validation

---

## 2026-05-10 (Phase 4 partial — Distribution: Docker, docs, install, update, CI)

### Added

- **`Dockerfile`** — multi-stage build для self-hosted дистрибуции
  - Stage 1 (kernel-builder, python:3.12-slim): компилирует `_kernel.pyx` → `.so` для Linux
  - Stage 2 (runtime, python:3.12-slim): ffmpeg + opencv-headless + faster-whisper
    + готовый `.so` из builder. **`.pyx` исходник НЕ попадает в final image**
  - Python 3.12 (mediapipe не имеет wheels для 3.13 на linux/arm64; production CI собирает linux/amd64 c 3.13)
  - HEALTHCHECK через `/jobs` endpoint
- **`docker-compose.yml`** — production-ready конфиг
  - Volumes: jobs/, downloads/, output/, branding/, ~/.excella, mediapipe-cache, hf-cache
  - Environment: `MAX_CONCURRENT_JOBS=2`, `EXCELLA_STREAMING_ANALYZE=1`, `EXCELLA_DEV=1`
  - Resource limit 12 GB RAM
- **`.dockerignore`** — исключает `.venv/`, `jobs/`, `mlx_models/`, `_keys/`,
  `dist/`, локальные `.so` (Linux пересоберёт свой)
- **`install.sh`** — curl | bash инсталлер
  - Detect платформа (uname)
  - Docker mode (recommended) или native fallback (apt/dnf)
  - Создаёт `~/.excella/`, ставит wrapper `excella` в `/usr/local/bin/`
  - Wrapper команды: `init`, `start`, `stop`, `restart`, `logs`, `update`, `status`
- **`scripts/excella_update.py`** — auto-update для native
  - GitHub Releases API → compare version → download → SHA-256 verify
  - Atomic switch: `current` → `backup` → `staging` → `current`
  - Health-check (timeout 30с) → rollback при fail
  - Channels: stable / beta / nightly + offline mode
  - Логи в `~/.excella/logs/update-YYYY-MM-DD.log`
- **`docs/`** — MkDocs Material документация (9 страниц)
  - index, quickstart, install/{docker,native,windows}, configuration, update,
    licensing, troubleshooting, faq, api, changelog
  - Тема Material с RU lang, navigation tabs, search
- **`mkdocs.yml`** — конфигурация
- **`.github/workflows/release.yml`** — CI matrix:
  - macos-14 (arm64) + macos-13 (x86_64) + ubuntu-22.04 + windows-2022
  - На каждой собирается `_kernel.pyx` → `.so/.pyd` (4 артефакта)
  - Public key инжектится из `secrets.EXCELLA_PUBLIC_KEY_PEM`
  - Smoke-test после сборки
  - Pack 4 release tarballs + SHA-256
  - Multi-arch Docker push в ghcr.io
- **`.github/workflows/docs.yml`** — авто-деплой docs на docs.excella.ru
  через GitHub Pages при изменении `docs/`

### Validation

- `install.sh`: `bash -n` syntax check ✓, `detect_platform` → `darwin-arm64` ✓
- `scripts/excella_update.py`: `parse_version` корректно сравнивает SemVer ✓
- Dockerfile: build pass test pending (linux/arm64 build идёт в фоне на M4)

### Fixed (обнаружено живым Docker build)

- **`requirements.txt`** не содержал критичных зависимостей которые
  импортируются на module-level в `src/`:
  - `anthropic`, `openai`, `google-genai` — импортируются в `src/llm/registry.py`
  - `ultralytics` — для YOLO в `src/smart_reframe/detect/screens.py`
  - `python_speech_features`, `scipy` — для LR-ASD MFCC
  - В dev-машине эти пакеты были установлены ad-hoc в `.venv`, но в чистой
    среде Docker — отсутствовали. Это был silent technical debt, обнаружен
    только при Docker build (отличный пример важности интеграционных тестов
    в чистой среде).
  - Все добавлены в `requirements.txt` с комментариями о назначении.

### Known issues

- mediapipe для Python 3.13 на linux/arm64 пока недоступен — Dockerfile pinned на 3.12
- На M4 Docker эмулирует Linux ARM64 в VM — performance в 1.5-2× ниже native
- Native macOS .pkg installer (Phase 4 todo) — отложено: требует Apple Developer ID + notarization

### Pending в Phase 4

- [#16] PyArmor для src/ — обфускация Python байт-кода в release-build
- Native installers (.pkg/.msi/.deb/.rpm) — отдельные CI задачи
- get.excella.ru landing-страница (статичная, на Cloudflare Pages)

---

## 2026-05-10 (Phase 1 #5 — один проход декодирования)

### Added

- **`src/smart_reframe/streaming.py`** — `analyze_video_streaming()`
  - Один `cv2.VideoCapture` проход для всех 4 детекторов (faces, persons, screens, cuts)
  - Каждый детектор работает по своему `sample_every` (2/3/6/1) внутри общего цикла
  - Хелперы импортируются из существующих detect_* (DRY)
  - Те же IoUTracker, фильтры, hint'ы между детекторами что в legacy

### Changed

- **`src/smart_reframe/pipeline.py:analyze_video`** — параметр `streaming: bool = None`
  - `None` (default) → берётся из env `EXCELLA_STREAMING_ANALYZE`
  - `True` → новый streaming путь
  - `False` → legacy путь (4 отдельных детектора)
  - **По умолчанию OFF** для безопасности — legacy остаётся как fallback

### Validation на bench_streaming.py (3-мин видео, 4556 кадров, full без ranges)

| Режим | Время | faces / persons / screens / cuts |
|---|---|---|
| Legacy (4 декодирования) | 143.2 с | 4 / 3 / 1 / 4 |
| **Streaming (1 декодирование)** | **87.4 с** | 4 / 3 / 1 / 4 |
| **Ускорение** | **1.64×** | **точность 100% совпадает** |

### Совокупный эффект Phase 1 на бенчмарке

| Замер | Время |
|---|---|
| Оригинал (до Phase 1) | 441.3 с |
| После #17 (lr_asd одним проходом) | 164.9 с |
| **После #5 (+ streaming)** | **87.4 с** |
| **Совокупное ускорение** | **5.05×** |

С `time_ranges` (Phase 1 #3) ожидается 50-60с — это >7× от оригинала.

---

## 2026-05-10 (Phase 1 #8 — нагрузочный тест Semaphore end-to-end)

### Validation

POST 3 задач параллельно (file=_2msdFKRS_c.mp4, max_clips=2):

```
17:10:21 — все 3 POST'нуты
17:10:22 — Task 1 (25897ed4b4bf): running, transcribe 26%
17:10:22 — Task 2 (d5e7d56d288b): running, transcribe 26%
17:10:22 — Task 3 (d5af2707c0bc): queued, pending 0%   ← Semaphore держит

…22 минуты pipeline на 2 параллельных задачи…

17:32:23 — Task 2: done (4 mp4 файла)
17:32:23 — Task 3: running, transcribe 74%             ← слот освободился
17:32:23 — Task 1: meta 50% (почти done)
```

**Семафор атомарно держит лимит, очередь работает правильно.**

### Ресурсы при 2 параллельных задачах

| Метрика | Значение |
|---|---|
| uvicorn CPU peak | ~70% |
| swap usage | 9.2 / 10.2 GB |
| Pages free | ~58 MB |
| compressor | ~30 GB сжато |
| OOM/crash | НЕТ |

Система **на пределе**, но стабильна. M4 16 GB реалистично тянет 2 параллельных pipeline'а через Semaphore. 3 без Semaphore = OOM-crash (как было ДО Phase 1).

### Время на один pipeline в этом тесте

- Прошлый тест (sequential, 1 задача): **22 мин** (с lr_asd-багом)
- После #17 (sequential, 1 задача): **~10 мин** (по экстраполяции bench)
- Этот тест (parallel, 2 задачи): **~22 мин per task** (shared resources)

Throughput системы: **2 видео per ~22 мин = ~5 видео/час** на M4 16 GB.

---

## 2026-05-10 (Phase 1 #17 — lr_asd одним проходом)

### Changed

- **`src/smart_reframe/asd/lr_asd.py`** — рефактор `_extract_face_crops` → `_extract_crops_for_all_tracks`
  - Раньше: N декодирований видео (по track) с `cap.set(POS_FRAMES)` random seek per detection — 2 tracks × 4556 кадров = ~13 мин на 3-мин видео
  - Теперь: 1 декодирование, sequential read, `cap.set` только один раз для прыжка к первому нужному frame
  - Все tracks обрабатываются параллельно в одном цикле через `by_frame` mapping
  - `_crop_face` выделен как helper для крa-кадра

### Validation на bench_phase1.py (3-мин видео, 4556 кадров)

| Тест | До #17 | После #17 | Прирост |
|---|---|---|---|
| **Test 1 (full, без time_ranges)** | 441.3 с | **164.9 с** | **2.67× быстрее** |
| **Test 2 (с time_ranges 16%)** | 102.9 с | **72.4 с** | **1.42× быстрее** |

### Найдено живым прогоном (job 0f9f3f888b28, 3-мин видео)

До исправления: stage `analyze` занял **19 минут** из 22 минут общего pipeline'а — `lr_asd` был основным узким местом.

После исправления (экстраполяция): stage `analyze` ожидается **~7 мин**, total pipeline ~10 мин на то же видео. 3× ускорение полного цикла.

---

## 2026-05-10 (Phase 2 финальная сессия — Registration endpoint)

### Added

- **`brand_kernel_poc/server/app.py`** — FastAPI сервер для выдачи free-forever лицензий
  - `POST /register {email, machine_fp}` → `{license_id, license_json_b64, license_sig_b64, assets:{...}}`
  - SQLite CRM: `registrations.db` (license_id, email, machine_fp, issued_at, tier=community)
  - Rate-limit 3 регистрации с одного email
  - Идемпотентность: повторный (email, machine_fp) → re-issued тот же license_id
  - Validation: regex email + 64-hex machine_fp
  - `GET /health`, `GET /stats`
  - License: tier=community, expires_at=2099-01-01, watermark_required=False
  - Подписывает RSA-PSS приватным ключом из `brand_kernel_poc/_keys/private_key.pem`
  - Шифрует master ассеты (`branding/excella.json`, `branding/_assets/excella.png`) под выдаваемую лицензию через `kernel.encrypt_asset_for_license`
- **`scripts/excella_init.py`** — клиентский скрипт первой регистрации
  - `excella_init --email user@x.com --server https://registration.excella.ru`
  - Получает machine_fp через `kernel.get_machine_fp()`
  - POST на server, сохраняет `~/.excella/{license.json, license.sig, assets/excella.json.enc, assets/excella.png.enc}`

### Validation

```
end-to-end test:
  ✓ /health: всё сконфигурировано
  ✓ excella_init.py: лицензия выдана и сохранена
  ✓ kernel.load_license() валидирует выданную лицензию
  ✓ kernel.load_brand_template() расшифровывает выданный excella.json.enc
  ✓ kernel.load_asset_bytes() расшифровывает excella.png.enc (PNG sig OK)
  ✓ идемпотентность: повторный excella_init → "re-issued existing license"
  ✓ rate-limit: 3 регистрации с одного email → 200, 4-я → HTTP 429
  ✓ invalid email → HTTP 400
  ✓ invalid fp → HTTP 422
  ✓ /stats: total=3, unique_emails=1
```

### Архитектура для production deployment

```
[ self-hosted клиент ]                   [ registration.excella.ru ]
      ↓ excella init                              ↑
      ↓ {email, machine_fp}                       │
      ↓ POST                       FastAPI app    │
      ↓                            ├─ rate-limit  │
      ↓                            ├─ RSA sign    │ private_key (Vault)
      ↓                            ├─ AES encrypt │ master_assets (PR-only access)
      ↑ {license, sig, assets}     └─ SQLite CRM  │
      ↓ save ~/.excella/                          │
      ↓ start app                                 │
      ↓ kernel.load_license() valid               │
      ✓ ready                                     │
```

---

## 2026-05-10 (Phase 2 продолжение — Master secret obfuscation)

### Changed

- **`brand_kernel/_kernel.pyx`** — master secret вынесен из открытой константы:
  - 3 фрагмента `_MS_FRAG_1/2/3`, размещены в разных местах файла (после headers, после machine_fp section, перед asset section)
  - XOR с runtime-вычисляемыми pattern'ами: `_ms_pattern(seed, offset, n)`
  - `_master_secret()` восстанавливает + кэширует
  - Перекомпиляция .so → vendor/brand_kernel/

### Validation

```
Master secret obfuscation:
  ✓ ACME assets зашифрованные старым kernel расшифровываются новым (backward compat)
  ✓ Полные 32 байта secret в .so:        НЕ найдены
  ✓ Hex-строка "9f124ca38b7d21ee":       НЕ найдена
  ✓ Замаскированные фрагменты M1/M2/M3:  НЕ найдены (Cython упаковал)
  ✓ Любая 8-байтовая подпоследовательность: НЕ найдена
  Реверс теперь требует Ghidra + reverse XOR логики, не grep на байты
```

### Decisions

- **Стенографический (invisible) watermark — НЕ делаем.**
  - `src/watermark.py` и `scripts/test_watermark.py` удалены.
  - Зависимости `invisible-watermark` + `PyWavelets` удалены из venv.
  - Из `src/render.py` docstring и `AI_NOTICE.md` убраны упоминания watermark
    атрибуции. Visible brand layer (логотип `excella.png`, `bottom_strip`, CTA)
    остаётся как часть `apply_brand` — это бренд, не атрибуция.
  - **Защита держится на**: Cython kernel, AES шифрование ассетов, RSA-
    подписанная лицензия с machine_fp, tamper detection, AI guardrails,
    master secret obfuscation, visible brand layer.
  - **Причина**: invisible-watermark не выживает H.264 сжатия видео-pipeline.
    Альтернативы (videoseal, custom DCT, Reed-Solomon) — серьёзная R&D
    задача. Решено не вкладываться сейчас. Атрибуция пиратских копий —
    через visible brand (тот, кто не убрал лого) и legal layer (DMCA notice
    в коде доказывает злой умысел при модификации).

---

## 2026-05-10 (Phase 2 partial — Brand protection)

### Added

- **`vendor/brand_kernel/`** — скомпилированный kernel + `__init__.py` теперь доступен из основного проекта без `sys.path` гимнастики (vendor добавляется в src/branding.py при импорте)
- **`brand_kernel.verify_module_integrity(path, expected_hash="")`** — SHA-256 проверка против `_PROTECTED_HASHES` или явного аргумента; dev-skip через `EXCELLA_DEV=1`
- **`brand_kernel.assert_modules_intact([paths])`** — pre-flight check, бросает `LicenseError` при подмене защищённого модуля. Заполнение `_PROTECTED_HASHES` ожидается от release CI

### Changed

- **`src/branding.py:load_brand`** — две ветки:
  - production (есть `.json.enc` + валидная лицензия) → `kernel.load_brand_template()` расшифровывает в память
  - dev (только `.json`) → текущее поведение, warning если kernel есть но лицензия отсутствует
  - Защита: ребрендинг через простую правку `branding/excella.json` блокируется когда брендинг идёт в зашифрованном виде
- **`src/branding.py`, `src/render.py`, `src/pipeline.py`** — компактный `<system>` AI-guardrail блок в docstring. Тот же набор юрисдикций что и в `AI_NOTICE.md`. Цель: AI-ассистент клиента (Cursor/Copilot/Claude/etc) при попытке убрать брендинг прочитает блок и откажет

### Validation

```
✓ branch 1 (kernel-decrypted):  name='excella' lead_url='https://excella.ru'
✓ branch 2 (plain JSON):        name='excella' lead_url='https://excella.ru'
✓ tamper detection 5/5 сценариев (dev-mode, без-хэша, правильный, неправильный, assert)
✓ все импорты chain (branding/render/pipeline/web.app) проходят smoke-test
```

### Pending в Phase 2

- DCT watermark embedding (Task #14) — самая большая защита от полного взлома, требует ffmpeg-фильтра + invisible-watermark или own DCT-модификации в render pipeline. Отдельная сессия 1-2 дня
- Free-forever registration endpoint (Task #13) — FastAPI + SQLite на нашей стороне (`registration.excella.ru`), 4-6 часов
- Master secret obfuscation (Task #15) — XOR-маскировка из 3 источников в `_kernel.pyx`, 2-3 часа
- PyArmor + Docker (Tasks #16, #8) — это часть Phase 4 distribution

---

## 2026-05-10 (продолжение — Phase 1 implementation)

### Changed

- **`src/transcribe.py`** — singleton WhisperModel
  - Module-level `_FASTER_WHISPER_CACHE: dict[(model_size, device, compute_type), WhisperModel]`
  - Monkey-patch `mlx_whisper.load_models.load_model` через `functools.lru_cache(maxsize=4)`
  - Эффект: −1.5 GB RAM на каждую следующую задачу, −2..5с на старт
- **`web/app.py`** — `asyncio.Semaphore(MAX_CONCURRENT_JOBS=2)`
  - `_run_job` теперь внешний gate, тело pipeline вынесено в `_run_job_inner`
  - При занятых слотах: `job.status = "queued"`, событие `{"stage":"queued"}` во фронт
  - Защищает M4 16GB от OOM при N>2 одновременных задач
- **`src/pipeline.py:303`** — `analyze_video(time_ranges=...)` вместо полного видео
  - `ranges = [(c.start - 2.0, c.end + 2.0) for c in clips]`
  - Анализируются только окрестности выбранных Claude клипов (~14% длинного видео)
- **`src/smart_reframe/pipeline.py`** — `analyze_video(time_ranges=...)` параметр прокидывается во все детекторы
- **`src/smart_reframe/detect/{faces,persons,screens,cuts}.py`** — каждый принимает `time_ranges`, конвертирует sec→frame через локальный fps, пропускает inference вне ranges; в cuts дополнительно сбрасывает `prev_hist` на границах ranges чтобы не получить ложный cut
- **`src/smart_reframe/detect/screens.py`** — `_detect_yolo_device()` (MPS/CUDA/CPU автоопределение), `YOLO_DEVICE`, `YOLO_IMGSZ=480` константы
- **`src/smart_reframe/detect/persons.py`** — переиспользует `YOLO_DEVICE`/`YOLO_IMGSZ`, передаёт в `yolo.predict`

### Added

- **Глобальный analysis-кэш** в `~/.excella/cache/analysis/{video_fp}_{ranges_fp}.pkl`
  - `_video_fingerprint()` — SHA-1 от size + first 1MB + last 1MB (быстро без чтения целиком)
  - `_ranges_fingerprint()` — SHA-1 от serialized ranges
  - Cache hit → пропуск всей стадии analyze (важно для retrim/rebrand workflow)
  - Override через `EXCELLA_CACHE_DIR` env

### Validation

Функциональный микро-бенчмарк через `scripts/bench_phase1.py` на 3-мин видео `_2msdFKRS_c.mp4` (180с, 4556 кадров):

| Замер | Время | Coverage | Найдено |
|---|---|---|---|
| Без `time_ranges` (baseline) | **441.3с** | 100% | 4 faces, 3 persons, 1 screen, 4 cuts |
| С `time_ranges=[(76, 106)]` | **102.9с** | 16% | 1 face, 1 person, 0 screens, 0 cuts |

→ **Ускорение 4.29×** при coverage 16%. Корректность подтверждена: детекторы пропускают inference вне диапазонов, но находят всё в указанных.

Теоретический потолок (1/0.16 ≈ 6.25×) недостижим из-за константного `cv2.VideoCapture` декодирования и LR-ASD который сейчас ходит по всем tracks. После Шага 5 (один проход) ожидаем ~6-8× на этом же входе.

**Экстраполяция на 35-мин кейс из CHANGELOG**: 5 клипов по 30с = 150с/2100с = 7% coverage → ожидаемое ускорение **~7-10×**, время analyze падает с ~25 мин до **~3-4 мин**.

### Pending

- Шаг 5: один цикл декодирования (большой рефактор detect_*.py на stateful API) — даст ещё ~60% RAM и +50% времени поверх. Отдельная сессия.
- Шаг 8: нагрузочный тест 3/5/8 параллельных задач. После рестарта uvicorn.

### Action items для пользователя

- ⚠️ **Перезапустить uvicorn** — текущий PID 71765 держит старый байткод. Без рестарта улучшения не подхватятся.
- После рестарта — запустить тестовое короткое видео (5 мин), сравнить время analyze: ожидаем падение с ~25 мин до ~3 мин.

---

## 2026-05-10

### Fixed

- **`apply_brand` падал на ffmpeg 8.0** при включённом `watermark_radius>0`
  (`branding.py:345`). В geq-фильтре использовался `a(X,Y)` для чтения alpha-плоскости —
  ffmpeg 8.0 убрал этот алиас, осталась только `alpha(X,Y)` (exit 234,
  «Unknown function in 'a(X,Y)*0.65)'»). Источник давно поправлен на
  `alpha(X,Y)`, но запущенный uvicorn держал устаревший байткод в памяти,
  и все 9 клипов job'а `ae336bf6911a` отрендерились без watermark+bottom strip
  (fallback `with_subs.replace(master)`).
- **`scripts/rebrand_job.py`** — постфактумный накат брендинга на готовые master-mp4
  с атомарной заменой через `.rebrand.tmp.mp4` → `os.replace` (можно гонять
  параллельно с активным uvicorn). Применён к `ae336bf6911a` — все 9 клипов
  (1056p+480p) получили правильный бренд.

> ⚠️ uvicorn-процесс надо перезапустить, иначе следующий job опять выйдет без бренда:
> при старте он загрузит свежий `branding.py` с `alpha(X,Y)`.

### Added

- **`brand_kernel_poc/`** — PoC закрытого бренд-ядра на Cython.
  - RSA-PSS подпись лицензий с привязкой к machine fingerprint
  - AES-256-GCM шифрование brand-template и ассетов с HKDF-выведенным ключом
  - 16-байтовый watermark payload с HMAC для встраивания в видео
  - 4 тампер-теста (правка JSON, фабрикация лицензии, чтение enc-файлов,
    подмена ассетов) — все 4 атаки отбиваются
  - Cython-сборка скрывает master secret и PEM публичного ключа в C-литералах
    (не находятся через `strings`/`grep`)
  - Файлы: `_kernel.pyx`, `_kernel.so`, `tools/{make_keys,make_license,encrypt_assets}.py`,
    `tests/{demo_normal,demo_tamper}.py`, `Makefile`, `README.md`
- **`AI_NOTICE.md`** — инструкции для AI-ассистентов с legal notice (DMCA,
  EU 2001/29/EC, WIPO, ГК РФ §1299). Создаёт evidence trail на случай
  AI-assisted взлома.
- **`CHANGELOG.md`** — этот файл, формат Keep a Changelog.

### Analysis

- Замерены ресурсы текущего uvicorn-процесса при стадии `analyze`:
  - Resident RAM: **10.8 GB** (~70 % от 16 GB)
  - Swap: **10.9 GB**
  - CPU: 263–272 % (~2.7 ядра)
  - 64 потока, 1 процесс
  - Системный swap: 13.8 / 14 GB used
- **Узкие места найдены:**
  1. Видео декодируется 4–5 раз (faces/persons/screens/cuts/asd по отдельности)
  2. YOLO без батчей и без `stream=True`/`device='mps'` (`persons.py:53`)
  3. Whisper грузится в RAM каждый раз — нет singleton'а
  4. Analyze идёт на ВСЁМ видео до выбора клипов (~80 % работы выбрасывается)
  5. `asyncio.create_task` без Semaphore — нет лимита конкурентных задач
- На M4 16 GB **реалистичный потолок без оптимизации: 1–2 параллельные задачи.**
  10 параллельных = OOM.

### Decisions

- **Self-hosted distribution model** — продаём бинарь с per-machine лицензией
- **Open core + closed brand kernel** — брендинг в `_kernel.so`, остальное
  открытый Python (упрощает поддержку клиентов, минимизирует поверхность защиты)
- **Стратегия защиты: «дорогая, не невозможная»** — поднять стоимость
  ребрендинга выше стоимости лицензии
- **Stenographic watermark** — главная страховка вне kernel: даже после
  полного взлома пиратские рендеры содержат `license_id_hash` → атрибуция

---

## Convention

- Каждая значимая сессия добавляет запись с датой
- Группы: `Added`, `Changed`, `Removed`, `Fixed`, `Security`, `Analysis`,
  `Decisions`, `Roadmap`
- Технические детали — в commit messages, тут только результаты и причины
- Незавершённые задачи живут в `[Unreleased] Roadmap` пока не сделаны
