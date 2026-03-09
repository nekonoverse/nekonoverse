import uuid

from tests.conftest import make_note


async def test_edit_updates_content(authed_client, test_user, db):
    """Editing a note should update its content and source."""
    note = await make_note(db, test_user.actor, content="Original content")
    await db.commit()

    resp = await authed_client.put(
        f"/api/v1/statuses/{note.id}",
        json={"content": "Edited content"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "Edited content" in data["content"]
    assert data["source"] == "Edited content"
    assert data["edited_at"] is not None


async def test_edit_creates_history(authed_client, test_user, db):
    """Editing a note should save the previous version in history."""
    note = await make_note(db, test_user.actor, content="Version 1")
    await db.commit()

    resp = await authed_client.put(
        f"/api/v1/statuses/{note.id}",
        json={"content": "Version 2"},
    )
    assert resp.status_code == 200

    hist_resp = await authed_client.get(f"/api/v1/statuses/{note.id}/history")
    assert hist_resp.status_code == 200
    history = hist_resp.json()
    # History should contain 2 entries: the original + the current
    assert len(history) == 2
    # First entry is the original version
    assert "Version 1" in history[0]["content"]
    # Second entry is the current version
    assert "Version 2" in history[1]["content"]


async def test_edit_non_author_403(authed_client, test_user, test_user_b, db):
    """Editing someone else's note should return 403."""
    note = await make_note(db, test_user_b.actor, content="Not yours")
    await db.commit()

    resp = await authed_client.put(
        f"/api/v1/statuses/{note.id}",
        json={"content": "Trying to edit"},
    )
    assert resp.status_code == 403


async def test_history_endpoint(authed_client, test_user, db):
    """The history endpoint should return all edit versions plus current."""
    note = await make_note(db, test_user.actor, content="First")
    await db.commit()

    # Make two edits
    await authed_client.put(
        f"/api/v1/statuses/{note.id}",
        json={"content": "Second"},
    )
    await authed_client.put(
        f"/api/v1/statuses/{note.id}",
        json={"content": "Third"},
    )

    resp = await authed_client.get(f"/api/v1/statuses/{note.id}/history")
    assert resp.status_code == 200
    history = resp.json()
    # 2 edits saved as history + 1 current version = 3 entries
    assert len(history) == 3
    assert "First" in history[0]["content"]
    assert "Second" in history[1]["content"]
    assert "Third" in history[2]["content"]


async def test_edit_not_found(authed_client):
    """Editing a non-existent note should return 404."""
    fake_id = uuid.uuid4()
    resp = await authed_client.put(
        f"/api/v1/statuses/{fake_id}",
        json={"content": "Does not exist"},
    )
    assert resp.status_code == 404


async def test_edit_updates_spoiler_text(authed_client, test_user, db):
    """Editing should update spoiler_text."""
    note = await make_note(db, test_user.actor, content="CW test")
    await db.commit()

    resp = await authed_client.put(
        f"/api/v1/statuses/{note.id}",
        json={"content": "Updated CW", "spoiler_text": "Spoiler!"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["spoiler_text"] == "Spoiler!"
