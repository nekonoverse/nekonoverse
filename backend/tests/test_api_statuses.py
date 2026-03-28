import uuid


async def test_create_status(authed_client, mock_valkey):
    resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Hello from test!", "visibility": "public"
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["content"].startswith("<p>")
    assert data["visibility"] == "public"


async def test_create_status_unauthenticated(app_client, mock_valkey):
    resp = await app_client.post("/api/v1/statuses", json={
        "content": "Hello!", "visibility": "public"
    })
    assert resp.status_code == 401


async def test_get_status(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Fetch me", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    resp = await authed_client.get(f"/api/v1/statuses/{note_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == note_id


async def test_get_status_not_found(app_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await app_client.get(f"/api/v1/statuses/{fake_id}")
    assert resp.status_code == 404


async def test_react_to_status(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "React to me", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/react/😀")
    assert resp.status_code == 200


async def test_react_invalid_emoji(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "React test", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/react/notanemoji")
    assert resp.status_code == 422


async def test_unreact(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Unreact test", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    await authed_client.post(f"/api/v1/statuses/{note_id}/react/😀")
    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/unreact/😀")
    assert resp.status_code == 200


async def test_unreact_not_found(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "test", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/unreact/😀")
    assert resp.status_code == 422


async def test_create_status_sensitive(authed_client, mock_valkey):
    resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Sensitive", "visibility": "public", "sensitive": True, "spoiler_text": "CW"
    })
    assert resp.status_code == 201
    assert resp.json()["sensitive"] is True


async def test_react_unauthenticated(app_client, mock_valkey):
    resp = await app_client.post("/api/v1/statuses/fake-id/react/😀")
    assert resp.status_code == 401


async def test_react_to_nonexistent_note(authed_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await authed_client.post(f"/api/v1/statuses/{fake_id}/react/😀")
    assert resp.status_code == 404


async def test_unreact_nonexistent_note(authed_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await authed_client.post(f"/api/v1/statuses/{fake_id}/unreact/😀")
    assert resp.status_code == 404


async def test_unreact_unauthenticated(app_client, mock_valkey):
    resp = await app_client.post("/api/v1/statuses/fake-id/unreact/😀")
    assert resp.status_code == 401


async def test_create_status_with_reply(authed_client, mock_valkey):
    parent = await authed_client.post("/api/v1/statuses", json={
        "content": "Parent", "visibility": "public"
    })
    parent_id = parent.json()["id"]

    resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Reply", "visibility": "public", "in_reply_to_id": parent_id,
    })
    assert resp.status_code == 201


async def test_create_status_unlisted(authed_client, mock_valkey):
    resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Unlisted post", "visibility": "unlisted"
    })
    assert resp.status_code == 201
    assert resp.json()["visibility"] == "unlisted"


async def test_create_status_followers(authed_client, mock_valkey):
    resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Followers only", "visibility": "followers"
    })
    assert resp.status_code == 201
    assert resp.json()["visibility"] == "private"


async def test_get_status_includes_reactions(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "With reactions", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    await authed_client.post(f"/api/v1/statuses/{note_id}/react/👍")
    resp = await authed_client.get(f"/api/v1/statuses/{note_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["reactions"]) == 1
    assert data["reactions"][0]["emoji"] == "👍"
    assert data["reactions"][0]["me"] is True


async def test_react_duplicate(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Dup react test", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    await authed_client.post(f"/api/v1/statuses/{note_id}/react/😀")
    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/react/😀")
    assert resp.status_code == 422


# --- Reblog/Unreblog tests ---


async def test_reblog(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Reblog me", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/reblog")
    assert resp.status_code == 200
    data = resp.json()
    assert data["reblog"] is not None
    assert data["reblog"]["id"] == note_id


async def test_reblog_duplicate(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Dup reblog", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    await authed_client.post(f"/api/v1/statuses/{note_id}/reblog")
    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/reblog")
    assert resp.status_code == 422


async def test_reblog_not_found(authed_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await authed_client.post(f"/api/v1/statuses/{fake_id}/reblog")
    assert resp.status_code == 404


async def test_reblog_unauthenticated(app_client, mock_valkey):
    resp = await app_client.post("/api/v1/statuses/fake-id/reblog")
    assert resp.status_code == 401


async def test_unreblog(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Unreblog me", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    await authed_client.post(f"/api/v1/statuses/{note_id}/reblog")
    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/unreblog")
    assert resp.status_code == 200


async def test_unreblog_not_reblogged(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Not reblogged", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/unreblog")
    assert resp.status_code == 422


async def test_reblog_direct_rejected(authed_client, mock_valkey):
    """directノートのブーストは常に拒否。"""
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Direct message", "visibility": "direct"
    })
    note_id = create_resp.json()["id"]
    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/reblog")
    assert resp.status_code == 422


async def test_reblog_unlisted_allowed(authed_client, mock_valkey):
    """unlistedノートのブーストは成功。"""
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Unlisted post", "visibility": "unlisted"
    })
    note_id = create_resp.json()["id"]
    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/reblog")
    assert resp.status_code == 200
    assert resp.json()["reblog"] is not None


async def test_reblog_own_followers_note(authed_client, mock_valkey):
    """自分のfollowersノートはブースト可能。"""
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Followers only post", "visibility": "followers"
    })
    note_id = create_resp.json()["id"]
    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/reblog")
    assert resp.status_code == 200
    data = resp.json()
    # Mastodon API互換: followers → private として返される
    assert data["visibility"] == "private"


async def test_reblog_with_visibility_unlisted(authed_client, mock_valkey):
    """publicノートをunlistedでブースト可能。"""
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Public post", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    resp = await authed_client.post(
        f"/api/v1/statuses/{note_id}/reblog",
        json={"visibility": "unlisted"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["visibility"] == "unlisted"


async def test_reblog_with_visibility_followers(authed_client, mock_valkey):
    """自分のpublicノートをfollowersでブースト可能。"""
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Public post", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    resp = await authed_client.post(
        f"/api/v1/statuses/{note_id}/reblog",
        json={"visibility": "followers"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Mastodon API互換: followers → private として返される
    assert data["visibility"] == "private"


async def test_reblog_with_visibility_direct_rejected(authed_client, mock_valkey):
    """directでのブーストは拒否。"""
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Public post", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    resp = await authed_client.post(
        f"/api/v1/statuses/{note_id}/reblog",
        json={"visibility": "direct"},
    )
    assert resp.status_code == 422


async def test_reblog_visibility_wider_than_original(authed_client, mock_valkey):
    """元ノートより広い公開範囲でのブーストは拒否。"""
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Unlisted post", "visibility": "unlisted"
    })
    note_id = create_resp.json()["id"]
    resp = await authed_client.post(
        f"/api/v1/statuses/{note_id}/reblog",
        json={"visibility": "public"},
    )
    assert resp.status_code == 422


