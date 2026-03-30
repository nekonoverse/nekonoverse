"""Tests for the mute service layer."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.mute_service import get_muted_ids, is_muting, mute_actor, unmute_actor


async def test_mute_actor_success(db, test_user, test_user_b):
    mute = await mute_actor(db, test_user, test_user_b.actor)
    await db.commit()

    assert mute is not None
    assert mute.actor_id == test_user.actor.id
    assert mute.target_id == test_user_b.actor.id
    assert mute.expires_at is None


async def test_mute_actor_duplicate(db, test_user, test_user_b):
    await mute_actor(db, test_user, test_user_b.actor)
    await db.commit()

    with pytest.raises(ValueError, match="Already muting"):
        await mute_actor(db, test_user, test_user_b.actor)


async def test_unmute_actor_success(db, test_user, test_user_b):
    await mute_actor(db, test_user, test_user_b.actor)
    await db.commit()

    await unmute_actor(db, test_user, test_user_b.actor)
    await db.commit()

    result = await is_muting(db, test_user.actor.id, test_user_b.actor.id)
    assert result is False


async def test_unmute_actor_not_muting(db, test_user, test_user_b):
    with pytest.raises(ValueError, match="Not muting"):
        await unmute_actor(db, test_user, test_user_b.actor)


async def test_get_muted_ids_empty(db, test_user):
    ids = await get_muted_ids(db, test_user.actor.id)
    assert ids == []


async def test_get_muted_ids_returns_targets(db, test_user, test_user_b):
    await mute_actor(db, test_user, test_user_b.actor)
    await db.commit()

    ids = await get_muted_ids(db, test_user.actor.id)
    assert test_user_b.actor.id in ids


async def test_get_muted_ids_excludes_expired(db, test_user, test_user_b):
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    await mute_actor(db, test_user, test_user_b.actor, expires_at=past)
    await db.commit()

    ids = await get_muted_ids(db, test_user.actor.id)
    assert test_user_b.actor.id not in ids


async def test_is_muting_true(db, test_user, test_user_b):
    await mute_actor(db, test_user, test_user_b.actor)
    await db.commit()

    result = await is_muting(db, test_user.actor.id, test_user_b.actor.id)
    assert result is True


async def test_is_muting_false(db, test_user, test_user_b):
    result = await is_muting(db, test_user.actor.id, test_user_b.actor.id)
    assert result is False


async def test_is_muting_expired_returns_false(db, test_user, test_user_b):
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    await mute_actor(db, test_user, test_user_b.actor, expires_at=past)
    await db.commit()

    result = await is_muting(db, test_user.actor.id, test_user_b.actor.id)
    assert result is False
