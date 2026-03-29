"""メディアタイムラインAPIのテスト。"""

import uuid

from tests.conftest import make_note, make_remote_actor


async def _make_attachment(db, note, *, mime="image/jpeg", url="https://r.example/img.jpg",
                           vision_tags=None, vision_caption=None):
    from app.models.note_attachment import NoteAttachment

    att = NoteAttachment(
        note_id=note.id,
        position=0,
        remote_url=url,
        remote_mime_type=mime,
        remote_vision_tags=vision_tags,
        remote_vision_caption=vision_caption,
    )
    db.add(att)
    await db.flush()
    return att


async def _make_local_attachment(db, note, *, mime="image/jpeg",
                                 vision_tags=None, vision_caption=None):
    from app.models.drive_file import DriveFile
    from app.models.note_attachment import NoteAttachment

    df = DriveFile(
        id=uuid.uuid4(),
        filename="test.jpg",
        s3_key=f"test/{uuid.uuid4()}.jpg",
        mime_type=mime,
        size_bytes=1234,
        vision_tags=vision_tags,
        vision_caption=vision_caption,
    )
    db.add(df)
    await db.flush()

    att = NoteAttachment(
        note_id=note.id,
        position=0,
        drive_file_id=df.id,
    )
    db.add(att)
    await db.flush()
    return att


# --- 基本的な表示 ---


async def test_media_timeline_empty(db, mock_valkey):
    """メディア添付なしの場合は空リストを返す。"""
    from app.services.note_service import get_media_timeline

    result = await get_media_timeline(db)
    assert result == []


async def test_media_timeline_returns_image_note(db, mock_valkey):
    """画像添付ありのノートがメディアタイムラインに表示される。"""
    from app.services.note_service import get_media_timeline

    actor = await make_remote_actor(db, username="mt_img", domain="mt.example")
    note = await make_note(db, actor, content="With image", local=False)
    await _make_attachment(db, note)

    result = await get_media_timeline(db)
    assert len(result) == 1
    assert result[0].id == note.id


async def test_media_timeline_returns_video_note(db, mock_valkey):
    """動画添付ありのノートもメディアタイムラインに表示される。"""
    from app.services.note_service import get_media_timeline

    actor = await make_remote_actor(db, username="mt_vid", domain="mt2.example")
    note = await make_note(db, actor, content="With video", local=False)
    await _make_attachment(db, note, mime="video/mp4")

    result = await get_media_timeline(db)
    assert len(result) == 1


async def test_media_timeline_excludes_no_attachment(db, mock_valkey):
    """メディア添付なしのノートは返さない。"""
    from app.services.note_service import get_media_timeline

    actor = await make_remote_actor(db, username="mt_txt", domain="mt3.example")
    await make_note(db, actor, content="Text only", local=False)

    result = await get_media_timeline(db)
    assert result == []


async def test_media_timeline_excludes_audio(db, mock_valkey):
    """音声のみの添付は返さない。"""
    from app.services.note_service import get_media_timeline

    actor = await make_remote_actor(db, username="mt_aud", domain="mt4.example")
    note = await make_note(db, actor, content="Audio", local=False)
    await _make_attachment(db, note, mime="audio/mpeg")

    result = await get_media_timeline(db)
    assert result == []


# --- 検索 ---


async def test_search_by_vision_tags(db, mock_valkey):
    """vision_tags で検索ヒットする。"""
    from app.services.note_service import get_media_timeline

    actor = await make_remote_actor(db, username="mt_tag", domain="mt5.example")
    note = await make_note(db, actor, content="Cat photo", local=False)
    await _make_attachment(db, note, vision_tags=["cat", "animal"])

    result = await get_media_timeline(db, q="cat")
    assert len(result) == 1
    assert result[0].id == note.id


