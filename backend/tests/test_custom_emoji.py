"""Tests for custom emoji support (model, service, validation, handlers)."""


# --- is_custom_emoji_shortcode ---


def test_custom_emoji_shortcode_basic():
    from app.utils.emoji import is_custom_emoji_shortcode
    assert is_custom_emoji_shortcode(":blobcat:")
    assert is_custom_emoji_shortcode(":emoji_name:")
    assert is_custom_emoji_shortcode(":cat@remote.example:")


def test_custom_emoji_shortcode_invalid():
    from app.utils.emoji import is_custom_emoji_shortcode
    assert not is_custom_emoji_shortcode("blobcat")
    assert not is_custom_emoji_shortcode("::")
    assert not is_custom_emoji_shortcode(":invalid emoji:")
    assert not is_custom_emoji_shortcode("")


# --- CustomEmoji model ---


async def test_create_custom_emoji(db, mock_valkey):
    from app.models.custom_emoji import CustomEmoji
    emoji = CustomEmoji(
        shortcode="blobcat",
        domain=None,
        url="http://localhost/emoji/blobcat.png",
        visible_in_picker=True,
        category="blobs",
    )
    db.add(emoji)
    await db.flush()
    assert emoji.id is not None
    assert emoji.shortcode == "blobcat"
    assert emoji.domain is None


async def test_create_remote_emoji(db, mock_valkey):
    from app.models.custom_emoji import CustomEmoji
    emoji = CustomEmoji(
        shortcode="neko",
        domain="remote.example",
        url="https://remote.example/emoji/neko.png",
        visible_in_picker=False,
    )
    db.add(emoji)
    await db.flush()
    assert emoji.domain == "remote.example"
    assert emoji.visible_in_picker is False


# --- emoji_service ---


async def test_upsert_remote_emoji_create(db, mock_valkey):
    from app.services.emoji_service import get_custom_emoji, upsert_remote_emoji
    emoji = await upsert_remote_emoji(db, "newcat", "remote2.example", "https://remote2.example/emoji/newcat.png")
    assert emoji.shortcode == "newcat"
    assert emoji.domain == "remote2.example"

    found = await get_custom_emoji(db, "newcat", "remote2.example")
    assert found is not None
    assert found.id == emoji.id


async def test_upsert_remote_emoji_update(db, mock_valkey):
    from app.services.emoji_service import get_custom_emoji, upsert_remote_emoji
    await upsert_remote_emoji(db, "updatecat", "upd.example", "https://upd.example/old.png")
    emoji = await upsert_remote_emoji(db, "updatecat", "upd.example", "https://upd.example/new.png")
    assert emoji.url == "https://upd.example/new.png"

    found = await get_custom_emoji(db, "updatecat", "upd.example")
    assert found.url == "https://upd.example/new.png"


async def test_list_local_emojis(db, mock_valkey):
    from app.models.custom_emoji import CustomEmoji
    from app.services.emoji_service import list_local_emojis

    local = CustomEmoji(
        shortcode="local_cat",
        domain=None,
        url="http://localhost/emoji/local_cat.png",
        visible_in_picker=True,
    )
    remote = CustomEmoji(
        shortcode="remote_cat",
        domain="other.example",
        url="https://other.example/emoji/remote_cat.png",
        visible_in_picker=True,
    )
    hidden = CustomEmoji(
        shortcode="hidden_cat",
        domain=None,
        url="http://localhost/emoji/hidden_cat.png",
        visible_in_picker=False,
    )
    db.add_all([local, remote, hidden])
    await db.flush()

    result = await list_local_emojis(db)
    shortcodes = [e.shortcode for e in result]
    assert "local_cat" in shortcodes
    assert "remote_cat" not in shortcodes
    assert "hidden_cat" not in shortcodes


# --- API: /api/v1/custom_emojis ---


