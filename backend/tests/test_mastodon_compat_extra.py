"""Tests for Mastodon-compatible stub/compat endpoints."""


# --- apps/verify_credentials ---


async def test_apps_verify_credentials(authed_client, app_client, mock_valkey):
    """POST /api/v1/apps + token exchange, then verify_credentials."""
    # Register an app
    app_resp = await app_client.post("/api/v1/apps", json={
        "client_name": "TestApp",
        "redirect_uris": "urn:ietf:wg:oauth:2.0:oob",
        "scopes": "read write",
    })
    assert app_resp.status_code == 200
    app_data = app_resp.json()
    assert "client_id" in app_data
    assert "client_secret" in app_data

    # Get client credentials token
    token_resp = await app_client.post("/oauth/token", data={
        "grant_type": "client_credentials",
        "client_id": app_data["client_id"],
        "client_secret": app_data["client_secret"],
        "scope": "read",
    })
    assert token_resp.status_code == 200
    token = token_resp.json()["access_token"]

    # Verify app credentials
    verify_resp = await app_client.get(
        "/api/v1/apps/verify_credentials",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert verify_resp.status_code == 200
    body = verify_resp.json()
    assert body["name"] == "TestApp"
    assert "scopes" in body


async def test_apps_verify_credentials_no_token(app_client, mock_valkey):
    """GET /api/v1/apps/verify_credentials without token returns 401."""
    resp = await app_client.get("/api/v1/apps/verify_credentials")
    assert resp.status_code == 401


# --- preferences ---


async def test_preferences(authed_client, mock_valkey):
    """GET /api/v1/preferences returns default preferences."""
    resp = await authed_client.get("/api/v1/preferences")
    assert resp.status_code == 200
    body = resp.json()
    assert "posting:default:visibility" in body
    assert "posting:default:sensitive" in body
    assert "reading:expand:media" in body


async def test_preferences_unauthenticated(app_client, mock_valkey):
    """GET /api/v1/preferences without auth returns 401."""
    resp = await app_client.get("/api/v1/preferences")
    assert resp.status_code == 401


async def test_preferences_includes_theme_customization(authed_client, mock_valkey):
    """GET /api/v1/preferences includes theme_customization (default null)."""
    resp = await authed_client.get("/api/v1/preferences")
    assert resp.status_code == 200
    assert resp.json()["theme_customization"] is None


_VALID_THEME = {
    "base": "dark",
    "colors": {
        "bg-primary": "#1a1a2e",
        "bg-secondary": "#16213e",
        "bg-card": "#0f3460",
        "text-primary": "#e0e0e0",
        "text-secondary": "#a0a0b0",
        "accent": "#e94560",
        "accent-hover": "#ff6b81",
        "accent-text": "#ffffff",
        "border": "#2a2a4a",
        "reblog": "#2ecc71",
        "favourite": "#f1c40f",
    },
    "name": "My Theme",
}


async def test_preferences_patch_theme_customization(authed_client, mock_valkey):
    """PATCH /api/v1/preferences sets theme_customization."""
    resp = await authed_client.patch(
        "/api/v1/preferences",
        json={"theme_customization": _VALID_THEME},
    )
    assert resp.status_code == 200
    tc = resp.json()["theme_customization"]
    assert tc["base"] == "dark"
    assert tc["colors"]["accent"] == "#e94560"
    assert tc["name"] == "My Theme"

    # Verify persistence via GET
    resp2 = await authed_client.get("/api/v1/preferences")
    assert resp2.json()["theme_customization"]["base"] == "dark"


async def test_preferences_patch_theme_customization_clear(authed_client, mock_valkey):
    """PATCH theme_customization with false clears it."""
    # Set first
    await authed_client.patch(
        "/api/v1/preferences",
        json={"theme_customization": _VALID_THEME},
    )
    # Clear
    resp = await authed_client.patch(
        "/api/v1/preferences",
        json={"theme_customization": False},
    )
    assert resp.status_code == 200
    assert resp.json()["theme_customization"] is None


async def test_preferences_patch_theme_invalid_base(authed_client, mock_valkey):
    """PATCH theme_customization with invalid base returns 422."""
    bad = {**_VALID_THEME, "base": "neon"}
    resp = await authed_client.patch(
        "/api/v1/preferences",
        json={"theme_customization": bad},
    )
    assert resp.status_code == 422


async def test_preferences_patch_theme_invalid_color(authed_client, mock_valkey):
    """PATCH theme_customization with non-hex color returns 422."""
    bad_colors = {**_VALID_THEME["colors"], "accent": "red"}
    bad = {**_VALID_THEME, "colors": bad_colors}
    resp = await authed_client.patch(
        "/api/v1/preferences",
        json={"theme_customization": bad},
    )
    assert resp.status_code == 422


async def test_preferences_patch_theme_missing_key(authed_client, mock_valkey):
    """PATCH theme_customization with missing color key returns 422."""
    incomplete = {k: v for k, v in _VALID_THEME["colors"].items() if k != "accent"}
    bad = {**_VALID_THEME, "colors": incomplete}
    resp = await authed_client.patch(
        "/api/v1/preferences",
        json={"theme_customization": bad},
    )
    assert resp.status_code == 422


async def test_preferences_patch_theme_name_too_long(authed_client, mock_valkey):
    """PATCH theme_customization with name > 50 chars returns 422."""
    bad = {**_VALID_THEME, "name": "x" * 51}
    resp = await authed_client.patch(
        "/api/v1/preferences",
        json={"theme_customization": bad},
    )
    assert resp.status_code == 422


# --- favourites list ---


async def test_favourites_list(authed_client, mock_valkey):
    """GET /api/v1/favourites returns favourited statuses."""
    # Create and favourite a status
    create = await authed_client.post(
        "/api/v1/statuses", json={"content": "fav list test", "visibility": "public"}
    )
    note_id = create.json()["id"]
    await authed_client.post(f"/api/v1/statuses/{note_id}/favourite")

    resp = await authed_client.get("/api/v1/favourites")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 1
    assert any(s["id"] == note_id for s in body)


async def test_favourites_list_empty(authed_client, db, mock_valkey):
    """GET /api/v1/favourites returns empty when no favourites."""
    # 全テストは共有DBなので、空の保証はできないが、レスポンス形式を検証
    resp = await authed_client.get("/api/v1/favourites")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# --- stub endpoints ---


async def test_filters_v1_stub(authed_client, mock_valkey):
    """GET /api/v1/filters returns empty array."""
    resp = await authed_client.get("/api/v1/filters")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_filters_v2_stub(authed_client, mock_valkey):
    """GET /api/v2/filters returns empty array."""
    resp = await authed_client.get("/api/v2/filters")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_announcements_stub(authed_client, mock_valkey):
    """GET /api/v1/announcements returns empty array."""
    resp = await authed_client.get("/api/v1/announcements")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_followed_tags_stub(authed_client, mock_valkey):
    """GET /api/v1/followed_tags returns empty array."""
    resp = await authed_client.get("/api/v1/followed_tags")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_conversations_stub(authed_client, mock_valkey):
    """GET /api/v1/conversations returns empty array."""
    resp = await authed_client.get("/api/v1/conversations")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_lists_stub(authed_client, mock_valkey):
    """GET /api/v1/lists returns empty array."""
    resp = await authed_client.get("/api/v1/lists")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_markers_get_stub(authed_client, mock_valkey):
    """GET /api/v1/markers returns empty object."""
    resp = await authed_client.get("/api/v1/markers")
    assert resp.status_code == 200
    assert resp.json() == {}


async def test_markers_post_stub(authed_client, mock_valkey):
    """POST /api/v1/markers returns empty object."""
    resp = await authed_client.post("/api/v1/markers")
    assert resp.status_code == 200
    assert resp.json() == {}


# --- instance API ---


async def test_instance_has_streaming_url(app_client, mock_valkey):
    """GET /api/v1/instance includes streaming_api URL."""
    resp = await app_client.get("/api/v1/instance")
    assert resp.status_code == 200
    body = resp.json()
    assert "streaming_api" in body["urls"]
    assert body["urls"]["streaming_api"].startswith("wss://")


async def test_instance_has_configuration(app_client, mock_valkey):
    """GET /api/v1/instance includes configuration object."""
    resp = await app_client.get("/api/v1/instance")
    assert resp.status_code == 200
    body = resp.json()
    assert "configuration" in body
    assert "statuses" in body["configuration"]
    assert "max_characters" in body["configuration"]["statuses"]
    assert "media_attachments" in body["configuration"]
    assert "polls" in body["configuration"]


async def test_instance_media_size_limits(app_client, mock_valkey):
    """GET /api/v1/instance returns configured media size limits."""
    resp = await app_client.get("/api/v1/instance")
    assert resp.status_code == 200
    ma = resp.json()["configuration"]["media_attachments"]
    assert ma["image_size_limit"] == 10 * 1024 * 1024
    assert ma["video_size_limit"] == 40 * 1024 * 1024
    assert ma["audio_size_limit"] == 10 * 1024 * 1024
    assert "video/mp4" in ma["supported_mime_types"]
    assert "audio/mpeg" in ma["supported_mime_types"]


async def test_instance_has_rules_and_contact(app_client, mock_valkey):
    """GET /api/v1/instance includes rules and contact."""
    resp = await app_client.get("/api/v1/instance")
    assert resp.status_code == 200
    body = resp.json()
    assert "rules" in body
    assert isinstance(body["rules"], list)
    assert "contact" in body
    assert "languages" in body
