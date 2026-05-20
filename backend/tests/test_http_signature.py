import json
import re
from datetime import datetime, timezone
from email.utils import format_datetime

from app.activitypub.http_signature import parse_signature_header, sign_request, verify_signature
from app.utils.crypto import generate_ed25519_keypair, generate_rsa_keypair


def test_sign_returns_required_headers():
    priv, _ = generate_rsa_keypair()
    headers = sign_request(priv, "key-id", "POST", "https://remote.example/inbox")
    assert "Host" in headers
    assert "Date" in headers
    assert "Signature" in headers


def test_sign_with_body_includes_digest():
    priv, _ = generate_rsa_keypair()
    body = json.dumps({"type": "Create"}).encode()
    headers = sign_request(priv, "key-id", "POST", "https://remote.example/inbox", body=body)
    assert "Digest" in headers
    assert headers["Digest"].startswith("SHA-256=")


def test_sign_without_body_no_digest():
    priv, _ = generate_rsa_keypair()
    headers = sign_request(priv, "key-id", "GET", "https://remote.example/users/alice")
    assert "Digest" not in headers


def test_parse_signature_header():
    sig = (
        'keyId="https://example.com/k",algorithm="rsa-sha256",'
        'headers="(request-target) host date",signature="abc123"'
    )
    parsed = parse_signature_header(sig)
    assert parsed["keyId"] == "https://example.com/k"
    assert parsed["algorithm"] == "rsa-sha256"
    assert parsed["signature"] == "abc123"


def test_sign_and_verify_roundtrip():
    priv, pub = generate_rsa_keypair()
    body = b'{"type":"Follow"}'
    headers = sign_request(
        priv,
        "https://local.example/users/alice#main-key",
        "POST",
        "https://remote.example/inbox",
        body=body,
    )
    verify_headers = {k.lower(): v for k, v in headers.items()}
    assert verify_signature(
        pub, headers["Signature"], "POST", "/inbox", verify_headers
    ) is True


def test_verify_fails_with_wrong_key():
    priv, _ = generate_rsa_keypair()
    _, wrong_pub = generate_rsa_keypair()
    headers = sign_request(priv, "key-id", "POST", "https://remote.example/inbox")
    verify_headers = {k.lower(): v for k, v in headers.items()}
    assert verify_signature(
        wrong_pub, headers["Signature"], "POST", "/inbox", verify_headers
    ) is False


def test_verify_fails_with_stale_date():
    priv, pub = generate_rsa_keypair()
    headers = sign_request(priv, "key-id", "POST", "https://remote.example/inbox")
    verify_headers = {k.lower(): v for k, v in headers.items()}
    old_date = format_datetime(datetime(2020, 1, 1, tzinfo=timezone.utc), usegmt=True)
    verify_headers["date"] = old_date
    assert verify_signature(pub, headers["Signature"], "POST", "/inbox", verify_headers) is False


def test_verify_missing_required_params():
    assert verify_signature("key", 'algorithm="rsa-sha256"', "POST", "/inbox", {}) is False


def test_sign_host_from_url():
    priv, _ = generate_rsa_keypair()
    headers = sign_request(priv, "key-id", "GET", "https://specific.host.example/users/alice")
    assert headers["Host"] == "specific.host.example"


def test_sign_and_verify_with_query_string():
    priv, pub = generate_rsa_keypair()
    headers = sign_request(priv, "key-id", "GET", "https://remote.example/outbox?page=true")
    verify_headers = {k.lower(): v for k, v in headers.items()}
    assert verify_signature(
        pub, headers["Signature"], "GET", "/outbox?page=true", verify_headers
    ) is True


# ── Ed25519 (FEP-521a Multikey) ────────────────────────────────────────────


def test_ed25519_sign_returns_required_headers():
    priv, _ = generate_ed25519_keypair()
    headers = sign_request(
        priv, "key-id", "POST", "https://remote.example/inbox", algorithm="ed25519"
    )
    assert "Host" in headers
    assert "Date" in headers
    assert "Signature" in headers
    # algorithm パラメータが 'ed25519' で出力されること
    assert 'algorithm="ed25519"' in headers["Signature"]


def test_ed25519_sign_and_verify_roundtrip():
    priv, pub_mb = generate_ed25519_keypair()
    body = b'{"type":"Follow"}'
    headers = sign_request(
        priv,
        "https://local.example/users/alice#ed25519-key",
        "POST",
        "https://remote.example/inbox",
        body=body,
        algorithm="ed25519",
    )
    verify_headers = {k.lower(): v for k, v in headers.items()}
    assert verify_signature(
        pub_mb, headers["Signature"], "POST", "/inbox", verify_headers
    ) is True


