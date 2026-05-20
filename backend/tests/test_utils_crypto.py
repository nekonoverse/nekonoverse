import pytest

from app.utils.crypto import (
    _base58btc_decode,
    _base58btc_encode,
    ed25519_multibase_to_public_bytes,
    generate_ed25519_keypair,
    generate_rsa_keypair,
)


@pytest.fixture(scope="module")
def rsa_keypair():
    """Generate a single RSA keypair shared across tests to avoid entropy exhaustion in CI."""
    return generate_rsa_keypair()


def test_returns_tuple_of_strings(rsa_keypair):
    private_pem, public_pem = rsa_keypair
    assert isinstance(private_pem, str)
    assert isinstance(public_pem, str)


def test_private_key_pem_markers(rsa_keypair):
    private_pem, _ = rsa_keypair
    assert "-----BEGIN PRIVATE KEY-----" in private_pem
    assert "-----END PRIVATE KEY-----" in private_pem


def test_public_key_pem_markers(rsa_keypair):
    _, public_pem = rsa_keypair
    assert "-----BEGIN PUBLIC KEY-----" in public_pem
    assert "-----END PUBLIC KEY-----" in public_pem


def test_each_call_generates_unique_keys():
    pair1 = generate_rsa_keypair()
    pair2 = generate_rsa_keypair()
    assert pair1[0] != pair2[0]
    assert pair1[1] != pair2[1]


# ── Ed25519 / Multikey (FEP-521a) ────────────────────────────────────────


def test_base58btc_roundtrip():
    for sample in (b"", b"\x00", b"\x00\x00\xff", b"hello", bytes(range(32))):
        assert _base58btc_decode(_base58btc_encode(sample)) == sample


def test_ed25519_keypair_returns_pem_and_multibase():
    private_pem, public_multibase = generate_ed25519_keypair()
    assert isinstance(private_pem, str)
    assert isinstance(public_multibase, str)
    assert "-----BEGIN PRIVATE KEY-----" in private_pem
    # FEP-521a Multikey: 'z' + base58btc(0xED 0x01 + 32 raw bytes) → 'z6Mk...'
    assert public_multibase.startswith("z6Mk")


def test_ed25519_each_call_unique():
    p1 = generate_ed25519_keypair()
    p2 = generate_ed25519_keypair()
    assert p1[0] != p2[0]
    assert p1[1] != p2[1]


def test_ed25519_multibase_to_public_bytes_roundtrip():
    _, multibase = generate_ed25519_keypair()
    raw = ed25519_multibase_to_public_bytes(multibase)
    assert len(raw) == 32


def test_ed25519_multibase_rejects_wrong_prefix():
    # 'z' で始まらない
    with pytest.raises(ValueError, match="must start with 'z'"):
        ed25519_multibase_to_public_bytes("notmultibase")


def test_ed25519_multibase_rejects_wrong_multicodec():
    # base58btc decode 後の multicodec が 0xED 0x01 ではない
    # 例: secp256k1 multicodec (0xE7 0x01) を模した不正な値
    bogus = "z" + _base58btc_encode(b"\xe7\x01" + b"\x00" * 33)
    with pytest.raises(ValueError, match="multicodec"):
        ed25519_multibase_to_public_bytes(bogus)


def test_ed25519_multibase_rejects_invalid_base58_char():
    # base58btc アルファベット外の '0' を含む
    with pytest.raises(ValueError, match="base58btc"):
        ed25519_multibase_to_public_bytes("z6Mk0invalid")
