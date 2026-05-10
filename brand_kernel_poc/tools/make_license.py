"""Генерация лицензии для конкретного клиента.

Использование:
    python tools/make_license.py \\
        --customer "ACME Corp" \\
        --machine-fp 7f1e3a4b... \\
        --tier standard --days 365 \\
        --out dist/ACME_license

Создаёт два файла:
    dist/ACME_license.json   — JSON с полями
    dist/ACME_license.sig    — RSA-PSS подпись JSON

Клиент кладёт оба файла рядом с brand_kernel и стартует приложение.
"""
import argparse
import json
import time
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as rsa_padding


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    p.add_argument("--machine-fp", required=True, help="hex от get_machine_fp.py клиента")
    p.add_argument("--tier", default="standard",
                   choices=["standard", "unlimited", "white-label"])
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--out", required=True, help="префикс выходных файлов (без расширения)")
    p.add_argument("--private-key", default="_keys/private_key.pem")
    args = p.parse_args()

    now = int(time.time())
    license_id = f"{args.customer.upper().replace(' ', '_')}-{now}"

    license_data = {
        "license_id": license_id,
        "customer": args.customer,
        "tier": args.tier,
        "machine_fp": args.machine_fp,
        "issued_at": now,
        "expires_at": now + args.days * 86400,
        "watermark_required": args.tier != "white-label",
        "features": ["render", "voiceover", "branding"],
    }
    license_bytes = json.dumps(license_data, indent=2, sort_keys=True).encode()

    pem = Path(args.private_key).read_bytes()
    private_key = serialization.load_pem_private_key(pem, password=None)
    signature = private_key.sign(
        license_bytes,
        rsa_padding.PSS(
            mgf=rsa_padding.MGF1(hashes.SHA256()),
            salt_length=rsa_padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_bytes(license_bytes)
    out.with_suffix(".sig").write_bytes(signature)

    print(f"✓ {out.with_suffix('.json')}")
    print(f"✓ {out.with_suffix('.sig')}")
    print(f"  license_id: {license_id}")
    print(f"  tier:       {args.tier}")
    print(f"  expires:    {time.ctime(license_data['expires_at'])}")


if __name__ == "__main__":
    main()