async def test_search_by_vision_caption(db, mock_valkey):
    """vision_caption で検索ヒットする。"""
    from app.services.note_service import get_media_timeline

    actor = await make_remote_actor(db, username="mt_cap", domain="mt6.example")
    note = await make_note(db, actor, content="Landscape", local=False)
    await _make_attachment(db, note, vision_caption="Beautiful mountain landscape")

    result = await get_media_timeline(db, q="mountain")
    assert len(result) == 1


async def test_search_by_note_content(db, mock_valkey):
    """ノート本文で検索ヒットする。"""
    from app.services.note_service import get_media_timeline

    actor = await make_remote_actor(db, username="mt_cnt", domain="mt7.example")
    note = await make_note(db, actor, content="Beautiful sunset photo", local=False)
    await _make_attachment(db, note)

    result = await get_media_timeline(db, q="sunset")
    assert len(result) == 1


async def test_search_no_match(db, mock_valkey):
    """検索がヒットしない場合は空リスト。"""
    from app.services.note_service import get_media_timeline

    actor = await make_remote_actor(db, username="mt_no", domain="mt8.example")
    note = await make_note(db, actor, content="Random post", local=False)
    await _make_attachment(db, note)

    result = await get_media_timeline(db, q="nonexistent_query_term")
    assert result == []


async def test_search_local_drive_file_tags(db, mock_valkey):
    """ローカルDriveFileのvision_tagsで検索ヒットする。"""
    from app.services.note_service import get_media_timeline

    actor = await make_remote_actor(db, username="mt_ldf", domain="mt9.example")
    note = await make_note(db, actor, content="Post", local=False)
    await _make_local_attachment(db, note, vision_tags=["flower", "garden"])

    result = await get_media_timeline(db, q="flower")
    assert len(result) == 1


# --- フィルタリング ---


async def test_excludes_renotes(db, mock_valkey):
    """ブースト(renote)はメディアタイムラインから除外される。"""
    from app.services.note_service import get_media_timeline

    actor = await make_remote_actor(db, username="mt_rn", domain="mt10.example")
    original = await make_note(db, actor, content="Original", local=False)
    await _make_attachment(db, original)

    boost = await make_note(db, actor, content="", local=False)
    boost.renote_of_id = original.id
    await db.flush()

    result = await get_media_timeline(db)
    ids = [n.id for n in result]
    assert original.id in ids
    assert boost.id not in ids


async def test_excludes_non_public(db, mock_valkey):
    """非公開/フォロワー限定ノートは匿名ユーザーに見えない。"""
    from app.services.note_service import get_media_timeline

    actor = await make_remote_actor(db, username="mt_priv", domain="mt11.example")

    pub = await make_note(db, actor, content="Public", local=False, visibility="public")
    await _make_attachment(db, pub)

    # followers-only は current_actor_id=None では見えない
    priv = await make_note(db, actor, content="Followers only", local=False,
                           visibility="followers")
    await _make_attachment(db, priv, url="https://r.example/priv.jpg")

    result = await get_media_timeline(db)
    assert len(result) == 1
    assert result[0].id == pub.id


async def test_excludes_silenced_actors(db, mock_valkey):
    """サイレンスされたアクターのノートは表示されない。"""
    from datetime import datetime, timezone

    from app.services.note_service import get_media_timeline

    actor = await make_remote_actor(db, username="mt_sil", domain="mt12.example")
    note = await make_note(db, actor, content="Silenced", local=False)
    await _make_attachment(db, note, url="https://r.example/sil.jpg")

    actor.silenced_at = datetime.now(timezone.utc)
    await db.flush()

    result = await get_media_timeline(db)
    assert result == []


# --- ページネーション ---


