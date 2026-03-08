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


async def test_create_local_emoji(db, mock_valkey):
    from app.services.emoji_service import create_local_emoji
    emoji = await create_local_emoji(
        db, shortcode="local_new", url="http://localhost/emoji/local_new.png",
        category="test", aliases=["ln"], license="CC0",
        author="artist", description="A test emoji",
        copy_permission="allow", is_sensitive=False,
    )
    assert emoji.shortcode == "local_new"
    assert emoji.domain is None
    assert emoji.visible_in_picker is True
    assert emoji.aliases == ["ln"]
    assert emoji.license == "CC0"
    assert emoji.author == "artist"
    assert emoji.copy_permission == "allow"


async def test_update_emoji(db, mock_valkey):
    from app.services.emoji_service import create_local_emoji, update_emoji
    emoji = await create_local_emoji(db, "upd_svc", "http://localhost/emoji/upd.png")
    updated = await update_emoji(db, emoji.id, {"category": "new_cat", "license": "MIT"})
    assert updated is not None
    assert updated.category == "new_cat"
    assert updated.license == "MIT"


async def test_update_emoji_not_found(db, mock_valkey):
    import uuid
    from app.services.emoji_service import update_emoji
    result = await update_emoji(db, uuid.uuid4(), {"category": "x"})
    assert result is None


async def test_delete_emoji(db, mock_valkey):
    from app.services.emoji_service import create_local_emoji, delete_emoji, get_emoji_by_id
    emoji = await create_local_emoji(db, "del_svc", "http://localhost/emoji/del.png")
    assert await delete_emoji(db, emoji.id) is True
    assert await get_emoji_by_id(db, emoji.id) is None


async def test_delete_emoji_not_found(db, mock_valkey):
    import uuid
    from app.services.emoji_service import delete_emoji
    assert await delete_emoji(db, uuid.uuid4()) is False


async def test_list_all_local_emojis(db, mock_valkey):
    from app.models.custom_emoji import CustomEmoji
    from app.services.emoji_service import list_all_local_emojis

    visible = CustomEmoji(
        shortcode="all_visible", domain=None,
        url="http://localhost/emoji/vis.png", visible_in_picker=True,
    )
    hidden = CustomEmoji(
        shortcode="all_hidden", domain=None,
        url="http://localhost/emoji/hid.png", visible_in_picker=False,
    )
    remote = CustomEmoji(
        shortcode="all_remote", domain="other.example",
        url="http://other.example/emoji/r.png",
    )
    db.add_all([visible, hidden, remote])
    await db.flush()

    result = await list_all_local_emojis(db)
    shortcodes = [e.shortcode for e in result]
    assert "all_visible" in shortcodes
    assert "all_hidden" in shortcodes  # list_all includes hidden
    assert "all_remote" not in shortcodes


async def test_upsert_remote_emoji_extended_fields(db, mock_valkey):
    from app.services.emoji_service import get_custom_emoji, upsert_remote_emoji
    emoji = await upsert_remote_emoji(
        db, "ext_emoji", "ext.example", "https://ext.example/emoji/ext.png",
        aliases=["alias1", "alias2"],
        license="CC-BY-SA",
        is_sensitive=True,
        author="remote_artist",
        description="A remote emoji",
        copy_permission="conditional",
        usage_info="Ask before use",
        is_based_on="https://original.example/emoji",
        category="remote_cat",
    )
    assert emoji.aliases == ["alias1", "alias2"]
    assert emoji.license == "CC-BY-SA"
    assert emoji.is_sensitive is True
    assert emoji.author == "remote_artist"
    assert emoji.copy_permission == "conditional"
    assert emoji.category == "remote_cat"

    found = await get_custom_emoji(db, "ext_emoji", "ext.example")
    assert found.usage_info == "Ask before use"
    assert found.is_based_on == "https://original.example/emoji"


# --- get_emojis_by_shortcodes ---


