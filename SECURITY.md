# Security checklist перед публикацией

## ⚠️ ОБЯЗАТЕЛЬНО ПЕРЕД ПЕРВЫМ `git push` В ПУБЛИЧНЫЙ РЕПО

### 1. Audit secrets

```bash
# Что сейчас не игнорируется и попадёт в push:
git ls-files --others --exclude-standard

# Должны видеть только:
# - public docs (docs/*, README.md, CHANGELOG.md, etc)
# - public source (src/*, web/*, scripts/*)
# - infrastructure (Dockerfile, docker-compose.yml, .github/*, mkdocs.yml)
# - shells (install.sh, *.example)

# НЕ должны видеть:
# - .env (любой)
# - private_key.pem
# - branding/_oauth/* (OAuth tokens)
# - branding/excella.json (template — должен идти через registration)
# - vendor/brand_kernel/*.so (компилируется в CI)
# - mlx_models/, *.pt (большие модели — lazy download)
```

### 2. Скан истории git (если уже были коммиты)

```bash
# поиск любых упоминаний секретных паттернов
git log --all -p -S "client_secret" 2>/dev/null | head -20
git log --all -p -S "refresh_token" 2>/dev/null | head -20
git log --all -p -S "BEGIN PRIVATE KEY" 2>/dev/null | head -20
git log --all -p -S "GROQ_API_KEY=" 2>/dev/null | head -20
```

Если найдено — **НЕЛЬЗЯ просто удалить файл и закомитить**. Нужно
переписать историю (`git filter-repo`) или **создать новый репо**.
И **revoke** все засветившиеся токены.

### 3. Создать production RSA pair (НЕ использовать тестовый)

```bash
# В защищённом окружении (vault, GitHub Actions secret)
python brand_kernel_poc/tools/make_keys.py
# → _keys/private_key.pem (НЕ commit!)
# → _keys/public_key.pem (вписан в .pyx)
```

Загрузить в GitHub Secrets:
- `EXCELLA_PUBLIC_KEY_PEM` — содержимое public_key.pem
- (опц) `EXCELLA_PRIVATE_KEY_PEM` — для CI registration server

### 4. Revoke all test tokens

Если в `branding/_oauth/` есть **ваши реальные** токены:

```bash
# YouTube — отозвать через Google Console
# https://myaccount.google.com/permissions

# VK — отозвать через VK developer panel
# https://vk.com/apps?act=manage
```

Потом сгенерировать новые **только на production-сервере**, не в dev.

### 5. Master secret в `_kernel.pyx`

Текущий `_MS_FRAG_1/2/3` — **PoC значение**. Перед production:

```bash
# Сгенерировать новый master_secret и вписать в .pyx
python -c "
import os
ms = os.urandom(32)
print('original:', ms.hex())
# ... compute new XOR fragments and inject
"
```

### 6. Проверка Docker image

```bash
docker build -t test-img .
docker run --rm --entrypoint sh test-img -c '
  find /app -name "*.pem" -o -name "*token*.json" -o -name "*.env"
'
# Должно быть пусто.
```

### 7. Проверка что .pyx исходник НЕ в Docker final image

```bash
docker run --rm --entrypoint sh test-img -c 'find /app -name "*.pyx"'
# Должно быть пусто (исходник остаётся в Stage 1 builder, не в final).
```

## Настройка GitHub repo

### Branch protection

```
main:
- Require pull request reviews before merging
- Require status checks: build-kernel, package-release, build-docker
- Require signed commits
- Restrict who can push (только maintainers)
```

### Secret scanning

GitHub автоматически сканирует repo на:
- Google API keys
- AWS credentials
- Stripe keys
- Slack tokens
- 100+ паттернов

Включить: Settings → Code security → Secret scanning → Enable.
**Push protection** — блокирует push если найден секрет.

### Dependabot

Settings → Code security → Dependabot alerts + security updates.

## Что произойдёт если ВСЁ-ТАКИ утечёт

### YouTube refresh_token утёк

```bash
# Немедленно отозвать
# https://myaccount.google.com/permissions
# Удалить app "excella shorts-cutter"

# Сгенерировать новый
python scripts/reauth_youtube.py
```

### VK access_token утёк

```bash
# https://vk.com/apps?act=manage
# Найти app, Settings → "Show service token" → Revoke
```

### Private RSA key утёк

**Это самое плохое.** Атакующий может:
- Подделать любую лицензию
- Расшифровать все ассеты которые мы рассылали (если он знает master_secret)

Действия:
1. Сгенерировать новую RSA пару
2. Перекомпилировать `_kernel.pyx` с новым public_key
3. Опубликовать новый Docker image / release
4. **Все старые лицензии станут невалидными** — все клиенты должны
   `excella init --refresh`
5. Опубликовать security advisory

### Master secret утёк

То же что выше, плюс **все ассеты которые мы шифровали — компрометированы**.
Атакующий может:
- Расшифровать `excella.json.enc` и `excella.png.enc` любого клиента
- Подделать watermark payload (если он есть)

Ротация: новый master_secret → новые XOR фрагменты → пересборка .so →
новый Docker image → ре-регистрация всех клиентов.

## Контакты для security report

- security@excella.ru
- [GitHub Security Advisories](https://github.com/excella/shorts-cutter/security/advisories/new)
- Bug bounty: TBD (планируется $50–500 за критичные уязвимости)
