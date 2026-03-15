"""Tests for fetch_remote_note — remote note ingestion from ActivityPub."""

from unittest.mock import AsyncMock, MagicMock, patch

from app.services.note_service import fetch_remote_note
from tests.conftest import make_note, make_remote_actor

_SIGNED_GET_PATCH = "app.services.actor_service._signed_get"


def _mock_response(data: dict, status_code: int = 200):
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    return resp


def _ap_note_data(
    ap_id: str,
    actor_ap_id: str,
    *,
    content: str = "<p>Hello from remote</p>",
    visibility: str = "public",
    source: dict | None = None,
    misskey_content: str | None = None,
    summary: str | None = None,
    sensitive: bool = False,
    in_reply_to: str | None = None,
    tags: list | None = None,
    attachments: list | None = None,
    published: str | None = "2025-01-01T00:00:00Z",
    obj_type: str = "Note",
    poll_choices: list | None = None,
    end_time: str | None = None,
    quote_url: str | None = None,
) -> dict:
    """Build a minimal AP Note JSON-LD payload."""
    public = "https://www.w3.org/ns/activitystreams#Public"
    if visibility == "public":
        to_list = [public]
        cc_list = [f"{actor_ap_id}/followers"]
    elif visibility == "unlisted":
        to_list = [f"{actor_ap_id}/followers"]
        cc_list = [public]
    elif visibility == "followers":
        to_list = [f"{actor_ap_id}/followers"]
        cc_list = []
    else:
        to_list = []
        cc_list = []

    data = {
        "type": obj_type,
        "id": ap_id,
        "attributedTo": actor_ap_id,
        "content": content,
        "to": to_list,
        "cc": cc_list,
        "sensitive": sensitive,
        "published": published,
    }
    if summary:
        data["summary"] = summary
    if source:
        data["source"] = source
    if misskey_content:
        data["_misskey_content"] = misskey_content
    if in_reply_to:
        data["inReplyTo"] = in_reply_to
    if tags:
        data["tag"] = tags
    if attachments:
        data["attachment"] = attachments
    if poll_choices:
        data["oneOf"] = poll_choices
    if end_time:
        data["endTime"] = end_time
    if quote_url:
        data["_misskey_quote"] = quote_url
    return data


# ── Basic fetch ──────────────────────────────────────────────────────────


async def test_fetch_remote_note_basic(db, mock_valkey):
    """Fetch a public Note and store it locally."""
    actor = await make_remote_actor(db, username="note_author", domain="remote1.example")
    ap_id = "https://remote1.example/notes/123"
    data = _ap_note_data(ap_id, actor.ap_id)

    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        note = await fetch_remote_note(db, ap_id)

    assert note is not None
    assert note.ap_id == ap_id
    assert note.actor_id == actor.id
    assert note.visibility == "public"
    assert note.local is False


async def test_fetch_remote_note_already_exists(db, mock_valkey, test_user):
    """If note already exists in DB, return it without fetching."""
    existing = await make_note(db, test_user.actor, content="already here")
    result = await fetch_remote_note(db, existing.ap_id)
    assert result is not None
    assert result.id == existing.id


# ── HTTP error handling ──────────────────────────────────────────────────


async def test_fetch_remote_note_http_error(db, mock_valkey):
    """Return None if HTTP request returns non-200."""
    resp = _mock_response({}, status_code=404)
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=resp):
        result = await fetch_remote_note(db, "https://gone.example/notes/1")
    assert result is None


async def test_fetch_remote_note_http_exception(db, mock_valkey):
    """Return None if HTTP request raises an exception."""
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, side_effect=Exception("timeout")):
        result = await fetch_remote_note(db, "https://timeout.example/notes/1")
    assert result is None


async def test_fetch_remote_note_none_response(db, mock_valkey):
    """Return None if _signed_get returns None."""
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=None):
        result = await fetch_remote_note(db, "https://none.example/notes/1")
    assert result is None


# ── Data validation ──────────────────────────────────────────────────────


async def test_fetch_remote_note_wrong_type(db, mock_valkey):
    """Return None if fetched object is not a Note or Question."""
    data = {"type": "Article", "id": "https://art.example/1", "attributedTo": "x"}
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        result = await fetch_remote_note(db, "https://art.example/1")
    assert result is None


