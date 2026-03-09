"""Extended tests for invitation_service — invite code management."""

from datetime import datetime, timedelta, timezone

from app.services.invitation_service import (
    create_invitation,
    delete_invitation,
    list_invitations,
    redeem_invitation,
    validate_invitation_code,
)


async def test_create_invitation(db, mock_valkey, test_user):
    invite = await create_invitation(db, test_user)
    assert invite.code is not None
    assert len(invite.code) == 32  # uuid4().hex
    assert invite.created_by_id == test_user.id


async def test_list_invitations(db, mock_valkey, test_user, test_user_b):
    """Lists only invitations for the specific user."""
    await create_invitation(db, test_user)
    await create_invitation(db, test_user)
    await create_invitation(db, test_user_b)
    await db.flush()

    invites = await list_invitations(db, test_user)
    assert len(invites) == 2
    assert all(i.created_by_id == test_user.id for i in invites)


async def test_validate_invitation_valid(db, mock_valkey, test_user):
    invite = await create_invitation(db, test_user)
    result = await validate_invitation_code(db, invite.code)
    assert result is not None
    assert result.code == invite.code


async def test_validate_invitation_nonexistent(db, mock_valkey):
    result = await validate_invitation_code(db, "nonexistent-code")
    assert result is None


async def test_validate_invitation_used(db, mock_valkey, test_user, test_user_b):
    invite = await create_invitation(db, test_user)
    await redeem_invitation(db, invite, test_user_b)
    result = await validate_invitation_code(db, invite.code)
    assert result is None


async def test_validate_invitation_expired(db, mock_valkey, test_user):
    invite = await create_invitation(db, test_user)
    invite.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.flush()
    result = await validate_invitation_code(db, invite.code)
    assert result is None


async def test_redeem_invitation(db, mock_valkey, test_user, test_user_b):
    invite = await create_invitation(db, test_user)
    await redeem_invitation(db, invite, test_user_b)
    assert invite.used_by_id == test_user_b.id
    assert invite.used_at is not None


async def test_delete_invitation_by_creator(db, mock_valkey, test_user):
    invite = await create_invitation(db, test_user)
    result = await delete_invitation(db, invite.code, test_user)
    assert result is True


async def test_delete_invitation_nonexistent(db, mock_valkey, test_user):
    result = await delete_invitation(db, "no-such-code", test_user)
    assert result is False


async def test_delete_invitation_by_non_creator(db, mock_valkey, test_user, test_user_b):
    """Non-creator non-admin cannot delete."""
    invite = await create_invitation(db, test_user)
    result = await delete_invitation(db, invite.code, test_user_b)
    assert result is False
