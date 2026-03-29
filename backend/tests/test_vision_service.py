"""neko-vision画像タグ付けサービスのテスト。"""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from tests.conftest import make_note, make_remote_actor


async def _make_attachment(db, note, *, mime="image/jpeg", url="https://r.example/img.jpg"):
    from app.models.note_attachment import NoteAttachment

    att = NoteAttachment(
        note_id=note.id,
        position=0,
        remote_url=url,
        remote_mime_type=mime,
    )
    db.add(att)
    await db.flush()
    return att


async def _make_drive_file(db, *, mime="image/jpeg"):
    from app.models.drive_file import DriveFile

    df = DriveFile(
        id=uuid.uuid4(),
        filename="test.jpg",
        s3_key=f"test/{uuid.uuid4()}.jpg",
        mime_type=mime,
        size_bytes=1234,
    )
    db.add(df)
    await db.flush()
    return df


# --- _strip_html ---


async def test_strip_html_removes_tags():
    from app.services.vision_service import _strip_html

    assert _strip_html("<p>hello <b>world</b></p>") == "hello world"


async def test_strip_html_converts_br():
    from app.services.vision_service import _strip_html

    assert _strip_html("line1<br>line2<br/>line3") == "line1\nline2\nline3"


async def test_strip_html_unescapes_entities():
    from app.services.vision_service import _strip_html

    assert _strip_html("&amp; &lt; &gt;") == "& < >"


# --- collect_reply_context ---


async def test_collect_reply_context_empty(db):
    """in_reply_to_id が None のノートは空リストを返す。"""
    from app.services.vision_service import collect_reply_context

    actor = await make_remote_actor(db, username="ctx_empty", domain="ctx.example")
    note = await make_note(db, actor, content="Root note", local=False)
    assert note.in_reply_to_id is None

    result = await collect_reply_context(db, note)
    assert result == []


async def test_collect_reply_context_chain(db):
    """リプライチェーンを辿って古い順に本文を取得する。"""
    from app.services.vision_service import collect_reply_context

    actor = await make_remote_actor(db, username="ctx_chain", domain="ctx2.example")
    n1 = await make_note(db, actor, content="Parent", local=False)
    n2 = await make_note(db, actor, content="Child", local=False)
    n3 = await make_note(db, actor, content="Grandchild", local=False)

    n2.in_reply_to_id = n1.id
    n3.in_reply_to_id = n2.id
    await db.flush()

    result = await collect_reply_context(db, n3)
    assert len(result) == 2
    assert "Parent" in result[0]
    assert "Child" in result[1]


async def test_collect_reply_context_max_depth(db):
    """max_depth を超えるノートは取得しない。"""
    from app.services.vision_service import collect_reply_context

    actor = await make_remote_actor(db, username="ctx_depth", domain="ctx3.example")
    notes = []
    for i in range(5):
        n = await make_note(db, actor, content=f"Note{i}", local=False)
        if notes:
            n.in_reply_to_id = notes[-1].id
        notes.append(n)
    await db.flush()

    result = await collect_reply_context(db, notes[-1], max_depth=2)
    assert len(result) == 2


# --- _tag_single_remote ---


async def test_tag_single_remote_success(db, mock_valkey):
    """リモート画像のタグ付けが成功するケース。"""
    from app.services.vision_service import _tag_single_remote

    actor = await make_remote_actor(db, username="vs_ok", domain="vs.example")
    note = await make_note(db, actor, content="Test image", local=False)
    att = await _make_attachment(db, note)

    vision_result = {"tags": ["cat", "photo"], "caption": "A cute cat"}

    with patch(
        "app.services.vision_service._download_image",
        new=AsyncMock(return_value=b"\xff\xd8" + b"\x00" * 100),
    ), patch(
        "app.services.vision_service._call_vision",
        new=AsyncMock(return_value=vision_result),
    ):
        result = await _tag_single_remote(att, note_text="Test image")

    assert result is True
    assert att.remote_vision_tags == ["cat", "photo"]
    assert att.remote_vision_caption == "A cute cat"
    assert att.vision_at is not None


async def test_tag_single_remote_skips_non_image(db, mock_valkey):
    """画像以外のMIMEタイプはスキップする。"""
    from app.services.vision_service import _tag_single_remote

    actor = await make_remote_actor(db, username="vs_vid", domain="vs2.example")
    note = await make_note(db, actor, content="Video", local=False)
    att = await _make_attachment(db, note, mime="video/mp4")

    result = await _tag_single_remote(att)
    assert result is False


async def test_tag_single_remote_skips_no_url(db, mock_valkey):
    """remote_url が None の場合はスキップする。"""
    from app.models.note_attachment import NoteAttachment
    from app.services.vision_service import _tag_single_remote

    actor = await make_remote_actor(db, username="vs_nourl", domain="vs3.example")
    note = await make_note(db, actor, content="No URL", local=False)
    att = NoteAttachment(
        note_id=note.id,
        position=0,
        remote_url=None,
        remote_mime_type="image/jpeg",
    )
    db.add(att)
    await db.flush()

    result = await _tag_single_remote(att)
    assert result is False


