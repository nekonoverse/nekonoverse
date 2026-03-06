"""Tests for mention parsing in text_to_html and note creation."""


# --- sanitize.py: text_to_html mention rendering ---


def test_mention_local_user():
    """@username is rendered as a mention link."""
    from app.utils.sanitize import text_to_html
    html = text_to_html("Hello @alice")
    assert 'class="u-url mention"' in html
    assert "@<span>alice</span>" in html
    assert 'href="http://localhost/@alice"' in html


def test_mention_remote_user():
    """@user@domain is rendered as a remote mention link."""
    from app.utils.sanitize import text_to_html
    html = text_to_html("Hello @bob@remote.example")
    assert 'class="u-url mention"' in html
    assert "@<span>bob</span>" in html
    assert 'href="https://remote.example/@bob"' in html


def test_mention_inside_url_not_replaced():
    """@ signs inside URLs should not be treated as mentions."""
    from app.utils.sanitize import text_to_html
    html = text_to_html("See https://example.com/@user/status/123")
    # The URL should be auto-linked, not turned into a mention
    assert 'class="u-url mention"' not in html or "example.com/@user" in html


def test_multiple_mentions():
    """Multiple mentions in the same text."""
    from app.utils.sanitize import text_to_html
    html = text_to_html("@alice @bob@remote.example hello!")
    assert html.count("u-url mention") == 2


def test_text_with_line_breaks():
    """Line breaks are converted to <br>."""
    from app.utils.sanitize import text_to_html
    html = text_to_html("Line 1\nLine 2")
    assert "<br>" in html


# --- note_service.py: extract_mentions ---


def test_extract_mentions_local():
    from app.services.note_service import extract_mentions
    mentions = extract_mentions("Hello @alice")
    assert ("alice", None) in mentions


def test_extract_mentions_remote():
    from app.services.note_service import extract_mentions
    mentions = extract_mentions("cc @bob@remote.example")
    assert ("bob", "remote.example") in mentions


def test_extract_mentions_mixed():
    from app.services.note_service import extract_mentions
    mentions = extract_mentions("@alice @bob@remote.example text")
    assert len(mentions) == 2
    assert ("alice", None) in mentions
    assert ("bob", "remote.example") in mentions


def test_extract_mentions_none():
    from app.services.note_service import extract_mentions
    mentions = extract_mentions("No mentions here")
    assert len(mentions) == 0


# --- Create handler: mentions from tag ---


async def test_handle_create_with_mentions(db, mock_valkey):
    """Incoming Create(Note) with Mention tags saves mentions data."""
    from app.activitypub.handlers.create import handle_create
    from tests.conftest import make_remote_actor

    remote_actor = await make_remote_actor(db, username="mentioner", domain="mention.example")
    await db.commit()

    note_ap_id = "http://mention.example/notes/with-mentions"
    activity = {
        "type": "Create",
        "actor": remote_actor.ap_id,
        "object": {
            "id": note_ap_id,
            "type": "Note",
            "attributedTo": remote_actor.ap_id,
            "content": "<p>Hello <span class='h-card'><a href='http://localhost/users/testuser'>@testuser</a></span></p>",
            "published": "2026-03-06T12:00:00Z",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
            "tag": [
                {
                    "type": "Mention",
                    "href": "http://localhost/users/testuser",
                    "name": "@testuser@localhost",
                },
            ],
        },
    }

    await handle_create(db, activity)

    from app.services.note_service import get_note_by_ap_id
    note = await get_note_by_ap_id(db, note_ap_id)
    assert note is not None
    assert note.mentions is not None
    assert len(note.mentions) == 1
    assert note.mentions[0]["ap_id"] == "http://localhost/users/testuser"


# --- Renderer: Mention tags ---


async def test_render_note_with_mentions(db, mock_valkey):
    """render_note() includes Mention tags for notes with mentions."""
    from app.activitypub.renderer import render_note
    from app.services.user_service import create_user
    from tests.conftest import make_note

    user = await create_user(db, "mention_render", "mr@test.com", "password1234")
    note = await make_note(db, user.actor, content="Test")

    # Manually set mentions
    note.mentions = [
        {"ap_id": "http://remote.example/users/bob", "username": "bob", "domain": "remote.example"},
    ]
    await db.flush()

    from app.services.note_service import get_note_by_id
    note = await get_note_by_id(db, note.id)

    rendered = render_note(note)
    assert "tag" in rendered
    assert any(t["type"] == "Mention" for t in rendered["tag"])
    mention_tag = [t for t in rendered["tag"] if t["type"] == "Mention"][0]
    assert mention_tag["href"] == "http://remote.example/users/bob"
    assert "@bob@remote.example" in mention_tag["name"]
