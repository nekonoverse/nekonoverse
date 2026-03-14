import pytest

from app.utils.crypto import generate_rsa_keypair


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
