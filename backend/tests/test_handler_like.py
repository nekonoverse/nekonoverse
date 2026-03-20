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
    assert r.emoji == "⭐"


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


async def test_handle_like_custom_emoji_extended_fields(db, test_user, mock_valkey):
    """Like with custom emoji tag containing CherryPick extended fields."""
    from app.activitypub.handlers.like import handle_like
    note = await make_note(db, test_user.actor)
    remote = await make_remote_actor(db, username="cplike", domain="cplike.example")
    activity = {
        "type": "Like",
        "id": "http://cplike.example/activities/like-ext",
        "actor": remote.ap_id,
        "object": note.ap_id,
        "content": ":ext_heart:",
        "_misskey_reaction": ":ext_heart:",
        "tag": [
            {
                "type": "Emoji",
                "name": ":ext_heart:",
                "icon": {"type": "Image", "url": "https://cplike.example/emoji/heart.png"},
                "license": "CC0",
                "keywords": ["love", "heart"],
                "author": "like_artist",
                "copyPermission": "allow",
                "category": "emotions",
            },
        ],
    }
    await handle_like(db, activity)

    from app.services.emoji_service import get_custom_emoji
    cached = await get_custom_emoji(db, "ext_heart", "cplike.example")
    assert cached is not None
    assert cached.license == "CC0"
    assert cached.aliases == ["love", "heart"]
    assert cached.author == "like_artist"
    assert cached.copy_permission == "allow"
    assert cached.category == "emotions"


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


# ── Pleroma/Akkoma EmojiReact compatibility ──────────────────


async def test_emoji_react_custom_emoji_with_tag(db, test_user, mock_valkey):
    """Pleroma EmojiReact with custom emoji shortcode and tag metadata."""
    from app.activitypub.handlers.like import handle_emoji_react
    note = await make_note(db, test_user.actor)
    remote = await make_remote_actor(db, username="plcustom", domain="pleroma.example")
    activity = {
        "type": "EmojiReact",
        "id": "http://pleroma.example/activities/react-custom",
        "actor": remote.ap_id,
        "object": note.ap_id,
        "content": ":blobcat:",
        "tag": [
            {
                "type": "Emoji",
                "name": ":blobcat:",
                "icon": {"type": "Image", "url": "https://pleroma.example/emoji/blobcat.png"},
            },
        ],
    }
    await handle_emoji_react(db, activity)
    from sqlalchemy import select
    from app.models.reaction import Reaction
    r = (await db.execute(select(Reaction).where(Reaction.note_id == note.id))).scalar_one_or_none()
    assert r is not None
    # Stored without domain qualifier (Pleroma sends `:blobcat:` not `:blobcat@domain:`)
    assert r.emoji == ":blobcat:"
    # Custom emoji should be cached with domain derived from actor
    from app.services.emoji_service import get_custom_emoji
    cached = await get_custom_emoji(db, "blobcat", "pleroma.example")
    assert cached is not None
    assert cached.url == "https://pleroma.example/emoji/blobcat.png"


async def test_emoji_react_empty_content_defaults_heart(db, test_user, mock_valkey):
    """EmojiReact with empty content should default to heart."""
    from app.activitypub.handlers.like import handle_emoji_react
    note = await make_note(db, test_user.actor)
    remote = await make_remote_actor(db, username="plempty", domain="plempty.example")
    activity = {
        "type": "EmojiReact",
        "id": "http://plempty.example/activities/react-empty",
        "actor": remote.ap_id,
        "object": note.ap_id,
        "content": "",
    }
    await handle_emoji_react(db, activity)
    from sqlalchemy import select
    from app.models.reaction import Reaction
    r = (await db.execute(select(Reaction).where(Reaction.note_id == note.id))).scalar_one_or_none()
    assert r is not None
    assert r.emoji == "❤"


async def test_emoji_react_null_content_defaults_heart(db, test_user, mock_valkey):
    """EmojiReact with null content should default to heart."""
    from app.activitypub.handlers.like import handle_emoji_react
    note = await make_note(db, test_user.actor)
    remote = await make_remote_actor(db, username="plnull", domain="plnull.example")
    activity = {
        "type": "EmojiReact",
        "id": "http://plnull.example/activities/react-null",
        "actor": remote.ap_id,
        "object": note.ap_id,
        "content": None,
    }
    await handle_emoji_react(db, activity)
    from sqlalchemy import select
    from app.models.reaction import Reaction
    r = (await db.execute(select(Reaction).where(Reaction.note_id == note.id))).scalar_one_or_none()
    assert r is not None
    assert r.emoji == "❤"


