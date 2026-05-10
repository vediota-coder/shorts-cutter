# Troubleshooting

## Установка

### "command not found: excella"

После Brew install / apt install бинарь не в PATH.

```bash
# проверить
which excella
echo $PATH

# вручную
export PATH="$PATH:/usr/local/bin"
# или для Apple Silicon Homebrew:
export PATH="$PATH:/opt/homebrew/bin"
```

Добавьте export в `~/.zshrc` или `~/.bashrc`.

### Docker: "Cannot connect to Docker daemon"

Docker Desktop не запущен. Откройте Docker Desktop, подождите пока
иконка станет зелёной, повторите.

### Docker: "no space left on device"

```bash
docker system prune -a    # удалит unused images
df -h                     # проверить свободное место
```

Если проблема в `/var/lib/docker/`, увеличьте Docker Desktop disk size:
Settings → Resources → Disk image size.

## Регистрация

### "ERROR: timeout connecting to registration.excella.ru"

Проверьте интернет, прокси, файрвол. Если проблема одностороння:

```bash
# offline-регистрация
1. На машине с интернетом: excella init --get-fp >fp.txt
2. Передать fp.txt на машину с интернетом
3. excella init --offline-fp=fp.txt → license.tar.gz
4. Перенести license.tar.gz на изолированную машину
5. excella init --offline-license=license.tar.gz
```

### "лицензия выдана для другой машины"

Machine fingerprint = SHA256(MAC + hostname + platform). Если поменяли
MAC (USB-Ethernet, виртуалка) или hostname — fp другой.

```bash
excella init --refresh   # перевыдать лицензию на текущий fp
```

## Pipeline

### "Out of Memory" при transcribe или analyze

Нужно ≥8 GB RAM. Если в Docker — проверить лимит:

```bash
docker compose down
# отредактировать docker-compose.yml: deploy.resources.limits.memory: 12G
docker compose up -d
```

На native — закрыть тяжёлые приложения, перезапустить excella server.

### "ffprobe: command not found"

ffmpeg не установлен или не в PATH.

```bash
# macOS
brew install ffmpeg

# Debian/Ubuntu
sudo apt install ffmpeg

# Windows
choco install ffmpeg
# или скачайте https://ffmpeg.org/download.html и добавьте в PATH
```

### "claude-code CLI not found"

Default LLM provider — Claude Code CLI. Установите:

```bash
npm install -g @anthropic-ai/claude-code
claude login
```

Альтернатива — переключить на Anthropic API:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# при создании job: llm_provider=anthropic
```

### Subtitles "не видны на видео"

Проверьте что в job_dir/output/_cache/ есть `*.ass` файл (субтитры).
Если есть — проблема в ffmpeg фильтре. Тогда:

```bash
# Перерендерить с другим subtitle template
curl -X POST localhost:8000/jobs/{job_id}/clips/{i}/restyle \
  -F "sub_template=block"
```

### Брендинг не отрисовался

Проверить лог job'а:

```bash
curl http://localhost:8000/jobs/{job_id} | jq .log
```

Если вы видите ошибку `apply_brand failed` — проверьте:

1. Файл `branding/excella.json` существует
2. Пути в нём корректны (`watermark_path`)
3. PNG-логотип существует

Если вы установили self-hosted с лицензией — проверьте что
`~/.excella/assets/excella.json.enc` существует:

```bash
ls -la ~/.excella/assets/
# excella.json.enc
# excella.png.enc
```

## Производительность

### "Pipeline стал медленнее после апдейта"

```bash
# Включить streaming analyze (1.6× быстрее)
export EXCELLA_STREAMING_ANALYZE=1
# Или в docker-compose.yml: environment: EXCELLA_STREAMING_ANALYZE=1
```

### "На M4 ожидал быстрее"

В Docker MPS не работает. Если вам важна скорость — поставьте native:

```bash
brew install excella/tap/shorts-cutter
```

На native M4 transcribe в **30× быстрее** (mlx-whisper) и YOLO в **3× быстрее** (MPS).

## Update

См. [Обновление / Если update не прошёл](update.md#если-update-не-прошёл).

## Support

Если ничего не помогло — соберите debug-info и отправьте:

```bash
excella debug-info > debug.tar.gz
# содержит: версию, OS, ENV (без секретов), последние логи, hash модулей
```

→ [GitHub Issues](https://github.com/excella/shorts-cutter/issues) с прикреплённым `debug.tar.gz`.

→ Telegram @excella_support
