from app.utils.crypto import generate_rsa_keypair


def test_returns_tuple_of_strings():
    private_pem, public_pem = generate_rsa_keypair()
    assert isinstance(private_pem, str)
    assert isinstance(public_pem, str)


def test_private_key_pem_markers():
    private_pem, _ = generate_rsa_keypair()
    assert "-----BEGIN PRIVATE KEY-----" in private_pem
    assert "-----END PRIVATE KEY-----" in private_pem


def test_public_key_pem_markers():
    _, public_pem = generate_rsa_keypair()
    assert "-----BEGIN PUBLIC KEY-----" in public_pem
    assert "-----END PUBLIC KEY-----" in public_pem


def test_each_call_generates_unique_keys():
    pair1 = generate_rsa_keypair()
    pair2 = generate_rsa_keypair()
    assert pair1[0] != pair2[0]
    assert pair1[1] != pair2[1]
