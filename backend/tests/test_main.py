import pytest


async def test_health(app_client):
    resp = await app_client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_instance_info(app_client):
    resp = await app_client.get("/api/v1/instance")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Nekonoverse"
    assert data["uri"] == "localhost"
    assert "registrations" in data
    assert "version" in data


async def test_instance_info_registrations(app_client):
    """registration_open setting is reflected in instance info."""
    resp = await app_client.get("/api/v1/instance")
    data = resp.json()
    assert isinstance(data["registrations"], bool)
