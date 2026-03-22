"""Tests for invitation code system."""

from unittest.mock import AsyncMock


async def _make_admin(db, mock_valkey, app_client, username="invadmin"):
    from app.services.user_service import create_user

    user = await create_user(db, username, f"{username}@test.com", "password1234", role="admin")
    mock_valkey.get = AsyncMock(return_value=str(user.id))
    app_client.cookies.set("nekonoverse_session", "test-session-id")
    return user


async def _make_user(db, mock_valkey, app_client, username="invuser"):
    from app.services.user_service import create_user

    user = await create_user(db, username, f"{username}@test.com", "password1234")
    mock_valkey.get = AsyncMock(return_value=str(user.id))
    app_client.cookies.set("nekonoverse_session", "test-session-id")
    return user


# --- Create invite ---


async def test_create_invite_as_admin(app_client, db, mock_valkey):
    """Admin can create an invite code."""
    await _make_admin(db, mock_valkey, app_client)
    resp = await app_client.post("/api/v1/invites")
    assert resp.status_code == 201
    data = resp.json()
    assert "code" in data
    assert len(data["code"]) == 32
    assert data["used_by"] is None


async def test_create_invite_forbidden_regular_user(app_client, db, mock_valkey):
    """Default invite_create_role is 'admin', so regular user is forbidden."""
    await _make_user(db, mock_valkey, app_client)
    resp = await app_client.post("/api/v1/invites")
    assert resp.status_code == 403


async def test_create_invite_unauthenticated(app_client, mock_valkey):
    """Unauthenticated user cannot create invites."""
    mock_valkey.get = AsyncMock(return_value=None)
    resp = await app_client.post("/api/v1/invites")
    assert resp.status_code == 401


# --- List invites ---


async def test_list_invites(app_client, db, mock_valkey):
    """Admin can list their invite codes."""
    await _make_admin(db, mock_valkey, app_client)
    await app_client.post("/api/v1/invites")
    await app_client.post("/api/v1/invites")
    resp = await app_client.get("/api/v1/invites")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


# --- Delete invite ---


async def test_delete_invite(app_client, db, mock_valkey):
    """Admin can delete their invite code."""
    await _make_admin(db, mock_valkey, app_client)
    create_resp = await app_client.post("/api/v1/invites")
    code = create_resp.json()["code"]
    resp = await app_client.delete(f"/api/v1/invites/{code}")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_delete_invite_not_found(app_client, db, mock_valkey):
    """Deleting non-existent invite returns 404."""
    await _make_admin(db, mock_valkey, app_client)
    resp = await app_client.delete("/api/v1/invites/00000000000000000000000000000000")
    assert resp.status_code == 404


# --- Registration with invites ---


async def test_register_with_valid_invite(app_client, db, mock_valkey):
    """Registration succeeds with a valid invite code in invite mode."""
    from app.services.server_settings_service import set_setting

    await set_setting(db, "registration_mode", "invite")
    await db.commit()

    # Admin creates an invite
    admin = await _make_admin(db, mock_valkey, app_client)
    create_resp = await app_client.post("/api/v1/invites")
    code = create_resp.json()["code"]

    # Clear auth so we register as anonymous
    mock_valkey.get = AsyncMock(return_value=None)
    app_client.cookies.clear()

    resp = await app_client.post("/api/v1/accounts", json={
        "username": "inviteduser",
        "email": "invited@test.com",
        "password": "password1234",
        "invite_code": code,
    })
    assert resp.status_code == 201
    assert resp.json()["username"] == "inviteduser"


async def test_register_without_invite_rejected(app_client, db, mock_valkey):
    """Registration without invite code fails in invite mode."""
    from app.services.server_settings_service import set_setting

    await set_setting(db, "registration_mode", "invite")
    await db.commit()

    mock_valkey.get = AsyncMock(return_value=None)
    resp = await app_client.post("/api/v1/accounts", json={
        "username": "noinvite",
        "email": "noinvite@test.com",
        "password": "password1234",
    })
    assert resp.status_code == 422
    assert "invitation code" in resp.json()["detail"].lower()


async def test_register_with_used_invite_rejected(app_client, db, mock_valkey):
    """Used invite code cannot be reused."""
    from app.services.server_settings_service import set_setting

    await set_setting(db, "registration_mode", "invite")
    await db.commit()

    admin = await _make_admin(db, mock_valkey, app_client)
    create_resp = await app_client.post("/api/v1/invites")
    code = create_resp.json()["code"]

    # First registration uses the invite
    mock_valkey.get = AsyncMock(return_value=None)
    app_client.cookies.clear()
    resp1 = await app_client.post("/api/v1/accounts", json={
        "username": "firstuser",
        "email": "first@test.com",
        "password": "password1234",
        "invite_code": code,
    })
    assert resp1.status_code == 201

    # Second registration with same code fails
    resp2 = await app_client.post("/api/v1/accounts", json={
        "username": "seconduser",
        "email": "second@test.com",
        "password": "password1234",
        "invite_code": code,
    })
    assert resp2.status_code == 422


async def test_register_open_mode_no_invite_needed(app_client, db, mock_valkey):
    """Registration in open mode does not require invite code."""
    from app.services.server_settings_service import set_setting

    await set_setting(db, "registration_mode", "open")
    await db.commit()

    mock_valkey.get = AsyncMock(return_value=None)
    resp = await app_client.post("/api/v1/accounts", json={
        "username": "openuser",
        "email": "open@test.com",
        "password": "password1234",
    })
    assert resp.status_code == 201


# --- IDOR tests ---


async def test_delete_invite_other_user(app_client, db, mock_valkey):
    """Non-admin cannot delete another user's invite code."""
    from app.services.server_settings_service import set_setting

    # Allow regular users to create invites
    await set_setting(db, "invite_create_role", "user")
    await db.commit()

    user_a = await _make_user(db, mock_valkey, app_client, username="invuser_a")

    # side_effect: return user ID for session lookup, None for settings (fall through to DB)
    user_a_id = str(user_a.id)

    async def get_side_effect_a(key):
        if key.startswith("setting:"):
            return None
        return user_a_id

    mock_valkey.get = AsyncMock(side_effect=get_side_effect_a)

    create_resp = await app_client.post("/api/v1/invites")
    assert create_resp.status_code == 201
    code = create_resp.json()["code"]

    # Switch to user B
    user_b = await _make_user(db, mock_valkey, app_client, username="invuser_b")
    user_b_id = str(user_b.id)

    async def get_side_effect_b(key):
        if key.startswith("setting:"):
            return None
        return user_b_id

    mock_valkey.get = AsyncMock(side_effect=get_side_effect_b)

    resp = await app_client.delete(f"/api/v1/invites/{code}")
    assert resp.status_code == 404
