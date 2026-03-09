"""Extended tests for actor_service — upsert_remote_actor, get_actor_public_key."""

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

from app.services.actor_service import (
    actor_uri,
    get_actor_by_ap_id,
    get_actor_by_username,
    get_actor_public_key,
    upsert_remote_actor,
)
from tests.conftest import make_remote_actor

# ── actor_uri ────────────────────────────────────────────────────────────


async def test_actor_uri_local(db, test_user):
    uri = actor_uri(test_user.actor)
    assert "/users/testuser" in uri
    assert test_user.actor.domain is None


async def test_actor_uri_remote(db):
    actor = await make_remote_actor(db, username="ruri", domain="uri.example")
    uri = actor_uri(actor)
    assert uri == actor.ap_id


# ── get_actor_by_ap_id — fallback path ──────────────────────────────────


async def test_get_actor_by_ap_id_exact_match(db):
    actor = await make_remote_actor(db, username="exact", domain="exact.example")
    found = await get_actor_by_ap_id(db, actor.ap_id)
    assert found is not None
    assert found.id == actor.id


async def test_get_actor_by_ap_id_local_fallback(db, test_user):
    """Fallback path when ap_id looks like a local URL but has scheme mismatch."""
    from app.config import settings

    # ローカルアクターURLを構築
    local_url = f"https://{settings.domain}/users/{test_user.actor.username}"
    found = await get_actor_by_ap_id(db, local_url)
    assert found is not None
    assert found.id == test_user.actor.id


async def test_get_actor_by_ap_id_not_found(db):
    found = await get_actor_by_ap_id(db, "http://nonexistent.example/users/nobody")
    assert found is None


# ── get_actor_by_username ────────────────────────────────────────────────


async def test_get_actor_by_username_local(db, test_user):
    found = await get_actor_by_username(db, test_user.actor.username)
    assert found is not None
    assert found.id == test_user.actor.id


async def test_get_actor_by_username_remote(db):
    actor = await make_remote_actor(db, username="remfind", domain="find.example")
    found = await get_actor_by_username(db, "remfind", "find.example")
    assert found is not None
    assert found.id == actor.id


async def test_get_actor_by_username_not_found(db):
    found = await get_actor_by_username(db, "nonexistent_user_xyz")
    assert found is None


# ── upsert_remote_actor — create new actor ───────────────────────────────


async def test_upsert_creates_full_actor(db):
    """Create a new remote actor with all fields populated."""
    data = {
        "id": "http://full.example/users/fulluser",
        "type": "Person",
        "preferredUsername": "fulluser",
        "name": "Full User",
        "summary": "<p>Hello world</p>",
        "inbox": "http://full.example/users/fulluser/inbox",
        "outbox": "http://full.example/users/fulluser/outbox",
        "followers": "http://full.example/users/fulluser/followers",
        "following": "http://full.example/users/fulluser/following",
        "publicKey": {"publicKeyPem": "TEST_PEM_DATA"},
        "endpoints": {"sharedInbox": "http://full.example/inbox"},
        "icon": {"type": "Image", "url": "http://full.example/avatar.png"},
        "image": {"type": "Image", "url": "http://full.example/header.png"},
        "isCat": True,
        "manuallyApprovesFollowers": True,
        "discoverable": False,
        "featured": "http://full.example/users/fulluser/collections/featured",
        "movedTo": "http://other.example/users/fulluser",
        "alsoKnownAs": ["http://other.example/users/fulluser"],
        "attachment": [
            {"type": "PropertyValue", "name": "Website", "value": "https://example.com"},
            {"type": "PropertyValue", "name": "GitHub", "value": "https://github.com/test"},
        ],
        "vcard:bday": "1990-05-15",
        "_misskey_requireSigninToViewContents": True,
        "_misskey_makeNotesFollowersOnlyBefore": 1700000000,
        "_misskey_makeNotesHiddenBefore": 1600000000,
    }
    actor = await upsert_remote_actor(db, data)
    assert actor is not None
    assert actor.username == "fulluser"
    assert actor.domain == "full.example"
    assert actor.display_name == "Full User"
    assert actor.summary is not None
    assert actor.avatar_url == "http://full.example/avatar.png"
    assert actor.header_url == "http://full.example/header.png"
    assert actor.is_cat is True
    assert actor.manually_approves_followers is True
    assert actor.discoverable is False
    assert len(actor.fields) == 2
    assert actor.birthday == date(1990, 5, 15)
    assert actor.require_signin_to_view is True
    assert actor.make_notes_followers_only_before == 1700000000
    assert actor.also_known_as == ["http://other.example/users/fulluser"]
    assert actor.moved_to_ap_id == "http://other.example/users/fulluser"
    assert actor.is_bot is False


