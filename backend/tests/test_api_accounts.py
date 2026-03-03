import uuid


async def test_get_account(app_client, test_user, mock_valkey):
    resp = await app_client.get(f"/api/v1/accounts/{test_user.actor_id}")
    assert resp.status_code == 200
    assert resp.json()["username"] == "testuser"


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
    assert resp.json()["username"] == "testuser"


async def test_lookup_account_not_found(app_client, mock_valkey):
    resp = await app_client.get("/api/v1/accounts/lookup", params={"acct": "nobody"})
    assert resp.status_code == 404