def test_ed25519_verify_fails_with_wrong_key():
    priv, _ = generate_ed25519_keypair()
    _, wrong_pub_mb = generate_ed25519_keypair()
    headers = sign_request(
        priv, "key-id", "POST", "https://remote.example/inbox", algorithm="ed25519"
    )
    verify_headers = {k.lower(): v for k, v in headers.items()}
    assert verify_signature(
        wrong_pub_mb, headers["Signature"], "POST", "/inbox", verify_headers
    ) is False


def test_cross_verify_rsa_sig_with_ed25519_key_rejected():
    """RSA で署名したものを Ed25519 公開鍵で検証 → algorithm 不整合で False。"""
    rsa_priv, _ = generate_rsa_keypair()
    _, ed_pub_mb = generate_ed25519_keypair()
    headers = sign_request(rsa_priv, "key-id", "POST", "https://remote.example/inbox")
    verify_headers = {k.lower(): v for k, v in headers.items()}
    assert verify_signature(
        ed_pub_mb, headers["Signature"], "POST", "/inbox", verify_headers
    ) is False


def test_cross_verify_ed25519_sig_with_rsa_key_rejected():
    """Ed25519 で署名したものを RSA 公開鍵 PEM で検証 → algorithm 不整合で False。"""
    ed_priv, _ = generate_ed25519_keypair()
    _, rsa_pub = generate_rsa_keypair()
    headers = sign_request(
        ed_priv, "key-id", "POST", "https://remote.example/inbox", algorithm="ed25519"
    )
    verify_headers = {k.lower(): v for k, v in headers.items()}
    assert verify_signature(
        rsa_pub, headers["Signature"], "POST", "/inbox", verify_headers
    ) is False


def test_hs2019_algorithm_dispatches_by_key_type():
    """algorithm='hs2019' (曖昧) を受け取った場合、公開鍵の種別から自動判別する。"""
    # Ed25519 鍵で sign したヘッダの algorithm を 'hs2019' に書き換えて受信側へ渡す
    ed_priv, ed_pub_mb = generate_ed25519_keypair()
    headers = sign_request(
        ed_priv, "key-id", "POST", "https://remote.example/inbox", algorithm="ed25519"
    )
    rewritten = headers["Signature"].replace('algorithm="ed25519"', 'algorithm="hs2019"')
    verify_headers = {k.lower(): v for k, v in headers.items()}
    verify_headers["signature"] = rewritten
    assert verify_signature(
        ed_pub_mb, rewritten, "POST", "/inbox", verify_headers
    ) is True


def test_empty_algorithm_with_ed25519_key_accepted():
    """algorithm パラメータが空の場合も algorithm_hint と鍵種別を尊重する。

    Ed25519 鍵保有相手が algorithm を省略してきても受理される (PR description の
    『受信: algorithm が空 を受理』を Ed25519 鍵保有相手でも成立させる)。
    """
    ed_priv, ed_pub_mb = generate_ed25519_keypair()
    headers = sign_request(
        ed_priv, "key-id", "POST", "https://remote.example/inbox", algorithm="ed25519"
    )
    # algorithm パラメータを除去 (空状態をシミュレート)
    stripped = re.sub(r',?algorithm="[^"]*"', "", headers["Signature"])
    verify_headers = {k.lower(): v for k, v in headers.items()}
    verify_headers["signature"] = stripped
    assert verify_signature(
        ed_pub_mb, stripped, "POST", "/inbox", verify_headers,
        algorithm_hint="ed25519",
    ) is True


def test_sign_rsa_algorithm_with_ed25519_key_raises():
    """algorithm='rsa-sha256' に Ed25519 秘密鍵を渡したら TypeError。"""
    import pytest

    ed_priv, _ = generate_ed25519_keypair()
    with pytest.raises(TypeError, match="requires an RSA"):
        sign_request(
            ed_priv,
            "key-id",
            "POST",
            "https://remote.example/inbox",
            algorithm="rsa-sha256",
        )


def test_sign_ed25519_algorithm_with_rsa_key_raises():
    """algorithm='ed25519' に RSA 秘密鍵を渡したら TypeError。"""
    import pytest

    rsa_priv, _ = generate_rsa_keypair()
    with pytest.raises(TypeError, match="requires an Ed25519"):
        sign_request(
            rsa_priv,
            "key-id",
            "POST",
            "https://remote.example/inbox",
            algorithm="ed25519",
        )