async def test_upsert_creates_service_actor_as_bot(db):
    data = {
        "id": "http://bot.example/users/botuser",
        "type": "Service",
        "preferredUsername": "botuser",
        "inbox": "http://bot.example/users/botuser/inbox",
        "publicKey": {"publicKeyPem": "BOT_PEM"},
    }
    actor = await upsert_remote_actor(db, data)
    assert actor.is_bot is True
    assert actor.type == "Service"


async def test_upsert_creates_minimal_actor(db):
    data = {
        "id": "http://min.example/users/minuser",
        "preferredUsername": "minuser",
        "inbox": "http://min.example/users/minuser/inbox",
    }
    actor = await upsert_remote_actor(db, data)
    assert actor is not None
    assert actor.username == "minuser"
    assert actor.display_name == "minuser"
    assert actor.summary is None
    assert actor.avatar_url is None
    assert actor.header_url is None
    assert actor.public_key_pem == ""
    assert actor.fields == []
    assert actor.birthday is None
    assert actor.also_known_as is None


async def test_upsert_icon_not_dict(db):
    data = {
        "id": "http://iconstr.example/users/iconstr",
        "preferredUsername": "iconstr",
        "inbox": "http://iconstr.example/users/iconstr/inbox",
        "icon": "not-a-dict",
    }
    actor = await upsert_remote_actor(db, data)
    assert actor.avatar_url is None


async def test_upsert_also_known_as_not_list(db):
    data = {
        "id": "http://akastr.example/users/akastr",
        "preferredUsername": "akastr",
        "inbox": "http://akastr.example/users/akastr/inbox",
        "alsoKnownAs": "http://other.example/users/akastr",
    }
    actor = await upsert_remote_actor(db, data)
    assert actor.also_known_as is None


async def test_upsert_invalid_birthday(db):
    data = {
        "id": "http://bday.example/users/badbday",
        "preferredUsername": "badbday",
        "inbox": "http://bday.example/users/badbday/inbox",
        "vcard:bday": "not-a-date",
    }
    actor = await upsert_remote_actor(db, data)
    assert actor.birthday is None


async def test_upsert_publickey_not_dict(db):
    data = {
        "id": "http://nopk.example/users/nopk",
        "preferredUsername": "nopk",
        "inbox": "http://nopk.example/users/nopk/inbox",
        "publicKey": "not-a-dict",
    }
    actor = await upsert_remote_actor(db, data)
    assert actor.public_key_pem == ""


async def test_upsert_endpoints_not_dict(db):
    data = {
        "id": "http://noep.example/users/noep",
        "preferredUsername": "noep",
        "inbox": "http://noep.example/users/noep/inbox",
        "endpoints": "not-a-dict",
    }
    actor = await upsert_remote_actor(db, data)
    assert actor.shared_inbox_url is None


async def test_upsert_returns_none_for_missing_id(db):
    result = await upsert_remote_actor(db, {"preferredUsername": "noid"})
    assert result is None


async def test_upsert_returns_none_for_empty_username(db):
    result = await upsert_remote_actor(
        db,
        {
            "id": "http://empty.example/users/empty",
            "preferredUsername": "",
        },
    )
    assert result is None


async def test_upsert_returns_none_for_missing_username(db):
    result = await upsert_remote_actor(
        db,
        {
            "id": "http://nouser.example/users/nouser",
        },
    )
    assert result is None


# ── upsert_remote_actor — update existing actor ─────────────────────────


