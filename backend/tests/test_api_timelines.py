async def test_public_timeline(authed_client, mock_valkey):
    await authed_client.post("/api/v1/statuses", json={"content": "tl1", "visibility": "public"})
    await authed_client.post("/api/v1/statuses", json={"content": "tl2", "visibility": "public"})
    resp = await authed_client.get("/api/v1/timelines/public")
    assert resp.status_code == 200
    assert len(resp.json()) >= 2


async def test_public_timeline_local_filter(authed_client, mock_valkey):
    await authed_client.post("/api/v1/statuses", json={"content": "local", "visibility": "public"})
    resp = await authed_client.get("/api/v1/timelines/public", params={"local": "true"})
    assert resp.status_code == 200


async def test_public_timeline_limit(app_client, mock_valkey):
    resp = await app_client.get("/api/v1/timelines/public", params={"limit": "1"})
    assert resp.status_code == 200
    assert len(resp.json()) <= 1


async def test_home_timeline_unauthenticated(app_client, mock_valkey):
    resp = await app_client.get("/api/v1/timelines/home")
    assert resp.status_code == 401


async def test_home_timeline(authed_client, mock_valkey):
    resp = await authed_client.get("/api/v1/timelines/home")
    assert resp.status_code == 200


async def test_public_timeline_no_auth_ok(app_client, mock_valkey):
    resp = await app_client.get("/api/v1/timelines/public")
    assert resp.status_code == 200
