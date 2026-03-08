from app.config import Settings


def test_server_url_http():
    s = Settings(domain="example.com", frontend_url="http://localhost:3000", use_https=False)
    assert s.server_url == "http://example.com"


def test_server_url_https():
    s = Settings(domain="example.com", frontend_url="https://example.com")
    assert s.server_url == "https://example.com"


def test_default_values():
    """Settings accepts explicit values."""
    s = Settings(domain="localhost", frontend_url="http://localhost:3000", debug=True)
    assert s.domain == "localhost"
    assert s.debug is True


def test_registration_open_flag():
    s = Settings(registration_open=True)
    assert s.registration_open is True