async def test_api_custom_emojis(app_client, db, mock_valkey):
    from app.models.custom_emoji import CustomEmoji
    emoji = CustomEmoji(
        shortcode="api_cat",
        domain=None,
        url="http://localhost/emoji/api_cat.png",
        visible_in_picker=True,
        category="cats",
    )
    db.add(emoji)
    await db.flush()

    resp = await app_client.get("/api/v1/custom_emojis")
    assert resp.status_code == 200
    data = resp.json()
    shortcodes = [e["shortcode"] for e in data]
    assert "api_cat" in shortcodes


# --- Like handler: custom emoji reaction ---


async def test_handle_like_custom_emoji(db, mock_valkey):
    """Like with custom emoji caches the emoji and saves the reaction."""
    from app.activitypub.handlers.like import handle_like
    from tests.conftest import make_note, make_remote_actor

    remote_actor = await make_remote_actor(db, username="emoji_reactor", domain="emoji.example")
    from app.services.user_service import create_user
    user = await create_user(db, "emoji_target", "et@test.com", "password1234")
    note = await make_note(db, user.actor, content="React to me")
    await db.commit()

    activity = {
        "id": "http://emoji.example/activities/like-emoji-1",
        "type": "Like",
        "actor": remote_actor.ap_id,
        "object": note.ap_id,
        "content": ":blobcatheart:",
        "_misskey_reaction": ":blobcatheart:",
        "tag": [
            {
                "type": "Emoji",
                "name": ":blobcatheart:",
                "icon": {"type": "Image", "url": "https://emoji.example/emoji/blobcatheart.png"},
            },
        ],
    }

    await handle_like(db, activity)

    # Verify reaction saved
    from sqlalchemy import select
    from app.models.reaction import Reaction
    result = await db.execute(
        select(Reaction).where(
            Reaction.note_id == note.id,
            Reaction.emoji == ":blobcatheart:",
        )
    )
    reaction = result.scalar_one_or_none()
    assert reaction is not None

    # Verify emoji was cached
    from app.services.emoji_service import get_custom_emoji
    cached = await get_custom_emoji(db, "blobcatheart", "emoji.example")
    assert cached is not None
    assert cached.url == "https://emoji.example/emoji/blobcatheart.png"


# --- Reaction service: custom emoji shortcode accepted ---


async def test_reaction_service_custom_emoji(db, mock_valkey):
    """add_reaction accepts custom emoji shortcodes."""
    from app.services.reaction_service import add_reaction
    from app.services.user_service import create_user
    from tests.conftest import make_note

    user = await create_user(db, "custom_react", "cr@test.com", "password1234")
    note = await make_note(db, user.actor, content="Custom reaction")

    reaction = await add_reaction(db, user, note, ":blobcat:")
    assert reaction.emoji == ":blobcat:"


# --- EmojiReact handler ---


async def test_handle_emoji_react(db, mock_valkey):
    """EmojiReact activity saves the reaction with the emoji."""
    from app.activitypub.handlers.like import handle_emoji_react
    from tests.conftest import make_note, make_remote_actor

    remote_actor = await make_remote_actor(db, username="pleroma_user", domain="pleroma.example")
    from app.services.user_service import create_user
    user = await create_user(db, "ereact_target", "ert@test.com", "password1234")
    note = await make_note(db, user.actor, content="EmojiReact test")
    await db.commit()

    activity = {
        "id": "http://pleroma.example/activities/emojireact-1",
        "type": "EmojiReact",
        "actor": remote_actor.ap_id,
        "object": note.ap_id,
        "content": "\U0001F31F",  # star
    }

    await handle_emoji_react(db, activity)

    from sqlalchemy import select
    from app.models.reaction import Reaction
    result = await db.execute(
        select(Reaction).where(Reaction.note_id == note.id)
    )
    reaction = result.scalar_one_or_none()
    assert reaction is not None
    assert reaction.emoji == "\U0001F31F"
