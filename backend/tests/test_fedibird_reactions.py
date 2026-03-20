"""Tests for Fedibird-compatible emoji reaction API endpoints."""

from tests.conftest import make_note


async def test_put_emoji_reaction(authed_client, db, test_user, mock_valkey):
    """PUT adds a reaction and returns status with emoji_reactions."""
    note = await make_note(db, test_user.actor)
    await db.commit()

    resp = await authed_client.put(f"/api/v1/statuses/{note.id}/emoji_reactions/😀")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(note.id)
    assert len(data["emoji_reactions"]) == 1
    er = data["emoji_reactions"][0]
    assert er["name"] == "😀"
    assert er["count"] == 1
    assert er["me"] is True
    assert str(test_user.actor_id) in er["account_ids"]


async def test_delete_emoji_reaction(authed_client, db, test_user, mock_valkey):
    """DELETE removes a reaction and returns status with updated emoji_reactions."""
    note = await make_note(db, test_user.actor)
    await db.commit()

    # Add first
    await authed_client.put(f"/api/v1/statuses/{note.id}/emoji_reactions/😀")
    # Remove
    resp = await authed_client.delete(f"/api/v1/statuses/{note.id}/emoji_reactions/😀")
    assert resp.status_code == 200
    data = resp.json()
    assert data["emoji_reactions"] == []


async def test_put_duplicate_reaction_idempotent(authed_client, db, test_user, mock_valkey):
    """PUT with same emoji twice is idempotent (no error)."""
    note = await make_note(db, test_user.actor)
    await db.commit()

    await authed_client.put(f"/api/v1/statuses/{note.id}/emoji_reactions/😀")
    resp = await authed_client.put(f"/api/v1/statuses/{note.id}/emoji_reactions/😀")
    assert resp.status_code == 200
    # Still just 1 reaction
    assert resp.json()["emoji_reactions"][0]["count"] == 1


async def test_delete_nonexistent_reaction_idempotent(authed_client, db, test_user, mock_valkey):
    """DELETE a reaction that doesn't exist is idempotent (no error)."""
    note = await make_note(db, test_user.actor)
    await db.commit()

    resp = await authed_client.delete(f"/api/v1/statuses/{note.id}/emoji_reactions/😀")
    assert resp.status_code == 200


async def test_emoji_reactions_in_status_response(authed_client, db, test_user, mock_valkey):
    """emoji_reactions field appears in single status GET."""
    note = await make_note(db, test_user.actor)
    await db.commit()

    await authed_client.put(f"/api/v1/statuses/{note.id}/emoji_reactions/❤️")
    resp = await authed_client.get(f"/api/v1/statuses/{note.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "emoji_reactions" in data
    assert len(data["emoji_reactions"]) == 1
    assert data["emoji_reactions"][0]["name"] == "❤️"


async def test_multiple_emoji_reactions(authed_client, db, test_user, test_user_b, mock_valkey):
    """Multiple different emoji reactions show correctly."""
    from unittest.mock import AsyncMock

    note = await make_note(db, test_user.actor)
    await db.commit()

    # User A reacts with 😀
    await authed_client.put(f"/api/v1/statuses/{note.id}/emoji_reactions/😀")

    # Add reaction from user B directly via service
    from app.services.reaction_service import add_reaction

    await add_reaction(db, test_user_b, note, "❤️")
    await db.commit()

    resp = await authed_client.get(f"/api/v1/statuses/{note.id}")
    assert resp.status_code == 200
    data = resp.json()
    names = {er["name"] for er in data["emoji_reactions"]}
    assert "😀" in names
    assert "❤️" in names


async def test_put_reaction_not_found(authed_client, mock_valkey):
    """PUT to nonexistent note returns 404."""
    import uuid

    resp = await authed_client.put(
        f"/api/v1/statuses/{uuid.uuid4()}/emoji_reactions/😀"
    )
    assert resp.status_code == 404


async def test_emoji_reactions_field_empty_by_default(authed_client, db, test_user, mock_valkey):
    """Status with no reactions has empty emoji_reactions list."""
    note = await make_note(db, test_user.actor)
    await db.commit()

    resp = await authed_client.get(f"/api/v1/statuses/{note.id}")
    assert resp.status_code == 200
    assert resp.json()["emoji_reactions"] == []