async def test_upsert_updates_all_fields(db):
    actor = await make_remote_actor(db, username="upd_all", domain="upd.example")
    original_id = actor.id

    data = {
        "id": actor.ap_id,
        "type": "Service",
        "preferredUsername": "upd_all",
        "name": "Updated Name",
        "summary": "<p>Updated summary</p>",
        "inbox": "http://upd.example/users/upd_all/inbox/new",
        "outbox": "http://upd.example/users/upd_all/outbox/new",
        "followers": "http://upd.example/users/upd_all/followers/new",
        "following": "http://upd.example/users/upd_all/following/new",
        "publicKey": {"publicKeyPem": "UPDATED_PEM"},
        "endpoints": {"sharedInbox": "http://upd.example/inbox/new"},
        "icon": {"type": "Image", "url": "http://upd.example/new_avatar.png"},
        "image": {"type": "Image", "url": "http://upd.example/new_header.png"},
        "isCat": True,
        "manuallyApprovesFollowers": True,
        "discoverable": False,
        "featured": "http://upd.example/users/upd_all/featured",
        "movedTo": "http://new.example/users/upd_all",
        "alsoKnownAs": ["http://new.example/users/upd_all"],
        "attachment": [
            {"type": "PropertyValue", "name": "Site", "value": "https://updated.com"},
        ],
        "vcard:bday": "2000-12-25",
        "_misskey_requireSigninToViewContents": True,
        "_misskey_makeNotesFollowersOnlyBefore": 9999,
        "_misskey_makeNotesHiddenBefore": 8888,
    }
    updated = await upsert_remote_actor(db, data)
    assert updated.id == original_id
    assert updated.type == "Service"
    assert updated.display_name == "Updated Name"
    assert updated.is_bot is True
    assert updated.avatar_url == "http://upd.example/new_avatar.png"
    assert updated.header_url == "http://upd.example/new_header.png"
    assert updated.is_cat is True
    assert updated.also_known_as == ["http://new.example/users/upd_all"]
    assert updated.birthday == date(2000, 12, 25)
    assert updated.require_signin_to_view is True


async def test_upsert_update_preserves_avatar_when_icon_absent(db):
    data_create = {
        "id": "http://iconkeep.example/users/iconkeep",
        "preferredUsername": "iconkeep",
        "inbox": "http://iconkeep.example/users/iconkeep/inbox",
        "icon": {"type": "Image", "url": "http://iconkeep.example/old_avatar.png"},
    }
    actor = await upsert_remote_actor(db, data_create)
    assert actor.avatar_url == "http://iconkeep.example/old_avatar.png"

    # iconフィールドがない場合、avatar_urlは更新されない
    data_update = {
        "id": actor.ap_id,
        "preferredUsername": "iconkeep",
        "name": "Updated",
        "inbox": actor.inbox_url,
    }
    updated = await upsert_remote_actor(db, data_update)
    assert updated.avatar_url == "http://iconkeep.example/old_avatar.png"


async def test_upsert_update_also_known_as_not_list_preserves_old(db):
    data_create = {
        "id": "http://akakeep.example/users/akakeep",
        "preferredUsername": "akakeep",
        "inbox": "http://akakeep.example/users/akakeep/inbox",
        "alsoKnownAs": ["http://old.example/users/akakeep"],
    }
    actor = await upsert_remote_actor(db, data_create)
    assert actor.also_known_as == ["http://old.example/users/akakeep"]

    # alsoKnownAsが文字列の場合、更新されない
    data_update = {
        "id": actor.ap_id,
        "preferredUsername": "akakeep",
        "inbox": actor.inbox_url,
        "alsoKnownAs": "http://new.example/users/akakeep",
    }
    updated = await upsert_remote_actor(db, data_update)
    assert updated.also_known_as == ["http://old.example/users/akakeep"]


async def test_upsert_attachment_filters_non_property_value(db):
    data = {
        "id": "http://mixatt.example/users/mixatt",
        "preferredUsername": "mixatt",
        "inbox": "http://mixatt.example/users/mixatt/inbox",
        "attachment": [
            {"type": "PropertyValue", "name": "Valid", "value": "Yes"},
            {"type": "IdentityProof", "name": "Invalid", "value": "No"},
            {"type": "PropertyValue", "name": "Also Valid", "value": "Indeed"},
        ],
    }
    actor = await upsert_remote_actor(db, data)
    assert len(actor.fields) == 2


# ── upsert_remote_actor — emoji tags ────────────────────────────────────


