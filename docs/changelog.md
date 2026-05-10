# Changelog

История изменений ведётся в [`CHANGELOG.md`](https://github.com/excella/shorts-cutter/blob/main/CHANGELOG.md)
в корне репозитория.

Формат: [Keep a Changelog](https://keepachangelog.com/) + семантическое
версионирование.

См. [последние записи →](https://github.com/excella/shorts-cutter/blob/main/CHANGELOG.md)

## Текущая версия

- **0.1.0-dev** (development) — Phase 1+2 закрыты, Phase 4 в процессе

## Roadmap

См. [`CHANGELOG.md` Roadmap section](https://github.com/excella/shorts-cutter/blob/main/CHANGELOG.md#roadmap-запланировано).

Краткая выжимка:

- **Phase 1 (perf)** ✅ — analyze 5× быстрее, Semaphore защита от OOM,
  cache analysis.pkl, streaming decoding (1 проход для всех детекторов)
- **Phase 2 (brand protection)** ✅ — Cython kernel, AES-шифрование ассетов,
  RSA-подписанные лицензии, machine_fp binding, tamper detection,
  master secret obfuscation, registration server, AI guardrails
- **Phase 3 (production hardening)** 🔜 — внешние API (Groq Whisper),
  multiprocessing воркеры, Celery + Redis для horizontal scale, pen-test
- **Phase 4 (distribution)** 🔄 в процессе — Docker, native installers,
  CI matrix для kernel.so, install.sh, auto-update, эта документация
