from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

# FEP-521a Multikey の Ed25519 multicodec プレフィックス (varint: 0xED 0x01)
_ED25519_MULTICODEC_PREFIX = b"\xed\x01"

# Bitcoin base58 alphabet (FEP-521a の base58btc に対応)
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def generate_rsa_keypair() -> tuple[str, str]:
    """RSA 鍵ペアを生成し、(private_pem, public_pem) を文字列として返す。"""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )

    return private_pem, public_pem


def _base58btc_encode(data: bytes) -> str:
    """base58btc エンコード (Bitcoin alphabet 固定)。leading zero は '1' で表現。"""
    n = int.from_bytes(data, "big")
    out = ""
    while n > 0:
        n, r = divmod(n, 58)
        out = _BASE58_ALPHABET[r] + out
    for byte in data:
        if byte == 0:
            out = _BASE58_ALPHABET[0] + out
        else:
            break
    return out


def _base58btc_decode(text: str) -> bytes:
    """base58btc デコード。不正な文字は ValueError。"""
    n = 0
    for ch in text:
        idx = _BASE58_ALPHABET.find(ch)
        if idx < 0:
            raise ValueError(f"invalid base58btc character: {ch!r}")
        n = n * 58 + idx
    # 数値部分を big-endian に
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n > 0 else b""
    # leading '1' を 0x00 byte に戻す
    leading_zeros = 0
    for ch in text:
        if ch == _BASE58_ALPHABET[0]:
            leading_zeros += 1
        else:
            break
    return b"\x00" * leading_zeros + body


def generate_ed25519_keypair() -> tuple[str, str]:
    """Ed25519 鍵ペアを生成し、(private_pem_pkcs8, public_multibase) を返す。

    public_multibase は FEP-521a Multikey 仕様の `z` プレフィックス + base58btc
    エンコード形式 (例: `z6Mk...`)。multicodec varint `0xED 0x01` を含む。
    """
    private_key = ed25519.Ed25519PrivateKey.generate()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    raw_public = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_multibase = "z" + _base58btc_encode(_ED25519_MULTICODEC_PREFIX + raw_public)

    return private_pem, public_multibase


def ed25519_multibase_to_public_bytes(multibase: str) -> bytes:
    """Multikey 形式 (`z6Mk...`) から Ed25519 公開鍵 32 byte を抽出する。

    `z` 以外のプレフィックスや multicodec 不一致は ValueError。
    """
    if not multibase.startswith("z"):
        raise ValueError("Multikey must start with 'z' (base58btc)")
    decoded = _base58btc_decode(multibase[1:])
    if not decoded.startswith(_ED25519_MULTICODEC_PREFIX):
        raise ValueError("Multikey does not have Ed25519 multicodec prefix (0xED 0x01)")
    raw = decoded[len(_ED25519_MULTICODEC_PREFIX) :]
    if len(raw) != 32:
        raise ValueError(f"Ed25519 public key must be 32 bytes, got {len(raw)}")
    return raw