async def test_upsert_emoji_tags(db):
    data = {
        "id": "http://emoji.example/users/emojiuser",
        "preferredUsername": "emojiuser",
        "inbox": "http://emoji.example/users/emojiuser/inbox",
        "tag": [
            {
                "type": "Emoji",
                "name": ":cat:",
                "icon": {
                    "url": "http://emoji.example/emoji/cat.png",
                    "staticUrl": "http://emoji.example/emoji/cat_static.png",
                },
                "keywords": ["neko"],
                "description": "A cat emoji",
                "category": "animals",
            }
        ],
    }
    with patch(
        "app.services.emoji_service.upsert_remote_emoji",
        new_callable=AsyncMock,
    ) as mock_emoji:
        await upsert_remote_actor(db, data)
    mock_emoji.assert_called_once()
    assert mock_emoji.call_args.kwargs["shortcode"] == "cat"
    assert mock_emoji.call_args.kwargs["domain"] == "emoji.example"


async def test_upsert_emoji_tag_as_single_dict(db):
    data = {
        "id": "http://emojisingle.example/users/es",
        "preferredUsername": "es",
        "inbox": "http://emojisingle.example/users/es/inbox",
        "tag": {
            "type": "Emoji",
            "name": ":dog:",
            "icon": {"url": "http://emojisingle.example/emoji/dog.png"},
        },
    }
    with patch(
        "app.services.emoji_service.upsert_remote_emoji",
        new_callable=AsyncMock,
    ) as mock_emoji:
        await upsert_remote_actor(db, data)
    mock_emoji.assert_called_once()


async def test_upsert_emoji_tag_with_misskey_license(db):
    data = {
        "id": "http://emojilic.example/users/el",
        "preferredUsername": "el",
        "inbox": "http://emojilic.example/users/el/inbox",
        "tag": [
            {
                "type": "Emoji",
                "name": ":licensed:",
                "icon": {"url": "http://emojilic.example/emoji/lic.png"},
                "_misskey_license": {"freeText": "CC-BY-4.0"},
            }
        ],
    }
    with patch(
        "app.services.emoji_service.upsert_remote_emoji",
        new_callable=AsyncMock,
    ) as mock_emoji:
        await upsert_remote_actor(db, data)
    assert mock_emoji.call_args.kwargs["license"] == "CC-BY-4.0"


async def test_upsert_emoji_without_icon_url_skipped(db):
    data = {
        "id": "http://emojinoicon.example/users/eni",
        "preferredUsername": "eni",
        "inbox": "http://emojinoicon.example/users/eni/inbox",
        "tag": [{"type": "Emoji", "name": ":noicon:", "icon": {}}],
    }
    with patch(
        "app.services.emoji_service.upsert_remote_emoji",
        new_callable=AsyncMock,
    ) as mock_emoji:
        await upsert_remote_actor(db, data)
    mock_emoji.assert_not_called()


async def test_upsert_non_emoji_tags_ignored(db):
    data = {
        "id": "http://noemojitag.example/users/net",
        "preferredUsername": "net",
        "inbox": "http://noemojitag.example/users/net/inbox",
        "tag": [
            {"type": "Hashtag", "name": "#test"},
            {"type": "Mention", "href": "http://example.com/users/someone"},
        ],
    }
    with patch(
        "app.services.emoji_service.upsert_remote_emoji",
        new_callable=AsyncMock,
    ) as mock_emoji:
        await upsert_remote_actor(db, data)
    mock_emoji.assert_not_called()


# ── get_actor_public_key ────────────────────────────────────────────────


async def test_get_actor_public_key_found(db):
    actor = await make_remote_actor(db, username="keyactor", domain="key.example")
    actor.last_fetched_at = datetime.now(timezone.utc)
    await db.flush()

    key_id = f"{actor.ap_id}#main-key"
    found_actor, pub_key = await get_actor_public_key(db, key_id)
    assert found_actor is not None
    assert found_actor.id == actor.id
    assert pub_key != ""


async def test_get_actor_public_key_not_found(db):
    with patch(
        "app.services.actor_service.fetch_remote_actor",
        new_callable=AsyncMock,
        return_value=None,
    ):
        found_actor, pub_key = await get_actor_public_key(
            db,
            "http://nonexistent.example/users/nobody#main-key",
        )
    assert found_actor is None
    assert pub_key == ""
