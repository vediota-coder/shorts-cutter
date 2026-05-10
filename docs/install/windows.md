# Установка на Windows

## Через .msi installer

1. Скачайте `excella-shorts-cutter-X.Y.Z.msi` с
   [GitHub Releases](https://github.com/excella/shorts-cutter/releases/latest)
2. Дважды кликните по .msi, следуйте инструкциям
3. Запустите PowerShell → `excella init`

## Через PowerShell (curl-style)

```powershell
iwr https://get.excella.ru/install.ps1 | iex
```

## Через Docker Desktop (альтернатива)

Если у вас уже стоит Docker Desktop:

```powershell
curl https://get.excella.ru/docker-compose.yml -o docker-compose.yml
docker compose up -d
```

## Требования

- Windows 10 (build 19041+) или Windows 11
- Минимум 8 GB RAM
- 20 GB свободного места
- ffmpeg в PATH (installer добавит автоматически)

!!! warning "Apple-Silicon специфичные ускорения недоступны"
    На Windows работает **только faster-whisper на CPU** (mlx-whisper —
    macOS arm64 only). Производительность примерно такая же как Docker
    в любой ОС.

## После установки

```powershell
# Запустить
excella server

# Откроется http://localhost:8000

# В отдельном PowerShell — зарегистрироваться
excella init
```

## Файлы

| Файл | Путь |
|---|---|
| Бинарь | `C:\Program Files\Excella\excella.exe` |
| Лицензия | `%USERPROFILE%\.excella\license.json` |
| Job state | `%USERPROFILE%\.excella\jobs\` |

## Удаление

Settings → Apps → Excella shorts-cutter → Uninstall.

Затем удалить `%USERPROFILE%\.excella\`.