# --- Delete tests ---


async def test_delete_status(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Delete me", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    resp = await authed_client.delete(f"/api/v1/statuses/{note_id}")
    assert resp.status_code == 204

    # Verify it's gone
    get_resp = await authed_client.get(f"/api/v1/statuses/{note_id}")
    assert get_resp.status_code == 404


async def test_delete_not_found(authed_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await authed_client.delete(f"/api/v1/statuses/{fake_id}")
    assert resp.status_code == 404


async def test_delete_unauthenticated(app_client, mock_valkey):
    resp = await app_client.delete("/api/v1/statuses/fake-id")
    assert resp.status_code == 401


# --- Visibility access control tests ---


async def test_get_status_followers_visible_to_author(authed_client, mock_valkey):
    """Author can always see their own followers-only note."""
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Followers only", "visibility": "followers"
    })
    note_id = create_resp.json()["id"]
    resp = await authed_client.get(f"/api/v1/statuses/{note_id}")
    assert resp.status_code == 200


async def test_get_status_followers_hidden_from_stranger(
    authed_client, test_user, test_user_b, db, app_client, mock_valkey,
):
    """A non-follower should get 404 for a followers-only note."""
    # User A creates a followers-only note
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Secret followers post", "visibility": "followers"
    })
    note_id = create_resp.json()["id"]

    # Switch to user B (not a follower of user A)
    from unittest.mock import AsyncMock
    mock_valkey.get = AsyncMock(return_value=str(test_user_b.id))
    app_client.cookies.set("nekonoverse_session", "session-b")

    resp = await app_client.get(f"/api/v1/statuses/{note_id}")
    assert resp.status_code == 404


