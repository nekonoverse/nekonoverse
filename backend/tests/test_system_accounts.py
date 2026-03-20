from unittest.mock import AsyncMock

import pytest

from app.services.system_account_service import (
    ensure_system_account,
    ensure_system_accounts,
    get_instance_actor,
    get_system_account,
)
from app.services.user_service import authenticate_user, reset_password

# -- ensure_system_account --


async def test_ensure_system_account_creates_account(db):
    user = await ensure_system_account(db, "instance.actor", "Instance Actor")
    assert user is not None
    assert user.is_system is True
    assert user.actor.username == "instance.actor"
    assert user.actor.type == "Application"
    assert user.actor.is_bot is True
    assert user.actor.discoverable is False
    assert user.actor.domain is None


async def test_ensure_system_account_is_idempotent(db):
    user1 = await ensure_system_account(db, "instance.actor", "Instance Actor")
    user2 = await ensure_system_account(db, "instance.actor", "Instance Actor")
    assert user1.id == user2.id


async def test_ensure_system_account_generates_keypair(db):
    user = await ensure_system_account(db, "instance.actor", "Instance Actor")
    assert "BEGIN PRIVATE KEY" in user.private_key_pem
    assert "BEGIN PUBLIC KEY" in user.actor.public_key_pem


# -- ensure_system_accounts --


async def test_ensure_system_accounts_creates_all(db):
    await ensure_system_accounts(db)
    user = await get_instance_actor(db)
    assert user is not None
    assert user.actor.username == "instance.actor"


# -- get_system_account --


async def test_get_system_account_returns_none_for_nonexistent(db):
    result = await get_system_account(db, "nonexistent.actor")
    assert result is None


async def test_get_system_account_returns_none_for_regular_user(db):
    """Regular users should not be returned by get_system_account."""
    from app.services.user_service import create_user

    await create_user(db, "alice", "alice@example.com", "password1234")
    result = await get_system_account(db, "alice")
    assert result is None


# -- get_instance_actor --


async def test_get_instance_actor(db):
    await ensure_system_account(db, "instance.actor", "Instance Actor")
    user = await get_instance_actor(db)
    assert user is not None
    assert user.actor.username == "instance.actor"


# -- Authentication rejection --


async def test_system_account_cannot_authenticate(db):
    await ensure_system_account(db, "instance.actor", "Instance Actor")
    result = await authenticate_user(db, "instance.actor", "any-password")
    assert result is None


# -- System account properties --


async def test_system_account_has_admin_role(db):
    user = await ensure_system_account(db, "instance.actor", "Instance Actor")
    assert user.role == "admin"


async def test_system_account_has_internal_email(db):
    user = await ensure_system_account(db, "instance.actor", "Instance Actor")
    assert user.email == "instance.actor@system.internal"


async def test_system_account_ap_urls(db):
    user = await ensure_system_account(db, "instance.actor", "Instance Actor")
    actor = user.actor
    assert "/users/instance.actor" in actor.ap_id
    assert "/users/instance.actor/inbox" in actor.inbox_url
    assert "/users/instance.actor/outbox" in actor.outbox_url


# -- Admin API protection --


async def _make_admin_client(db, app_client, mock_valkey):
    """Create an admin user and return an authenticated client."""
    from app.services.user_service import create_user

    admin = await create_user(
        db, "adminuser", "admin@example.com", "password1234", role="admin"
    )
    mock_valkey.get = AsyncMock(return_value=str(admin.id))
    app_client.cookies.set("nekonoverse_session", "test-session-id")
    return app_client



async def test_admin_cannot_suspend_system_account(db, app_client, mock_valkey):
    sys_user = await ensure_system_account(db, "instance.actor", "Instance Actor")
    client = await _make_admin_client(db, app_client, mock_valkey)
    response = await client.post(f"/api/v1/admin/users/{sys_user.id}/suspend")
    assert response.status_code == 422
    assert "system account" in response.json()["detail"].lower()



async def test_admin_cannot_silence_system_account(db, app_client, mock_valkey):
    sys_user = await ensure_system_account(db, "instance.actor", "Instance Actor")
    client = await _make_admin_client(db, app_client, mock_valkey)
    response = await client.post(f"/api/v1/admin/users/{sys_user.id}/silence")
    assert response.status_code == 422
    assert "system account" in response.json()["detail"].lower()



async def test_admin_cannot_change_system_account_role(db, app_client, mock_valkey):
    sys_user = await ensure_system_account(db, "instance.actor", "Instance Actor")
    client = await _make_admin_client(db, app_client, mock_valkey)
    response = await client.patch(
        f"/api/v1/admin/users/{sys_user.id}/role",
        json={"role": "user"},
    )
    assert response.status_code == 422
    assert "system account" in response.json()["detail"].lower()



async def test_admin_user_list_includes_is_system_field(db, app_client, mock_valkey):
    await ensure_system_account(db, "instance.actor", "Instance Actor")
    client = await _make_admin_client(db, app_client, mock_valkey)
    response = await client.get("/api/v1/admin/users")
    assert response.status_code == 200
    users = response.json()
    system_users = [u for u in users if u["is_system"]]
    assert len(system_users) >= 1
    assert system_users[0]["username"] == "instance.actor"


# -- CLI reset-password protection --


async def test_reset_password_rejected_for_system_account(db):
    await ensure_system_account(db, "instance.actor", "Instance Actor")
    with pytest.raises(ValueError, match="system account"):
        await reset_password(db, "instance.actor", "newpassword1234")