async def test_fetch_remote_note_no_id(db, mock_valkey):
    """Return None if note has no id field."""
    data = {"type": "Note", "attributedTo": "https://x.example/users/x"}
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        result = await fetch_remote_note(db, "https://noid.example/1")
    assert result is None


async def test_fetch_remote_note_no_attributed_to(db, mock_valkey):
    """Return None if note has no attributedTo."""
    data = {"type": "Note", "id": "https://noattr.example/notes/1"}
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        result = await fetch_remote_note(db, "https://noattr.example/notes/1")
    assert result is None


async def test_fetch_remote_note_actor_not_found(db, mock_valkey):
    """Return None if the attributedTo actor cannot be resolved."""
    data = _ap_note_data(
        "https://unknown.example/notes/1",
        "https://unknown.example/users/ghost",
    )
    with (
        patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)),
        patch(
            "app.services.actor_service.fetch_remote_actor",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await fetch_remote_note(db, "https://unknown.example/notes/1")
    assert result is None


# ── Visibility detection ─────────────────────────────────────────────────


async def test_fetch_remote_note_unlisted(db, mock_valkey):
    actor = await make_remote_actor(db, username="unl_author", domain="vis1.example")
    ap_id = "https://vis1.example/notes/unl"
    data = _ap_note_data(ap_id, actor.ap_id, visibility="unlisted")
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        note = await fetch_remote_note(db, ap_id)
    assert note.visibility == "unlisted"


async def test_fetch_remote_note_followers(db, mock_valkey):
    actor = await make_remote_actor(db, username="fol_author", domain="vis2.example")
    ap_id = "https://vis2.example/notes/fol"
    data = _ap_note_data(ap_id, actor.ap_id, visibility="followers")
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        note = await fetch_remote_note(db, ap_id)
    assert note.visibility == "followers"


async def test_fetch_remote_note_direct(db, mock_valkey):
    actor = await make_remote_actor(db, username="dir_author", domain="vis3.example")
    ap_id = "https://vis3.example/notes/dir"
    data = _ap_note_data(ap_id, actor.ap_id, visibility="direct")
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        note = await fetch_remote_note(db, ap_id)
    assert note.visibility == "direct"


# ── Source / content extraction ──────────────────────────────────────────


async def test_fetch_remote_note_source_dict(db, mock_valkey):
    """Extract source from source.content dict (Mastodon style)."""
    actor = await make_remote_actor(db, username="src_author", domain="src1.example")
    ap_id = "https://src1.example/notes/src"
    data = _ap_note_data(
        ap_id,
        actor.ap_id,
        source={"content": "plain text source", "mediaType": "text/plain"},
    )
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        note = await fetch_remote_note(db, ap_id)
    assert note.source == "plain text source"


async def test_fetch_remote_note_misskey_content(db, mock_valkey):
    """Extract source from _misskey_content (Misskey style)."""
    actor = await make_remote_actor(db, username="mk_author", domain="mk1.example")
    ap_id = "https://mk1.example/notes/mk"
    data = _ap_note_data(
        ap_id,
        actor.ap_id,
        misskey_content="misskey plain text",
    )
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        note = await fetch_remote_note(db, ap_id)
    assert note.source == "misskey plain text"


async def test_fetch_remote_note_sensitive_with_summary(db, mock_valkey):
    """Sensitive note with spoiler text (CW)."""
    actor = await make_remote_actor(db, username="cw_author", domain="cw1.example")
    ap_id = "https://cw1.example/notes/cw"
    data = _ap_note_data(
        ap_id,
        actor.ap_id,
        summary="Content Warning",
        sensitive=True,
    )
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        note = await fetch_remote_note(db, ap_id)
    assert note.sensitive is True
    assert note.spoiler_text == "Content Warning"


# ── Reply resolution ────────────────────────────────────────────────────


async def test_fetch_remote_note_reply(db, mock_valkey, test_user):
    """Resolve inReplyTo to local note ID."""
    parent = await make_note(db, test_user.actor, content="parent note")
    actor = await make_remote_actor(db, username="reply_author", domain="reply1.example")
    ap_id = "https://reply1.example/notes/reply"
    data = _ap_note_data(
        ap_id,
        actor.ap_id,
        in_reply_to=parent.ap_id,
    )
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        note = await fetch_remote_note(db, ap_id)
    assert note.in_reply_to_id == parent.id


# ── Quote resolution ────────────────────────────────────────────────────


async def test_fetch_remote_note_quote(db, mock_valkey, test_user):
    """Resolve _misskey_quote to local note."""
    quoted = await make_note(db, test_user.actor, content="quoted note")
    actor = await make_remote_actor(db, username="qt_author", domain="qt1.example")
    ap_id = "https://qt1.example/notes/qt"
    data = _ap_note_data(
        ap_id,
        actor.ap_id,
        quote_url=quoted.ap_id,
    )
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        note = await fetch_remote_note(db, ap_id)
    assert note.quote_id == quoted.id


# ── Tags: Mentions ──────────────────────────────────────────────────────


async def test_fetch_remote_note_with_mentions(db, mock_valkey):
    """Process Mention tags."""
    actor = await make_remote_actor(db, username="tag_author", domain="tag1.example")
    ap_id = "https://tag1.example/notes/tagged"
    data = _ap_note_data(
        ap_id,
        actor.ap_id,
        tags=[
            {
                "type": "Mention",
                "href": "https://other.example/users/alice",
                "name": "@alice@other.example",
            },
        ],
    )
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        note = await fetch_remote_note(db, ap_id)
    assert len(note.mentions) == 1
    assert note.mentions[0]["ap_id"] == "https://other.example/users/alice"


async def test_fetch_remote_note_tags_as_dict(db, mock_valkey):
    """Handle tag as a single dict (instead of list)."""
    actor = await make_remote_actor(db, username="tagd_author", domain="tagd.example")
    ap_id = "https://tagd.example/notes/dict"
    data = _ap_note_data(ap_id, actor.ap_id)
    # tag が辞書の場合にリストに変換されるか確認
    data["tag"] = {"type": "Mention", "href": "https://x.example/u/a", "name": "@a"}
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        note = await fetch_remote_note(db, ap_id)
    assert len(note.mentions) == 1


# ── Tags: Custom Emoji ──────────────────────────────────────────────────


async def test_fetch_remote_note_with_emoji_tag(db, mock_valkey):
    """Process Emoji tags and upsert remote emoji."""
    actor = await make_remote_actor(db, username="emo_author", domain="emoji1.example")
    ap_id = "https://emoji1.example/notes/emo"
    data = _ap_note_data(
        ap_id,
        actor.ap_id,
        content="<p>:blobcat:</p>",
        tags=[
            {
                "type": "Emoji",
                "name": ":blobcat:",
                "icon": {"url": "https://emoji1.example/emoji/blobcat.png"},
            },
        ],
    )
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        note = await fetch_remote_note(db, ap_id)
    assert note is not None
    # リモート絵文字が保存されたか確認
    from app.services.emoji_service import get_custom_emoji

    emoji = await get_custom_emoji(db, "blobcat", "emoji1.example")
    assert emoji is not None
    assert emoji.url == "https://emoji1.example/emoji/blobcat.png"


# ── Poll / Question ─────────────────────────────────────────────────────


async def test_fetch_remote_note_question(db, mock_valkey):
    """Fetch a Question (poll) note."""
    actor = await make_remote_actor(db, username="poll_author", domain="poll1.example")
    ap_id = "https://poll1.example/notes/poll"
    data = _ap_note_data(
        ap_id,
        actor.ap_id,
        obj_type="Question",
        poll_choices=[
            {"name": "Yes", "replies": {"totalItems": 5}},
            {"name": "No", "replies": {"totalItems": 3}},
        ],
        end_time="2025-12-31T23:59:59Z",
    )
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        note = await fetch_remote_note(db, ap_id)
    assert note.is_poll is True
    assert len(note.poll_options) == 2
    assert note.poll_options[0]["title"] == "Yes"
    assert note.poll_options[0]["votes_count"] == 5
    assert note.poll_expires_at is not None


async def test_fetch_remote_note_question_any_of(db, mock_valkey):
    """Fetch a Question with anyOf (multiple choice)."""
    actor = await make_remote_actor(db, username="mpoll_author", domain="poll2.example")
    ap_id = "https://poll2.example/notes/mpoll"
    data = _ap_note_data(ap_id, actor.ap_id, obj_type="Question")
    data["anyOf"] = [
        {"name": "A", "replies": {"totalItems": 1}},
        {"name": "B", "replies": {"totalItems": 2}},
    ]
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        note = await fetch_remote_note(db, ap_id)
    assert note.is_poll is True
    assert note.poll_multiple is True


# ── Attachments ──────────────────────────────────────────────────────────


async def test_fetch_remote_note_with_attachments(db, mock_valkey):
    """Process Document/Image attachments."""
    actor = await make_remote_actor(db, username="att_author", domain="att1.example")
    ap_id = "https://att1.example/notes/att"
    data = _ap_note_data(
        ap_id,
        actor.ap_id,
        attachments=[
            {
                "type": "Image",
                "url": "https://att1.example/media/photo.jpg",
                "mediaType": "image/jpeg",
                "name": "A photo",
                "blurhash": "LEHV6nWB2y",
                "width": 1920,
                "height": 1080,
            },
        ],
    )
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        note = await fetch_remote_note(db, ap_id)
    assert note is not None
    # 添付ファイルが保存されたか確認
    from sqlalchemy import select

    from app.models.note_attachment import NoteAttachment

    result = await db.execute(select(NoteAttachment).where(NoteAttachment.note_id == note.id))
    attachments = list(result.scalars().all())
    assert len(attachments) == 1
    assert attachments[0].remote_url == "https://att1.example/media/photo.jpg"
    assert attachments[0].remote_mime_type == "image/jpeg"


async def test_fetch_remote_note_attachment_url_as_list(db, mock_valkey):
    """Handle attachment url as a list of link objects."""
    actor = await make_remote_actor(db, username="attl_author", domain="attl.example")
    ap_id = "https://attl.example/notes/attl"
    data = _ap_note_data(
        ap_id,
        actor.ap_id,
        attachments=[
            {
                "type": "Document",
                "url": [{"href": "https://attl.example/media/vid.mp4"}],
                "mediaType": "video/mp4",
            },
        ],
    )
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        note = await fetch_remote_note(db, ap_id)
    from sqlalchemy import select

    from app.models.note_attachment import NoteAttachment

    result = await db.execute(select(NoteAttachment).where(NoteAttachment.note_id == note.id))
    atts = list(result.scalars().all())
    assert len(atts) == 1
    assert atts[0].remote_url == "https://attl.example/media/vid.mp4"


async def test_fetch_remote_note_attachment_skip_unsupported_type(db, mock_valkey):
    """Skip attachments with unsupported types."""
    actor = await make_remote_actor(db, username="atts_author", domain="atts.example")
    ap_id = "https://atts.example/notes/atts"
    data = _ap_note_data(
        ap_id,
        actor.ap_id,
        attachments=[
            {"type": "Link", "url": "https://atts.example/link"},
        ],
    )
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        note = await fetch_remote_note(db, ap_id)
    from sqlalchemy import select

    from app.models.note_attachment import NoteAttachment

    result = await db.execute(select(NoteAttachment).where(NoteAttachment.note_id == note.id))
    assert list(result.scalars().all()) == []


async def test_fetch_remote_note_attachment_as_dict(db, mock_valkey):
    """Handle attachment as a single dict (instead of list)."""
    actor = await make_remote_actor(db, username="attd_author", domain="attd.example")
    ap_id = "https://attd.example/notes/attd"
    data = _ap_note_data(ap_id, actor.ap_id)
    data["attachment"] = {
        "type": "Image",
        "url": "https://attd.example/img.png",
        "mediaType": "image/png",
    }
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        note = await fetch_remote_note(db, ap_id)
    from sqlalchemy import select

    from app.models.note_attachment import NoteAttachment

    result = await db.execute(select(NoteAttachment).where(NoteAttachment.note_id == note.id))
    assert len(list(result.scalars().all())) == 1


# ── Published timestamp ─────────────────────────────────────────────────


async def test_fetch_remote_note_published_timestamp(db, mock_valkey):
    """Parse published ISO timestamp."""
    actor = await make_remote_actor(db, username="ts_author", domain="ts1.example")
    ap_id = "https://ts1.example/notes/ts"
    data = _ap_note_data(
        ap_id,
        actor.ap_id,
        published="2025-06-15T12:30:00Z",
    )
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        note = await fetch_remote_note(db, ap_id)
    assert note.published is not None
    assert note.published.year == 2025
    assert note.published.month == 6


async def test_fetch_remote_note_invalid_published(db, mock_valkey):
    """Invalid published timestamp doesn't break note creation."""
    actor = await make_remote_actor(db, username="badt_author", domain="badt.example")
    ap_id = "https://badt.example/notes/badt"
    data = _ap_note_data(
        ap_id,
        actor.ap_id,
        published="not-a-date",
    )
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        note = await fetch_remote_note(db, ap_id)
    # ノートは作成されるが、publishedはデフォルト値
    assert note is not None


# ── Hashtags from AP tags ────────────────────────────────────────────────


async def test_fetch_remote_note_enqueues_face_detect(db, mock_valkey):
    """Enqueue face detection for image attachments without focal point."""
    actor = await make_remote_actor(db, username="fd_author", domain="fd1.example")
    ap_id = "https://fd1.example/notes/fd"
    data = _ap_note_data(
        ap_id,
        actor.ap_id,
        attachments=[
            {
                "type": "Image",
                "url": "https://fd1.example/media/portrait.jpg",
                "mediaType": "image/jpeg",
                "width": 800,
                "height": 1200,
            },
        ],
    )
    from app.config import settings

    with (
        patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)),
        patch.object(settings, "face_detect_url", "http://face-detect:8000/detect"),
        patch(
            "app.services.face_detect_queue.enqueue_remote",
            new_callable=AsyncMock,
        ) as mock_enqueue,
    ):
        note = await fetch_remote_note(db, ap_id)

    assert note is not None
    mock_enqueue.assert_called_once()
    call_args = mock_enqueue.call_args
    assert call_args[0][0] == note.id
    assert len(call_args[0][1]) == 1  # one attachment ID


