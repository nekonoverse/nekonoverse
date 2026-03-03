from tests.conftest import make_note, make_remote_actor


async def test_handle_like_default_heart(db, test_user, mock_valkey):
    from app.activitypub.handlers.like import handle_like
    note = await make_note(db, test_user.actor)
    remote = await make_remote_actor(db, username="liker", domain="liker.example")
    activity = {
        "type": "Like",
        "id": "http://liker.example/activities/like1",
        "actor": remote.ap_id,
        "object": note.ap_id,
    }
    await handle_like(db, activity)
    from sqlalchemy import select
    from app.models.reaction import Reaction
    r = (await db.execute(select(Reaction).where(Reaction.note_id == note.id))).scalar_one_or_none()
    assert r is not None
    assert r.emoji == "❤"


async def test_handle_like_misskey_reaction(db, test_user, mock_valkey):
    from app.activitypub.handlers.like import handle_like
    note = await make_note(db, test_user.actor)
    remote = await make_remote_actor(db, username="misskey", domain="misskey.example")
    activity = {
        "type": "Like",
        "id": "http://misskey.example/activities/like2",
        "actor": remote.ap_id,
        "object": note.ap_id,
        "_misskey_reaction": "😀",
    }
    await handle_like(db, activity)
    from sqlalchemy import select
    from app.models.reaction import Reaction
    r = (await db.execute(select(Reaction).where(Reaction.note_id == note.id))).scalar_one_or_none()
    assert r.emoji == "😀"


async def test_handle_like_content_emoji(db, test_user, mock_valkey):
    from app.activitypub.handlers.like import handle_like
    note = await make_note(db, test_user.actor)
    remote = await make_remote_actor(db, username="content", domain="content.example")
    activity = {
        "type": "Like",
        "id": "http://content.example/activities/like3",
        "actor": remote.ap_id,
        "object": note.ap_id,
        "content": "⭐",
    }
    await handle_like(db, activity)
    from sqlalchemy import select
    from app.models.reaction import Reaction
    r = (await db.execute(select(Reaction).where(Reaction.note_id == note.id))).scalar_one_or_none()
    assert r.emoji == "⭐"


async def test_handle_like_duplicate_skipped(db, test_user, mock_valkey):
    from app.activitypub.handlers.like import handle_like
    note = await make_note(db, test_user.actor)
    remote = await make_remote_actor(db, username="duplike", domain="duplike.example")
    activity = {
        "type": "Like",
        "id": "http://duplike.example/activities/like4",
        "actor": remote.ap_id,
        "object": note.ap_id,
    }
    await handle_like(db, activity)
    await handle_like(db, activity)  # Should not raise
    from sqlalchemy import select, func
    from app.models.reaction import Reaction
    count = await db.scalar(select(func.count()).where(Reaction.note_id == note.id))
    assert count == 1


async def test_handle_like_note_not_found(db, mock_valkey):
    from app.activitypub.handlers.like import handle_like
    remote = await make_remote_actor(db, username="lnf", domain="lnf.example")
    activity = {
        "type": "Like",
        "id": "http://lnf.example/activities/like5",
        "actor": remote.ap_id,
        "object": "http://localhost/notes/nonexistent",
    }
    await handle_like(db, activity)  # Should not raise


async def test_handle_emoji_react(db, test_user, mock_valkey):
    from app.activitypub.handlers.like import handle_emoji_react
    note = await make_note(db, test_user.actor)
    remote = await make_remote_actor(db, username="pleroma", domain="pleroma.example")
    activity = {
        "type": "EmojiReact",
        "id": "http://pleroma.example/activities/react1",
        "actor": remote.ap_id,
        "object": note.ap_id,
        "content": "🎉",
    }
    await handle_emoji_react(db, activity)
    from sqlalchemy import select
    from app.models.reaction import Reaction
    r = (await db.execute(select(Reaction).where(Reaction.note_id == note.id))).scalar_one_or_none()
    assert r.emoji == "🎉"


async def test_handle_like_increments_count(db, test_user, mock_valkey):
    from app.activitypub.handlers.like import handle_like
    note = await make_note(db, test_user.actor)
    assert note.reactions_count == 0
    remote = await make_remote_actor(db, username="cnt", domain="cnt.example")
    activity = {
        "type": "Like",
        "id": "http://cnt.example/activities/like6",
        "actor": remote.ap_id,
        "object": note.ap_id,
    }
    await handle_like(db, activity)
    await db.refresh(note)
    assert note.reactions_count == 1