async def test_get_emojis_by_shortcodes_basic(db, mock_valkey):
    from app.services.emoji_service import create_local_emoji, get_emojis_by_shortcodes
    await create_local_emoji(db, "batch_a", "http://localhost/emoji/a.png")
    await create_local_emoji(db, "batch_b", "http://localhost/emoji/b.png")
    await db.flush()

    result = await get_emojis_by_shortcodes(db, {"batch_a", "batch_b"})
    shortcodes = {e.shortcode for e in result}
    assert shortcodes == {"batch_a", "batch_b"}


async def test_get_emojis_by_shortcodes_empty(db, mock_valkey):
    from app.services.emoji_service import get_emojis_by_shortcodes
    result = await get_emojis_by_shortcodes(db, set())
    assert result == []


async def test_get_emojis_by_shortcodes_partial(db, mock_valkey):
    """Only existing shortcodes are returned, missing ones are silently ignored."""
    from app.services.emoji_service import create_local_emoji, get_emojis_by_shortcodes
    await create_local_emoji(db, "exists_one", "http://localhost/emoji/e.png")
    await db.flush()

    result = await get_emojis_by_shortcodes(db, {"exists_one", "nonexistent"})
    assert len(result) == 1
    assert result[0].shortcode == "exists_one"


async def test_get_emojis_by_shortcodes_domain_filter(db, mock_valkey):
    """Shortcodes are filtered by domain."""
    from app.services.emoji_service import create_local_emoji, get_emojis_by_shortcodes, upsert_remote_emoji
    await create_local_emoji(db, "same_code", "http://localhost/emoji/local.png")
    await upsert_remote_emoji(db, "same_code", "remote.example", "https://remote.example/emoji/remote.png")
    await db.flush()

    local = await get_emojis_by_shortcodes(db, {"same_code"}, None)
    assert len(local) == 1
    assert local[0].url == "http://localhost/emoji/local.png"

    remote = await get_emojis_by_shortcodes(db, {"same_code"}, "remote.example")
    assert len(remote) == 1
    assert remote[0].url == "https://remote.example/emoji/remote.png"


# --- note_to_response: emojis field ---


async def test_note_response_includes_emojis(db, mock_valkey):
    """note_to_response populates emojis field for notes with custom emoji shortcodes."""
    from app.api.mastodon.statuses import note_to_response
    from app.services.emoji_service import create_local_emoji
    from app.services.user_service import create_user
    from tests.conftest import make_note

    await create_local_emoji(db, "testcat", "http://localhost/emoji/testcat.png")
    user = await create_user(db, "emoji_note_user", "enu@test.com", "password1234")
    note = await make_note(db, user.actor, content="Hello :testcat: world")
    await db.commit()
    await db.refresh(note, ["actor", "attachments"])

    resp = await note_to_response(note, db=db)
    assert len(resp.emojis) == 1
    assert resp.emojis[0].shortcode == "testcat"
    assert resp.emojis[0].url is not None


async def test_note_response_emojis_empty_when_no_match(db, mock_valkey):
    """Notes without custom emoji shortcodes have empty emojis list."""
    from app.api.mastodon.statuses import note_to_response
    from app.services.user_service import create_user
    from tests.conftest import make_note

    user = await create_user(db, "no_emoji_user", "neu@test.com", "password1234")
    note = await make_note(db, user.actor, content="No emojis here")
    await db.commit()
    await db.refresh(note, ["actor", "attachments"])

    resp = await note_to_response(note, db=db)
    assert resp.emojis == []


async def test_note_response_remote_emoji_preferred(db, mock_valkey):
    """For remote notes, remote domain emoji is preferred over local."""
    from app.api.mastodon.statuses import note_to_response
    from app.models.note import Note
    from app.services.emoji_service import create_local_emoji, upsert_remote_emoji
    from tests.conftest import make_remote_actor

    await create_local_emoji(db, "sharedcat", "http://localhost/emoji/local_shared.png")
    await upsert_remote_emoji(
        db, "sharedcat", "other.example", "https://other.example/emoji/remote_shared.png",
    )

    remote_actor = await make_remote_actor(db, username="emoji_poster", domain="other.example")

    import uuid
    note_id = uuid.uuid4()
    note = Note(
        id=note_id,
        ap_id=f"http://other.example/notes/{note_id}",
        actor_id=remote_actor.id,
        content="<p>Look :sharedcat: cute</p>",
        source="Look :sharedcat: cute",
        visibility="public",
        to=["https://www.w3.org/ns/activitystreams#Public"],
        cc=[],
        local=False,
    )
    db.add(note)
    await db.flush()
    await db.refresh(note, ["actor", "attachments"])

    resp = await note_to_response(note, db=db)
    assert len(resp.emojis) == 1
    assert resp.emojis[0].shortcode == "sharedcat"
    # Should use the remote emoji URL, not local
    assert "remote_shared" in resp.emojis[0].url or "other.example" in resp.emojis[0].url


