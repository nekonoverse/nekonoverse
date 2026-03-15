"""Tests for legal pages (terms of service, privacy policy)."""

from app.services.server_settings_service import set_setting


async def test_terms_not_set(app_client, db, mock_valkey):
    resp = await app_client.get("/api/v1/instance/terms")
    assert resp.status_code == 200
    data = resp.json()
    assert data["content_html"] is None
    assert data["content_raw"] is None


async def test_terms_markdown_rendered(app_client, db, mock_valkey):
    await set_setting(db, "terms_of_service", "# Terms\n\nHello **world**.")
    await db.commit()

    resp = await app_client.get("/api/v1/instance/terms")
    assert resp.status_code == 200
    data = resp.json()
    assert "<h1>Terms</h1>" in data["content_html"]
    assert "<strong>world</strong>" in data["content_html"]
    assert data["content_raw"] == "# Terms\n\nHello **world**."


async def test_privacy_not_set(app_client, db, mock_valkey):
    resp = await app_client.get("/api/v1/instance/privacy")
    assert resp.status_code == 200
    data = resp.json()
    assert data["content_html"] is None


async def test_privacy_markdown_rendered(app_client, db, mock_valkey):
    await set_setting(db, "privacy_policy", "## Privacy\n\n- Item 1\n- Item 2")
    await db.commit()

    resp = await app_client.get("/api/v1/instance/privacy")
    assert resp.status_code == 200
    data = resp.json()
    assert "<h2>Privacy</h2>" in data["content_html"]
    assert "<li>Item 1</li>" in data["content_html"]


async def test_script_tag_not_rendered(app_client, db, mock_valkey):
    await set_setting(db, "terms_of_service", "Hello <script>alert(1)</script> world")
    await db.commit()

    resp = await app_client.get("/api/v1/instance/terms")
    data = resp.json()
    # Python markdown escapes raw HTML by default
    assert "<script>" not in data["content_html"]


async def test_instance_includes_tos_url(app_client, db, mock_valkey):
    await set_setting(db, "terms_of_service", "# Terms")
    await db.commit()

    resp = await app_client.get("/api/v1/instance")
    assert resp.status_code == 200
    data = resp.json()
    assert "tos_url" in data
    assert "/terms" in data["tos_url"]


async def test_instance_includes_privacy_url(app_client, db, mock_valkey):
    await set_setting(db, "privacy_policy", "# Privacy")
    await db.commit()

    resp = await app_client.get("/api/v1/instance")
    assert resp.status_code == 200
    data = resp.json()
    assert "privacy_policy_url" in data
    assert "/privacy" in data["privacy_policy_url"]


async def test_instance_falls_back_to_tos_url_setting(app_client, db, mock_valkey):
    await set_setting(db, "tos_url", "https://example.com/terms")
    await db.commit()

    resp = await app_client.get("/api/v1/instance")
    data = resp.json()
    assert data.get("tos_url") == "https://example.com/terms"
