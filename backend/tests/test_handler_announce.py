"""Tests for Announce (boost/renote) handler."""

from unittest.mock import AsyncMock, patch

from tests.conftest import make_note, make_remote_actor


async def test_handle_announce(db, mock_valkey):
    from app.activitypub.handlers.announce import handle_announce

    remote_actor = await make_remote_actor(db, username="booster", domain="remote.example")
    from sqlalchemy import select

    from app.models.actor import Actor

    result = await db.execute(select(Actor).where(Actor.domain.is_(None)).limit(1))
    local_actor = result.scalar_one_or_none()
    if not local_actor:
        # Create a local actor for making a note
        # Use make_note with a minimal local actor setup
        from app.services.user_service import create_user

        user = await create_user(db, "announceuser", "announce@test.com", "password1234")
        local_actor = user.actor

    note = await make_note(db, local_actor, content="Original post")
    await db.commit()

    activity = {
        "id": "http://remote.example/activities/announce-1",
        "type": "Announce",
        "actor": remote_actor.ap_id,
        "object": note.ap_id,
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "cc": [remote_actor.followers_url],
        "published": "2026-03-06T12:00:00Z",
    }

    await handle_announce(db, activity)

    # Verify renote was created
    from app.services.note_service import get_note_by_ap_id

    renote = await get_note_by_ap_id(db, "http://remote.example/activities/announce-1")
    assert renote is not None
    assert renote.renote_of_id == note.id
    assert renote.renote_of_ap_id == note.ap_id
    assert renote.visibility == "public"

    # Verify renotes_count incremented
    await db.refresh(note)
    assert note.renotes_count == 1


async def test_handle_announce_duplicate(db, mock_valkey):
    from app.activitypub.handlers.announce import handle_announce

    remote_actor = await make_remote_actor(db, username="dup_booster", domain="dup.example")
    from app.services.user_service import create_user

    user = await create_user(db, "dupannounce", "dupann@test.com", "password1234")
    note = await make_note(db, user.actor, content="Dup test")
    await db.commit()

    activity = {
        "id": "http://dup.example/activities/announce-dup",
        "type": "Announce",
        "actor": remote_actor.ap_id,
        "object": note.ap_id,
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "cc": [],
    }

    await handle_announce(db, activity)
    await handle_announce(db, activity)  # duplicate

    # Should only have one renote
    from sqlalchemy import func, select

    from app.models.note import Note

    count_result = await db.execute(
        select(func.count())
        .select_from(Note)
        .where(
            Note.renote_of_id == note.id,
            Note.deleted_at.is_(None),
        )
    )
    assert count_result.scalar() == 1


@patch("app.services.actor_service._signed_get", new_callable=AsyncMock, return_value=None)
async def test_handle_announce_unknown_note(mock_get, db, mock_valkey):
    """Announce of a note we don't have (and fetch fails) still creates the renote."""
    from app.activitypub.handlers.announce import handle_announce

    remote_actor = await make_remote_actor(db, username="unk_booster", domain="unk.example")
    await db.commit()

    activity = {
        "id": "http://unk.example/activities/announce-unk",
        "type": "Announce",
        "actor": remote_actor.ap_id,
        "object": "http://other.example/notes/unknown-note",
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "cc": [],
    }

    await handle_announce(db, activity)

    from app.services.note_service import get_note_by_ap_id

    renote = await get_note_by_ap_id(db, "http://unk.example/activities/announce-unk")
    assert renote is not None
    assert renote.renote_of_id is None
    assert renote.renote_of_ap_id == "http://other.example/notes/unknown-note"


