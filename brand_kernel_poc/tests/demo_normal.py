"""Демо: нормальная работа brand_kernel изнутри pipeline.

Показывает:
1. Загрузку и валидацию лицензии (RSA-PSS, machine_fp, expires_at)
2. Расшифровку brand-template JSON и logo PNG в память
3. Получение watermark-payload для встраивания в видео
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from brand_kernel import (  # noqa: E402
    kernel_info, load_license,
    load_brand_template, load_asset_bytes,
    watermark_payload, verify_watermark_payload,
)


def main():
    print("=" * 60)
    print("brand_kernel PoC — normal flow")
    print("=" * 60, "\n")

    print("[1] kernel_info():", kernel_info())
    print()

    lic_path = ROOT / "dist" / "ACME_license.json"
    sig_path = ROOT / "dist" / "ACME_license.sig"
    print(f"[2] загружаем лицензию из {lic_path.name}…")
    lic = load_license(str(lic_path), str(sig_path))
    print(f"    {lic!r}")
    print(f"    expires: {lic.expires_at}, watermark_required={lic.watermark_required}")
    print()

    template_path = ROOT / "dist" / "ACME_assets" / "excella.json.enc"
    print(f"[3] расшифровываем brand template из {template_path.name}…")
    template = load_brand_template(str(template_path), lic)
    print(f"    name:       {template.get('name')}")
    print(f"    lead_url:   {template.get('lead_url')}")
    strip = template.get("bottom_strip") or {}
    print(f"    strip text: {strip.get('text')!r}")
    print()

    logo_path = ROOT / "dist" / "ACME_assets" / "excella.png.enc"
    print(f"[4] расшифровываем logo {logo_path.name} в BytesIO…")
    logo = load_asset_bytes(str(logo_path), lic)
    raw = logo.getvalue()
    print(f"    размер расшифрованного: {len(raw)} B")
    print(f"    первые байты:           {raw[:8].hex()}  (PNG sig: 89504e470d0a1a0a)")
    is_png = raw[:8] == b"\x89PNG\r\n\x1a\n"
    print(f"    валидный PNG?           {is_png}")
    print()

    print("[5] watermark payload (16 байт для DCT-встраивания в видео):")
    payload = watermark_payload(lic)
    print(f"    payload:    {payload.hex()}")
    decoded = verify_watermark_payload(payload)
    print(f"    обратная проверка HMAC: {decoded}")
    print()

    print("[6] симуляция: подделанный payload должен отвергнуться")
    fake = bytearray(payload)
    fake[15] ^= 0x01
    decoded_fake = verify_watermark_payload(bytes(fake))
    print(f"    {decoded_fake}  (ожидаем None)")
    print()

    print("✓ всё работает")


if __name__ == "__main__":
    main()
