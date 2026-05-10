# Обновление

## Auto-update команда

```bash
excella update
```

Что делает:

1. **Check** — GET `https://api.github.com/repos/excella/shorts-cutter/releases/latest`
2. **Compare** — сравнивает `version.txt` локально с remote
3. **Download** — качает архив в `~/.excella/staging/`
4. **Verify** — проверяет SHA-256 + GPG подпись релиза
5. **Atomic switch** — переименовывает `current` → `backup`, `staging` → `current`
6. **Health-check** — стартует новую версию, ждёт `/health` 30 секунд
7. **Rollback при fail** — если health-check не прошёл, откат на `backup`

После успешного апдейта `excella restart` (или Docker сам подхватит).

## Что обновится

- `brand_kernel/_kernel.so` — закрытый бинарник
- `src/`, `web/` — основной Python код
- `branding/_assets/` — обновлённые master ассеты
- Документация (если используете offline)

## Что не обновится

- Ваша лицензия (`~/.excella/license.json`) — она привязана к этой машине
- Ваши brand templates (`branding/{custom}.json`) — клиентские конфиги не трогаем
- Job state (`~/.excella/jobs/`) — все ваши готовые видео остаются

## Если update не прошёл

### "Нет места на диске"

```
ERROR: Нужно X GB, доступно Y GB. Освободите место и попробуйте `excella update --resume`.
```

→ Освободить ≥10 GB на разделе с `~/.excella/`.

### "Не удалось скачать"

```
ERROR: GET github.com/.../releases failed: timeout
```

→ Проверить интернет. Можно скачать вручную и поставить через `excella update --offline=path/to/release.tar.gz`.

### "Подпись повреждена"

```
ERROR: GPG signature verification failed.
```

→ **Не игнорируйте.** Файл повреждён или подменён. Откатились на старую версию.
Свяжитесь с поддержкой через [GitHub Issues](https://github.com/excella/shorts-cutter/issues).

### "Health-check провалился"

```
ERROR: Новая версия не запустилась за 30с. Откатился на 1.2.3.
       Лог: ~/.excella/logs/update-failed-2026-05-10.log
```

→ Откат сработал автоматически — продукт продолжает работать на старой версии.
Лог отправьте в саппорт.

### "Лицензия устарела"

```
WARNING: лицензия выдана для другой версии kernel. Перерегистрируйтесь:
         excella init --refresh
```

→ Это редкий случай при major-апдейте с разным public_key. Команда `init --refresh`
скачает новую лицензию для текущего machine_fp.

## Channel: stable / beta / nightly

```bash
excella update --channel=stable    # default — последний release
excella update --channel=beta      # pre-release tags
excella update --channel=nightly   # каждую ночь с main, для тестирования
```

## Отчёт об обновлении

После каждого `excella update` создаётся файл
`~/.excella/logs/update-YYYY-MM-DD.log` с:

- Старая → новая версия
- Время каждого шага
- Health-check результаты
- Любые предупреждения

Автоматически отправляется на наш сервер только при `excella update --report`
(opt-in, для проактивной поддержки).