async def test_renote_api_response_includes_reblog(authed_client, test_user, mock_valkey):
    """Renote in timeline returns reblog field with the original note data."""
    # 元ノートを作成
    create_resp = await authed_client.post(
        "/api/v1/statuses",
        json={"content": "Original post for renote test", "visibility": "public"},
    )
    assert create_resp.status_code == 201
    original = create_resp.json()

    # リブログ
    reblog_resp = await authed_client.post(f"/api/v1/statuses/{original['id']}/reblog")
    assert reblog_resp.status_code == 200
    reblog_data = reblog_resp.json()
    assert reblog_data["reblog"] is not None
    assert reblog_data["reblog"]["id"] == original["id"]
    assert reblog_data["reblog"]["content"] == original["content"]

    # タイムラインでrenoteがreblogフィールド付きで表示されることを確認
    tl_resp = await authed_client.get("/api/v1/timelines/home")
    assert tl_resp.status_code == 200
    tl_data = tl_resp.json()
    # タイムラインの最新ノートはrenoteのはず
    renote_in_tl = next((n for n in tl_data if n.get("reblog")), None)
    assert renote_in_tl is not None
    assert renote_in_tl["reblog"]["id"] == original["id"]


async def test_remote_renote_has_reblog_in_response(db, authed_client, test_user, mock_valkey):
    """Remote Announce creates renote that appears with reblog in API response."""
    from app.activitypub.handlers.announce import handle_announce

    # ローカルノートを作成
    original = await make_note(db, test_user.actor, content="Renote me")
    remote_actor = await make_remote_actor(db, username="rn_booster", domain="rn.example")
    await db.commit()

    activity = {
        "id": "http://rn.example/activities/announce-api-test",
        "type": "Announce",
        "actor": remote_actor.ap_id,
        "object": original.ap_id,
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "cc": [remote_actor.followers_url],
        "published": "2026-03-08T12:00:00Z",
    }
    await handle_announce(db, activity)

    from app.services.note_service import get_note_by_ap_id

    renote = await get_note_by_ap_id(db, "http://rn.example/activities/announce-api-test")
    assert renote is not None

    # APIレスポンスにreblogが含まれることを確認
    resp = await authed_client.get(f"/api/v1/statuses/{renote.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["reblog"] is not None
    assert data["reblog"]["content"] == original.content


async def test_announce_unknown_user_note_fetched_successfully(
    db, authed_client, test_user, mock_valkey
):
    """Announce of a note from a previously unknown user: both actor and note are
    fetched remotely, and the resulting renote has reblog populated in the API."""
    from unittest.mock import AsyncMock, patch

    from app.activitypub.handlers.announce import handle_announce
    from app.models.follow import Follow

    # ブースターは既知のリモートユーザー(test_userがフォロー済み)
    booster = await make_remote_actor(db, username="known_booster", domain="booster.example")
    follow = Follow(
        follower_id=test_user.actor_id,
        following_id=booster.id,
        accepted=True,
    )
    db.add(follow)
    await db.commit()

    # 未知のユーザーとノートのJSON-LDレスポンスをモック
    unknown_actor_ap_id = "http://unknown.example/users/alice"
    unknown_note_ap_id = "http://unknown.example/notes/first-post"

    actor_json = {
        "id": unknown_actor_ap_id,
        "type": "Person",
        "preferredUsername": "alice",
        "name": "Alice",
        "inbox": "http://unknown.example/users/alice/inbox",
        "outbox": "http://unknown.example/users/alice/outbox",
        "followers": "http://unknown.example/users/alice/followers",
        "publicKey": {
            "id": f"{unknown_actor_ap_id}#main-key",
            "publicKeyPem": "-----BEGIN PUBLIC KEY-----\nMIIBIjANB\n-----END PUBLIC KEY-----\n",
        },
    }
    note_json = {
        "id": unknown_note_ap_id,
        "type": "Note",
        "attributedTo": unknown_actor_ap_id,
        "content": "<p>Hello from unknown user</p>",
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "cc": [f"{unknown_actor_ap_id}/followers"],
        "published": "2026-03-12T10:00:00Z",
    }

    class FakeResponse:
        def __init__(self, data):
            self.status_code = 200
            self._data = data

        def json(self):
            return self._data

    async def mock_signed_get(db_, url):
        if "notes/" in url:
            return FakeResponse(note_json)
        if "users/" in url:
            return FakeResponse(actor_json)
        return None

    mock_get = AsyncMock(side_effect=mock_signed_get)
    with patch("app.services.actor_service._signed_get", mock_get):
        activity = {
            "id": "http://booster.example/activities/announce-unknown",
            "type": "Announce",
            "actor": booster.ap_id,
            "object": unknown_note_ap_id,
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [booster.followers_url],
            "published": "2026-03-12T12:00:00Z",
        }
        await handle_announce(db, activity)

    # --- 検証 ---
    from app.services.note_service import get_note_by_ap_id

    # 1. 元ノートがDBに存在する
    original = await get_note_by_ap_id(db, unknown_note_ap_id)
    assert original is not None, "fetch_remote_noteで元ノートが作成されるべき"
    assert original.content == "<p>Hello from unknown user</p>"

    # 2. リノートがrenote_of_idを持っている
    renote = await get_note_by_ap_id(db, "http://booster.example/activities/announce-unknown")
    assert renote is not None
    assert renote.renote_of_id == original.id, (
        f"renote_of_idが{original.id}であるべきだが{renote.renote_of_id}だった"
    )
    assert renote.renote_of_ap_id == unknown_note_ap_id

    # 3. APIレスポンスでreblogが含まれる
    resp = await authed_client.get(f"/api/v1/statuses/{renote.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["reblog"] is not None, "APIレスポンスにreblogフィールドが必要"
    assert "Hello from unknown user" in data["reblog"]["content"]
    assert data["reblog"]["actor"]["username"] == "alice"
    assert data["actor"]["username"] == "known_booster"

    # 4. ホームタイムラインでreblog付きで表示される
    tl_resp = await authed_client.get("/api/v1/timelines/home")
    assert tl_resp.status_code == 200
    tl_data = tl_resp.json()
    renote_in_tl = next(
        (n for n in tl_data if n.get("reblog") and n["actor"]["username"] == "known_booster"),
        None,
    )
    assert renote_in_tl is not None, "ホームタイムラインにreblog付きリノートが表示されるべき"

    # 5. パブリックタイムラインで重複排除が正しく動作する
    pub_resp = await authed_client.get("/api/v1/timelines/public")
    assert pub_resp.status_code == 200
    pub_data = pub_resp.json()
    # リノートR (reblog付き) が存在すること
    renote_in_pub = [
        n for n in pub_data if n.get("reblog") and n["actor"]["username"] == "known_booster"
    ]
    assert len(renote_in_pub) >= 1, "パブリックTLにreblog付きリノートが表示されるべき"
    # 元ノートNがスタンドアロンで重複表示されないこと
    standalone_original = [
        n for n in pub_data if n["id"] == str(original.id) and n.get("reblog") is None
    ]
    assert len(standalone_original) == 0, (
        "元ノートがリノートとして表示される場合、スタンドアロンで重複表示されるべきでない"
    )


async def test_handle_announce_existing_note_enqueues_focal(db, mock_valkey):
    """When the original note already exists in DB, handle_announce should
    enqueue focal detection for attachments without focal point."""
    from unittest.mock import AsyncMock, patch

    from app.activitypub.handlers.announce import handle_announce
    from app.models.note_attachment import NoteAttachment

    remote_actor = await make_remote_actor(
        db, username="focal_booster", domain="focal.example"
    )
    from app.services.user_service import create_user

    user = await create_user(db, "focalannounce", "focalann@test.com", "password1234")
    note = await make_note(db, user.actor, content="Image post")

    # Add an attachment without focal point
    att = NoteAttachment(
        note_id=note.id,
        remote_url="http://remote.example/image.jpg",
        remote_mime_type="image/jpeg",
        remote_focal_x=None,
        remote_focal_y=None,
    )
    db.add(att)
    await db.commit()
    await db.refresh(att)

    activity = {
        "id": "http://focal.example/activities/announce-focal",
        "type": "Announce",
        "actor": remote_actor.ap_id,
        "object": note.ap_id,
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "cc": [],
    }

    mock_enqueue = AsyncMock()
    with (
        patch("app.config.settings") as mock_settings,
        patch(
            "app.activitypub.handlers.announce.enqueue_remote",
            mock_enqueue,
            create=True,
        ),
        patch("app.services.face_detect_queue.enqueue_remote", mock_enqueue),
    ):
        mock_settings.face_detect_url = "http://face-detect.example"
        await handle_announce(db, activity)

    mock_enqueue.assert_called_once_with(note.id, [att.id])


async def test_fetch_remote_note_integrity_error_fallback(db, mock_valkey):
    """When fetch_remote_note hits IntegrityError (duplicate ap_id from concurrent
    Create+Announce), it falls back to the existing note instead of crashing."""
    from unittest.mock import AsyncMock, patch

    from app.activitypub.handlers.announce import handle_announce
    from app.services.note_service import get_note_by_ap_id

    booster = await make_remote_actor(db, username="ie_booster", domain="ie.example")
    await db.commit()

    # 元ノートのap_id
    original_note_ap_id = "http://ie-origin.example/notes/race-note"

    # 先にCreate活動で元ノートがDBに存在する状態をシミュレート
    from app.models.note import Note

    original_actor = await make_remote_actor(db, username="ie_author", domain="ie-origin.example")
    pre_existing_note = Note(
        ap_id=original_note_ap_id,
        actor_id=original_actor.id,
        content="<p>I was created by handle_create first</p>",
        visibility="public",
        local=False,
    )
    db.add(pre_existing_note)
    await db.commit()
    await db.refresh(pre_existing_note)

    # fetch_remote_noteがリモートフェッチを試行してflushでIntegrityErrorになるケース
    # _signed_getはノートデータを返すが、DBには既にap_idが存在する
    actor_json = {
        "id": original_actor.ap_id,
        "type": "Person",
        "preferredUsername": "ie_author",
        "name": "IE Author",
        "inbox": f"{original_actor.ap_id}/inbox",
        "outbox": f"{original_actor.ap_id}/outbox",
        "followers": f"{original_actor.ap_id}/followers",
        "publicKey": {
            "id": f"{original_actor.ap_id}#main-key",
            "publicKeyPem": "-----BEGIN PUBLIC KEY-----\nMIIBIjANB\n-----END PUBLIC KEY-----\n",
        },
    }
    note_json = {
        "id": original_note_ap_id,
        "type": "Note",
        "attributedTo": original_actor.ap_id,
        "content": "<p>I was created by handle_create first</p>",
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "cc": [f"{original_actor.ap_id}/followers"],
        "published": "2026-03-12T10:00:00Z",
    }

    class FakeResponse:
        def __init__(self, data):
            self.status_code = 200
            self._data = data

        def json(self):
            return self._data

    async def mock_signed_get(db_, url):
        if "notes/" in url:
            return FakeResponse(note_json)
        if "users/" in url:
            return FakeResponse(actor_json)
        return None

    # announce活動: 元ノートは存在するがget_note_by_ap_idがNoneを返す
    # (キャッシュの不整合など)→fetch_remote_noteが呼ばれてIntegrityError
    # このテストでは、元ノートのap_idをDBに先に挿入した状態で
    # handle_announceが正常にリノートを作成することを検証
    mock_get = AsyncMock(side_effect=mock_signed_get)
    with patch("app.services.actor_service._signed_get", mock_get):
        activity = {
            "id": "http://ie.example/activities/announce-race",
            "type": "Announce",
            "actor": booster.ap_id,
            "object": original_note_ap_id,
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [booster.followers_url],
            "published": "2026-03-12T12:00:00Z",
        }
        await handle_announce(db, activity)

    # リノートが正常に作成されていること
    renote = await get_note_by_ap_id(db, "http://ie.example/activities/announce-race")
    assert renote is not None, "IntegrityError後もリノートは作成されるべき"
    assert renote.renote_of_id == pre_existing_note.id
    assert renote.renote_of_ap_id == original_note_ap_id
