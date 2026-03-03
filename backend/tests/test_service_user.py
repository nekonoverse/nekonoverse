import pytest

from app.services.user_service import authenticate_user, create_user, get_user_by_id


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
    with pytest.raises(ValueError, match="Username already taken"):
        await create_user(db, "alice", "alice2@example.com", "password1234")


async def test_create_user_duplicate_email(db):
    await create_user(db, "alice", "alice@example.com", "password1234")
    with pytest.raises(ValueError, match="Email already registered"):
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