async def test_note_response_remote_fallback_to_local(db, mock_valkey):
    """For remote notes, if remote emoji not found, fall back to local."""
    from app.api.mastodon.statuses import note_to_response
    from app.models.note import Note
    from app.services.emoji_service import create_local_emoji
    from tests.conftest import make_remote_actor

    await create_local_emoji(db, "localonly", "http://localhost/emoji/localonly.png")
    remote_actor = await make_remote_actor(db, username="fb_poster", domain="fb.example")

    import uuid
    note_id = uuid.uuid4()
    note = Note(
        id=note_id,
        ap_id=f"http://fb.example/notes/{note_id}",
        actor_id=remote_actor.id,
        content="<p>Check :localonly:</p>",
        source="Check :localonly:",
        visibility="public",
        to=["https://www.w3.org/ns/activitystreams#Public"],
        cc=[],
        local=False,
    )
    db.add(note)
    await db.flush()
    await db.refresh(note, ["actor", "attachments"])

    resp = await note_to_response(note, db=db)
    assert len(resp.emojis) == 1
    assert resp.emojis[0].shortcode == "localonly"


# --- get_reaction_summary: remote emoji resolution ---


async def test_reaction_summary_resolves_remote_emoji_without_domain(db, mock_valkey):
    """When reaction emoji is ':blobcat:' (no domain, as Misskey sends it),
    get_reaction_summary should find the remote-cached emoji."""
    from app.models.reaction import Reaction
    from app.services.emoji_service import upsert_remote_emoji
    from app.services.note_service import get_reaction_summary
    from app.services.user_service import create_user
    from tests.conftest import make_note, make_remote_actor

    # Cache a remote emoji (as the like handler would)
    await upsert_remote_emoji(
        db, "remotereact", "misskey.example",
        "https://misskey.example/emoji/remotereact.png",
    )

    user = await create_user(db, "rxn_target", "rxn@test.com", "password1234")
    note = await make_note(db, user.actor, content="Hello")
    remote_actor = await make_remote_actor(db, username="rxn_sender", domain="misskey.example")

    # Store reaction as ":remotereact:" (no domain — Misskey format)
    reaction = Reaction(
        actor_id=remote_actor.id,
        note_id=note.id,
        emoji=":remotereact:",
    )
    db.add(reaction)
    await db.flush()

    summary = await get_reaction_summary(db, note.id)
    assert len(summary) == 1
    assert summary[0]["emoji"] == ":remotereact:"
    assert summary[0]["emoji_url"] != ""
    assert "remotereact" in summary[0]["emoji_url"]


async def test_reaction_summary_prefers_local_over_remote(db, mock_valkey):
    """When both local and remote emoji exist with same shortcode,
    local version should be preferred."""
    from app.models.reaction import Reaction
    from app.services.emoji_service import create_local_emoji, upsert_remote_emoji
    from app.services.note_service import get_reaction_summary
    from app.services.user_service import create_user
    from tests.conftest import make_note, make_remote_actor

    await create_local_emoji(db, "dupreact", "http://localhost/emoji/dupreact_local.png")
    await upsert_remote_emoji(
        db, "dupreact", "remote.example",
        "https://remote.example/emoji/dupreact_remote.png",
    )

    user = await create_user(db, "rxn_dup_target", "rxndup@test.com", "password1234")
    note = await make_note(db, user.actor, content="Test")
    remote_actor = await make_remote_actor(db, username="rxn_dup_sender", domain="remote.example")

    reaction = Reaction(
        actor_id=remote_actor.id,
        note_id=note.id,
        emoji=":dupreact:",
    )
    db.add(reaction)
    await db.flush()

    summary = await get_reaction_summary(db, note.id)
    assert len(summary) == 1
    # Should use local emoji URL
    assert "dupreact_local" in summary[0]["emoji_url"]


