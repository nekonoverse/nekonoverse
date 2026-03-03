async def test_health(app_client, mock_valkey):
    resp = await app_client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_instance_info(app_client, mock_valkey):
    resp = await app_client.get("/api/v1/instance")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Nekonoverse"
    assert "registrations" in data


async def test_actor_json(app_client, test_user, mock_valkey):
    resp = await app_client.get("/users/testuser", headers={"Accept": "application/activity+json"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "Person"
    assert data["preferredUsername"] == "testuser"
    assert "publicKey" in data


async def test_actor_not_found(app_client, mock_valkey):
    resp = await app_client.get("/users/nobody", headers={"Accept": "application/activity+json"})
    assert resp.status_code == 404


async def test_outbox(authed_client, test_user, mock_valkey):
    await authed_client.post("/api/v1/statuses", json={"content": "outbox test", "visibility": "public"})
    resp = await authed_client.get("/users/testuser/outbox", headers={"Accept": "application/activity+json"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "OrderedCollection"


async def test_followers_collection(app_client, test_user, mock_valkey):
    resp = await app_client.get("/users/testuser/followers", headers={"Accept": "application/activity+json"})
    assert resp.status_code == 200
    assert resp.json()["type"] == "OrderedCollection"


async def test_following_collection(app_client, test_user, mock_valkey):
    resp = await app_client.get("/users/testuser/following", headers={"Accept": "application/activity+json"})
    assert resp.status_code == 200
    assert resp.json()["type"] == "OrderedCollection"


async def test_webfinger(app_client, test_user, mock_valkey):
    resp = await app_client.get("/.well-known/webfinger", params={"resource": "acct:testuser@localhost"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["subject"] == "acct:testuser@localhost"


async def test_webfinger_not_found(app_client, mock_valkey):
    resp = await app_client.get("/.well-known/webfinger", params={"resource": "acct:nobody@localhost"})
    assert resp.status_code == 404


async def test_nodeinfo_discovery(app_client, mock_valkey):
    resp = await app_client.get("/.well-known/nodeinfo")
    assert resp.status_code == 200
    data = resp.json()
    assert "links" in data


async def test_nodeinfo(app_client, mock_valkey):
    resp = await app_client.get("/nodeinfo/2.0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["software"]["name"] == "nekonoverse"


async def test_note_ap_endpoint(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={"content": "AP note", "visibility": "public"})
    note_id = create_resp.json()["id"]
    resp = await authed_client.get(f"/notes/{note_id}", headers={"Accept": "application/activity+json"})
    assert resp.status_code == 200
    assert resp.json()["type"] == "Note"
