"""Tests for emoji import-by-shortcode and importable flag in reaction summaries."""

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


# --- import-by-shortcode endpoint ---


async def test_import_by_shortcode_no_auth(app_client, remote_emoji):
    resp = await app_client.post(
        "/api/v1/admin/emoji/import-by-shortcode",
        json={"shortcode": "blobcat", "domain": "remote.example"},
    )
    assert resp.status_code == 401 or resp.status_code == 403


async def test_import_by_shortcode_regular_user_forbidden(authed_client, remote_emoji):
    resp = await authed_client.post(
        "/api/v1/admin/emoji/import-by-shortcode",
        json={"shortcode": "blobcat", "domain": "remote.example"},
    )
    assert resp.status_code == 403


async def test_import_by_shortcode_not_found(admin_client):
    resp = await admin_client.post(
        "/api/v1/admin/emoji/import-by-shortcode",
        json={"shortcode": "nonexistent", "domain": "nowhere.example"},
    )
    assert resp.status_code == 404


async def test_import_by_shortcode_copy_denied(admin_client, remote_emoji_denied):
    resp = await admin_client.post(
        "/api/v1/admin/emoji/import-by-shortcode",
        json={"shortcode": "denied_cat", "domain": "remote.example"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    if isinstance(detail, list):
        detail = str(detail)
    assert "deny" in detail.lower() or "denied" in detail.lower()


async def test_import_by_shortcode_with_overrides(
    admin_client, db, remote_emoji, mock_valkey
):
    """Import with metadata overrides should apply them."""
    with patch(
        "app.services.emoji_service.import_remote_emoji_to_local",
        new_callable=AsyncMock,
    ) as mock_import:
        from app.models.custom_emoji import CustomEmoji

        from datetime import datetime, timezone

        local = CustomEmoji(
            id=remote_emoji.id,
            shortcode="blobcat",
            domain=None,
            url="https://localhost/emoji/blobcat.png",
            visible_in_picker=True,
            author="NewAuthor",
            category="cats",
            is_sensitive=False,
            local_only=False,
            created_at=datetime.now(timezone.utc),
        )
        mock_import.return_value = local

        resp = await admin_client.post(
            "/api/v1/admin/emoji/import-by-shortcode",
            json={
                "shortcode": "blobcat",
                "domain": "remote.example",
                "category": "cats",
                "author": "NewAuthor",
            },
        )
        assert resp.status_code == 200
        mock_import.assert_called_once()


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


# --- remote-sources endpoint ---


async def test_remote_sources_multiple(admin_client, db):
    from app.models.custom_emoji import CustomEmoji

    e1 = CustomEmoji(
        shortcode="multicat",
        domain="alpha.example",
        url="https://alpha.example/emoji/multicat.png",
        copy_permission="allow",
    )
    e2 = CustomEmoji(
        shortcode="multicat",
        domain="beta.example",
        url="https://beta.example/emoji/multicat.png",
        copy_permission="deny",
    )
    db.add_all([e1, e2])
    await db.flush()

    resp = await admin_client.get(
        "/api/v1/emoji/remote-sources",
        params={"shortcode": "multicat"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    domains = [e["domain"] for e in data]
    assert "alpha.example" in domains
    assert "beta.example" in domains


async def test_remote_sources_empty(admin_client):
    resp = await admin_client.get(
        "/api/v1/emoji/remote-sources",
        params={"shortcode": "nonexistent"},
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_remote_sources_no_auth(app_client):
    resp = await app_client.get(
        "/api/v1/emoji/remote-sources",
        params={"shortcode": "anycat"},
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
