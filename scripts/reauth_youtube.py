"""Перезапрашивает YouTube OAuth с актуальным набором scope.

Нужно после расширения SCOPES в src/publish/youtube.py — старый токен
работает только под старые scope, для videos.update требуется свежий
consent с включённым https://www.googleapis.com/auth/youtube.

Использование:
    python -m scripts.reauth_youtube                # бренд excella
    python -m scripts.reauth_youtube --brand other  # другой бренд
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.publish import youtube as yt  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", default="excella")
    args = ap.parse_args()

    yt.disconnect(args.brand)  # снести старый токен
    print(f"Открываю браузер для авторизации YouTube (бренд={args.brand})…")
    print(f"Scopes: {yt.SCOPES}")
    creds = yt.start_oauth(args.brand)
    print(f"OK, токен сохранён. valid={creds.valid}, scopes={list(creds.scopes or [])}")
    status = yt.get_status(args.brand)
    print(f"Канал: {status.channel_title} (id={status.channel_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
