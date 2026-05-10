# Установка native (macOS / Linux)

## macOS

### Требования
- macOS 12+ (Apple Silicon рекомендуется)
- Python 3.13
- ffmpeg
- 8 GB RAM минимум

### Через Homebrew (рекомендуется)

```bash
brew install excella/tap/shorts-cutter
excella init     # email + лицензия
excella server   # запуск web UI на :8000
```

### Через .pkg

Скачайте `excella-shorts-cutter-X.Y.Z.pkg` с
[GitHub Releases](https://github.com/excella/shorts-cutter/releases/latest),
дважды кликните, следуйте инструкциям.

### Из исходников (для разработчиков)

```bash
git clone https://github.com/excella/shorts-cutter
cd shorts-cutter
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg
.venv/bin/python -m uvicorn web.app:app --host 127.0.0.1 --port 8000
```

## Linux (Debian/Ubuntu)

```bash
# Через apt repository
curl -fsSL https://get.excella.ru/install.sh | bash

# Или вручную:
wget https://github.com/excella/shorts-cutter/releases/latest/download/excella-cutter_amd64.deb
sudo apt install ./excella-cutter_amd64.deb
```

## Linux (RHEL/Fedora)

```bash
sudo dnf install \
  https://github.com/excella/shorts-cutter/releases/latest/download/excella-cutter.x86_64.rpm
```

## После установки

```bash
excella init
# Email для регистрации (бесплатно навсегда): user@example.com
# [1/3] machine_fp:  4daa594a4c10e540…
# [2/3] получаю лицензию с registration.excella.ru…
# [3/3] лицензия активирована, валидна до 2099-12-31

excella server
# → http://localhost:8000
```

## Файлы и пути

| Файл | Путь |
|---|---|
| Лицензия | `~/.excella/license.json` |
| Подпись | `~/.excella/license.sig` |
| Зашифрованные ассеты | `~/.excella/assets/` |
| Job state | `~/.excella/jobs/` |
| Бинарь | `/usr/local/bin/excella` (Mac/Linux) |

## Удаление

```bash
brew uninstall shorts-cutter            # macOS
sudo apt remove excella-cutter          # Debian/Ubuntu
sudo dnf remove excella-cutter          # RHEL/Fedora

# Удалить лицензию и кэш
rm -rf ~/.excella
```