async def test_cursor_pagination(db, mock_valkey):
    """max_id でカーソルページネーションが動作する。"""
    from app.services.note_service import get_media_timeline

    actor = await make_remote_actor(db, username="mt_page", domain="mt13.example")
    notes = []
    for i in range(3):
        n = await make_note(db, actor, content=f"Note {i}", local=False)
        await _make_attachment(db, n, url=f"https://r.example/page{i}.jpg")
        notes.append(n)

    # 最新2件取得
    first_page = await get_media_timeline(db, limit=2)
    assert len(first_page) == 2

    # 2件目のIDをカーソルに次ページ取得
    second_page = await get_media_timeline(db, limit=2, max_id=first_page[-1].id)
    assert len(second_page) == 1

    # 重複なし
    first_ids = {n.id for n in first_page}
    second_ids = {n.id for n in second_page}
    assert first_ids.isdisjoint(second_ids)


# --- IDOR / アクセス制御 ---


async def test_excludes_direct_notes(db, mock_valkey):
    """DM (direct) ノートはメディアタイムラインに表示されない。"""
    from app.services.note_service import get_media_timeline

    actor = await make_remote_actor(db, username="mt_dm", domain="mt14.example")
    note = await make_note(db, actor, content="Secret DM", local=False,
                           visibility="direct")
    await _make_attachment(db, note, url="https://r.example/dm.jpg")

    # 匿名
    result = await get_media_timeline(db)
    assert result == []

    # 認証済みでも見えない
    result = await get_media_timeline(db, current_actor_id=actor.id)
    assert result == []


async def test_excludes_followers_only_for_non_follower(db, mock_valkey):
    """フォロワー限定ノートは認証済み非フォロワーにも見えない。"""
    from app.services.note_service import get_media_timeline

    author = await make_remote_actor(db, username="mt_fo_author", domain="mt15.example")
    viewer = await make_remote_actor(db, username="mt_fo_viewer", domain="mt16.example")

    note = await make_note(db, author, content="Followers only",
                           local=False, visibility="followers")
    await _make_attachment(db, note, url="https://r.example/fo.jpg")

    # viewer はフォロワーではない
    result = await get_media_timeline(db, current_actor_id=viewer.id)
    assert result == []


async def test_excludes_blocked_user_notes(db, mock_valkey):
    """ブロックしたユーザーのノートは表示されない。"""
    from app.models.user_block import UserBlock
    from app.services.note_service import get_media_timeline

    author = await make_remote_actor(db, username="mt_blk_author", domain="mt17.example")
    viewer = await make_remote_actor(db, username="mt_blk_viewer", domain="mt18.example")

    note = await make_note(db, author, content="Blocked", local=False)
    await _make_attachment(db, note, url="https://r.example/blk.jpg")

    # viewer が author をブロック
    db.add(UserBlock(actor_id=viewer.id, target_id=author.id))
    await db.flush()

    result = await get_media_timeline(db, current_actor_id=viewer.id)
    assert result == []


async def test_excludes_require_signin_anonymous(db, mock_valkey):
    """require_signin_to_view のアクターのノートは匿名で見えない。"""
    from app.services.note_service import get_media_timeline

    actor = await make_remote_actor(db, username="mt_signin", domain="mt19.example")
    actor.require_signin_to_view = True
    await db.flush()

    note = await make_note(db, actor, content="Signin required", local=False)
    await _make_attachment(db, note, url="https://r.example/signin.jpg")

    # 匿名では見えない
    result = await get_media_timeline(db)
    assert result == []

    # 認証済みなら見える
    other = await make_remote_actor(db, username="mt_signin_v", domain="mt20.example")
    result = await get_media_timeline(db, current_actor_id=other.id)
    assert len(result) == 1


async def test_excludes_deleted_notes(db, mock_valkey):
    """削除済みノートはメディアタイムラインに表示されない。"""
    from datetime import datetime, timezone

    from app.services.note_service import get_media_timeline

    actor = await make_remote_actor(db, username="mt_del", domain="mt21.example")
    note = await make_note(db, actor, content="Deleted", local=False)
    await _make_attachment(db, note, url="https://r.example/del.jpg")

    note.deleted_at = datetime.now(timezone.utc)
    await db.flush()

    result = await get_media_timeline(db)
    assert result == []
