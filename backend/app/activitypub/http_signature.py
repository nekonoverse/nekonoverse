import base64
import functools
import hashlib
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

from app.utils.crypto import ed25519_multibase_to_public_bytes


# C-4: パース済み鍵をキャッシュして CPU 負荷を削減。
# Ed25519 PEM も load_pem_*_key で型が判別されて返るため、関数自体は単一。
@functools.lru_cache(maxsize=256)
def _parse_private_key(pem: str):
    return serialization.load_pem_private_key(pem.encode(), password=None)


@functools.lru_cache(maxsize=1024)
def _parse_public_key(pem: str):
    return serialization.load_pem_public_key(pem.encode())


@functools.lru_cache(maxsize=1024)
def _parse_public_key_multibase(multibase: str) -> ed25519.Ed25519PublicKey:
    """FEP-521a Multikey (`z6Mk...`) を Ed25519PublicKey に復元する。"""
    raw = ed25519_multibase_to_public_bytes(multibase)
    return ed25519.Ed25519PublicKey.from_public_bytes(raw)


def sign_request(
    private_key_pem: str,
    key_id: str,
    method: str,
    url: str,
    body: bytes | None = None,
    algorithm: str = "rsa-sha256",
) -> dict[str, str]:
    """ActivityPub 配送用に HTTP リクエストに署名する。

    algorithm:
      - "rsa-sha256" (デフォルト, cavage 互換): PKCS1v15 + SHA-256
      - "ed25519": Ed25519 (内部で SHA-512、ハッシュ前計算不要)
    """
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
    if algorithm == "rsa-sha256":
        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise TypeError("algorithm='rsa-sha256' requires an RSA private key")
        signature = private_key.sign(
            signed_string.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    elif algorithm == "ed25519":
        if not isinstance(private_key, ed25519.Ed25519PrivateKey):
            raise TypeError("algorithm='ed25519' requires an Ed25519 private key")
        # Ed25519 はハッシュ前計算しない (内部で SHA-512)
        signature = private_key.sign(signed_string.encode("utf-8"))
    else:
        raise ValueError(f"unsupported algorithm: {algorithm!r}")

    signature_b64 = base64.b64encode(signature).decode()
    headers_str = " ".join(headers_to_sign)
    sig_header = (
        f'keyId="{key_id}",'
        f'algorithm="{algorithm}",'
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
    public_key_material: str,
    signature_header: str,
    method: str,
    path: str,
    headers: dict[str, str],
    algorithm_hint: str | None = None,
) -> bool:
    """公開鍵に対して HTTP Signature を検証する。

    public_key_material:
      - RSA PEM 文字列 ("-----BEGIN PUBLIC KEY-----" で始まる)、または
      - Ed25519 Multikey (`z6Mk...`) のいずれか。

    algorithm_hint:
      - signature header の algorithm パラメータが `hs2019` や空の場合に、
        どちらのアルゴリズムでパースするかを呼び出し側が指定する。
        通常は鍵種別から自動判別する。
    """
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

    # 鍵種別の自動判別 (algorithm hint が無ければ public_key_material から推定)
    is_multibase = public_key_material.startswith("z")

    # algorithm パラメータの解釈:
    #   - "ed25519" → Ed25519 強制
    #   - "rsa-sha256" or 空 → RSA
    #   - "hs2019" → algorithm_hint or 鍵種別から決定
    declared = (params.get("algorithm") or "").lower()
    if declared == "ed25519":
        algo = "ed25519"
    elif declared == "rsa-sha256":
        algo = "rsa-sha256"
    elif declared in ("hs2019", ""):
        # algorithm 不在 / hs2019 はどちらも曖昧。algorithm_hint を尊重しつつ、
        # なければ鍵種別から推定。Ed25519 鍵保有相手が空 algorithm を送ってきても
        # 取りこぼさない。
        algo = algorithm_hint or ("ed25519" if is_multibase else "rsa-sha256")
    else:
        return False

    # 鍵種別と algorithm の整合性を確認 (取り違えで誤受理しないよう厳格に)
    if algo == "ed25519" and not is_multibase:
        return False
    if algo == "rsa-sha256" and is_multibase:
        return False

    try:
        signature_bytes = base64.b64decode(params["signature"])
        if algo == "rsa-sha256":
            public_key = _parse_public_key(public_key_material)
            public_key.verify(
                signature_bytes,
                signed_string.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        else:
            ed_key = _parse_public_key_multibase(public_key_material)
            ed_key.verify(signature_bytes, signed_string.encode("utf-8"))
        return True
    except Exception:
        return False
