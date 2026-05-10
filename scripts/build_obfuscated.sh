#!/usr/bin/env bash
# scripts/build_obfuscated.sh — PyArmor обфускация src/ для release-сборки.
#
# ЭТО ОТДЕЛЬНАЯ ОТ brand_kernel мера защиты:
#   - brand_kernel.so содержит ключевые секреты (master_secret, RSA pub key).
#   - PyArmor обфусцирует ОСТАЛЬНОЙ Python-код: pipeline.py, render.py,
#     branding.py wrapper'ы и т.д. → клиент не видит исходник в plain text.
#
# Что делает:
#   1. Запускает `pyarmor gen --recursive src/` → генерит dist/
#   2. Заменяет src/ обфусцированным dist/src/
#   3. Копирует pyarmor_runtime/ рядом (нужна .so/.pyd для расшифровки)
#
# Использование (только в release-CI, НЕ в dev):
#   bash scripts/build_obfuscated.sh
#
# Платформы:
#   PyArmor runtime платформо-специфичный (darwin.arm64, linux.x86_64,
#   windows.x86_64). CI matrix должна вызывать этот скрипт под нужную ОС.

set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYARMOR="${ROOT}/.venv/bin/pyarmor"
SRC="${ROOT}/src"
OUT="${ROOT}/build/obfuscated"

if ! command -v "$PYARMOR" >/dev/null 2>&1; then
    if ! command -v pyarmor >/dev/null 2>&1; then
        echo "ERROR: pyarmor не установлен. pip install pyarmor"
        exit 1
    fi
    PYARMOR=pyarmor
fi

echo "[*] обфусцирую $SRC → $OUT"
rm -rf "$OUT"
mkdir -p "$OUT"

# Генерация обфусцированной версии. --recursive обходит подпапки.
# --restrict 0 разрешает импорт обфусцированных модулей друг из друга
# (нужно для src/ где много локальных импортов).
"$PYARMOR" gen \
    --output "$OUT" \
    --recursive \
    --restrict 0 \
    "$SRC"

echo "[✓] готово"
echo
echo "Обфусцированный src/ + runtime — в $OUT"
echo "Структура:"
find "$OUT" -maxdepth 2 -type d | head -10
echo
echo "Для использования: подменить ROOT/src/ на $OUT/src/"
echo "и поместить $OUT/pyarmor_runtime_*/ рядом с src/."
