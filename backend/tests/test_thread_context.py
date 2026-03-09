import uuid
from unittest.mock import AsyncMock


async def test_context_empty(authed_client, mock_valkey):
    """A note with no replies or parent has empty context."""
    resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Standalone note", "visibility": "public"
    })
    note_id = resp.json()["id"]

    ctx = await authed_client.get(f"/api/v1/statuses/{note_id}/context")
    assert ctx.status_code == 200
    data = ctx.json()
    assert data["ancestors"] == []
    assert data["descendants"] == []


async def test_context_ancestors(authed_client, mock_valkey):
    """Context returns ancestors for a reply chain."""
    # Create grandparent -> parent -> child
    gp = await authed_client.post("/api/v1/statuses", json={
        "content": "Grandparent", "visibility": "public"
    })
    gp_id = gp.json()["id"]

    parent = await authed_client.post("/api/v1/statuses", json={
        "content": "Parent", "visibility": "public",
        "in_reply_to_id": gp_id,
    })
    parent_id = parent.json()["id"]

    child = await authed_client.post("/api/v1/statuses", json={
        "content": "Child", "visibility": "public",
        "in_reply_to_id": parent_id,
    })
    child_id = child.json()["id"]

    ctx = await authed_client.get(f"/api/v1/statuses/{child_id}/context")
    assert ctx.status_code == 200
    data = ctx.json()

    # ancestors: grandparent, parent (oldest first)
    assert len(data["ancestors"]) == 2
    assert data["ancestors"][0]["id"] == gp_id
    assert data["ancestors"][1]["id"] == parent_id
    assert data["descendants"] == []


async def test_context_descendants(authed_client, mock_valkey):
    """Context returns descendants for a note with replies."""
    root = await authed_client.post("/api/v1/statuses", json={
        "content": "Root", "visibility": "public"
    })
    root_id = root.json()["id"]

    reply1 = await authed_client.post("/api/v1/statuses", json={
        "content": "Reply 1", "visibility": "public",
        "in_reply_to_id": root_id,
    })
    reply1_id = reply1.json()["id"]

    reply2 = await authed_client.post("/api/v1/statuses", json={
        "content": "Reply 2", "visibility": "public",
        "in_reply_to_id": root_id,
    })
    reply2_id = reply2.json()["id"]

    # Nested reply to reply1
    nested = await authed_client.post("/api/v1/statuses", json={
        "content": "Nested reply", "visibility": "public",
        "in_reply_to_id": reply1_id,
    })
    nested_id = nested.json()["id"]

    ctx = await authed_client.get(f"/api/v1/statuses/{root_id}/context")
    assert ctx.status_code == 200
    data = ctx.json()

    assert data["ancestors"] == []
    desc_ids = [d["id"] for d in data["descendants"]]
    assert reply1_id in desc_ids
    assert reply2_id in desc_ids
    assert nested_id in desc_ids
    assert len(data["descendants"]) == 3


async def test_context_full_thread(authed_client, mock_valkey):
    """Context from the middle note returns both ancestors and descendants."""
    root = await authed_client.post("/api/v1/statuses", json={
        "content": "Root", "visibility": "public"
    })
    root_id = root.json()["id"]

    middle = await authed_client.post("/api/v1/statuses", json={
        "content": "Middle", "visibility": "public",
        "in_reply_to_id": root_id,
    })
    middle_id = middle.json()["id"]

    leaf = await authed_client.post("/api/v1/statuses", json={
        "content": "Leaf", "visibility": "public",
        "in_reply_to_id": middle_id,
    })
    leaf_id = leaf.json()["id"]

    ctx = await authed_client.get(f"/api/v1/statuses/{middle_id}/context")
    assert ctx.status_code == 200
    data = ctx.json()

    assert len(data["ancestors"]) == 1
    assert data["ancestors"][0]["id"] == root_id
    assert len(data["descendants"]) == 1
    assert data["descendants"][0]["id"] == leaf_id


async def test_context_not_found(app_client, mock_valkey):
    """Context for nonexistent note returns 404."""
    fake_id = str(uuid.uuid4())
    resp = await app_client.get(f"/api/v1/statuses/{fake_id}/context")
    assert resp.status_code == 404


async def test_context_visibility_filtering(
    authed_client, test_user, test_user_b, db, app_client, mock_valkey,
):
    """Followers-only replies are hidden from non-followers in context."""
    root = await authed_client.post("/api/v1/statuses", json={
        "content": "Public root", "visibility": "public"
    })
    root_id = root.json()["id"]

    # Reply with followers-only visibility
    await authed_client.post("/api/v1/statuses", json={
        "content": "Followers only reply", "visibility": "followers",
        "in_reply_to_id": root_id,
    })

    # Public reply
    pub_reply = await authed_client.post("/api/v1/statuses", json={
        "content": "Public reply", "visibility": "public",
        "in_reply_to_id": root_id,
    })
    pub_reply_id = pub_reply.json()["id"]

    # Switch to user B (not a follower)
    mock_valkey.get = AsyncMock(return_value=str(test_user_b.id))
    app_client.cookies.set("nekonoverse_session", "session-b")

    ctx = await app_client.get(f"/api/v1/statuses/{root_id}/context")
    assert ctx.status_code == 200
    data = ctx.json()

    # Only public reply should be visible
    desc_ids = [d["id"] for d in data["descendants"]]
    assert pub_reply_id in desc_ids
    assert len(data["descendants"]) == 1


async def test_reply_creation_sets_in_reply_to_id(authed_client, mock_valkey):
    """Creating a reply populates in_reply_to_id in the response."""
    parent = await authed_client.post("/api/v1/statuses", json={
        "content": "Parent", "visibility": "public"
    })
    parent_id = parent.json()["id"]

    reply = await authed_client.post("/api/v1/statuses", json={
        "content": "Reply", "visibility": "public",
        "in_reply_to_id": parent_id,
    })
    assert reply.status_code == 201
    data = reply.json()
    assert data["in_reply_to_id"] == parent_id
    assert data["in_reply_to_account_id"] is not None


async def test_reply_increments_replies_count(authed_client, mock_valkey):
    """Creating a reply increments the parent's replies_count."""
    parent = await authed_client.post("/api/v1/statuses", json={
        "content": "Parent", "visibility": "public"
    })
    parent_id = parent.json()["id"]
    assert parent.json()["replies_count"] == 0

    await authed_client.post("/api/v1/statuses", json={
        "content": "Reply", "visibility": "public",
        "in_reply_to_id": parent_id,
    })

    # Fetch parent again
    resp = await authed_client.get(f"/api/v1/statuses/{parent_id}")
    assert resp.json()["replies_count"] == 1
