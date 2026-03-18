"""Tests for import-and-react endpoint and importable flag in reaction summaries."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
async def admin_user(db):
    from app.services.user_service import create_user

    return await create_user(
        db,
        "adminuser",
        "admin@example.com",
        "password1234",
        display_name="Admin User",
        role="admin",
    )


@pytest.fixture
async def admin_client(app_client, admin_user, mock_valkey):
    mock_valkey.get = AsyncMock(return_value=str(admin_user.id))
    app_client.cookies.set("nekonoverse_session", "admin-session")
    return app_client


@pytest.fixture
async def remote_emoji(db):
    from app.models.custom_emoji import CustomEmoji

    emoji = CustomEmoji(
        shortcode="blobcat",
        domain="remote.example",
        url="https://remote.example/emoji/blobcat.png",
        visible_in_picker=False,
        author="Artist",
        license="CC0",
        copy_permission="allow",
    )
    db.add(emoji)
    await db.flush()
    return emoji


@pytest.fixture
async def remote_emoji_denied(db):
    from app.models.custom_emoji import CustomEmoji

    emoji = CustomEmoji(
        shortcode="denied_cat",
        domain="remote.example",
        url="https://remote.example/emoji/denied_cat.png",
        visible_in_picker=False,
        copy_permission="deny",
    )
    db.add(emoji)
    await db.flush()
    return emoji


@pytest.fixture
async def note(db, admin_user):
    from app.models.note import Note

    note = Note(
        id=uuid.uuid4(),
        ap_id=f"https://localhost/notes/{uuid.uuid4()}",
        actor_id=admin_user.actor_id,
        content="Test note",
        source="Test note",
        visibility="public",
    )
    db.add(note)
    await db.flush()
    return note


# --- import-react endpoint ---


async def test_import_react_no_auth(app_client, note, remote_emoji):
    resp = await app_client.post(
        f"/api/v1/statuses/{note.id}/import-react",
        json={"emoji": ":blobcat@remote.example:"},
    )
    assert resp.status_code == 401 or resp.status_code == 403


async def test_import_react_regular_user_forbidden(authed_client, note, remote_emoji):
    resp = await authed_client.post(
        f"/api/v1/statuses/{note.id}/import-react",
        json={"emoji": ":blobcat@remote.example:"},
    )
    assert resp.status_code == 403


async def test_import_react_already_exists_reacts(
    admin_client, db, note, remote_emoji, mock_valkey
):
    """When local emoji exists, import is skipped and reaction is created."""
    from app.models.custom_emoji import CustomEmoji

    local = CustomEmoji(
        shortcode="blobcat",
        domain=None,
        url="https://localhost/emoji/blobcat.png",
        visible_in_picker=True,
    )
    db.add(local)
    await db.flush()

    resp = await admin_client.post(
        f"/api/v1/statuses/{note.id}/import-react",
        json={"emoji": ":blobcat@remote.example:"},
    )
    assert resp.status_code == 200


async def test_import_react_invalid_format(admin_client, note):
    resp = await admin_client.post(
        f"/api/v1/statuses/{note.id}/import-react",
        json={"emoji": ":blobcat:"},
    )
    assert resp.status_code == 422


async def test_import_react_not_found(admin_client, note):
    resp = await admin_client.post(
        f"/api/v1/statuses/{note.id}/import-react",
        json={"emoji": ":nonexistent@nowhere.example:"},
    )
    assert resp.status_code == 404


async def test_import_react_copy_denied(admin_client, note, remote_emoji_denied):
    resp = await admin_client.post(
        f"/api/v1/statuses/{note.id}/import-react",
        json={"emoji": ":denied_cat@remote.example:"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    if isinstance(detail, list):
        detail = str(detail)
    assert "deny" in detail.lower() or "denied" in detail.lower()


async def test_import_react_already_local(admin_client, db, note, remote_emoji, mock_valkey):
    """When a local emoji already exists, skip import and react directly."""
    from app.models.custom_emoji import CustomEmoji

    local = CustomEmoji(
        shortcode="blobcat",
        domain=None,
        url="https://localhost/emoji/blobcat.png",
        visible_in_picker=True,
    )
    db.add(local)
    await db.flush()

    resp = await admin_client.post(
        f"/api/v1/statuses/{note.id}/import-react",
        json={"emoji": ":blobcat@remote.example:"},
    )
    assert resp.status_code == 200


# --- remote-info endpoint ---


async def test_remote_info_success(admin_client, remote_emoji):
    resp = await admin_client.get(
        "/api/v1/emoji/remote-info",
        params={"shortcode": "blobcat", "domain": "remote.example"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["shortcode"] == "blobcat"
    assert data["domain"] == "remote.example"
    assert data["author"] == "Artist"


async def test_remote_info_not_found(admin_client):
    resp = await admin_client.get(
        "/api/v1/emoji/remote-info",
        params={"shortcode": "nonexistent", "domain": "nowhere.example"},
    )
    assert resp.status_code == 404


async def test_remote_info_no_auth(app_client, remote_emoji):
    resp = await app_client.get(
        "/api/v1/emoji/remote-info",
        params={"shortcode": "blobcat", "domain": "remote.example"},
    )
    assert resp.status_code == 401 or resp.status_code == 403


# --- importable flag in reaction summaries ---


async def test_reaction_summary_importable_flag(db, admin_user, note, remote_emoji, mock_valkey):
    """Remote-only custom emoji reactions should have importable=True."""
    from app.models.reaction import Reaction
    from app.services.note_service import get_reaction_summaries

    # Add a reaction with remote emoji
    reaction = Reaction(
        id=uuid.uuid4(),
        ap_id=f"https://localhost/reactions/{uuid.uuid4()}",
        actor_id=admin_user.actor_id,
        note_id=note.id,
        emoji=":blobcat@remote.example:",
    )
    db.add(reaction)
    await db.flush()

    summaries = await get_reaction_summaries(db, [note.id])
    assert note.id in summaries
    assert len(summaries[note.id]) == 1
    assert summaries[note.id][0]["importable"] is True
    assert summaries[note.id][0]["import_domain"] == "remote.example"


async def test_reaction_summary_local_not_importable(db, admin_user, note, mock_valkey):
    """Local custom emoji reactions should have importable=False."""
    from app.models.custom_emoji import CustomEmoji
    from app.models.reaction import Reaction
    from app.services.note_service import get_reaction_summaries

    local = CustomEmoji(
        shortcode="localcat",
        domain=None,
        url="https://localhost/emoji/localcat.png",
        visible_in_picker=True,
    )
    db.add(local)
    await db.flush()

    reaction = Reaction(
        id=uuid.uuid4(),
        ap_id=f"https://localhost/reactions/{uuid.uuid4()}",
        actor_id=admin_user.actor_id,
        note_id=note.id,
        emoji=":localcat:",
    )
    db.add(reaction)
    await db.flush()

    summaries = await get_reaction_summaries(db, [note.id])
    assert summaries[note.id][0]["importable"] is False


async def test_reaction_summary_importable_without_domain(
    db, admin_user, note, remote_emoji, mock_valkey
):
    """Reaction stored as :shortcode: (no @domain) should still be importable with domain."""
    from app.models.reaction import Reaction
    from app.services.note_service import get_reaction_summaries

    # Reaction stored without @domain (e.g., local user reacted with :shortcode:)
    reaction = Reaction(
        id=uuid.uuid4(),
        ap_id=f"https://localhost/reactions/{uuid.uuid4()}",
        actor_id=admin_user.actor_id,
        note_id=note.id,
        emoji=":blobcat:",
    )
    db.add(reaction)
    await db.flush()

    summaries = await get_reaction_summaries(db, [note.id])
    assert len(summaries[note.id]) == 1
    assert summaries[note.id][0]["importable"] is True
    assert summaries[note.id][0]["import_domain"] == "remote.example"


async def test_reaction_summary_unicode_not_importable(db, admin_user, note, mock_valkey):
    """Unicode emoji reactions should have importable=False."""
    from app.models.reaction import Reaction
    from app.services.note_service import get_reaction_summaries

    reaction = Reaction(
        id=uuid.uuid4(),
        ap_id=f"https://localhost/reactions/{uuid.uuid4()}",
        actor_id=admin_user.actor_id,
        note_id=note.id,
        emoji="\u2b50",
    )
    db.add(reaction)
    await db.flush()

    summaries = await get_reaction_summaries(db, [note.id])
    assert summaries[note.id][0]["importable"] is False


# --- verify_credentials permissions ---


async def test_verify_credentials_admin_permissions(admin_client):
    resp = await admin_client.get("/api/v1/accounts/verify_credentials")
    assert resp.status_code == 200
    data = resp.json()
    assert "nekonoverse_permissions" in data
    assert "emoji" in data["nekonoverse_permissions"]


async def test_verify_credentials_regular_user_no_permissions(authed_client):
    resp = await authed_client.get("/api/v1/accounts/verify_credentials")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("nekonoverse_permissions", []) == []
