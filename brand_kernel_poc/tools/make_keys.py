"""Генерация RSA-2048 пары для подписи лицензий.

Запускается ОДИН раз при настройке релиз-инфраструктуры.

Приватный ключ (private_key.pem):
    - НИКОГДА не коммитить
    - Хранить в vault / в зашифрованном виде на CI
    - Ротация раз в год + revocation list

Публичный ключ (public_key.pem):
    - Вставляется в brand_kernel/_kernel.pyx в _PUBLIC_KEY_PEM
    - Перекомпиляция .so после смены ключа
"""
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


KEYS_DIR = Path(__file__).resolve().parent.parent / "_keys"
KEYS_DIR.mkdir(exist_ok=True)

private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
public_key = private_key.public_key()

priv_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)
pub_pem = public_key.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)

priv_path = KEYS_DIR / "private_key.pem"
pub_path = KEYS_DIR / "public_key.pem"
priv_path.write_bytes(priv_pem)
pub_path.write_bytes(pub_pem)

# вставляем публичный ключ в _kernel.pyx
pyx_path = Path(__file__).resolve().parent.parent / "brand_kernel" / "_kernel.pyx"
src = pyx_path.read_text()
import re
new_src = re.sub(
    rb"_PUBLIC_KEY_PEM = b\"\"\".*?-----END PUBLIC KEY-----\"\"\"",
    b"_PUBLIC_KEY_PEM = b\"\"\"" + pub_pem.rstrip() + b"\"\"\"",
    src.encode(),
    count=1,
    flags=re.DOTALL,
).decode()
pyx_path.write_text(new_src)

print(f"✓ приватный ключ: {priv_path}  (НЕ КОММИТИТЬ!)")
print(f"✓ публичный ключ: {pub_path}")
print(f"✓ публичный ключ вписан в {pyx_path.relative_to(pyx_path.parent.parent)}")
print()
print("теперь собери модуль:")
print("    python setup.py build_ext --inplace")