async def test_reaction_summary_with_domain_in_emoji(db, mock_valkey):
    """When reaction emoji has domain (e.g. ':cat@other.example:'),
    get_reaction_summary should find the remote emoji by domain."""
    from app.models.reaction import Reaction
    from app.services.emoji_service import upsert_remote_emoji
    from app.services.note_service import get_reaction_summary
    from app.services.user_service import create_user
    from tests.conftest import make_note, make_remote_actor

    await upsert_remote_emoji(
        db, "domcat", "other.example",
        "https://other.example/emoji/domcat.png",
    )

    user = await create_user(db, "rxn_dom_target", "rxndom@test.com", "password1234")
    note = await make_note(db, user.actor, content="Test")
    remote_actor = await make_remote_actor(db, username="rxn_dom_sender", domain="other.example")

    reaction = Reaction(
        actor_id=remote_actor.id,
        note_id=note.id,
        emoji=":domcat@other.example:",
    )
    db.add(reaction)
    await db.flush()

    summary = await get_reaction_summary(db, note.id)
    assert len(summary) == 1
    assert summary[0]["emoji_url"] != ""
    assert "domcat" in summary[0]["emoji_url"]


# --- import-by-shortcode endpoint ---


async def test_import_by_shortcode_finds_remote(db, app_client, mock_valkey):
    """Admin endpoint finds the remote emoji and imports it successfully."""
    from unittest.mock import AsyncMock, patch

    from app.models.custom_emoji import CustomEmoji
    from app.services.emoji_service import upsert_remote_emoji
    from app.services.user_service import create_user

    admin = await create_user(db, "imp_admin", "impadm@test.com", "password1234")
    admin.role = "admin"
    await db.flush()

    await upsert_remote_emoji(
        db, "importme", "remote.example",
        "https://remote.example/emoji/importme.png",
    )
    await db.commit()

    mock_valkey.get = AsyncMock(return_value=str(admin.id))
    app_client.cookies.set("nekonoverse_session", "test-session-id")

    async def fake_import(db_session, emoji_id):
        local = CustomEmoji(
            shortcode="importme",
            domain=None,
            url="https://local.example/emoji/importme.png",
        )
        db_session.add(local)
        await db_session.flush()
        return local

    with patch(
        "app.services.emoji_service.import_remote_emoji_to_local",
        side_effect=fake_import,
    ):
        resp = await app_client.post(
            "/api/v1/admin/emoji/import-by-shortcode",
            json={"shortcode": "importme", "domain": "remote.example"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["shortcode"] == "importme"


async def test_import_by_shortcode_not_found(db, app_client, mock_valkey):
    """Returns 404 when remote emoji not found."""
    from unittest.mock import AsyncMock

    from app.services.user_service import create_user

    admin = await create_user(db, "imp_admin2", "impadm2@test.com", "password1234")
    admin.role = "admin"
    await db.flush()
    await db.commit()

    mock_valkey.get = AsyncMock(return_value=str(admin.id))
    app_client.cookies.set("nekonoverse_session", "test-session-id")

    resp = await app_client.post(
        "/api/v1/admin/emoji/import-by-shortcode",
        json={"shortcode": "nonexistent", "domain": "nowhere.example"},
    )
    assert resp.status_code == 404


async def test_import_by_shortcode_non_admin_forbidden(db, app_client, mock_valkey):
    """Non-admin users get 403."""
    from unittest.mock import AsyncMock

    from app.services.user_service import create_user

    user = await create_user(db, "imp_user", "impusr@test.com", "password1234")
    await db.commit()

    mock_valkey.get = AsyncMock(return_value=str(user.id))
    app_client.cookies.set("nekonoverse_session", "test-session-id")

    resp = await app_client.post(
        "/api/v1/admin/emoji/import-by-shortcode",
        json={"shortcode": "test", "domain": "test.example"},
    )
    assert resp.status_code == 403


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