async def test_tag_single_remote_download_failure(db, mock_valkey):
    """画像ダウンロード失敗時はFalseを返す。"""
    from app.services.vision_service import _tag_single_remote

    actor = await make_remote_actor(db, username="vs_dl", domain="vs4.example")
    note = await make_note(db, actor, content="DL fail", local=False)
    att = await _make_attachment(db, note)

    with patch(
        "app.services.vision_service._download_image",
        new=AsyncMock(return_value=None),
    ):
        result = await _tag_single_remote(att)

    assert result is False
    assert att.remote_vision_tags is None


async def test_tag_single_remote_vision_failure(db, mock_valkey):
    """neko-vision API 失敗時はFalseを返す。"""
    from app.services.vision_service import _tag_single_remote

    actor = await make_remote_actor(db, username="vs_api", domain="vs5.example")
    note = await make_note(db, actor, content="API fail", local=False)
    att = await _make_attachment(db, note)

    with patch(
        "app.services.vision_service._download_image",
        new=AsyncMock(return_value=b"fake-image"),
    ), patch(
        "app.services.vision_service._call_vision",
        new=AsyncMock(return_value=None),
    ):
        result = await _tag_single_remote(att)

    assert result is False
    assert att.remote_vision_tags is None


# --- auto_tag_image ---


async def test_auto_tag_image_success(db, mock_valkey):
    """ローカルDriveFileのタグ付け成功。"""
    from app.services.vision_service import auto_tag_image

    df = await _make_drive_file(db)

    vision_result = {"tags": ["landscape", "mountain"], "caption": "Mountain view"}

    with patch("app.services.vision_service.settings") as mock_settings, \
         patch(
             "app.services.vision_service._read_file_data",
             new=AsyncMock(return_value=b"fake-image"),
         ), \
         patch(
             "app.services.vision_service._call_vision",
             new=AsyncMock(return_value=vision_result),
         ):
        mock_settings.neko_vision_enabled = True
        await auto_tag_image(db, df, note_text="Beautiful mountain")

    assert df.vision_tags == ["landscape", "mountain"]
    assert df.vision_caption == "Mountain view"
    assert df.vision_at is not None


async def test_auto_tag_image_skips_non_image(db, mock_valkey):
    """画像以外のMIMEタイプはスキップする。"""
    from app.services.vision_service import auto_tag_image

    df = await _make_drive_file(db, mime="video/mp4")

    with patch("app.services.vision_service.settings") as mock_settings:
        mock_settings.neko_vision_enabled = True
        await auto_tag_image(db, df)

    assert df.vision_tags is None


async def test_auto_tag_image_skips_when_disabled(db, mock_valkey):
    """neko-vision無効時はスキップする。"""
    from app.services.vision_service import auto_tag_image

    df = await _make_drive_file(db)

    with patch("app.services.vision_service.settings") as mock_settings:
        mock_settings.neko_vision_enabled = False
        await auto_tag_image(db, df)

    assert df.vision_tags is None


async def test_auto_tag_image_s3_failure(db, mock_valkey):
    """S3読み込み失敗時は静かに失敗する。"""
    from app.services.vision_service import auto_tag_image

    df = await _make_drive_file(db)

    with patch("app.services.vision_service.settings") as mock_settings, \
         patch(
             "app.services.vision_service._read_file_data",
             new=AsyncMock(return_value=None),
         ):
        mock_settings.neko_vision_enabled = True
        await auto_tag_image(db, df)

    assert df.vision_tags is None


# --- tag_remote_attachments ---


async def test_tag_remote_attachments_integration(db, mock_valkey):
    """リモート添付ファイルのバッチタグ付け統合テスト。"""
    from app.services.vision_service import tag_remote_attachments

    actor = await make_remote_actor(db, username="tr_full", domain="tr.example")
    note = await make_note(db, actor, content="Full test", local=False)
    att = await _make_attachment(db, note)
    await db.flush()

    @asynccontextmanager
    async def fake_session():
        yield db

    vision_result = {"tags": ["test"], "caption": "Test caption"}

    with patch("app.services.vision_service.settings") as mock_settings, \
         patch("app.database.async_session", fake_session), \
         patch(
             "app.services.vision_service._download_image",
             new=AsyncMock(return_value=b"img"),
         ), \
         patch(
             "app.services.vision_service._call_vision",
             new=AsyncMock(return_value=vision_result),
         ), \
         patch(
             "app.services.vision_service._publish_update",
             new=AsyncMock(),
         ) as mock_publish:
        mock_settings.neko_vision_enabled = True
        mock_settings.skip_ssl_verify = False
        await tag_remote_attachments(note.id, [att.id], note_text="Full test")

    mock_publish.assert_called_once_with(note.id)


async def test_tag_remote_attachments_disabled(mock_valkey):
    """neko-vision無効時は何もしない。"""
    from app.services.vision_service import tag_remote_attachments

    with patch("app.services.vision_service.settings") as mock_settings:
        mock_settings.neko_vision_enabled = False
        await tag_remote_attachments(uuid.uuid4(), [uuid.uuid4()])
    # 例外が発生しなければOK
