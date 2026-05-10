"""Клиентский скрипт первой регистрации.

Использование (после установки self-hosted):
    excella init
    → запрашивает email
    → берёт machine_fp через brand_kernel
    → POST на registration.excella.ru/register
    → сохраняет license + assets в ~/.excella/

В PoC указываем --server http://localhost:8001 (локальный dev).
"""
import argparse
import base64
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from brand_kernel import get_machine_fp  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--email", help="email для регистрации (если не задан — спросим)")
    p.add_argument("--server", default="https://registration.excella.ru",
                   help="URL registration сервера")
    p.add_argument("--out", default=str(Path.home() / ".excella"),
                   help="куда сохранять license + assets")
    args = p.parse_args()

    email = args.email or input("email для регистрации (бесплатно навсегда): ").strip()
    fp = get_machine_fp()
    print(f"[1/3] machine_fp:  {fp[:16]}…")
    print(f"[2/3] получаю лицензию с {args.server}…")

    payload = json.dumps({"email": email, "machine_fp": fp}).encode()
    req = urllib.request.Request(
        f"{args.server}/register",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.out)
    assets_dir = out_dir / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "license.json").write_bytes(base64.b64decode(data["license_json_b64"]))
    (out_dir / "license.sig").write_bytes(base64.b64decode(data["license_sig_b64"]))
    for name, b64 in data["assets"].items():
        (assets_dir / name).write_bytes(base64.b64decode(b64))

    print(f"[3/3] лицензия сохранена в {out_dir}")
    print(f"      license_id: {data['license_id']}")
    print(f"      note:       {data['note']}")
    print()
    print("готово. excella shorts-cutter готов к использованию.")


if __name__ == "__main__":
    main()