async def test_fetch_remote_note_skips_face_detect_with_focal(db, mock_valkey):
    """Don't enqueue face detection when focalPoint is already provided."""
    actor = await make_remote_actor(db, username="fds_author", domain="fds1.example")
    ap_id = "https://fds1.example/notes/fds"
    data = _ap_note_data(
        ap_id,
        actor.ap_id,
        attachments=[
            {
                "type": "Image",
                "url": "https://fds1.example/media/portrait.jpg",
                "mediaType": "image/jpeg",
                "focalPoint": [0.0, 0.5],
                "width": 800,
                "height": 1200,
            },
        ],
    )
    from app.config import settings

    with (
        patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)),
        patch.object(settings, "face_detect_url", "http://face-detect:8000/detect"),
        patch(
            "app.services.face_detect_queue.enqueue_remote",
            new_callable=AsyncMock,
        ) as mock_enqueue,
    ):
        note = await fetch_remote_note(db, ap_id)

    assert note is not None
    mock_enqueue.assert_not_called()


# ── Hashtags from AP tags ────────────────────────────────────────────────


async def test_fetch_remote_note_with_hashtags(db, mock_valkey):
    """Extract hashtags from AP Hashtag tags."""
    actor = await make_remote_actor(db, username="ht_author", domain="ht1.example")
    ap_id = "https://ht1.example/notes/ht"
    data = _ap_note_data(
        ap_id,
        actor.ap_id,
        tags=[
            {"type": "Hashtag", "name": "#fediverse", "href": "https://ht1.example/tags/fediverse"},
        ],
    )
    with patch(_SIGNED_GET_PATCH, new_callable=AsyncMock, return_value=_mock_response(data)):
        note = await fetch_remote_note(db, ap_id)
    assert note is not None