async def test_get_status_followers_visible_to_follower(
    authed_client, test_user, test_user_b, db, app_client, mock_valkey,
):
    """A follower should be able to see a followers-only note."""
    # User A creates a followers-only note
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "For my followers", "visibility": "followers"
    })
    note_id = create_resp.json()["id"]

    # Make user B follow user A
    from app.models.follow import Follow
    follow = Follow(
        follower_id=test_user_b.actor_id,
        following_id=test_user.actor_id,
        accepted=True,
    )
    db.add(follow)
    await db.flush()

    # Switch to user B
    from unittest.mock import AsyncMock
    mock_valkey.get = AsyncMock(return_value=str(test_user_b.id))
    app_client.cookies.set("nekonoverse_session", "session-b")

    resp = await app_client.get(f"/api/v1/statuses/{note_id}")
    assert resp.status_code == 200


async def test_get_status_direct_visible_to_author(authed_client, mock_valkey):
    """Author can always see their own direct message."""
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "DM to nobody", "visibility": "direct"
    })
    note_id = create_resp.json()["id"]
    resp = await authed_client.get(f"/api/v1/statuses/{note_id}")
    assert resp.status_code == 200


async def test_get_status_direct_hidden_from_stranger(
    authed_client, test_user_b, app_client, mock_valkey,
):
    """A non-mentioned user should get 404 for a direct message."""
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Secret DM", "visibility": "direct"
    })
    note_id = create_resp.json()["id"]

    # Switch to user B (not mentioned)
    from unittest.mock import AsyncMock
    mock_valkey.get = AsyncMock(return_value=str(test_user_b.id))
    app_client.cookies.set("nekonoverse_session", "session-b")

    resp = await app_client.get(f"/api/v1/statuses/{note_id}")
    assert resp.status_code == 404


async def test_get_status_followers_hidden_unauthenticated(
    authed_client, app_client, mock_valkey,
):
    """Unauthenticated users cannot see followers-only notes."""
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Followers only anon", "visibility": "followers"
    })
    note_id = create_resp.json()["id"]

    # Reset to unauthenticated
    from unittest.mock import AsyncMock
    mock_valkey.get = AsyncMock(return_value=None)
    app_client.cookies.clear()

    resp = await app_client.get(f"/api/v1/statuses/{note_id}")
    assert resp.status_code == 404


# --- Edit tests ---


async def test_edit_status(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Original content", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    resp = await authed_client.put(f"/api/v1/statuses/{note_id}", json={
        "content": "Edited content"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "Edited content" in data["content"]
    assert data["edited_at"] is not None


async def test_edit_status_not_found(authed_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await authed_client.put(f"/api/v1/statuses/{fake_id}", json={
        "content": "Edited"
    })
    assert resp.status_code == 404


async def test_edit_status_not_owner(authed_client, test_user_b, db, app_client, mock_valkey):
    """Cannot edit another user's note."""
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Not yours", "visibility": "public"
    })
    note_id = create_resp.json()["id"]

    from unittest.mock import AsyncMock
    mock_valkey.get = AsyncMock(return_value=str(test_user_b.id))
    app_client.cookies.set("nekonoverse_session", "session-b")

    resp = await app_client.put(f"/api/v1/statuses/{note_id}", json={
        "content": "Hijacked"
    })
    assert resp.status_code == 403


async def test_edit_status_unauthenticated(app_client, mock_valkey):
    resp = await app_client.put(f"/api/v1/statuses/{uuid.uuid4()}", json={
        "content": "Edited"
    })
    assert resp.status_code == 401


# --- History tests ---


async def test_get_status_history(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Version 1", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    await authed_client.put(f"/api/v1/statuses/{note_id}", json={
        "content": "Version 2"
    })

    resp = await authed_client.get(f"/api/v1/statuses/{note_id}/history")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert "Version 1" in data[0]["content"]
    assert "Version 2" in data[1]["content"]


