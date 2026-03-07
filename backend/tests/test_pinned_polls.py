"""Tests for pinned notes, polls, and Misskey talk features."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import make_note, make_remote_actor


# ==================== Pinned Notes ====================


@pytest.mark.asyncio
async def test_pin_note(authed_client, test_user, db):
    note = await make_note(db, test_user.actor)
    resp = await authed_client.post(f"/api/v1/statuses/{note.id}/pin")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_pin_note_not_yours(authed_client, test_user, test_user_b, db):
    note = await make_note(db, test_user_b.actor)
    resp = await authed_client.post(f"/api/v1/statuses/{note.id}/pin")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_pin_duplicate(authed_client, test_user, db):
    note = await make_note(db, test_user.actor)
    await authed_client.post(f"/api/v1/statuses/{note.id}/pin")
    resp = await authed_client.post(f"/api/v1/statuses/{note.id}/pin")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_pin_limit(authed_client, test_user, db):
    for i in range(5):
        note = await make_note(db, test_user.actor, content=f"Pin {i}")
        await authed_client.post(f"/api/v1/statuses/{note.id}/pin")

    extra = await make_note(db, test_user.actor, content="Extra pin")
    resp = await authed_client.post(f"/api/v1/statuses/{extra.id}/pin")
    assert resp.status_code == 422
    assert "Maximum" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_unpin_note(authed_client, test_user, db):
    note = await make_note(db, test_user.actor)
    await authed_client.post(f"/api/v1/statuses/{note.id}/pin")
    resp = await authed_client.post(f"/api/v1/statuses/{note.id}/unpin")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_unpin_not_pinned(authed_client, test_user, db):
    note = await make_note(db, test_user.actor)
    resp = await authed_client.post(f"/api/v1/statuses/{note.id}/unpin")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_featured_collection(app_client, test_user, db, mock_valkey):
    note = await make_note(db, test_user.actor)
    from app.services.pinned_note_service import pin_note
    await pin_note(db, test_user, note.id)
    await db.commit()

    resp = await app_client.get(
        f"/users/{test_user.actor.username}/featured",
        headers={"accept": "application/activity+json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "OrderedCollection"
    assert data["totalItems"] == 1
    assert len(data["orderedItems"]) == 1
    assert data["orderedItems"][0]["id"] == note.ap_id


@pytest.mark.asyncio
async def test_featured_collection_empty(app_client, test_user, db, mock_valkey):
    resp = await app_client.get(
        f"/users/{test_user.actor.username}/featured",
        headers={"accept": "application/activity+json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["totalItems"] == 0


# ==================== Polls ====================


@pytest.mark.asyncio
async def test_create_poll_note(authed_client, test_user, db):
    resp = await authed_client.post("/api/v1/statuses", json={
        "content": "What's your favorite color?",
        "poll": {
            "options": ["Red", "Blue", "Green"],
            "expires_in": 3600,
            "multiple": False,
        },
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["content"]  # Content should be set


@pytest.mark.asyncio
async def test_create_poll_then_get(authed_client, test_user, db):
    # Create poll note
    resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Pick one",
        "poll": {
            "options": ["A", "B"],
            "expires_in": 3600,
        },
    })
    assert resp.status_code == 201
    note_id = resp.json()["id"]

    # Get poll data
    resp2 = await authed_client.get(f"/api/v1/polls/{note_id}")
    assert resp2.status_code == 200
    poll = resp2.json()
    assert len(poll["options"]) == 2
    assert poll["options"][0]["title"] == "A"
    assert poll["options"][1]["title"] == "B"
    assert poll["expired"] is False
    assert poll["multiple"] is False


@pytest.mark.asyncio
async def test_vote_on_poll(authed_client, test_user, test_user_b, db, mock_valkey):
    # Create poll as user A
    from app.services.note_service import create_note
    note = await create_note(
        db, test_user, "Vote please",
        poll_options=["Yes", "No"],
        poll_expires_in=3600,
    )

    # Vote as user B
    session_id_b = "test-session-b"
    mock_valkey.get = AsyncMock(return_value=str(test_user_b.id))

    from app.dependencies import get_db
    from app.main import app

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client_b:
        client_b.cookies.set("nekonoverse_session", session_id_b)
        resp = await client_b.post(f"/api/v1/polls/{note.id}/votes", json={
            "choices": [0],
        })
        assert resp.status_code == 200
        poll = resp.json()
        assert poll["voted"] is True
        assert poll["own_votes"] == [0]
        assert poll["options"][0]["votes_count"] == 1


@pytest.mark.asyncio
async def test_vote_duplicate(authed_client, test_user, db):
    from app.services.note_service import create_note
    note = await create_note(
        db, test_user, "Vote once",
        poll_options=["A", "B"],
        poll_expires_in=3600,
    )

    resp = await authed_client.post(f"/api/v1/polls/{note.id}/votes", json={"choices": [0]})
    assert resp.status_code == 200

    resp2 = await authed_client.post(f"/api/v1/polls/{note.id}/votes", json={"choices": [1]})
    assert resp2.status_code == 422
    assert "Already voted" in resp2.json()["detail"]


@pytest.mark.asyncio
async def test_poll_multiple_choice(authed_client, test_user, db):
    from app.services.note_service import create_note
    note = await create_note(
        db, test_user, "Pick many",
        poll_options=["X", "Y", "Z"],
        poll_expires_in=3600,
        poll_multiple=True,
    )

    resp = await authed_client.post(f"/api/v1/polls/{note.id}/votes", json={"choices": [0, 2]})
    assert resp.status_code == 200
    poll = resp.json()
    assert poll["own_votes"] == [0, 2]
    assert poll["options"][0]["votes_count"] == 1
    assert poll["options"][2]["votes_count"] == 1


@pytest.mark.asyncio
async def test_poll_reject_multiple_when_single(authed_client, test_user, db):
    from app.services.note_service import create_note
    note = await create_note(
        db, test_user, "Pick one only",
        poll_options=["A", "B"],
        poll_expires_in=3600,
        poll_multiple=False,
    )

    resp = await authed_client.post(f"/api/v1/polls/{note.id}/votes", json={"choices": [0, 1]})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_poll_not_found(authed_client):
    resp = await authed_client.get(f"/api/v1/polls/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_poll_expired(authed_client, test_user, db):
    from app.models.note import Note
    from app.services.note_service import create_note
    note = await create_note(
        db, test_user, "Expired poll",
        poll_options=["Old", "Ancient"],
        poll_expires_in=1,
    )
    # Manually expire
    note.poll_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db.commit()

    resp = await authed_client.post(f"/api/v1/polls/{note.id}/votes", json={"choices": [0]})
    assert resp.status_code == 422
    assert "expired" in resp.json()["detail"]


# ==================== AP Rendering ====================


@pytest.mark.asyncio
async def test_render_poll_note_as_question(test_user, db):
    from app.activitypub.renderer import render_note
    from app.services.note_service import create_note
    note = await create_note(
        db, test_user, "Which?",
        poll_options=["Alpha", "Beta"],
        poll_expires_in=3600,
    )
    data = render_note(note)
    assert data["type"] == "Question"
    assert "oneOf" in data
    assert len(data["oneOf"]) == 2
    assert data["oneOf"][0]["name"] == "Alpha"
    assert "endTime" in data


@pytest.mark.asyncio
async def test_render_multiple_poll_uses_anyof(test_user, db):
    from app.activitypub.renderer import render_note
    from app.services.note_service import create_note
    note = await create_note(
        db, test_user, "Pick many",
        poll_options=["X", "Y"],
        poll_expires_in=3600,
        poll_multiple=True,
    )
    data = render_note(note)
    assert data["type"] == "Question"
    assert "anyOf" in data
    assert "oneOf" not in data


@pytest.mark.asyncio
async def test_render_actor_featured_url(test_user, db):
    from app.activitypub.renderer import render_actor
    data = render_actor(test_user.actor)
    assert "featured" in data
    assert "/featured" in data["featured"]


@pytest.mark.asyncio
async def test_render_actor_moved_to(test_user, db):
    from app.activitypub.renderer import render_actor
    test_user.actor.moved_to_ap_id = "http://remote.example/users/alice"
    data = render_actor(test_user.actor)
    assert data["movedTo"] == "http://remote.example/users/alice"


@pytest.mark.asyncio
async def test_render_actor_also_known_as(test_user, db):
    from app.activitypub.renderer import render_actor
    test_user.actor.also_known_as = ["http://old.example/users/alice"]
    data = render_actor(test_user.actor)
    assert data["alsoKnownAs"] == ["http://old.example/users/alice"]


# ==================== Incoming Question ====================


@pytest.mark.asyncio
async def test_incoming_question_creates_poll(db):
    """Receiving a Create(Question) should create a poll note."""
    remote = await make_remote_actor(db, username="pollster", domain="poll.example")

    from app.activitypub.handlers.create import handle_create
    activity = {
        "type": "Create",
        "actor": remote.ap_id,
        "object": {
            "type": "Question",
            "id": f"{remote.ap_id}/notes/q1",
            "attributedTo": remote.ap_id,
            "content": "<p>Best language?</p>",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
            "published": "2025-06-01T00:00:00Z",
            "oneOf": [
                {"type": "Note", "name": "Python", "replies": {"type": "Collection", "totalItems": 5}},
                {"type": "Note", "name": "Rust", "replies": {"type": "Collection", "totalItems": 3}},
            ],
            "endTime": "2025-06-08T00:00:00Z",
        },
    }
    await handle_create(db, activity)

    from app.services.note_service import get_note_by_ap_id
    note = await get_note_by_ap_id(db, f"{remote.ap_id}/notes/q1")
    assert note is not None
    assert note.is_poll is True
    assert note.poll_multiple is False
    assert len(note.poll_options) == 2
    assert note.poll_options[0]["title"] == "Python"
    assert note.poll_options[0]["votes_count"] == 5
    assert note.poll_expires_at is not None


@pytest.mark.asyncio
async def test_incoming_question_anyof(db):
    """anyOf questions should set poll_multiple=True."""
    remote = await make_remote_actor(db, username="multipoll", domain="poll.example")

    from app.activitypub.handlers.create import handle_create
    activity = {
        "type": "Create",
        "actor": remote.ap_id,
        "object": {
            "type": "Question",
            "id": f"{remote.ap_id}/notes/q2",
            "attributedTo": remote.ap_id,
            "content": "<p>Pick many</p>",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
            "published": "2025-06-01T00:00:00Z",
            "anyOf": [
                {"type": "Note", "name": "A", "replies": {"type": "Collection", "totalItems": 0}},
                {"type": "Note", "name": "B", "replies": {"type": "Collection", "totalItems": 0}},
            ],
        },
    }
    await handle_create(db, activity)

    from app.services.note_service import get_note_by_ap_id
    note = await get_note_by_ap_id(db, f"{remote.ap_id}/notes/q2")
    assert note is not None
    assert note.is_poll is True
    assert note.poll_multiple is True


@pytest.mark.asyncio
async def test_incoming_misskey_talk(db):
    """_misskey_talk flag should set is_talk."""
    remote = await make_remote_actor(db, username="talker", domain="talk.example")

    from app.activitypub.handlers.create import handle_create
    activity = {
        "type": "Create",
        "actor": remote.ap_id,
        "object": {
            "type": "Note",
            "id": f"{remote.ap_id}/notes/talk1",
            "attributedTo": remote.ap_id,
            "content": "<p>Chat message</p>",
            "to": [remote.ap_id],
            "cc": [],
            "published": "2025-06-01T00:00:00Z",
            "_misskey_talk": True,
        },
    }
    await handle_create(db, activity)

    from app.services.note_service import get_note_by_ap_id
    note = await get_note_by_ap_id(db, f"{remote.ap_id}/notes/talk1")
    assert note is not None
    assert note.is_talk is True


@pytest.mark.asyncio
async def test_render_talk_flag(test_user, db):
    from app.activitypub.renderer import render_note
    from app.models.note import Note
    note = await make_note(db, test_user.actor, content="DM")
    note.is_talk = True
    await db.flush()
    # Re-fetch to get actor loaded
    from app.services.note_service import get_note_by_id
    note = await get_note_by_id(db, note.id)
    data = render_note(note)
    assert data.get("_misskey_talk") is True


# ==================== Update Question ====================


@pytest.mark.asyncio
async def test_update_question_updates_votes(db):
    """Update(Question) should update poll vote counts."""
    remote = await make_remote_actor(db, username="updater", domain="poll.example")

    from app.activitypub.handlers.create import handle_create
    activity = {
        "type": "Create",
        "actor": remote.ap_id,
        "object": {
            "type": "Question",
            "id": f"{remote.ap_id}/notes/qu1",
            "attributedTo": remote.ap_id,
            "content": "<p>Vote?</p>",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
            "published": "2025-06-01T00:00:00Z",
            "oneOf": [
                {"type": "Note", "name": "Yes", "replies": {"type": "Collection", "totalItems": 0}},
                {"type": "Note", "name": "No", "replies": {"type": "Collection", "totalItems": 0}},
            ],
        },
    }
    await handle_create(db, activity)

    # Now update with new vote counts
    from app.activitypub.handlers.update import handle_update
    update_activity = {
        "type": "Update",
        "actor": remote.ap_id,
        "object": {
            "type": "Question",
            "id": f"{remote.ap_id}/notes/qu1",
            "attributedTo": remote.ap_id,
            "content": "<p>Vote?</p>",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
            "oneOf": [
                {"type": "Note", "name": "Yes", "replies": {"type": "Collection", "totalItems": 10}},
                {"type": "Note", "name": "No", "replies": {"type": "Collection", "totalItems": 5}},
            ],
        },
    }
    await handle_update(db, update_activity)

    from app.services.note_service import get_note_by_ap_id
    note = await get_note_by_ap_id(db, f"{remote.ap_id}/notes/qu1")
    assert note.poll_options[0]["votes_count"] == 10
    assert note.poll_options[1]["votes_count"] == 5


# ==================== Pinned Note Service ====================


@pytest.mark.asyncio
async def test_pinned_note_service_list(test_user, db):
    from app.services.pinned_note_service import get_pinned_notes, pin_note

    n1 = await make_note(db, test_user.actor, content="First pin")
    n2 = await make_note(db, test_user.actor, content="Second pin")
    await pin_note(db, test_user, n1.id)
    await pin_note(db, test_user, n2.id)
    await db.commit()

    pins = await get_pinned_notes(db, test_user.actor.id)
    assert len(pins) == 2
    assert pins[0].note_id == n1.id
    assert pins[1].note_id == n2.id


# ==================== Actor Service Parse ====================


@pytest.mark.asyncio
async def test_upsert_actor_parses_featured(db):
    from app.utils.crypto import generate_rsa_keypair
    _, public_pem = generate_rsa_keypair()

    from app.services.actor_service import upsert_remote_actor
    data = {
        "id": "http://remote.example/users/featured_user",
        "type": "Person",
        "preferredUsername": "featured_user",
        "inbox": "http://remote.example/inbox",
        "publicKey": {"publicKeyPem": public_pem},
        "featured": "http://remote.example/users/featured_user/featured",
        "movedTo": "http://new.example/users/featured_user",
        "alsoKnownAs": ["http://old.example/users/featured_user"],
    }
    actor = await upsert_remote_actor(db, data)
    assert actor.featured_url == "http://remote.example/users/featured_user/featured"
    assert actor.moved_to_ap_id == "http://new.example/users/featured_user"
    assert actor.also_known_as == ["http://old.example/users/featured_user"]