async def test_emoji_react_zwj_compound_emoji(db, test_user, mock_valkey):
    """EmojiReact with ZWJ compound emoji (family, flag, etc.)."""
    from app.activitypub.handlers.like import handle_emoji_react
    note = await make_note(db, test_user.actor)
    remote = await make_remote_actor(db, username="plzwj", domain="plzwj.example")
    activity = {
        "type": "EmojiReact",
        "id": "http://plzwj.example/activities/react-zwj",
        "actor": remote.ap_id,
        "object": note.ap_id,
        "content": "👨‍👩‍👧‍👦",
    }
    await handle_emoji_react(db, activity)
    from sqlalchemy import select
    from app.models.reaction import Reaction
    r = (await db.execute(select(Reaction).where(Reaction.note_id == note.id))).scalar_one_or_none()
    assert r is not None
    assert r.emoji == "👨‍👩‍👧‍👦"


async def test_emoji_react_skin_tone_modifier(db, test_user, mock_valkey):
    """EmojiReact with skin tone modifier."""
    from app.activitypub.handlers.like import handle_emoji_react
    note = await make_note(db, test_user.actor)
    remote = await make_remote_actor(db, username="pltone", domain="pltone.example")
    activity = {
        "type": "EmojiReact",
        "id": "http://pltone.example/activities/react-tone",
        "actor": remote.ap_id,
        "object": note.ap_id,
        "content": "👋🏻",
    }
    await handle_emoji_react(db, activity)
    from sqlalchemy import select
    from app.models.reaction import Reaction
    r = (await db.execute(select(Reaction).where(Reaction.note_id == note.id))).scalar_one_or_none()
    assert r is not None
    assert r.emoji == "👋🏻"


async def test_emoji_react_text_content_defaults_heart(db, test_user, mock_valkey):
    """EmojiReact with plain text (not emoji) in content should default to heart."""
    from app.activitypub.handlers.like import handle_emoji_react
    note = await make_note(db, test_user.actor)
    remote = await make_remote_actor(db, username="pltext", domain="pltext.example")
    activity = {
        "type": "EmojiReact",
        "id": "http://pltext.example/activities/react-text",
        "actor": remote.ap_id,
        "object": note.ap_id,
        "content": "hello",
    }
    await handle_emoji_react(db, activity)
    from sqlalchemy import select
    from app.models.reaction import Reaction
    r = (await db.execute(select(Reaction).where(Reaction.note_id == note.id))).scalar_one_or_none()
    assert r is not None
    assert r.emoji == "❤"


async def test_emoji_react_duplicate_idempotent(db, test_user, mock_valkey):
    """Duplicate EmojiReact from same actor is idempotent."""
    from app.activitypub.handlers.like import handle_emoji_react
    note = await make_note(db, test_user.actor)
    remote = await make_remote_actor(db, username="pldup", domain="pldup.example")
    activity = {
        "type": "EmojiReact",
        "id": "http://pldup.example/activities/react-dup",
        "actor": remote.ap_id,
        "object": note.ap_id,
        "content": "🔥",
    }
    await handle_emoji_react(db, activity)
    await handle_emoji_react(db, activity)
    from sqlalchemy import select, func
    from app.models.reaction import Reaction
    count = await db.scalar(select(func.count()).where(Reaction.note_id == note.id))
    assert count == 1


async def test_emoji_react_remote_custom_emoji_with_domain(db, test_user, mock_valkey):
    """EmojiReact with domain-qualified custom emoji (:emoji@domain:)."""
    from app.activitypub.handlers.like import handle_emoji_react
    note = await make_note(db, test_user.actor)
    remote = await make_remote_actor(db, username="pldom", domain="akkoma.example")
    activity = {
        "type": "EmojiReact",
        "id": "http://akkoma.example/activities/react-dom",
        "actor": remote.ap_id,
        "object": note.ap_id,
        "content": ":neko@akkoma.example:",
        "tag": [
            {
                "type": "Emoji",
                "name": ":neko:",
                "icon": {"type": "Image", "url": "https://akkoma.example/emoji/neko.webp"},
            },
        ],
    }
    await handle_emoji_react(db, activity)
    from sqlalchemy import select
    from app.models.reaction import Reaction
    r = (await db.execute(select(Reaction).where(Reaction.note_id == note.id))).scalar_one_or_none()
    assert r is not None
    assert r.emoji == ":neko@akkoma.example:"


async def test_undo_emoji_react_without_ap_id(db, test_user, mock_valkey):
    """Undo EmojiReact falls back to actor+note lookup when no ap_id."""
    from app.activitypub.handlers.undo import handle_undo
    from sqlalchemy import select
    remote = await make_remote_actor(db, username="plundo", domain="plundo.example")
    note = await make_note(db, test_user.actor)
    from app.models.reaction import Reaction
    reaction = Reaction(actor_id=remote.id, note_id=note.id, emoji="🎉")
    db.add(reaction)
    note.reactions_count = 1
    await db.flush()
    activity = {
        "type": "Undo",
        "actor": remote.ap_id,
        "object": {
            "type": "EmojiReact",
            "actor": remote.ap_id,
            "object": note.ap_id,
            # No "id" field — Pleroma may omit it
        }
    }
    await handle_undo(db, activity)
    result = await db.execute(select(Reaction).where(Reaction.id == reaction.id))
    assert result.scalar_one_or_none() is None
    await db.refresh(note)
    assert note.reactions_count == 0
