"""Extended tests for user_service: reserved usernames, CRUD, auth, password management."""

import uuid

import pytest

from app.services.user_service import (
    authenticate_user,
    change_password,
    create_user,
    get_user_by_id,
    is_reserved_username,
    reset_password,
    update_display_name,
)

# -- is_reserved_username --


def test_is_reserved_username_true():
    assert is_reserved_username("admin") is True
    assert is_reserved_username("root") is True
    assert is_reserved_username("ADMIN") is True  # case-insensitive


def test_is_reserved_username_false():
    assert is_reserved_username("alice") is False
    assert is_reserved_username("nekochan") is False


# -- create_user --


async def test_create_user(db, seed_roles):
    user = await create_user(
        db, "newuser", "newuser@example.com", "password1234", display_name="New User"
    )
    assert user.actor is not None
    assert user.actor.username == "newuser"
    assert user.actor.display_name == "New User"
    assert user.email == "newuser@example.com"
    assert user.role == "user"
    assert user.approval_status == "approved"


async def test_create_user_reserved_username(db, seed_roles):
    with pytest.raises(ValueError, match="reserved"):
        await create_user(db, "admin", "admin@example.com", "password1234")


async def test_create_user_skip_reserved_check(db, seed_roles):
    user = await create_user(
        db,
        "admin",
        "admin@example.com",
        "password1234",
        skip_reserved_check=True,
    )
    assert user.actor.username == "admin"


# -- authenticate_user --


async def test_authenticate_user_success(db, seed_roles):
    await create_user(db, "authuser", "authuser@example.com", "password1234")
    user = await authenticate_user(db, "authuser", "password1234")
    assert user is not None
    assert user.actor.username == "authuser"


async def test_authenticate_user_wrong_password(db, seed_roles):
    await create_user(db, "authuser2", "authuser2@example.com", "password1234")
    user = await authenticate_user(db, "authuser2", "wrongpassword")
    assert user is None


async def test_authenticate_user_nonexistent(db, seed_roles):
    user = await authenticate_user(db, "ghost", "password1234")
    assert user is None


# -- reset_password --


async def test_reset_password(db, seed_roles):
    await create_user(db, "resetuser", "resetuser@example.com", "oldpassword")
    await reset_password(db, "resetuser", "newpassword5678")

    # 新しいパスワードで認証できることを確認
    user = await authenticate_user(db, "resetuser", "newpassword5678")
    assert user is not None

    # 古いパスワードでは認証できないことを確認
    user_old = await authenticate_user(db, "resetuser", "oldpassword")
    assert user_old is None


# -- update_display_name --


async def test_update_display_name(db, seed_roles):
    user = await create_user(db, "dispuser", "dispuser@example.com", "password1234")
    updated = await update_display_name(db, user, "Updated Name")
    assert updated.actor.display_name == "Updated Name"


# -- change_password --


async def test_change_password(db, seed_roles):
    user = await create_user(db, "chguser", "chguser@example.com", "password1234")
    await change_password(db, user, "password1234", "newpassword5678")

    # 新しいパスワードで認証可能
    authed = await authenticate_user(db, "chguser", "newpassword5678")
    assert authed is not None

    # 古いパスワードでは認証不可
    authed_old = await authenticate_user(db, "chguser", "password1234")
    assert authed_old is None


async def test_change_password_wrong_current(db, seed_roles):
    user = await create_user(db, "chguser2", "chguser2@example.com", "password1234")
    with pytest.raises(ValueError, match="Current password is incorrect"):
        await change_password(db, user, "wrongpassword", "newpassword5678")


# -- get_user_by_id --


async def test_get_user_by_id(db, seed_roles):
    created = await create_user(db, "finduser", "finduser@example.com", "password1234")
    fetched = await get_user_by_id(db, created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.actor.username == "finduser"


async def test_get_user_by_id_not_found(db):
    fetched = await get_user_by_id(db, uuid.uuid4())
    assert fetched is None
