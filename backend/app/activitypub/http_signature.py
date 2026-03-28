import base64
import functools
import hashlib
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


# C-4: パース済みRSA鍵をキャッシュしてCPU負荷を削減
@functools.lru_cache(maxsize=256)
def _parse_private_key(pem: str):
    return serialization.load_pem_private_key(pem.encode(), password=None)


@functools.lru_cache(maxsize=1024)
def _parse_public_key(pem: str):
    return serialization.load_pem_public_key(pem.encode())


def sign_request(
    private_key_pem: str,
    key_id: str,
    method: str,
    url: str,
    body: bytes | None = None,
) -> dict[str, str]:
    """ActivityPub 配送用に HTTP リクエストに署名する。"""
    parsed = urlparse(url)
    path = parsed.path
    if parsed.query:
        path += f"?{parsed.query}"
    host = parsed.hostname

    date = format_datetime(datetime.now(timezone.utc), usegmt=True)

    headers_to_sign = ["(request-target)", "host", "date"]
    signed_parts = [
        f"(request-target): {method.lower()} {path}",
        f"host: {host}",
        f"date: {date}",
    ]

    result_headers = {
        "Host": host,
        "Date": date,
    }

    if body is not None:
        digest_value = hashlib.sha256(body).digest()
        digest = f"SHA-256={base64.b64encode(digest_value).decode()}"
        headers_to_sign.append("digest")
        signed_parts.append(f"digest: {digest}")
        result_headers["Digest"] = digest

    signed_string = "\n".join(signed_parts)

    private_key = _parse_private_key(private_key_pem)
    signature = private_key.sign(
        signed_string.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )

    signature_b64 = base64.b64encode(signature).decode()
    headers_str = " ".join(headers_to_sign)
    sig_header = (
        f'keyId="{key_id}",'
        f'algorithm="rsa-sha256",'
        f'headers="{headers_str}",'
        f'signature="{signature_b64}"'
    )
    result_headers["Signature"] = sig_header

    return result_headers


def parse_signature_header(sig_header: str) -> dict[str, str]:
    """HTTP Signature ヘッダーをコンポーネントにパースする。"""
    params = {}
    for part in sig_header.split(","):
        part = part.strip()
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"')
        params[key] = value
    return params


def verify_signature(
    public_key_pem: str,
    signature_header: str,
    method: str,
    path: str,
    headers: dict[str, str],
) -> bool:
    """公開鍵に対して HTTP Signature を検証する。"""
    params = parse_signature_header(signature_header)

    if "signature" not in params or "headers" not in params or "keyId" not in params:
        return False

    # Date ヘッダーの鮮度チェック (Mastodon と同じく 12 時間のズレを許容)
    if "date" in headers:
        try:
            request_date = parsedate_to_datetime(headers["date"])
            now = datetime.now(timezone.utc)
            if abs((now - request_date).total_seconds()) > 43200:
                return False
        except Exception:
            return False

    # 署名文字列を再構成
    signed_headers = params["headers"].split()
    signed_parts = []
    for h in signed_headers:
        if h == "(request-target)":
            signed_parts.append(f"(request-target): {method.lower()} {path}")
        else:
            header_value = headers.get(h.lower(), "")
            signed_parts.append(f"{h}: {header_value}")

    signed_string = "\n".join(signed_parts)

    try:
        public_key = _parse_public_key(public_key_pem)
        public_key.verify(
            base64.b64decode(params["signature"]),
            signed_string.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except Exception:
        return False
