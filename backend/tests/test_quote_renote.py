"""Tests for quote renote (Misskey-style quoting)."""

import uuid

from tests.conftest import make_note, make_remote_actor


# --- Note model: quote fields ---


async def test_note_quote_fields(db, mock_valkey):
    """Note model has quote_id and quote_ap_id fields."""
    from app.services.user_service import create_user
    user = await create_user(db, "quote_user", "qu@test.com", "password1234")
    original = await make_note(db, user.actor, content="Original post")

    quote_id = uuid.uuid4()
    from app.models.note import Note
    quote = Note(
        id=quote_id,
        ap_id=f"http://localhost/notes/{quote_id}",
        actor_id=user.actor.id,
        content="<p>Quoting this</p>",
        source="Quoting this",
        visibility="public",
        to=["https://www.w3.org/ns/activitystreams#Public"],
        cc=[],
        local=True,
        quote_id=original.id,
        quote_ap_id=original.ap_id,
    )
    db.add(quote)
    await db.flush()

    assert quote.quote_id == original.id
    assert quote.quote_ap_id == original.ap_id


# --- API: create status with quote_id ---


async def test_create_status_with_quote(authed_client, mock_valkey):
    """Creating a status with quote_id includes the quoted note."""
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Original to quote", "visibility": "public"
    })
    original_id = create_resp.json()["id"]

    resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Quoting this!",
        "visibility": "public",
        "quote_id": original_id,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["quote"] is not None
    assert data["quote"]["id"] == original_id


async def test_create_status_with_invalid_quote(authed_client, mock_valkey):
    """quote_id pointing to nonexistent note is silently ignored."""
    resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Bad quote",
        "visibility": "public",
        "quote_id": str(uuid.uuid4()),
    })
    assert resp.status_code == 201
    assert resp.json()["quote"] is None


# --- AP renderer: _misskey_quote and quoteUrl ---


async def test_render_note_with_quote(db, mock_valkey):
    """render_note() outputs _misskey_quote and quoteUrl."""
    from app.activitypub.renderer import render_note
    from app.services.user_service import create_user

    user = await create_user(db, "render_quote", "rq@test.com", "password1234")
    original = await make_note(db, user.actor, content="Original")

    quote_id = uuid.uuid4()
    from app.models.note import Note
    quote = Note(
        id=quote_id,
        ap_id=f"http://localhost/notes/{quote_id}",
        actor_id=user.actor.id,
        content="<p>Quote</p>",
        source="Quote",
        visibility="public",
        to=["https://www.w3.org/ns/activitystreams#Public"],
        cc=[],
        local=True,
        quote_id=original.id,
        quote_ap_id=original.ap_id,
    )
    db.add(quote)
    await db.flush()

    from app.services.note_service import get_note_by_id
    quote = await get_note_by_id(db, quote_id)

    rendered = render_note(quote)
    assert rendered["_misskey_quote"] == original.ap_id
    assert rendered["quoteUrl"] == original.ap_id


# --- Incoming Create with quote ---


async def test_handle_create_with_misskey_quote(db, mock_valkey):
    """Incoming note with _misskey_quote resolves quote_id."""
    from app.activitypub.handlers.create import handle_create
    from app.services.user_service import create_user

    # Create a local note that will be quoted
    user = await create_user(db, "quoted_user", "qusr@test.com", "password1234")
    local_note = await make_note(db, user.actor, content="Quote me")

    remote_actor = await make_remote_actor(db, username="quoter", domain="quote.example")
    await db.commit()

    note_ap_id = "http://quote.example/notes/with-quote"
    activity = {
        "type": "Create",
        "actor": remote_actor.ap_id,
        "object": {
            "id": note_ap_id,
            "type": "Note",
            "attributedTo": remote_actor.ap_id,
            "content": "<p>RE: Quote me</p>",
            "published": "2026-03-06T12:00:00Z",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
            "_misskey_quote": local_note.ap_id,
        },
    }

    await handle_create(db, activity)

    from app.services.note_service import get_note_by_ap_id
    note = await get_note_by_ap_id(db, note_ap_id)
    assert note is not None
    assert note.quote_id == local_note.id
    assert note.quote_ap_id == local_note.ap_id


async def test_handle_create_with_quoteUrl(db, mock_valkey):
    """Incoming note with quoteUrl (no _misskey_quote) resolves quote."""
    from app.activitypub.handlers.create import handle_create
    from app.services.user_service import create_user

    user = await create_user(db, "quoted_user2", "qusr2@test.com", "password1234")
    local_note = await make_note(db, user.actor, content="Quote me too")

    remote_actor = await make_remote_actor(db, username="quoter2", domain="quote2.example")
    await db.commit()

    note_ap_id = "http://quote2.example/notes/with-quoteurl"
    activity = {
        "type": "Create",
        "actor": remote_actor.ap_id,
        "object": {
            "id": note_ap_id,
            "type": "Note",
            "attributedTo": remote_actor.ap_id,
            "content": "<p>RE: Quote me too</p>",
            "published": "2026-03-06T12:00:00Z",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
            "quoteUrl": local_note.ap_id,
        },
    }

    await handle_create(db, activity)

    from app.services.note_service import get_note_by_ap_id
    note = await get_note_by_ap_id(db, note_ap_id)
    assert note is not None
    assert note.quote_id == local_note.id


