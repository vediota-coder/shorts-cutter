"""Smoke-test подключения к ElevenLabs: проверяет ключ, баланс, доступ к Dubbing API.

Запуск:
    .venv/bin/python scripts/check_elevenlabs.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).parent.parent / ".env")

API = "https://api.elevenlabs.io/v1"


def get(path: str, key: str) -> tuple[int, dict | str]:
    req = urllib.request.Request(
        f"{API}{path}",
        headers={"xi-api-key": key, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        return e.code, body


def main() -> int:
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        print("❌ ELEVENLABS_API_KEY не задан в .env")
        return 1
    print(f"🔑 ключ найден ({key[:8]}...{key[-4:]})")

    code, data = get("/user", key)
    if code != 200:
        print(f"❌ /user → HTTP {code}: {data}")
        return 1
    sub = data.get("subscription", {}) if isinstance(data, dict) else {}
    tier = sub.get("tier", "?")
    used = sub.get("character_count", 0)
    cap = sub.get("character_limit", 0)
    print(f"✅ авторизация ок · план: {tier} · использовано: {used}/{cap} симв")

    code, data = get("/models", key)
    if code == 200 and isinstance(data, list):
        ids = [m.get("model_id") for m in data]
        v3 = "eleven_v3" in ids
        print(f"📦 моделей доступно: {len(ids)} · eleven_v3: {'✅' if v3 else '❌'}")
    else:
        print(f"⚠ /models → HTTP {code}")

    # Dubbing требует Pro+ — пробуем GET несуществующий job, по коду понимаем доступ
    code, data = get("/dubbing/_probe_nonexistent_", key)
    if code in (404, 422):
        print("✅ Dubbing API доступен (clone-режим работает)")
    elif code in (401, 403):
        print(f"⚠ Dubbing API недоступен на текущем плане ({tier}) — нужен Pro+. "
              f"Library-режим всё равно работает.")
    else:
        print(f"? Dubbing probe → HTTP {code}: {str(data)[:120]}")

    print("\nГотово. Можно запускать pipeline с --voiceover.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
