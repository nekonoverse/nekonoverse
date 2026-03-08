from datetime import datetime, timezone
from types import SimpleNamespace

from app.activitypub.renderer import (
    render_accept_activity,
    render_actor,
    render_create_activity,
    render_delete_activity,
    render_follow_activity,
    render_like_activity,
    render_note,
    render_ordered_collection,
    render_ordered_collection_page,
    render_undo_activity,
)


def _make_actor(**overrides):
    defaults = dict(
        ap_id="http://localhost/users/alice", type="Person", username="alice",
        display_name="Alice", inbox_url="http://localhost/users/alice/inbox",
        outbox_url="http://localhost/users/alice/outbox",
        shared_inbox_url="http://localhost/inbox",
        followers_url="http://localhost/users/alice/followers",
        following_url="http://localhost/users/alice/following",
        public_key_pem="PUBLIC_KEY_PEM",
        is_cat=False, manually_approves_followers=False, discoverable=True,
        summary=None, avatar_url=None, header_url=None, domain=None,
        fields=None, require_signin_to_view=False,
        make_notes_followers_only_before=None, make_notes_hidden_before=None,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_note(actor=None, **overrides):
    if actor is None:
        actor = _make_actor()
    defaults = dict(
        id="test-note-id", ap_id="http://localhost/notes/test-note-id",
        content="<p>Hello</p>", source="Hello", visibility="public",
        sensitive=False, spoiler_text=None,
        to=["https://www.w3.org/ns/activitystreams#Public"],
        cc=["http://localhost/users/alice/followers"],
        published=datetime(2025, 6, 1, tzinfo=timezone.utc),
        in_reply_to_ap_id=None, actor=actor,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_render_actor_type_and_username():
    data = render_actor(_make_actor())
    assert data["type"] == "Person"
    assert data["preferredUsername"] == "alice"
    assert "@context" in data


def test_render_actor_public_key():
    from app.config import settings

    data = render_actor(_make_actor())
    assert data["publicKey"]["id"] == f"{settings.server_url}/users/alice#main-key"
    assert data["publicKey"]["publicKeyPem"] == "PUBLIC_KEY_PEM"


def test_render_actor_summary():
    data = render_actor(_make_actor(summary="Hello bio"))
    assert data["summary"] == "Hello bio"


def test_render_actor_icon():
    data = render_actor(_make_actor(avatar_url="http://example.com/avatar.png"))
    assert data["icon"]["url"] == "http://example.com/avatar.png"


def test_render_note_type_and_content():
    data = render_note(_make_note())
    assert data["type"] == "Note"
    assert data["content"] == "<p>Hello</p>"


def test_render_note_source():
    data = render_note(_make_note())
    assert data["source"]["content"] == "Hello"


def test_render_note_sensitive():
    data = render_note(_make_note(sensitive=True, spoiler_text="CW"))
    assert data["sensitive"] is True
    assert data["summary"] == "CW"


def test_render_create_activity():
    note = _make_note()
    data = render_create_activity(note)
    assert data["type"] == "Create"
    assert data["object"]["type"] == "Note"


def test_render_like_activity_misskey():
    data = render_like_activity("act-id", "actor-id", "note-id", "\U0001f600")
    assert data["type"] == "Like"
    assert data["_misskey_reaction"] == "\U0001f600"
    assert data["content"] == "\U0001f600"


def test_render_follow_activity():
    data = render_follow_activity("act-id", "actor-id", "target-id")
    assert data["type"] == "Follow"
    assert data["object"] == "target-id"


def test_render_undo_activity():
    inner = {"type": "Follow", "actor": "a", "object": "b"}
    data = render_undo_activity("undo-id", "actor-id", inner)
    assert data["type"] == "Undo"
    assert data["object"] == inner


def test_render_note_emoji_tags():
    """Note with _emoji_tags should render Emoji tags in AP output."""
    note = _make_note()
    note._emoji_tags = [
        {
            "shortcode": "neko_smile",
            "url": "http://localhost/emoji/neko_smile.png",
            "aliases": ["neko", "smile"],
            "license": "CC-BY-4.0",
            "is_sensitive": False,
            "author": "neko_artist",
            "description": "A smiling neko",
            "copy_permission": "allow",
            "usage_info": None,
            "is_based_on": None,
            "category": "neko",
        },
    ]
    data = render_note(note)
    assert "tag" in data
    emoji_tags = [t for t in data["tag"] if t.get("type") == "Emoji"]
    assert len(emoji_tags) == 1
    et = emoji_tags[0]
    assert et["name"] == ":neko_smile:"
    assert et["icon"]["url"] == "http://localhost/emoji/neko_smile.png"
    assert et["icon"]["mediaType"] == "image/png"
    assert et["_misskey_license"] == {"freeText": "CC-BY-4.0"}
    assert et["license"] == "CC-BY-4.0"
    assert et["keywords"] == ["neko", "smile"]
    assert et["author"] == "neko_artist"
    assert et["description"] == "A smiling neko"
    assert et["copyPermission"] == "allow"
    assert et["category"] == "neko"
    assert "isSensitive" not in et  # False -> omitted
    assert "usageInfo" not in et  # None -> omitted
    assert "isBasedOn" not in et  # None -> omitted


def test_render_note_emoji_tags_empty():
    """Note without _emoji_tags should not have Emoji tags."""
    note = _make_note()
    data = render_note(note)
    # No mentions and no emoji -> no tag key
    assert "tag" not in data


def test_render_ordered_collection():
    data = render_ordered_collection("col-id", 42, "page-1")
    assert data["type"] == "OrderedCollection"
    assert data["totalItems"] == 42
    assert data["first"] == "page-1"
