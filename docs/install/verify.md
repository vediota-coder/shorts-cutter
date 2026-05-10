# Проверка подписи install.sh и release artifact'ов

## Зачем

`curl | bash` — потенциально опасный паттерн (если сеть скомпрометирована —
выполняется чужой код). Чтобы себя обезопасить, проверяйте подпись скрипта
перед запуском.

## Проверка install.sh

```bash
# 1. Скачайте скрипт ОТДЕЛЬНО (не запускайте)
curl -fsSL https://get.excella.ru/install.sh -o install.sh
curl -fsSL https://get.excella.ru/install.sh.sig -o install.sh.sig

# 2. Скачайте наш публичный GPG ключ
curl -fsSL https://get.excella.ru/excella-signing.pub.asc | gpg --import

# 3. Проверьте подпись
gpg --verify install.sh.sig install.sh
# → "Good signature from excella security <security@excella.ru>"

# 4. Прочитайте скрипт глазами
less install.sh

# 5. Только теперь запускайте
bash install.sh
```

## Проверка release-tarball'ов

Каждый release-tarball на GitHub Releases имеет:

- `excella-cutter-vX.Y.Z-{platform}.tar.gz` — основной артефакт
- `excella-cutter-vX.Y.Z-{platform}.tar.gz.sha256` — хэш
- `excella-cutter-vX.Y.Z-{platform}.tar.gz.sig` — GPG подпись

```bash
# SHA-256
sha256sum -c excella-cutter-v0.1.0-linux-x86_64.tar.gz.sha256

# GPG
gpg --verify excella-cutter-v0.1.0-linux-x86_64.tar.gz.sig
```

## Наш GPG ключ

```
Fingerprint: TBD (будет опубликован при первом релизе)
```

Ключ хранится в Vault, ротация раз в год. Старые ключи остаются
действительными для проверки старых релизов.

## Проверка Docker image

```bash
# Через docker scout (если установлен)
docker scout quickview ghcr.io/excella/shorts-cutter:latest

# Через cosign (рекомендуется)
cosign verify ghcr.io/excella/shorts-cutter:latest \
  --certificate-identity=https://github.com/excella/shorts-cutter/.github/workflows/release.yml@refs/tags/v0.1.0 \
  --certificate-oidc-issuer=https://token.actions.githubusercontent.com
```

## Если подпись не сходится

**Не запускайте код.** Сообщите нам через
[GitHub Security](https://github.com/excella/shorts-cutter/security/advisories/new)
или security@excella.ru.

Возможные причины:
- MITM атака на ваш интернет
- Скомпрометированный CDN (мы используем Cloudflare с TLS-only)
- Утечка наших signing-ключей (мы ротируем + revoke если узнаём)
