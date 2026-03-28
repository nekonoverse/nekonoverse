import base64
import hashlib
import secrets
import string

import bcrypt as _bcrypt
import pyotp
from cryptography.fernet import Fernet

from app.config import settings


def _get_fernet() -> Fernet:
    # PBKDF2で鍵を導出 (ソルトは固定だが、SECRET_KEYから安全に鍵を導出する)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        settings.secret_key.encode(),
        b"nekonoverse-totp-encryption",
        iterations=600_000,
    )
    key = base64.urlsafe_b64encode(dk)
    return Fernet(key)


def _get_legacy_fernet() -> Fernet:
    """移行用のレガシー鍵導出 (SHA-256直接導出)。"""
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())
    return Fernet(key)


def encrypt_secret(secret: str) -> str:
    return _get_fernet().encrypt(secret.encode()).decode()


def decrypt_secret(encrypted: str) -> str:
    try:
        return _get_fernet().decrypt(encrypted.encode()).decode()
    except Exception:
        # レガシー鍵導出でのフォールバック
        return _get_legacy_fernet().decrypt(encrypted.encode()).decode()


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def generate_provisioning_uri(
    secret: str,
    username: str,
    issuer: str | None = None,
) -> str:
    if issuer is None:
        issuer = f"Nekonoverse ({settings.domain})"
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name=issuer)


def verify_totp_code(secret: str, code: str) -> bool:
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def generate_recovery_codes(count: int = 8) -> list[str]:
    alphabet = string.ascii_lowercase + string.digits
    codes: list[str] = []
    for _ in range(count):
        part1 = "".join(secrets.choice(alphabet) for _ in range(5))
        part2 = "".join(secrets.choice(alphabet) for _ in range(5))
        codes.append(f"{part1}-{part2}")
    return codes


def hash_recovery_codes(codes: list[str]) -> list[str]:
    hashed: list[str] = []
    for code in codes:
        h = _bcrypt.hashpw(code.encode(), _bcrypt.gensalt())
        hashed.append(h.decode())
    return hashed


def verify_recovery_code(
    code: str,
    hashed_codes: list[str],
) -> tuple[bool, list[str]]:
    # M-2: タイミング攻撃対策 -- 全コードに対してbcrypt照合を実行
    matched_index: int | None = None
    for i, hashed in enumerate(hashed_codes):
        if _bcrypt.checkpw(code.encode(), hashed.encode()):
            if matched_index is None:
                matched_index = i
    if matched_index is not None:
        remaining = hashed_codes[:matched_index] + hashed_codes[matched_index + 1 :]
        return True, remaining
    return False, hashed_codes
