"""Tests for Mastodon-compatible API endpoints (favourite, relationships, search)."""

import uuid

# --- favourite / unfavourite ---


async def test_favourite_status(authed_client, mock_valkey):
    """POST /api/v1/statuses/{id}/favourite creates ⭐ reaction."""
    create = await authed_client.post(
        "/api/v1/statuses", json={"content": "fav test", "visibility": "public"}
    )
    assert create.status_code == 201
    note_id = create.json()["id"]

    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/favourite")
    assert resp.status_code == 200
    body = resp.json()
    assert body["favourited"] is True


async def test_favourite_idempotent(authed_client, mock_valkey):
    """Favouriting twice should not error (idempotent)."""
    create = await authed_client.post(
        "/api/v1/statuses", json={"content": "fav idem", "visibility": "public"}
    )
    note_id = create.json()["id"]

    await authed_client.post(f"/api/v1/statuses/{note_id}/favourite")
    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/favourite")
    assert resp.status_code == 200
    assert resp.json()["favourited"] is True


async def test_favourite_not_found(authed_client, mock_valkey):
    """Favouriting a non-existent note returns 404."""
    fake_id = str(uuid.uuid4())
    resp = await authed_client.post(f"/api/v1/statuses/{fake_id}/favourite")
    assert resp.status_code == 404


async def test_favourite_unauthenticated(app_client, mock_valkey):
    """Favouriting without auth returns 401."""
    fake_id = str(uuid.uuid4())
    resp = await app_client.post(f"/api/v1/statuses/{fake_id}/favourite")
    assert resp.status_code == 401


async def test_unfavourite_status(authed_client, mock_valkey):
    """POST /api/v1/statuses/{id}/unfavourite removes ⭐ reaction."""
    create = await authed_client.post(
        "/api/v1/statuses", json={"content": "unfav test", "visibility": "public"}
    )
    note_id = create.json()["id"]

    await authed_client.post(f"/api/v1/statuses/{note_id}/favourite")
    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/unfavourite")
    assert resp.status_code == 200
    assert resp.json()["favourited"] is False


async def test_unfavourite_not_favourited(authed_client, mock_valkey):
    """Unfavouriting when not favourited should not error."""
    create = await authed_client.post(
        "/api/v1/statuses", json={"content": "unfav noop", "visibility": "public"}
    )
    note_id = create.json()["id"]

    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/unfavourite")
    assert resp.status_code == 200
    assert resp.json()["favourited"] is False


async def test_unfavourite_not_found(authed_client, mock_valkey):
    """Unfavouriting a non-existent note returns 404."""
    fake_id = str(uuid.uuid4())
    resp = await authed_client.post(f"/api/v1/statuses/{fake_id}/unfavourite")
    assert resp.status_code == 404


# --- favourited_by ---


async def test_favourited_by(authed_client, mock_valkey):
    """GET /api/v1/statuses/{id}/favourited_by returns accounts that favourited."""
    create = await authed_client.post(
        "/api/v1/statuses", json={"content": "fav by test", "visibility": "public"}
    )
    note_id = create.json()["id"]

    await authed_client.post(f"/api/v1/statuses/{note_id}/favourite")

    resp = await authed_client.get(f"/api/v1/statuses/{note_id}/favourited_by")
    assert resp.status_code == 200
    accounts = resp.json()
    assert len(accounts) >= 1
    assert "id" in accounts[0]
    assert "username" in accounts[0]


async def test_favourited_by_empty(authed_client, mock_valkey):
    """GET /api/v1/statuses/{id}/favourited_by returns empty when no favourites."""
    create = await authed_client.post(
        "/api/v1/statuses", json={"content": "no favs", "visibility": "public"}
    )
    note_id = create.json()["id"]

    resp = await authed_client.get(f"/api/v1/statuses/{note_id}/favourited_by")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_favourited_by_not_found(authed_client, mock_valkey):
    """GET /api/v1/statuses/{id}/favourited_by for non-existent note returns 404."""
    fake_id = str(uuid.uuid4())
    resp = await authed_client.get(f"/api/v1/statuses/{fake_id}/favourited_by")
    assert resp.status_code == 404


# --- accounts/relationships ---


async def test_relationships_empty(authed_client, mock_valkey):
    """GET /api/v1/accounts/relationships with no ids returns empty."""
    resp = await authed_client.get("/api/v1/accounts/relationships")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_relationships_batch(authed_client, test_user_b, mock_valkey):
    """GET /api/v1/accounts/relationships returns batch results."""
    actor_id = str(test_user_b.actor_id)
    resp = await authed_client.get(
        f"/api/v1/accounts/relationships?id[]={actor_id}"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == actor_id
    assert "following" in body[0]
    assert "followed_by" in body[0]
    assert "blocking" in body[0]
    assert "muting" in body[0]
    assert "requested" in body[0]


async def test_relationships_unauthenticated(app_client, mock_valkey):
    """GET /api/v1/accounts/relationships without auth returns 401."""
    resp = await app_client.get("/api/v1/accounts/relationships")
    assert resp.status_code == 401


async def test_relationships_invalid_uuid(authed_client, mock_valkey):
    """GET /api/v1/accounts/relationships with invalid UUID returns empty."""
    resp = await authed_client.get(
        "/api/v1/accounts/relationships?id[]=not-a-uuid"
    )
    assert resp.status_code == 200
    assert resp.json() == []


# --- search ---


async def test_search_accounts(authed_client, test_user, mock_valkey):
    """GET /api/v2/search?type=accounts finds accounts by username."""
    username = test_user.actor.username
    resp = await authed_client.get(
        f"/api/v2/search?q={username}&type=accounts"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "accounts" in body
    assert "statuses" in body
    assert "hashtags" in body
    # accounts検索結果にテストユーザーが含まれる
    assert len(body["accounts"]) >= 1
    assert body["statuses"] == []
    assert body["hashtags"] == []


async def test_search_statuses(authed_client, mock_valkey):
    """GET /api/v2/search?type=statuses finds public notes by content."""
    # ユニークな検索語を含むノートを作成
    unique = f"searchtest_{uuid.uuid4().hex[:8]}"
    await authed_client.post(
        "/api/v1/statuses", json={"content": unique, "visibility": "public"}
    )

    resp = await authed_client.get(
        f"/api/v2/search?q={unique}&type=statuses"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["statuses"]) >= 1
    assert body["accounts"] == []
    assert body["hashtags"] == []


async def test_search_hashtags(authed_client, db, mock_valkey):
    """GET /api/v2/search?type=hashtags finds hashtags."""
    unique_tag = f"testtag{uuid.uuid4().hex[:6]}"
    await authed_client.post(
        "/api/v1/statuses",
        json={"content": f"post with #{unique_tag}", "visibility": "public"},
    )

    resp = await authed_client.get(
        f"/api/v2/search?q={unique_tag}&type=hashtags"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["hashtags"]) >= 1
    assert body["hashtags"][0]["name"] == unique_tag


async def test_search_all(authed_client, mock_valkey):
    """GET /api/v2/search without type searches all categories."""
    resp = await authed_client.get("/api/v2/search?q=test")
    assert resp.status_code == 200
    body = resp.json()
    assert "accounts" in body
    assert "statuses" in body
    assert "hashtags" in body


async def test_search_empty_query(authed_client, mock_valkey):
    """GET /api/v2/search with empty query returns 422."""
    resp = await authed_client.get("/api/v2/search?q=")
    assert resp.status_code == 422
