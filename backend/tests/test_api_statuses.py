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
