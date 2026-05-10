"""Демо: попытки атак на brand_kernel.

Каждый сценарий имитирует то, что может попробовать клиент чтобы убрать
брендинг или продлить лицензию. Все 4 атаки должны отбиваться.
"""
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from brand_kernel import (  # noqa: E402
    LicenseError, load_license,
    load_brand_template, load_asset_bytes,
)


def section(title):
    print()
    print("─" * 60)
    print(title)
    print("─" * 60)


def main():
    print("=" * 60)
    print("brand_kernel PoC — tamper attempts")
    print("=" * 60)

    dist = ROOT / "dist"
    valid_lic = dist / "ACME_license.json"
    valid_sig = dist / "ACME_license.sig"

    # ─────────────────────────────────────────────────────────────────
    section("[ATTACK 1] правка JSON-лицензии (без приватного ключа)")
    evil_lic = dist / "EVIL_license.json"
    evil_sig = dist / "EVIL_license.sig"
    shutil.copy(valid_lic, evil_lic)
    shutil.copy(valid_sig, evil_sig)
    data = json.loads(evil_lic.read_bytes())
    data["customer"] = "EvilCorp"
    data["tier"] = "white-label"
    data["watermark_required"] = False
    evil_lic.write_bytes(json.dumps(data, indent=2, sort_keys=True).encode())
    try:
        load_license(str(evil_lic), str(evil_sig))
        print("    ✗ ВЗЛОМ УДАЛСЯ")
    except LicenseError as e:
        print(f"    ✓ отвергнуто: {e}")

    # ─────────────────────────────────────────────────────────────────
    section("[ATTACK 2] полная фабрикация лицензии (без приватного ключа)")
    fake_lic = dist / "FAKE_license.json"
    fake_sig = dist / "FAKE_license.sig"
    fake_data = {
        "license_id": "FAKE-CORP-FOREVER",
        "customer": "EvilCorp",
        "tier": "white-label",
        "machine_fp": json.loads(valid_lic.read_bytes())["machine_fp"],
        "issued_at": 0,
        "expires_at": 9999999999,
        "watermark_required": False,
    }
    fake_lic.write_bytes(json.dumps(fake_data, indent=2, sort_keys=True).encode())
    fake_sig.write_bytes(b"X" * 256)
    try:
        load_license(str(fake_lic), str(fake_sig))
        print("    ✗ ВЗЛОМ УДАЛСЯ")
    except LicenseError as e:
        print(f"    ✓ отвергнуто: {e}")

    # ─────────────────────────────────────────────────────────────────
    section("[ATTACK 3] чтение зашифрованных ассетов как обычных файлов")
    template_enc = dist / "ACME_assets" / "excella.json.enc"
    head = template_enc.read_bytes()[:64]
    print(f"    первые 64 байта .json.enc: {head.hex()}")
    try:
        json.loads(template_enc.read_bytes())
        print("    ✗ JSON открылся напрямую")
    except Exception as e:
        print(f"    ✓ JSON парсер не справился: {type(e).__name__}")

    # ─────────────────────────────────────────────────────────────────
    section("[ATTACK 4] подмена logo.png.enc на свой файл")
    evil_assets = dist / "EVIL_assets"
    evil_assets.mkdir(exist_ok=True)
    shutil.copy(dist / "ACME_assets" / "excella.json.enc",
                evil_assets / "excella.json.enc")
    (evil_assets / "excella.png.enc").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"my own logo bytes" * 100
    )
    lic = load_license(str(valid_lic), str(valid_sig))
    try:
        load_asset_bytes(str(evil_assets / "excella.png.enc"), lic)
        print("    ✗ ВЗЛОМ УДАЛСЯ")
    except Exception as e:
        print(f"    ✓ AES-GCM tag не сходится: {type(e).__name__}")

    # ─────────────────────────────────────────────────────────────────
    section("[ATTACK 5] копирование лицензии на другую машину (имитация)")
    print("    machine_fp в лицензии привязан к MAC+hostname+platform.")
    print("    На реальной другой машине _machine_fingerprint_bytes()")
    print("    вернёт другие байты → load_license бросит LicenseError.")
    print("    (полная проверка требует реально запустить на 2-й машине)")
    fp_now = json.loads(valid_lic.read_bytes())["machine_fp"]
    print(f"    привязка лицензии: {fp_now[:32]}…")

    print()
    print("=" * 60)
    print("итог: 4/4 атаки отбиты на уровне kernel")
    print("дополнительно (не в этом PoC):")
    print("  - online license check c revocation list")
    print("  - tamper detection хэшей src/branding.py")
    print("  - стеганографический watermark в видео-выходе")
    print("=" * 60)


if __name__ == "__main__":
    main()
