import pytest

from tests.conftest import make_note, make_remote_actor


async def test_add_reaction(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction
    note = await make_note(db, test_user.actor)
    reaction = await add_reaction(db, test_user, note, "\U0001f600")
    assert reaction.emoji == "\U0001f600"
    assert note.reactions_count == 1


async def test_add_reaction_invalid_emoji(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction
    note = await make_note(db, test_user.actor)
    with pytest.raises(ValueError, match="Invalid emoji"):
        await add_reaction(db, test_user, note, "not-an-emoji")


async def test_add_reaction_duplicate(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction
    note = await make_note(db, test_user.actor)
    await add_reaction(db, test_user, note, "\U0001f600")
    with pytest.raises(ValueError, match="Already reacted"):
        await add_reaction(db, test_user, note, "\U0001f600")


async def test_add_reaction_different_emoji_ok(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction
    note = await make_note(db, test_user.actor)
    await add_reaction(db, test_user, note, "\U0001f600")
    r2 = await add_reaction(db, test_user, note, "\u2764")
    assert r2.emoji == "\u2764"
    assert note.reactions_count == 2


async def test_remove_reaction(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction, remove_reaction
    note = await make_note(db, test_user.actor)
    await add_reaction(db, test_user, note, "\U0001f600")
    await remove_reaction(db, test_user, note, "\U0001f600")
    assert note.reactions_count == 0


async def test_remove_reaction_not_found(db, test_user, mock_valkey):
    from app.services.reaction_service import remove_reaction
    note = await make_note(db, test_user.actor)
    with pytest.raises(ValueError):
        await remove_reaction(db, test_user, note, "\U0001f600")


async def test_add_reaction_remote_note_enqueues(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction
    remote_actor = await make_remote_actor(db)
    note = await make_note(db, remote_actor, local=False)
    await add_reaction(db, test_user, note, "\U0001f600")
    mock_valkey.lpush.assert_called()


async def test_remove_reaction_count_floor(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction, remove_reaction
    note = await make_note(db, test_user.actor)
    await add_reaction(db, test_user, note, "\U0001f600")
    note.reactions_count = 0  # Force to 0
    await remove_reaction(db, test_user, note, "\U0001f600")
    assert note.reactions_count >= 0