# --- _misskey_content ---


async def test_handle_create_misskey_content_fallback(db, mock_valkey):
    """Incoming note uses _misskey_content as source fallback."""
    from app.activitypub.handlers.create import handle_create

    remote_actor = await make_remote_actor(db, username="misskey_user", domain="misskey.example")
    await db.commit()

    note_ap_id = "http://misskey.example/notes/misskey-content"
    activity = {
        "type": "Create",
        "actor": remote_actor.ap_id,
        "object": {
            "id": note_ap_id,
            "type": "Note",
            "attributedTo": remote_actor.ap_id,
            "content": "<p>Hello <b>world</b></p>",
            "_misskey_content": "Hello **world**",
            "published": "2026-03-06T12:00:00Z",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
        },
    }

    await handle_create(db, activity)

    from app.services.note_service import get_note_by_ap_id
    note = await get_note_by_ap_id(db, note_ap_id)
    assert note is not None
    assert note.source == "Hello **world**"


async def test_render_note_includes_misskey_content(db, mock_valkey):
    """render_note() includes _misskey_content when source is present."""
    from app.activitypub.renderer import render_note
    from app.services.user_service import create_user

    user = await create_user(db, "misskey_render", "mkr@test.com", "password1234")
    note = await make_note(db, user.actor, content="Plain text source")

    from app.services.note_service import get_note_by_id
    note = await get_note_by_id(db, note.id)

    rendered = render_note(note)
    assert "_misskey_content" in rendered
    assert rendered["_misskey_content"] == note.source
    assert rendered["source"]["content"] == note.source
    assert rendered["source"]["mediaType"] == "text/plain"


async def test_handle_create_source_takes_priority(db, mock_valkey):
    """When both source and _misskey_content are present, source wins."""
    from app.activitypub.handlers.create import handle_create

    remote_actor = await make_remote_actor(db, username="both_src", domain="both.example")
    await db.commit()

    note_ap_id = "http://both.example/notes/both-source"
    activity = {
        "type": "Create",
        "actor": remote_actor.ap_id,
        "object": {
            "id": note_ap_id,
            "type": "Note",
            "attributedTo": remote_actor.ap_id,
            "content": "<p>Content</p>",
            "source": {"content": "From source field", "mediaType": "text/plain"},
            "_misskey_content": "From misskey_content",
            "published": "2026-03-06T12:00:00Z",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
        },
    }

    await handle_create(db, activity)

    from app.services.note_service import get_note_by_ap_id
    note = await get_note_by_ap_id(db, note_ap_id)
    assert note.source == "From source field"


async def test_handle_create_source_html_mediatype_ignored(db, mock_valkey):
    """source with mediaType text/html should NOT be stored as MFM source."""
    from app.activitypub.handlers.create import handle_create

    remote_actor = await make_remote_actor(db, username="html_src", domain="html.example")
    await db.commit()

    note_ap_id = "http://html.example/notes/html-source"
    activity = {
        "type": "Create",
        "actor": remote_actor.ap_id,
        "object": {
            "id": note_ap_id,
            "type": "Note",
            "attributedTo": remote_actor.ap_id,
            "content": "<p>Hello <b>world</b></p>",
            "source": {"content": "<p>Hello <b>world</b></p>", "mediaType": "text/html"},
            "published": "2026-03-06T12:00:00Z",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
        },
    }

    await handle_create(db, activity)

    from app.services.note_service import get_note_by_ap_id
    note = await get_note_by_ap_id(db, note_ap_id)
    assert note is not None
    assert note.source is None


async def test_handle_create_source_bbcode_mediatype_ignored(db, mock_valkey):
    """source with mediaType text/bbcode should NOT be stored as MFM source."""
    from app.activitypub.handlers.create import handle_create

    remote_actor = await make_remote_actor(db, username="bb_src", domain="bb.example")
    await db.commit()

    note_ap_id = "http://bb.example/notes/bbcode-source"
    activity = {
        "type": "Create",
        "actor": remote_actor.ap_id,
        "object": {
            "id": note_ap_id,
            "type": "Note",
            "attributedTo": remote_actor.ap_id,
            "content": "<p>Hello <b>world</b></p>",
            "source": {"content": "[b]Hello[/b] world", "mediaType": "text/bbcode"},
            "published": "2026-03-06T12:00:00Z",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
        },
    }

    await handle_create(db, activity)

    from app.services.note_service import get_note_by_ap_id
    note = await get_note_by_ap_id(db, note_ap_id)
    assert note is not None
    assert note.source is None