async def test_get_status_history_not_found(app_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await app_client.get(f"/api/v1/statuses/{fake_id}/history")
    assert resp.status_code == 404


# --- Context tests ---


async def test_get_status_context(authed_client, mock_valkey):
    parent = await authed_client.post("/api/v1/statuses", json={
        "content": "Parent", "visibility": "public"
    })
    parent_id = parent.json()["id"]

    reply = await authed_client.post("/api/v1/statuses", json={
        "content": "Reply", "visibility": "public", "in_reply_to_id": parent_id
    })
    reply_id = reply.json()["id"]

    resp = await authed_client.get(f"/api/v1/statuses/{reply_id}/context")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["ancestors"]) >= 1
    assert data["ancestors"][0]["id"] == parent_id

    resp2 = await authed_client.get(f"/api/v1/statuses/{parent_id}/context")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["descendants"]) >= 1
    assert data2["descendants"][0]["id"] == reply_id


async def test_get_status_context_empty(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "No context", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    resp = await authed_client.get(f"/api/v1/statuses/{note_id}/context")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ancestors"] == []
    assert data["descendants"] == []


async def test_get_status_context_not_found(app_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await app_client.get(f"/api/v1/statuses/{fake_id}/context")
    assert resp.status_code == 404


# --- Reacted by tests ---


async def test_reacted_by(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Reacted by test", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    await authed_client.post(f"/api/v1/statuses/{note_id}/react/👍")

    resp = await authed_client.get(f"/api/v1/statuses/{note_id}/reacted_by")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["emoji"] == "👍"
    actor = data[0]["actor"]
    assert actor["username"] == "testuser"
    # Mastodon-compatible fields must be populated (#856)
    assert actor["acct"] == "testuser"
    assert actor["url"] != ""
    assert actor["uri"] != ""
    assert actor["avatar"] != ""


async def test_reacted_by_filter_emoji(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Multi react", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    await authed_client.post(f"/api/v1/statuses/{note_id}/react/👍")

    resp = await authed_client.get(
        f"/api/v1/statuses/{note_id}/reacted_by", params={"emoji": "👍"},
    )
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    resp2 = await authed_client.get(
        f"/api/v1/statuses/{note_id}/reacted_by", params={"emoji": "😀"},
    )
    assert resp2.status_code == 200
    assert len(resp2.json()) == 0


async def test_reacted_by_not_found(app_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await app_client.get(f"/api/v1/statuses/{fake_id}/reacted_by")
    assert resp.status_code == 404


# --- Bookmark tests ---


async def test_bookmark_status(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Bookmark me", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/bookmark")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_bookmark_not_found(authed_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await authed_client.post(f"/api/v1/statuses/{fake_id}/bookmark")
    assert resp.status_code == 404


async def test_bookmark_duplicate(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Dup bookmark", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    await authed_client.post(f"/api/v1/statuses/{note_id}/bookmark")
    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/bookmark")
    assert resp.status_code == 422


async def test_unbookmark_status(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Unbookmark me", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    await authed_client.post(f"/api/v1/statuses/{note_id}/bookmark")
    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/unbookmark")
    assert resp.status_code == 200


async def test_unbookmark_not_found(authed_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await authed_client.post(f"/api/v1/statuses/{fake_id}/unbookmark")
    assert resp.status_code == 404


async def test_bookmark_unauthenticated(app_client, mock_valkey):
    resp = await app_client.post(f"/api/v1/statuses/{uuid.uuid4()}/bookmark")
    assert resp.status_code == 401


# --- Pin/Unpin tests ---


async def test_reply_visibility_clamped_to_parent(authed_client, mock_valkey):
    """Replying to a restricted note with wider visibility is clamped to parent."""
    parent = await authed_client.post("/api/v1/statuses", json={
        "content": "Followers only", "visibility": "followers"
    })
    parent_id = parent.json()["id"]

    resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Public reply", "visibility": "public",
        "in_reply_to_id": parent_id,
    })
    assert resp.status_code == 201
    # Public reply to followers-only parent is clamped to private (followers)
    assert resp.json()["visibility"] == "private"


async def test_reply_visibility_enforcement(authed_client, mock_valkey):
    """Reply visibility is clamped: cannot be wider than parent."""
    # "followers" maps to "private" in the API response
    vis_response_map = {
        "public": "public",
        "unlisted": "unlisted",
        "followers": "private",
        "direct": "direct",
    }
    # (parent_vis, requested_reply_vis, expected_reply_vis)
    combos = [
        # Narrower or equal → allowed as-is
        ("public", "public", "public"),
        ("public", "unlisted", "unlisted"),
        ("public", "followers", "followers"),
        ("public", "direct", "direct"),
        ("unlisted", "unlisted", "unlisted"),
        ("followers", "followers", "followers"),
        ("direct", "direct", "direct"),
        # Wider → clamped to parent
        ("unlisted", "public", "unlisted"),
        ("followers", "public", "followers"),
        ("followers", "unlisted", "followers"),
        ("direct", "public", "direct"),
        ("direct", "unlisted", "direct"),
        ("direct", "followers", "direct"),
    ]
    for parent_vis, reply_vis, expected_vis in combos:
        parent = await authed_client.post("/api/v1/statuses", json={
            "content": f"Parent {parent_vis}", "visibility": parent_vis,
        })
        parent_id = parent.json()["id"]

        resp = await authed_client.post("/api/v1/statuses", json={
            "content": f"Reply {reply_vis}",
            "visibility": reply_vis,
            "in_reply_to_id": parent_id,
        })
        assert resp.status_code == 201, (
            f"Failed: parent={parent_vis}, reply={reply_vis}"
        )
        assert resp.json()["visibility"] == vis_response_map[expected_vis], (
            f"Visibility mismatch: parent={parent_vis}, reply={reply_vis}, "
            f"expected={vis_response_map[expected_vis]}, got={resp.json()['visibility']}"
        )


async def test_pin_status(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Pin me", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/pin")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_pin_duplicate(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Dup pin", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    await authed_client.post(f"/api/v1/statuses/{note_id}/pin")
    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/pin")
    assert resp.status_code == 422


async def test_unpin_status(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Unpin me", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    await authed_client.post(f"/api/v1/statuses/{note_id}/pin")
    resp = await authed_client.post(f"/api/v1/statuses/{note_id}/unpin")
    assert resp.status_code == 200


async def test_unpin_not_found(authed_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await authed_client.post(f"/api/v1/statuses/{fake_id}/unpin")
    assert resp.status_code == 404


async def test_pin_unauthenticated(app_client, mock_valkey):
    resp = await app_client.post(f"/api/v1/statuses/{uuid.uuid4()}/pin")
    assert resp.status_code == 401


# --- IDOR tests ---


async def test_delete_status_not_owner(authed_client, test_user_b, db, app_client, mock_valkey):
    """Cannot delete another user's note."""
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Not yours to delete", "visibility": "public"
    })
    note_id = create_resp.json()["id"]

    from unittest.mock import AsyncMock
    mock_valkey.get = AsyncMock(return_value=str(test_user_b.id))
    app_client.cookies.set("nekonoverse_session", "session-b")

    resp = await app_client.delete(f"/api/v1/statuses/{note_id}")
    assert resp.status_code == 403


async def test_pin_status_not_owner(authed_client, test_user_b, db, app_client, mock_valkey):
    """Cannot pin another user's note."""
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Not yours to pin", "visibility": "public"
    })
    note_id = create_resp.json()["id"]

    from unittest.mock import AsyncMock
    mock_valkey.get = AsyncMock(return_value=str(test_user_b.id))
    app_client.cookies.set("nekonoverse_session", "session-b")

    resp = await app_client.post(f"/api/v1/statuses/{note_id}/pin")
    assert resp.status_code == 422
    assert "own" in resp.json()["detail"].lower()


async def test_unpin_status_not_owner(authed_client, test_user_b, db, app_client, mock_valkey):
    """Cannot unpin another user's note (returns 422 since it's not in their pins)."""
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "Not yours to unpin", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    await authed_client.post(f"/api/v1/statuses/{note_id}/pin")

    from unittest.mock import AsyncMock
    mock_valkey.get = AsyncMock(return_value=str(test_user_b.id))
    app_client.cookies.set("nekonoverse_session", "session-b")

    resp = await app_client.post(f"/api/v1/statuses/{note_id}/unpin")
    assert resp.status_code == 422
