"""Extended tests for passkey_service — credential management (list/delete)."""

import uuid

import pytest

from app.models.passkey import PasskeyCredential
from app.services.passkey_service import delete_passkey, list_passkeys


async def _create_passkey(db, user, *, name="Test Key") -> PasskeyCredential:
    """Insert a PasskeyCredential directly for testing."""
    passkey = PasskeyCredential(
        user_id=user.id,
        credential_id=uuid.uuid4().bytes,
        public_key=b"fake-public-key-data",
        sign_count=0,
        name=name,
    )
    db.add(passkey)
    await db.flush()
    return passkey


async def test_list_passkeys_empty(db, mock_valkey, test_user):
    result = await list_passkeys(db, test_user)
    assert result == []


async def test_list_passkeys_returns_user_keys(db, mock_valkey, test_user):
    await _create_passkey(db, test_user, name="Key 1")
    await _create_passkey(db, test_user, name="Key 2")
    result = await list_passkeys(db, test_user)
    assert len(result) == 2
    names = {p.name for p in result}
    assert names == {"Key 1", "Key 2"}


async def test_list_passkeys_excludes_other_users(db, mock_valkey, test_user, test_user_b):
    await _create_passkey(db, test_user, name="User A Key")
    await _create_passkey(db, test_user_b, name="User B Key")
    result = await list_passkeys(db, test_user)
    assert len(result) == 1
    assert result[0].name == "User A Key"


async def test_delete_passkey_success(db, mock_valkey, test_user):
    pk = await _create_passkey(db, test_user, name="To Delete")
    await delete_passkey(db, test_user, pk.id)
    result = await list_passkeys(db, test_user)
    assert len(result) == 0


async def test_delete_passkey_not_found(db, mock_valkey, test_user):
    with pytest.raises(ValueError, match="Passkey not found"):
        await delete_passkey(db, test_user, uuid.uuid4())


async def test_delete_passkey_other_user(db, mock_valkey, test_user, test_user_b):
    """Cannot delete another user's passkey."""
    pk = await _create_passkey(db, test_user, name="Not Yours")
    with pytest.raises(ValueError, match="Passkey not found"):
        await delete_passkey(db, test_user_b, pk.id)
