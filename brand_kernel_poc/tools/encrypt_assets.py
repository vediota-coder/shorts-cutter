"""Шифруем ассеты бренда под конкретного клиента.

Использование (после make_license):
    python tools/encrypt_assets.py \\
        --license dist/ACME_license.json \\
        --asset ../branding/_assets/excella.png \\
        --asset ../branding/excella.json \\
        --out dist/ACME_assets/

Каждый входной файл становится `<basename>.enc` в --out директории.
Ключ AES-256 = HKDF(master_secret, salt=license_id || machine_fp).
"""
import argparse
import json
import sys
from pathlib import Path

# импорт прямо из бинарника
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from brand_kernel import encrypt_asset_for_license  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--license", required=True, help="путь к license.json")
    p.add_argument("--asset", action="append", required=True,
                   help="файл ассета; можно повторять")
    p.add_argument("--out", required=True, help="выходная директория")
    args = p.parse_args()

    license_data = json.loads(Path(args.license).read_bytes())
    license_id = license_data["license_id"]
    machine_fp = license_data["machine_fp"]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for asset_path_str in args.asset:
        asset_path = Path(asset_path_str)
        plaintext = asset_path.read_bytes()
        ciphertext = encrypt_asset_for_license(plaintext, license_id, machine_fp)
        out_path = out_dir / (asset_path.name + ".enc")
        out_path.write_bytes(ciphertext)
        print(f"✓ {asset_path.name} ({len(plaintext)} B) → {out_path} ({len(ciphertext)} B)")


if __name__ == "__main__":
    main()
