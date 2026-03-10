import uuid

from tests.conftest import make_note, make_remote_actor


async def test_get_account(app_client, test_user, mock_valkey):
    resp = await app_client.get(f"/api/v1/accounts/{test_user.actor_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "testuser"
    assert "created_at" in data


async def test_get_account_not_found(app_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await app_client.get(f"/api/v1/accounts/{fake_id}")
    assert resp.status_code == 404


async def test_follow(authed_client, test_user_b, mock_valkey):
    resp = await authed_client.post(f"/api/v1/accounts/{test_user_b.actor_id}/follow")
    assert resp.status_code == 200


async def test_follow_self(authed_client, test_user, mock_valkey):
    resp = await authed_client.post(f"/api/v1/accounts/{test_user.actor_id}/follow")
    assert resp.status_code == 422


async def test_unfollow(authed_client, test_user_b, mock_valkey):
    await authed_client.post(f"/api/v1/accounts/{test_user_b.actor_id}/follow")
    resp = await authed_client.post(f"/api/v1/accounts/{test_user_b.actor_id}/unfollow")
    assert resp.status_code == 200


async def test_follow_unauthenticated(app_client, test_user, mock_valkey):
    resp = await app_client.post(f"/api/v1/accounts/{test_user.actor_id}/follow")
    assert resp.status_code == 401


async def test_lookup_account(app_client, test_user, mock_valkey):
    resp = await app_client.get("/api/v1/accounts/lookup", params={"acct": "testuser"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "testuser"
    assert data["acct"] == "testuser"
    assert "created_at" in data


async def test_lookup_account_not_found(app_client, mock_valkey):
    resp = await app_client.get("/api/v1/accounts/lookup", params={"acct": "nobody"})
    assert resp.status_code == 404


async def test_get_account_statuses(app_client, db, test_user, mock_valkey):
    from sqlalchemy import select

    from app.models.actor import Actor

    result = await db.execute(select(Actor).where(Actor.id == test_user.actor_id))
    actor = result.scalar_one()
    await make_note(db, actor, content="Post 1")
    await make_note(db, actor, content="Post 2")
    await db.commit()

    resp = await app_client.get(f"/api/v1/accounts/{test_user.actor_id}/statuses")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["actor"]["username"] == "testuser"


async def test_get_account_statuses_empty(app_client, test_user, mock_valkey):
    resp = await app_client.get(f"/api/v1/accounts/{test_user.actor_id}/statuses")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_account_statuses_not_found(app_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await app_client.get(f"/api/v1/accounts/{fake_id}/statuses")
    assert resp.status_code == 404


async def test_get_account_statuses_excludes_private(app_client, db, test_user, mock_valkey):
    from sqlalchemy import select

    from app.models.actor import Actor

    result = await db.execute(select(Actor).where(Actor.id == test_user.actor_id))
    actor = result.scalar_one()
    await make_note(db, actor, content="Public post", visibility="public")
    await make_note(db, actor, content="Followers only", visibility="followers")
    await make_note(db, actor, content="Direct msg", visibility="direct")
    await db.commit()

    resp = await app_client.get(f"/api/v1/accounts/{test_user.actor_id}/statuses")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert "Public post" in data[0]["content"]


async def test_get_account_statuses_includes_unlisted(app_client, db, test_user, mock_valkey):
    from sqlalchemy import select

    from app.models.actor import Actor

    result = await db.execute(select(Actor).where(Actor.id == test_user.actor_id))
    actor = result.scalar_one()
    await make_note(db, actor, content="Public post", visibility="public")
    await make_note(db, actor, content="Unlisted post", visibility="unlisted")
    await db.commit()

    resp = await app_client.get(f"/api/v1/accounts/{test_user.actor_id}/statuses")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


# --- Search endpoint tests ---


async def test_search_accounts_local(app_client, test_user, mock_valkey):
    resp = await app_client.get("/api/v1/accounts/search", params={"q": "testuser"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["username"] == "testuser"


async def test_search_accounts_not_found(app_client, mock_valkey):
    resp = await app_client.get("/api/v1/accounts/search", params={"q": "nobody"})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_search_accounts_with_at_prefix(app_client, test_user, mock_valkey):
    resp = await app_client.get("/api/v1/accounts/search", params={"q": "@testuser"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["username"] == "testuser"


async def test_search_accounts_remote_no_resolve(app_client, db, mock_valkey):
    await make_remote_actor(db, username="alice", domain="remote.example")
    await db.commit()

    resp = await app_client.get(
        "/api/v1/accounts/search",
        params={"q": "alice@remote.example"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["username"] == "alice"
    assert data[0]["acct"] == "alice@remote.example"


async def test_search_accounts_remote_not_found_no_resolve(app_client, mock_valkey):
    resp = await app_client.get(
        "/api/v1/accounts/search",
        params={"q": "unknown@nowhere.example", "resolve": "false"},
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_unfollow_not_found(authed_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await authed_client.post(f"/api/v1/accounts/{fake_id}/unfollow")
    assert resp.status_code == 404


async def test_follow_not_found(authed_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await authed_client.post(f"/api/v1/accounts/{fake_id}/follow")
    assert resp.status_code == 404


async def test_get_account_avatar_fallback(app_client, test_user, mock_valkey):
    resp = await app_client.get(f"/api/v1/accounts/{test_user.actor_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["avatar"] == "/default-avatar.svg"


# --- Block/Unblock tests ---


async def test_block_account(authed_client, test_user_b, mock_valkey):
    resp = await authed_client.post(f"/api/v1/accounts/{test_user_b.actor_id}/block")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_block_self(authed_client, test_user, mock_valkey):
    resp = await authed_client.post(f"/api/v1/accounts/{test_user.actor_id}/block")
    assert resp.status_code == 422


async def test_block_not_found(authed_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await authed_client.post(f"/api/v1/accounts/{fake_id}/block")
    assert resp.status_code == 404


async def test_unblock_account(authed_client, test_user_b, mock_valkey):
    await authed_client.post(f"/api/v1/accounts/{test_user_b.actor_id}/block")
    resp = await authed_client.post(f"/api/v1/accounts/{test_user_b.actor_id}/unblock")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_unblock_not_found(authed_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await authed_client.post(f"/api/v1/accounts/{fake_id}/unblock")
    assert resp.status_code == 404


# --- Mute/Unmute tests ---


async def test_mute_account(authed_client, test_user_b, mock_valkey):
    resp = await authed_client.post(f"/api/v1/accounts/{test_user_b.actor_id}/mute")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_mute_self(authed_client, test_user, mock_valkey):
    resp = await authed_client.post(f"/api/v1/accounts/{test_user.actor_id}/mute")
    assert resp.status_code == 422


async def test_mute_not_found(authed_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await authed_client.post(f"/api/v1/accounts/{fake_id}/mute")
    assert resp.status_code == 404


async def test_unmute_account(authed_client, test_user_b, mock_valkey):
    await authed_client.post(f"/api/v1/accounts/{test_user_b.actor_id}/mute")
    resp = await authed_client.post(f"/api/v1/accounts/{test_user_b.actor_id}/unmute")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_unmute_not_found(authed_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await authed_client.post(f"/api/v1/accounts/{fake_id}/unmute")
    assert resp.status_code == 404


# --- Followers/Following lists ---


async def test_list_followers(app_client, test_user, test_user_b, db, mock_valkey):
    from app.models.follow import Follow
    follow = Follow(
        follower_id=test_user_b.actor_id,
        following_id=test_user.actor_id,
        accepted=True,
    )
    db.add(follow)
    await db.flush()

    resp = await app_client.get(f"/api/v1/accounts/{test_user.actor_id}/followers")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["username"] == "testuser_b"


async def test_list_followers_empty(app_client, test_user, mock_valkey):
    resp = await app_client.get(f"/api/v1/accounts/{test_user.actor_id}/followers")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_followers_not_found(app_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await app_client.get(f"/api/v1/accounts/{fake_id}/followers")
    assert resp.status_code == 404


async def test_list_following(app_client, test_user, test_user_b, db, mock_valkey):
    from app.models.follow import Follow
    follow = Follow(
        follower_id=test_user.actor_id,
        following_id=test_user_b.actor_id,
        accepted=True,
    )
    db.add(follow)
    await db.flush()

    resp = await app_client.get(f"/api/v1/accounts/{test_user.actor_id}/following")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["username"] == "testuser_b"


async def test_list_following_empty(app_client, test_user, mock_valkey):
    resp = await app_client.get(f"/api/v1/accounts/{test_user.actor_id}/following")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_following_not_found(app_client, mock_valkey):
    fake_id = str(uuid.uuid4())
    resp = await app_client.get(f"/api/v1/accounts/{fake_id}/following")
    assert resp.status_code == 404


# --- Relationship ---


async def test_get_relationship(authed_client, test_user, test_user_b, mock_valkey):
    resp = await authed_client.get(f"/api/v1/accounts/{test_user_b.actor_id}/relationship")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(test_user_b.actor_id)
    assert data["following"] is False
    assert data["followed_by"] is False
    assert data["blocking"] is False
    assert data["muting"] is False
    assert data["requested"] is False


async def test_get_relationship_following(authed_client, test_user, test_user_b, db, mock_valkey):
    from app.models.follow import Follow
    follow = Follow(
        follower_id=test_user.actor_id,
        following_id=test_user_b.actor_id,
        accepted=True,
    )
    db.add(follow)
    await db.flush()

    resp = await authed_client.get(f"/api/v1/accounts/{test_user_b.actor_id}/relationship")
    assert resp.status_code == 200
    data = resp.json()
    assert data["following"] is True
    assert data["requested"] is False


async def test_get_relationship_pending(authed_client, test_user, test_user_b, db, mock_valkey):
    from app.models.follow import Follow
    follow = Follow(
        follower_id=test_user.actor_id,
        following_id=test_user_b.actor_id,
        accepted=False,
    )
    db.add(follow)
    await db.flush()

    resp = await authed_client.get(f"/api/v1/accounts/{test_user_b.actor_id}/relationship")
    assert resp.status_code == 200
    data = resp.json()
    assert data["following"] is False
    assert data["requested"] is True


async def test_get_relationship_unauthenticated(app_client, test_user, mock_valkey):
    resp = await app_client.get(f"/api/v1/accounts/{test_user.actor_id}/relationship")
    assert resp.status_code == 401


# --- Following IDs ---


async def test_following_ids(authed_client, test_user, test_user_b, db, mock_valkey):
    from app.models.follow import Follow
    follow = Follow(
        follower_id=test_user.actor_id,
        following_id=test_user_b.actor_id,
        accepted=True,
    )
    db.add(follow)
    await db.flush()

    resp = await authed_client.get("/api/v1/following_ids")
    assert resp.status_code == 200
    data = resp.json()
    assert str(test_user_b.actor_id) in data


async def test_following_ids_empty(authed_client, test_user, mock_valkey):
    resp = await authed_client.get("/api/v1/following_ids")
    assert resp.status_code == 200
    assert resp.json() == []


# --- Blocks/Mutes lists ---


async def test_blocks_list(authed_client, test_user, test_user_b, mock_valkey):
    await authed_client.post(f"/api/v1/accounts/{test_user_b.actor_id}/block")
    resp = await authed_client.get("/api/v1/blocks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["username"] == "testuser_b"


async def test_blocks_list_empty(authed_client, test_user, mock_valkey):
    resp = await authed_client.get("/api/v1/blocks")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_mutes_list(authed_client, test_user, test_user_b, mock_valkey):
    await authed_client.post(f"/api/v1/accounts/{test_user_b.actor_id}/mute")
    resp = await authed_client.get("/api/v1/mutes")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["username"] == "testuser_b"


async def test_mutes_list_empty(authed_client, test_user, mock_valkey):
    resp = await authed_client.get("/api/v1/mutes")
    assert resp.status_code == 200
    assert resp.json() == []
