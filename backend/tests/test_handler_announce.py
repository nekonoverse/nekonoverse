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
        from tests.conftest import make_remote_actor as _mra
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
    from sqlalchemy import select, func
    from app.models.note import Note
    count_result = await db.execute(
        select(func.count()).select_from(Note).where(
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
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Original post for renote test", "visibility": "public"
    })
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