async def test_handle_create_source_mfm_mediatype_stored(db, mock_valkey):
    """source with mediaType text/x.misskeymarkdown should be stored."""
    from app.activitypub.handlers.create import handle_create

    remote_actor = await make_remote_actor(db, username="mfm_src", domain="mfm.example")
    await db.commit()

    note_ap_id = "http://mfm.example/notes/mfm-source"
    activity = {
        "type": "Create",
        "actor": remote_actor.ap_id,
        "object": {
            "id": note_ap_id,
            "type": "Note",
            "attributedTo": remote_actor.ap_id,
            "content": "<p>Hello <b>world</b></p>",
            "source": {"content": "Hello **world**", "mediaType": "text/x.misskeymarkdown"},
            "published": "2026-03-06T12:00:00Z",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
        },
    }

    await handle_create(db, activity)

    from app.services.note_service import get_note_by_ap_id
    note = await get_note_by_ap_id(db, note_ap_id)
    assert note is not None
    assert note.source == "Hello **world**"


async def test_handle_create_source_no_mediatype_stored(db, mock_valkey):
    """source without mediaType should be stored (defaults to MFM-safe)."""
    from app.activitypub.handlers.create import handle_create

    remote_actor = await make_remote_actor(db, username="nomt_src", domain="nomt.example")
    await db.commit()

    note_ap_id = "http://nomt.example/notes/no-mediatype"
    activity = {
        "type": "Create",
        "actor": remote_actor.ap_id,
        "object": {
            "id": note_ap_id,
            "type": "Note",
            "attributedTo": remote_actor.ap_id,
            "content": "<p>Hello world</p>",
            "source": {"content": "Hello world"},
            "published": "2026-03-06T12:00:00Z",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
        },
    }

    await handle_create(db, activity)

    from app.services.note_service import get_note_by_ap_id
    note = await get_note_by_ap_id(db, note_ap_id)
    assert note is not None
    assert note.source == "Hello world"


async def test_handle_create_html_source_misskey_fallback(db, mock_valkey):
    """When source is text/html but _misskey_content exists, use _misskey_content."""
    from app.activitypub.handlers.create import handle_create

    remote_actor = await make_remote_actor(db, username="htmlmk", domain="htmlmk.example")
    await db.commit()

    note_ap_id = "http://htmlmk.example/notes/html-with-misskey"
    activity = {
        "type": "Create",
        "actor": remote_actor.ap_id,
        "object": {
            "id": note_ap_id,
            "type": "Note",
            "attributedTo": remote_actor.ap_id,
            "content": "<p>Hello</p>",
            "source": {"content": "<p>Hello</p>", "mediaType": "text/html"},
            "_misskey_content": "Hello",
            "published": "2026-03-06T12:00:00Z",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
        },
    }

    await handle_create(db, activity)

    from app.services.note_service import get_note_by_ap_id
    note = await get_note_by_ap_id(db, note_ap_id)
    assert note is not None
    assert note.source == "Hello"


# --- resolve_source_media_type ---


def test_resolve_source_media_type_auto_plain():
    """Auto mode with plain text returns text/plain."""
    from app.activitypub import resolve_source_media_type
    assert resolve_source_media_type("Hello world") == "text/plain"


def test_resolve_source_media_type_auto_mfm():
    """Auto mode with MFM function syntax returns text/x.misskeymarkdown."""
    from app.activitypub import resolve_source_media_type
    assert resolve_source_media_type("$[spin Hello]") == "text/x.misskeymarkdown"


def test_resolve_source_media_type_pref_mfm():
    """Preference mfm always returns text/x.misskeymarkdown."""
    from app.activitypub import resolve_source_media_type
    assert resolve_source_media_type("Hello", {"source_media_type": "mfm"}) == "text/x.misskeymarkdown"


def test_resolve_source_media_type_pref_plain():
    """Preference plain always returns text/plain."""
    from app.activitypub import resolve_source_media_type
    assert resolve_source_media_type("$[spin Hello]", {"source_media_type": "plain"}) == "text/plain"


# --- Incoming Create with Emoji tags ---


async def test_handle_create_caches_custom_emoji(db, mock_valkey):
    """Incoming note with Emoji tags caches the custom emojis."""
    from app.activitypub.handlers.create import handle_create

    remote_actor = await make_remote_actor(db, username="emoji_note", domain="emonote.example")
    await db.commit()

    note_ap_id = "http://emonote.example/notes/with-emoji"
    activity = {
        "type": "Create",
        "actor": remote_actor.ap_id,
        "object": {
            "id": note_ap_id,
            "type": "Note",
            "attributedTo": remote_actor.ap_id,
            "content": "<p>:nyancat: is cute</p>",
            "published": "2026-03-06T12:00:00Z",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
            "tag": [
                {
                    "type": "Emoji",
                    "name": ":nyancat:",
                    "icon": {"type": "Image", "url": "https://emonote.example/emoji/nyancat.gif"},
                },
            ],
        },
    }

    await handle_create(db, activity)

    from app.services.emoji_service import get_custom_emoji
    cached = await get_custom_emoji(db, "nyancat", "emonote.example")
    assert cached is not None
    assert cached.url == "https://emonote.example/emoji/nyancat.gif"
