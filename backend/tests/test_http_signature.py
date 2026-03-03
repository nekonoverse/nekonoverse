import json
from datetime import datetime, timezone
from email.utils import format_datetime

from app.activitypub.http_signature import parse_signature_header, sign_request, verify_signature
from app.utils.crypto import generate_rsa_keypair


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
    sig = 'keyId="https://example.com/k",algorithm="rsa-sha256",headers="(request-target) host date",signature="abc123"'
    parsed = parse_signature_header(sig)
    assert parsed["keyId"] == "https://example.com/k"
    assert parsed["algorithm"] == "rsa-sha256"
    assert parsed["signature"] == "abc123"


def test_sign_and_verify_roundtrip():
    priv, pub = generate_rsa_keypair()
    body = b'{"type":"Follow"}'
    headers = sign_request(priv, "https://local.example/users/alice#main-key", "POST", "https://remote.example/inbox", body=body)
    verify_headers = {k.lower(): v for k, v in headers.items()}
    assert verify_signature(pub, headers["Signature"], "POST", "/inbox", verify_headers) is True


def test_verify_fails_with_wrong_key():
    priv, _ = generate_rsa_keypair()
    _, wrong_pub = generate_rsa_keypair()
    headers = sign_request(priv, "key-id", "POST", "https://remote.example/inbox")
    verify_headers = {k.lower(): v for k, v in headers.items()}
    assert verify_signature(wrong_pub, headers["Signature"], "POST", "/inbox", verify_headers) is False


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
    assert verify_signature(pub, headers["Signature"], "GET", "/outbox?page=true", verify_headers) is True
