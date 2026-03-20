import pytest

from app.services.user_service import (
    authenticate_user,
    change_password,
    create_user,
    get_user_by_id,
    update_display_name,
)


async def test_create_user_returns_user_with_actor(db):
    user = await create_user(db, "alice", "alice@example.com", "password1234")
    assert user.actor is not None
    assert user.actor.username == "alice"
    assert user.actor.domain is None


async def test_create_user_generates_rsa_keys(db):
    user = await create_user(db, "alice", "alice@example.com", "password1234")
    assert "BEGIN PRIVATE KEY" in user.private_key_pem
    assert "BEGIN PUBLIC KEY" in user.actor.public_key_pem


async def test_create_user_hashes_password(db):
    user = await create_user(db, "alice", "alice@example.com", "password1234")
    assert user.password_hash != "password1234"
    assert user.password_hash.startswith("$2b$")


async def test_create_user_with_role(db):
    user = await create_user(db, "admin", "admin@example.com", "password1234", role="admin")
    assert user.role == "admin"
    assert user.is_admin is True


async def test_create_user_duplicate_username(db):
    await create_user(db, "alice", "alice@example.com", "password1234")
    with pytest.raises(ValueError, match="already in use"):
        await create_user(db, "alice", "alice2@example.com", "password1234")


async def test_create_user_duplicate_email(db):
    await create_user(db, "alice", "alice@example.com", "password1234")
    with pytest.raises(ValueError, match="already in use"):
        await create_user(db, "bob", "alice@example.com", "password1234")


async def test_authenticate_user_success(db):
    await create_user(db, "alice", "alice@example.com", "password1234")
    user = await authenticate_user(db, "alice", "password1234")
    assert user is not None
    assert user.actor.username == "alice"


async def test_authenticate_user_wrong_password(db):
    await create_user(db, "alice", "alice@example.com", "password1234")
    user = await authenticate_user(db, "alice", "wrongpassword")
    assert user is None


async def test_authenticate_user_nonexistent(db):
    user = await authenticate_user(db, "nobody", "password1234")
    assert user is None


async def test_get_user_by_id(db):
    created = await create_user(db, "alice", "alice@example.com", "password1234")
    fetched = await get_user_by_id(db, created.id)
    assert fetched is not None
    assert fetched.id == created.id


# ── Case-insensitive username ──


async def test_create_user_normalizes_username_to_lowercase(db):
    user = await create_user(db, "Alice", "alice@example.com", "password1234")
    assert user.actor.username == "alice"


async def test_create_user_duplicate_case_insensitive(db):
    await create_user(db, "alice", "alice@example.com", "password1234")
    with pytest.raises(ValueError, match="already in use"):
        await create_user(db, "Alice", "alice2@example.com", "password1234")


async def test_authenticate_user_case_insensitive(db):
    await create_user(db, "alice", "alice@example.com", "password1234")
    user = await authenticate_user(db, "Alice", "password1234")
    assert user is not None
    assert user.actor.username == "alice"


# ── update_display_name ──


async def test_update_display_name(db):
    user = await create_user(db, "alice", "alice@example.com", "password1234")
    updated = await update_display_name(db, user, "New Name")
    assert updated.actor.display_name == "New Name"


async def test_update_display_name_to_none(db):
    user = await create_user(db, "alice", "alice@example.com", "password1234", display_name="Old")
    updated = await update_display_name(db, user, None)
    assert updated.actor.display_name is None


# ── change_password ──


async def test_change_password_success(db):
    user = await create_user(db, "alice", "alice@example.com", "password1234")
    await change_password(db, user, "password1234", "newpassword5678")
    authed = await authenticate_user(db, "alice", "newpassword5678")
    assert authed is not None


async def test_change_password_wrong_current(db):
    user = await create_user(db, "alice", "alice@example.com", "password1234")
    with pytest.raises(ValueError, match="Current password is incorrect"):
        await change_password(db, user, "wrongpassword", "newpassword5678")
