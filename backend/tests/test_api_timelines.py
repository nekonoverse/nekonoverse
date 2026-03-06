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


async def test_public_timeline_pagination(authed_client, mock_valkey):
    # Create 3 notes
    ids = []
    for i in range(3):
        resp = await authed_client.post("/api/v1/statuses", json={
            "content": f"page{i}", "visibility": "public"
        })
        ids.append(resp.json()["id"])

    # Get first page with limit 2
    resp = await authed_client.get("/api/v1/timelines/public", params={"limit": "2"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) <= 2

    # Use max_id from last item to get next page
    if len(data) == 2:
        last_id = data[-1]["id"]
        resp2 = await authed_client.get(
            "/api/v1/timelines/public",
            params={"limit": "2", "max_id": last_id},
        )
        assert resp2.status_code == 200


async def test_public_timeline_excludes_private(authed_client, mock_valkey):
    await authed_client.post("/api/v1/statuses", json={
        "content": "Public visible", "visibility": "public"
    })
    await authed_client.post("/api/v1/statuses", json={
        "content": "Private hidden", "visibility": "followers"
    })
    resp = await authed_client.get("/api/v1/timelines/public")
    assert resp.status_code == 200
    contents = [n["content"] for n in resp.json()]
    assert any("Public visible" in c for c in contents)
    assert not any("Private hidden" in c for c in contents)


async def test_home_timeline_returns_notes(authed_client, mock_valkey):
    await authed_client.post("/api/v1/statuses", json={
        "content": "Home note", "visibility": "public"
    })
    resp = await authed_client.get("/api/v1/timelines/home")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


async def test_public_timeline_includes_reactions(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "TL reactions", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    await authed_client.post(f"/api/v1/statuses/{note_id}/react/❤️")

    resp = await authed_client.get("/api/v1/timelines/public")
    assert resp.status_code == 200
    for note in resp.json():
        if note["id"] == note_id:
            assert len(note["reactions"]) >= 1
            break
