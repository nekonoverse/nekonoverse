"""Tests for the reaction service layer."""

from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import make_note

# reaction_serviceはenqueue_delivery, get_follower_inboxes, get_follower_ids,
# ignores_emoji_reactionsを関数内でインポートするため、元モジュール側をパッチする
_PATCHES = [
    patch("app.services.delivery_service.enqueue_delivery", new_callable=AsyncMock),
    patch(
        "app.services.follow_service.get_follower_inboxes",
        new_callable=AsyncMock,
        return_value=[],
    ),
    patch(
        "app.services.follow_service.get_follower_ids",
        new_callable=AsyncMock,
        return_value=[],
    ),
    patch(
        "app.utils.nodeinfo.ignores_emoji_reactions",
        new_callable=AsyncMock,
        return_value=False,
    ),
]


def _apply_patches():
    """Start all patches and return the list of mocks."""
    return [p.start() for p in _PATCHES]


def _stop_patches():
    for p in _PATCHES:
        p.stop()


@pytest.fixture(autouse=True)
def _patch_reaction_deps():
    _apply_patches()
    yield
    _stop_patches()


async def test_add_reaction_unicode_emoji(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction

    note = await make_note(db, test_user.actor)
    reaction = await add_reaction(db, test_user, note, "\U0001f44d")

    assert reaction is not None
    assert reaction.emoji == "\U0001f44d"
    assert reaction.actor_id == test_user.actor.id
    assert reaction.note_id == note.id


async def test_add_reaction_star(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction

    note = await make_note(db, test_user.actor)
    reaction = await add_reaction(db, test_user, note, "\u2b50")

    assert reaction is not None
    assert reaction.emoji == "\u2b50"


async def test_add_reaction_invalid_emoji(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction

    note = await make_note(db, test_user.actor)
    with pytest.raises(ValueError, match="Invalid emoji"):
        await add_reaction(db, test_user, note, "not-an-emoji")


async def test_add_reaction_duplicate(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction

    note = await make_note(db, test_user.actor)
    await add_reaction(db, test_user, note, "\U0001f44d")
    with pytest.raises(ValueError, match="Already reacted"):
        await add_reaction(db, test_user, note, "\U0001f44d")


async def test_remove_reaction_success(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction, remove_reaction

    note = await make_note(db, test_user.actor)
    await add_reaction(db, test_user, note, "\U0001f44d")
    await remove_reaction(db, test_user, note, "\U0001f44d")

    # ノートのreactions_countが0に戻っていること
    assert note.reactions_count == 0


async def test_remove_reaction_not_found(db, test_user, mock_valkey):
    from app.services.reaction_service import remove_reaction

    note = await make_note(db, test_user.actor)
    with pytest.raises(ValueError, match="Reaction not found"):
        await remove_reaction(db, test_user, note, "\U0001f44d")
