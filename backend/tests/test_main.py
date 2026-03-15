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


async def test_instance_contact_account(app_client, db, mock_valkey):
    """contact.account returns admin Account object for Mastodon client compat."""
    from app.services.user_service import create_user

    await create_user(db, "adminuser", "admin@example.com", "password1234", role="admin")
    await db.commit()

    resp = await app_client.get("/api/v1/instance")
    data = resp.json()
    contact = data["contact"]
    assert contact["account"] is not None
    account = contact["account"]
    assert account["username"] == "adminuser"
    assert "id" in account
    assert "acct" in account
    assert "display_name" in account
    assert "avatar" in account
    assert "url" in account
    assert "created_at" in account
    assert "followers_count" in account
    assert "emojis" in account
    # CredentialAccount compat: account.email must exist (empty for public API)
    assert "email" in account
    assert account["email"] == ""
    assert contact["email"] == "admin@example.com"
    # v1 compat: email and contact_account at root level
    assert data["email"] == "admin@example.com"
    assert data["contact_account"] is not None
    assert data["contact_account"]["username"] == "adminuser"


async def test_instance_v2(app_client):
    """GET /api/v2/instance returns v2 response structure."""
    resp = await app_client.get("/api/v2/instance")
    assert resp.status_code == 200
    data = resp.json()

    # v2 uses "domain" instead of "uri"
    assert data["domain"] == "localhost"
    assert data["title"] == "Nekonoverse"
    assert isinstance(data["version"], str)
    assert isinstance(data["source_url"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["languages"], list)
    assert isinstance(data["rules"], list)
    assert isinstance(data["icon"], list)

    # usage replaces stats
    assert isinstance(data["usage"]["users"]["active_month"], int)

    # registrations is an object (not boolean)
    reg = data["registrations"]
    assert isinstance(reg, dict)
    assert isinstance(reg["enabled"], bool)
    assert isinstance(reg["approval_required"], bool)

    # configuration expanded
    config = data["configuration"]
    assert "streaming" in config["urls"]
    assert isinstance(config["statuses"]["max_characters"], int)
    assert isinstance(config["accounts"]["max_pinned_statuses"], int)
    assert isinstance(config["translation"]["enabled"], bool)

    # api_versions
    assert data["api_versions"]["mastodon"] == 2

    # contact is nested object
    assert isinstance(data["contact"]["email"], str)


async def test_instance_v2_contact_account(app_client, db, mock_valkey):
    """v2 instance contact.account returns admin Account object."""
    from app.services.user_service import create_user

    await create_user(db, "v2admin", "v2admin@example.com", "password1234", role="admin")
    await db.commit()

    resp = await app_client.get("/api/v2/instance")
    data = resp.json()
    assert data["contact"]["account"] is not None
    assert data["contact"]["account"]["username"] == "v2admin"
