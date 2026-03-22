"""Tests for Misskey profile visibility restrictions (_misskey_requireSigninToViewContents etc.)."""

import uuid
from datetime import datetime, timezone, timedelta

from tests.conftest import make_note, make_remote_actor


async def test_upsert_extracts_misskey_visibility_fields(db, mock_valkey):
    """upsert_remote_actor should save requireSigninToViewContents and date-based fields."""
    from app.services.actor_service import upsert_remote_actor
    from app.utils.crypto import generate_rsa_keypair

    _, public_pem = generate_rsa_keypair()
    epoch_ms = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

    data = {
        "id": "https://misskey.example/users/alice",
        "type": "Person",
        "preferredUsername": "alice",
        "inbox": "https://misskey.example/users/alice/inbox",
        "publicKey": {"publicKeyPem": public_pem},
        "isCat": False,
        "_misskey_requireSigninToViewContents": True,
        "_misskey_makeNotesFollowersOnlyBefore": epoch_ms,
        "_misskey_makeNotesHiddenBefore": epoch_ms,
    }
    actor = await upsert_remote_actor(db, data)
    assert actor is not None
    assert actor.require_signin_to_view is True
    assert actor.make_notes_followers_only_before == epoch_ms
    assert actor.make_notes_hidden_before == epoch_ms


async def test_upsert_defaults_when_fields_absent(db, mock_valkey):
    """upsert_remote_actor should default to False/None when Misskey fields are absent."""
    from app.services.actor_service import upsert_remote_actor
    from app.utils.crypto import generate_rsa_keypair

    _, public_pem = generate_rsa_keypair()
    data = {
        "id": "https://mastodon.example/users/bob",
        "type": "Person",
        "preferredUsername": "bob",
        "inbox": "https://mastodon.example/users/bob/inbox",
        "publicKey": {"publicKeyPem": public_pem},
    }
    actor = await upsert_remote_actor(db, data)
    assert actor is not None
    assert actor.require_signin_to_view is False
    assert actor.make_notes_followers_only_before is None
    assert actor.make_notes_hidden_before is None


