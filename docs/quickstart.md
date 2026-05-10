# Quickstart — 5 минут до первого видео

## 1. Установить (1 минута)

=== "Docker (рекомендуется)"

    ```bash
    curl -fsSL https://get.excella.ru/install.sh | bash
    ```

    Установит Docker-образ + создаст `~/.excella/` для лицензии и кэша.

=== "macOS native"

    ```bash
    brew install excella/tap/shorts-cutter
    ```

=== "Linux native"

    ```bash
    curl -fsSL https://get.excella.ru/install.sh | bash
    # Установит .deb (Debian/Ubuntu) или .rpm (RHEL/Fedora)
    ```

=== "Windows"

    Скачайте `.msi` с [GitHub Releases](https://github.com/excella/shorts-cutter/releases/latest)
    и запустите.

## 2. Зарегистрироваться (30 секунд)

```bash
excella init
```

Спросит email. Бесплатная лицензия привязывается к этой машине.

## 3. Запустить (10 секунд)

=== "Docker"

    ```bash
    excella start
    # → http://localhost:8000
    ```

=== "Native"

    ```bash
    excella server
    # → http://localhost:8000
    ```

## 4. Сделать первый short

Откройте http://localhost:8000 → вставьте YouTube URL или загрузите файл →
выберите количество клипов (обычно 3–8) → жмите «Создать».

Готовые клипы окажутся в `~/.excella/output/<job_id>/`.

## Для разработчиков — REST API

```bash
curl -X POST http://localhost:8000/jobs \
  -F "url=https://www.youtube.com/watch?v=..." \
  -F "max_clips=5" \
  -F "brand=excella"
# → {"job_id": "abc123..."}

curl http://localhost:8000/jobs/abc123...
# → статус и прогресс
```

## Что дальше

- [Конфигурация](configuration.md) — настройки бренда, voiceover, субтитры
- [Troubleshooting](troubleshooting.md) — если что-то не работает
- [API reference](api.md) — полное описание endpoint'ов
