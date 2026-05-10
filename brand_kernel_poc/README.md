# brand_kernel — PoC бренд-защиты для self-hosted

Closed-source ядро на Cython, через которое идёт всё что касается бренда:
- загрузка лицензии (RSA-PSS подпись + привязка к machine fingerprint)
- расшифровка ассетов (logo, intro/outro, brand template) только в память
- генерация stenographic watermark payload для встраивания в видео-выход

После сборки клиент получает только `_kernel.cpython-*.so` — нативный бинарь.
Исходник `.pyx` в дистрибутив не включается.

## Структура

```
brand_kernel_poc/
├── brand_kernel/
│   ├── _kernel.pyx      ← закрытый исходник (НЕ отдаём клиенту)
│   ├── _kernel.so       ← скомпилированный бинарь (отдаём)
│   └── __init__.py      ← публичный фасад
├── tools/
│   ├── make_keys.py     ← одноразово: генерация RSA пары
│   ├── make_license.py  ← на каждого клиента: лицензия с подписью
│   └── encrypt_assets.py← на каждого клиента: шифрование PNG/JSON
├── tests/
│   ├── demo_normal.py   ← нормальный flow
│   └── demo_tamper.py   ← симуляция атак
├── _keys/               ← .gitignore — приватный ключ хранится в vault
└── dist/                ← .gitignore — лицензии и зашифрованные ассеты
```

## Quick start

```bash
make keys      # 1. сгенерировать RSA-пару, вписать pubkey в .pyx
make build     # 2. скомпилировать .pyx → .so
make license   # 3. выпустить лицензию для текущей машины
make assets    # 4. зашифровать excella.png + excella.json под лицензию
make demo      # 5. прогнать normal flow
make tamper    # 6. показать что атаки отбиваются
```

## API kernel'а (что вызывает основной pipeline)

```python
from brand_kernel import (
    load_license,           # лицензию проверяем на старте приложения
    load_brand_template,    # вместо чтения excella.json
    load_asset_bytes,       # вместо открытия excella.png
    watermark_payload,      # 16 байт для встраивания в render
    get_machine_fp,         # для клиента — узнать свой fp
)

# при старте:
lic = load_license("license.json", "license.sig")  # → LicenseError если что-то не так

# при рендере клипа:
template = load_brand_template("assets/excella.json.enc", lic)  # → dict
logo_bio = load_asset_bytes("assets/excella.png.enc", lic)      # → BytesIO для ffmpeg
wm = watermark_payload(lic)                                      # → 16 bytes для DCT
```

В `src/branding.py` основного проекта прямые `open(json)`, `Path(png)` и хардкод
заменяются на эти 4 вызова.

## Что отбивает PoC

| Атака | Защита |
|---|---|
| Правка `excella.json` блокнотом | Зашифрован AES-256-GCM, ключ нельзя достать без kernel |
| Замена `excella.png` своим логотипом | AES-GCM tag не сходится при расшифровке |
| Правка `customer` или `tier` в license.json | RSA-PSS подпись не сходится |
| Фабрикация фейковой лицензии | Без приватного ключа подпись не подделать |
| Копирование лицензии на другую машину | machine_fp в подписанной лицензии не совпадёт |
| Видимый watermark убрали обрезкой | Stenographic payload в DCT-коэффициентах остаётся (см. TODO) |
| Правка `src/branding.py` | TODO: kernel проверяет SHA-256 модуля перед рендером |

## Что НЕ закрывает PoC (для следующей фазы)

- **Online license check** — пинг сервера лицензий раз в N часов с HWID + revocation list. Сейчас offline only.
- **Реальное встраивание watermark** — есть только генерация payload (16 байт). Само DCT-встраивание в видеопоток ffmpeg-фильтром = отдельная задача.
- **Tamper-detection других модулей** — kernel должен проверять SHA-256 ключевых файлов `src/branding.py`, `src/render.py` перед каждым рендером.
- **Anti-debug / anti-LD_PRELOAD** — определить присутствие отладчика, отказать.
- **PyArmor для остального Python** — обфускация всего `src/`, не только бренд-кернеля.
- **Master secret obfuscation** — сейчас лежит одной константой. В проде XOR-маскировать рантайм-сборкой из 3-4 источников.

## Пределы защиты (честно)

Любая клиентская защита **может быть сломана** при достаточной мотивации
атакующего: декомпиляция Mach-O через Ghidra/Hopper, RE крипто-функций, dump
расшифрованных байт из памяти процесса.

Цель PoC — поднять стоимость взлома с «5 минут блокнотом» до «нужен реверс-инженер
и 1-2 недели работы». При цене лицензии < этого порога экономика пиратства не
сходится — клиенту дешевле купить.

Главная страховка вне kernel: **invisible watermark** в видео-выходе. Даже если
клиент полностью распаковал бинарь, рендеры **которые он уже сделал** содержат
license_id_hash. Найдём пиратскую копию в интернете → знаем кто слил.

## Что показал прогон

```
✓ .so собрался: 174 KB (vs 12 KB исходник .pyx)
✓ kernel_info() работает после компиляции
✓ нормальный flow: лицензия валидна, brand template и PNG расшифрованы в память
✓ watermark payload подписан HMAC, обратная проверка сходится
✓ 4/4 атаки отбиты (правка JSON, фабрикация лицензии, чтение enc-файлов, подмена ассетов)

проверка `strings ._kernel.so | grep`:
  master_secret bytes:  НЕ найден
  master_secret hex:    НЕ найден
  "excella":            НЕ найден
  "BEGIN PUBLIC KEY":   НЕ найден
```