async def test_account_hidden_for_unauthenticated(app_client, db, mock_valkey):
    """GET /api/v1/accounts/{id} should return limited info for require_signin_to_view actors when unauthenticated."""
    actor = await make_remote_actor(db, username="private_mk", domain="mk.example")
    actor.require_signin_to_view = True
    actor.summary = "This should be hidden"
    await db.commit()

    resp = await app_client.get(f"/api/v1/accounts/{actor.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["limited"] is True
    assert data["note"] == ""
    assert data["fields"] == []
    assert data["avatar"].endswith("/default-avatar.svg")
    assert data["avatar"].startswith("http")


async def test_account_visible_for_authenticated(authed_client, db, test_user, mock_valkey):
    """GET /api/v1/accounts/{id} should return full info for require_signin_to_view actors when authenticated."""
    actor = await make_remote_actor(db, username="private_mk2", domain="mk2.example")
    actor.require_signin_to_view = True
    actor.summary = "Visible to logged in users"
    await db.commit()

    resp = await authed_client.get(f"/api/v1/accounts/{actor.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "limited" not in data
    assert data["note"] == "Visible to logged in users"


async def test_statuses_empty_for_unauthenticated(app_client, db, mock_valkey):
    """GET /api/v1/accounts/{id}/statuses should return empty for require_signin_to_view actors when unauthenticated."""
    actor = await make_remote_actor(db, username="private_mk3", domain="mk3.example")
    actor.require_signin_to_view = True
    await db.commit()
    await make_note(db, actor, content="Hidden note", local=False)

    resp = await app_client.get(f"/api/v1/accounts/{actor.id}/statuses")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_public_timeline_filters_require_signin(app_client, db, mock_valkey):
    """Public timeline should exclude notes from require_signin_to_view actors for unauthenticated users."""
    # Create a normal actor with a note
    normal_actor = await make_remote_actor(db, username="normal", domain="normal.example")
    await make_note(db, normal_actor, content="Normal note", local=False)

    # Create a restricted actor with a note
    private_actor = await make_remote_actor(db, username="restricted", domain="restricted.example")
    private_actor.require_signin_to_view = True
    await db.commit()
    await make_note(db, private_actor, content="Private note", local=False)

    resp = await app_client.get("/api/v1/timelines/public")
    assert resp.status_code == 200
    notes = resp.json()
    contents = [n["content"] for n in notes]
    assert any("Normal note" in c for c in contents)
    assert not any("Private note" in c for c in contents)


async def test_notes_hidden_before_filtered(app_client, db, mock_valkey):
    """Notes published before make_notes_hidden_before should be hidden from public timeline."""
    actor = await make_remote_actor(db, username="hider", domain="hider.example")
    # Set hidden_before to current time (all existing notes should be hidden)
    now = datetime.now(timezone.utc)
    actor.make_notes_hidden_before = int(now.timestamp() * 1000)
    await db.commit()

    # Create a note with published time in the past (before the threshold)
    from app.models.note import Note
    from app.utils.sanitize import text_to_html
    note_id = uuid.uuid4()
    old_note = Note(
        id=note_id,
        ap_id=f"http://hider.example/notes/{note_id}",
        actor_id=actor.id,
        content=text_to_html("Old hidden note"),
        source="Old hidden note",
        visibility="public",
        to=["https://www.w3.org/ns/activitystreams#Public"],
        cc=[],
        local=False,
        published=now - timedelta(hours=1),
    )
    db.add(old_note)
    await db.flush()

    resp = await app_client.get("/api/v1/timelines/public")
    assert resp.status_code == 200
    notes = resp.json()
    assert not any("Old hidden note" in n["content"] for n in notes)


async def test_notes_followers_only_before_unauthenticated(app_client, db, mock_valkey):
    """Notes published before make_notes_followers_only_before should be hidden for unauthenticated users."""
    actor = await make_remote_actor(db, username="fonly", domain="fonly.example")
    now = datetime.now(timezone.utc)
    actor.make_notes_followers_only_before = int(now.timestamp() * 1000)
    await db.commit()

    from app.models.note import Note
    from app.utils.sanitize import text_to_html
    note_id = uuid.uuid4()
    old_note = Note(
        id=note_id,
        ap_id=f"http://fonly.example/notes/{note_id}",
        actor_id=actor.id,
        content=text_to_html("Followers only old note"),
        source="Followers only old note",
        visibility="public",
        to=["https://www.w3.org/ns/activitystreams#Public"],
        cc=[],
        local=False,
        published=now - timedelta(hours=1),
    )
    db.add(old_note)
    await db.flush()

    resp = await app_client.get("/api/v1/timelines/public")
    assert resp.status_code == 200
    notes = resp.json()
    assert not any("Followers only old note" in n["content"] for n in notes)


async def test_render_actor_outputs_misskey_fields(db, mock_valkey):
    """render_actor should include Misskey visibility fields in AP output."""
    from app.activitypub.renderer import render_actor

    actor = await make_remote_actor(db, username="rendered", domain="rendered.example")
    epoch_ms = int(datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp() * 1000)
    actor.require_signin_to_view = True
    actor.make_notes_followers_only_before = epoch_ms
    actor.make_notes_hidden_before = epoch_ms
    await db.commit()

    data = render_actor(actor)
    assert data["_misskey_requireSigninToViewContents"] is True
    assert data["_misskey_makeNotesFollowersOnlyBefore"] == epoch_ms
    assert data["_misskey_makeNotesHiddenBefore"] == epoch_ms

    # Context should include the namespace mappings
    context_dict = data["@context"][2]
    assert "_misskey_requireSigninToViewContents" in context_dict
    assert "_misskey_makeNotesFollowersOnlyBefore" in context_dict
    assert "_misskey_makeNotesHiddenBefore" in context_dict


async def test_render_actor_omits_unset_fields(db, mock_valkey):
    """render_actor should not include Misskey visibility fields when not set."""
    from app.activitypub.renderer import render_actor

    actor = await make_remote_actor(db, username="plain", domain="plain.example")
    await db.commit()

    data = render_actor(actor)
    assert "_misskey_requireSigninToViewContents" not in data
    assert "_misskey_makeNotesFollowersOnlyBefore" not in data
    assert "_misskey_makeNotesHiddenBefore" not in data
