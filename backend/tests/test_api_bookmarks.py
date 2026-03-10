"""Tests for GET /api/v1/bookmarks endpoint."""


from tests.conftest import make_note


async def test_get_bookmarks_authenticated(authed_client, test_user, db, mock_valkey):
    """Authenticated user gets their bookmarked notes."""
    note = await make_note(db, test_user.actor, content="bookmarked note")
    from app.services.bookmark_service import create_bookmark

    await create_bookmark(db, test_user.actor_id, note.id)
    await db.flush()

    resp = await authed_client.get("/api/v1/bookmarks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    contents = [n["content"] for n in data]
    assert any("bookmarked note" in c for c in contents)


async def test_get_bookmarks_empty(authed_client, test_user, db, mock_valkey):
    """Returns empty list when no bookmarks."""
    resp = await authed_client.get("/api/v1/bookmarks")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_bookmarks_unauthenticated(app_client, mock_valkey):
    """Unauthenticated request gets 401."""
    resp = await app_client.get("/api/v1/bookmarks")
    assert resp.status_code == 401


async def test_get_bookmarks_with_limit(authed_client, test_user, db, mock_valkey):
    """Respects limit parameter."""
    for i in range(5):
        note = await make_note(db, test_user.actor, content=f"note {i}")
        from app.services.bookmark_service import create_bookmark

        await create_bookmark(db, test_user.actor_id, note.id)
    await db.flush()

    resp = await authed_client.get("/api/v1/bookmarks?limit=2")
    assert resp.status_code == 200
    assert len(resp.json()) <= 2
