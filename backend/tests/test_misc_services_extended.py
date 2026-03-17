"""Extended tests for moderation, domain_block, and reaction services."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.domain_block_service import (
    create_domain_block,
    is_domain_blocked,
    list_domain_blocks,
    remove_domain_block,
)
from app.services.moderation_service import (
    admin_delete_note,
    force_sensitive,
    silence_actor,
    suspend_actor,
    unsilence_actor,
    unsuspend_actor,
)
from app.services.reaction_service import add_reaction, remove_reaction
from tests.conftest import make_note, make_remote_actor

# ── moderation_service ───────────────────────────────────────────────────


async def test_suspend_local_actor_delivers(db, mock_valkey, test_user, test_user_b):
    """Suspending a local actor delivers Delete to followers."""
    actor = test_user_b.actor
    with (
        patch(
            "app.services.follow_service.get_follower_inboxes",
            new_callable=AsyncMock,
            return_value=["http://remote.example/inbox"],
        ),
        patch(
            "app.services.delivery_service.enqueue_delivery",
            new_callable=AsyncMock,
        ) as mock_deliver,
    ):
        await suspend_actor(db, actor, test_user, reason="spam")
    assert actor.suspended_at is not None
    mock_deliver.assert_called_once()


async def test_unsuspend_actor(db, mock_valkey, test_user, test_user_b):
    await suspend_actor(db, test_user_b.actor, test_user)
    await unsuspend_actor(db, test_user_b.actor, test_user)
    assert test_user_b.actor.suspended_at is None


async def test_silence_actor(db, mock_valkey, test_user, test_user_b):
    await silence_actor(db, test_user_b.actor, test_user, reason="harassment")
    assert test_user_b.actor.silenced_at is not None


async def test_unsilence_actor(db, mock_valkey, test_user, test_user_b):
    await silence_actor(db, test_user_b.actor, test_user)
    await unsilence_actor(db, test_user_b.actor, test_user)
    assert test_user_b.actor.silenced_at is None


async def test_admin_delete_note_local(db, mock_valkey, test_user, test_user_b):
    """Deleting a local note delivers Delete to followers."""
    note = await make_note(db, test_user_b.actor, content="to delete")
    with (
        patch(
            "app.services.follow_service.get_follower_inboxes",
            new_callable=AsyncMock,
            return_value=["http://remote.example/inbox"],
        ),
        patch(
            "app.services.delivery_service.enqueue_delivery",
            new_callable=AsyncMock,
        ) as mock_deliver,
    ):
        await admin_delete_note(db, note, test_user, reason="violation")
    assert note.deleted_at is not None
    mock_deliver.assert_called_once()


async def test_admin_delete_note_remote(db, mock_valkey, test_user):
    """Deleting a remote note does NOT trigger delivery."""
    remote_actor = await make_remote_actor(db, username="rem_del", domain="del.example")
    note = await make_note(db, remote_actor, content="remote note", local=False)
    await admin_delete_note(db, note, test_user, reason="spam")
    assert note.deleted_at is not None


async def test_force_sensitive(db, mock_valkey, test_user, test_user_b):
    note = await make_note(db, test_user_b.actor, content="nsfw content")
    assert note.sensitive is False
    await force_sensitive(db, note, test_user)
    assert note.sensitive is True


# ── domain_block_service ─────────────────────────────────────────────────


async def test_remove_domain_block_success(db, mock_valkey, test_user):
    await create_domain_block(db, "blocked.example", "suspend", "spam", test_user)
    result = await remove_domain_block(db, "blocked.example")
    assert result is True


async def test_remove_domain_block_not_found(db, mock_valkey):
    result = await remove_domain_block(db, "nonexistent.example")
    assert result is False


async def test_list_domain_blocks(db, mock_valkey, test_user):
    await create_domain_block(db, "block1.example", "suspend", None, test_user)
    await create_domain_block(db, "block2.example", "silence", "spam", test_user)
    blocks = await list_domain_blocks(db)
    assert len(blocks) >= 2
    domains = {b.domain for b in blocks}
    assert "block1.example" in domains
    assert "block2.example" in domains


async def test_is_domain_blocked_true(db, mock_valkey, test_user):
    await create_domain_block(db, "bad.example", "suspend", None, test_user)
    result = await is_domain_blocked(db, "bad.example")
    assert result is True


async def test_is_domain_blocked_false(db, mock_valkey):
    result = await is_domain_blocked(db, "good.example")
    assert result is False


async def test_is_domain_blocked_empty_domain(db, mock_valkey):
    result = await is_domain_blocked(db, "")
    assert result is False


async def test_is_domain_blocked_cached(db, mock_valkey, test_user):
    """When cache returns a value, it uses cached result."""
    mock_valkey.get = AsyncMock(return_value="1")
    result = await is_domain_blocked(db, "cached.example")
    assert result is True

    mock_valkey.get = AsyncMock(return_value="0")
    result = await is_domain_blocked(db, "cached.example")
    assert result is False


# ── reaction_service ─────────────────────────────────────────────────────


async def test_add_reaction_invalid_emoji(db, mock_valkey, test_user):
    note = await make_note(db, test_user.actor, content="react test")
    with pytest.raises(ValueError, match="Invalid emoji"):
        await add_reaction(db, test_user, note, "not-an-emoji")


async def test_add_reaction_duplicate(db, mock_valkey, test_user, test_user_b):
    note = await make_note(db, test_user.actor, content="dup react")
    await add_reaction(db, test_user_b, note, "\u2764\ufe0f")
    with pytest.raises(ValueError, match="Already reacted"):
        await add_reaction(db, test_user_b, note, "\u2764\ufe0f")


async def test_add_reaction_to_remote_note_delivers(db, mock_valkey, test_user):
    """Reacting to a remote note triggers delivery."""
    remote_actor = await make_remote_actor(db, username="rem_react", domain="react.example")
    note = await make_note(db, remote_actor, content="remote note", local=False)
    # Use ⭐ (favourite) — sent to all servers regardless of software
    with patch(
        "app.services.delivery_service.enqueue_delivery",
        new_callable=AsyncMock,
    ) as mock_deliver:
        await add_reaction(db, test_user, note, "\u2b50")
    assert mock_deliver.call_count == 1


async def test_remove_reaction_success(db, mock_valkey, test_user, test_user_b):
    note = await make_note(db, test_user.actor, content="remove react")
    await add_reaction(db, test_user_b, note, "\U0001f44d")
    await remove_reaction(db, test_user_b, note, "\U0001f44d")
    assert note.reactions_count == 0


async def test_remove_reaction_not_found(db, mock_valkey, test_user):
    note = await make_note(db, test_user.actor, content="no react")
    with pytest.raises(ValueError, match="Reaction not found"):
        await remove_reaction(db, test_user, note, "\u2764\ufe0f")


async def test_remove_reaction_from_remote_note_delivers(db, mock_valkey, test_user):
    """Removing reaction from a remote note sends Undo(Like)."""
    remote_actor = await make_remote_actor(db, username="rem_undo", domain="undo.example")
    note = await make_note(db, remote_actor, content="remote undo", local=False)
    # Use ⭐ (favourite) — sent to all servers regardless of software
    await add_reaction(db, test_user, note, "\u2b50")
    with patch(
        "app.services.delivery_service.enqueue_delivery",
        new_callable=AsyncMock,
    ) as mock_deliver:
        await remove_reaction(db, test_user, note, "\u2b50")
    assert mock_deliver.call_count == 1


async def test_add_reaction_custom_emoji_to_remote(db, mock_valkey, test_user):
    """Custom emoji reaction to remote note attaches emoji tag."""
    from app.models.custom_emoji import CustomEmoji

    # ローカルカスタム絵文字を作成
    emoji = CustomEmoji(
        shortcode="blobcat",
        domain=None,
        url="https://local.example/emoji/blobcat.png",
        visible_in_picker=True,
    )
    db.add(emoji)
    await db.flush()

    remote_actor = await make_remote_actor(db, username="rem_custom", domain="custom.example")
    note = await make_note(db, remote_actor, content="custom react", local=False)

    # Mock: custom.example is a Misskey instance (supports emoji via Like)
    with (
        patch(
            "app.utils.nodeinfo.get_domain_software",
            new_callable=AsyncMock,
            return_value="misskey",
        ),
        patch(
            "app.services.delivery_service.enqueue_delivery",
            new_callable=AsyncMock,
        ) as mock_deliver,
    ):
        await add_reaction(db, test_user, note, ":blobcat:")

    assert mock_deliver.call_count == 1
    # Activity should have emoji tag
    activity = mock_deliver.call_args_list[0][0][3]
    assert "tag" in activity
    assert activity["tag"][0]["name"] == ":blobcat:"
