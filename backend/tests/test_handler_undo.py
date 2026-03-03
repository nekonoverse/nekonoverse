from app.models.follow import Follow
from app.models.reaction import Reaction
from tests.conftest import make_note, make_remote_actor


async def test_undo_follow(db, test_user, mock_valkey):
    from app.activitypub.handlers.undo import handle_undo
    from sqlalchemy import select
    remote = await make_remote_actor(db, username="undof", domain="undof.example")
    follow = Follow(follower_id=remote.id, following_id=test_user.actor_id, accepted=True)
    db.add(follow)
    await db.flush()
    activity = {
        "type": "Undo",
        "actor": remote.ap_id,
        "object": {
            "type": "Follow",
            "actor": remote.ap_id,
            "object": test_user.actor.ap_id,
        }
    }
    await handle_undo(db, activity)
    result = await db.execute(select(Follow).where(Follow.id == follow.id))
    assert result.scalar_one_or_none() is None


async def test_undo_like(db, test_user, mock_valkey):
    from app.activitypub.handlers.undo import handle_undo
    from sqlalchemy import select
    remote = await make_remote_actor(db, username="undol", domain="undol.example")
    note = await make_note(db, test_user.actor)
    reaction = Reaction(
        actor_id=remote.id, note_id=note.id, emoji="❤",
        ap_id="http://undol.example/activities/like1"
    )
    db.add(reaction)
    note.reactions_count = 1
    await db.flush()
    activity = {
        "type": "Undo",
        "actor": remote.ap_id,
        "object": {
            "type": "Like",
            "id": "http://undol.example/activities/like1",
            "actor": remote.ap_id,
            "object": note.ap_id,
        }
    }
    await handle_undo(db, activity)
    result = await db.execute(select(Reaction).where(Reaction.id == reaction.id))
    assert result.scalar_one_or_none() is None
    await db.refresh(note)
    assert note.reactions_count == 0


async def test_undo_non_dict_ignored(db, mock_valkey):
    from app.activitypub.handlers.undo import handle_undo
    activity = {
        "type": "Undo",
        "actor": "http://example.com/users/x",
        "object": "http://example.com/activities/string-ref"
    }
    await handle_undo(db, activity)  # Should not raise


async def test_undo_emoji_react(db, test_user, mock_valkey):
    from app.activitypub.handlers.undo import handle_undo
    from sqlalchemy import select
    remote = await make_remote_actor(db, username="undoer", domain="undoer.example")
    note = await make_note(db, test_user.actor)
    reaction = Reaction(
        actor_id=remote.id, note_id=note.id, emoji="🎉",
        ap_id="http://undoer.example/activities/react1"
    )
    db.add(reaction)
    note.reactions_count = 1
    await db.flush()
    activity = {
        "type": "Undo",
        "actor": remote.ap_id,
        "object": {
            "type": "EmojiReact",
            "id": "http://undoer.example/activities/react1",
            "actor": remote.ap_id,
            "object": note.ap_id,
        }
    }
    await handle_undo(db, activity)
    result = await db.execute(select(Reaction).where(Reaction.id == reaction.id))
    assert result.scalar_one_or_none() is None
