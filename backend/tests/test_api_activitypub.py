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
    await authed_client.post(
        "/api/v1/statuses", json={"content": "outbox test", "visibility": "public"},
    )
    resp = await authed_client.get(
        "/users/testuser/outbox", headers={"Accept": "application/activity+json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "OrderedCollection"


async def test_followers_collection(app_client, test_user, mock_valkey):
    resp = await app_client.get(
        "/users/testuser/followers", headers={"Accept": "application/activity+json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "OrderedCollection"
    # first must be a page URL, not the collection itself (Pleroma compat)
    assert data["first"] != data["id"]
    assert "?page=true" in data["first"]


async def test_following_collection(app_client, test_user, mock_valkey):
    resp = await app_client.get(
        "/users/testuser/following", headers={"Accept": "application/activity+json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "OrderedCollection"
    assert data["first"] != data["id"]
    assert "?page=true" in data["first"]


async def test_followers_collection_page(app_client, test_user, mock_valkey):
    resp = await app_client.get(
        "/users/testuser/followers?page=true",
        headers={"Accept": "application/activity+json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "OrderedCollectionPage"
    assert "partOf" in data
    assert isinstance(data["orderedItems"], list)


async def test_following_collection_page(app_client, test_user, mock_valkey):
    resp = await app_client.get(
        "/users/testuser/following?page=true",
        headers={"Accept": "application/activity+json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "OrderedCollectionPage"
    assert "partOf" in data
    assert isinstance(data["orderedItems"], list)


async def test_webfinger(app_client, test_user, mock_valkey):
    resp = await app_client.get(
        "/.well-known/webfinger", params={"resource": "acct:testuser@localhost"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["subject"] == "acct:testuser@localhost"


async def test_webfinger_not_found(app_client, mock_valkey):
    resp = await app_client.get(
        "/.well-known/webfinger", params={"resource": "acct:nobody@localhost"},
    )
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
    create_resp = await authed_client.post(
        "/api/v1/statuses", json={"content": "AP note", "visibility": "public"},
    )
    note_id = create_resp.json()["id"]
    resp = await authed_client.get(
        f"/notes/{note_id}", headers={"Accept": "application/activity+json"},
    )
    assert resp.status_code == 200
    assert resp.json()["type"] == "Note"


async def test_actor_browser_redirect(app_client, test_user, mock_valkey):
    """Non-AP request to actor endpoint should redirect to profile page."""
    resp = await app_client.get(
        "/users/testuser", headers={"Accept": "text/html"}, follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/@testuser"


async def test_outbox_page(authed_client, test_user, mock_valkey):
    """Outbox with page=true should return OrderedCollectionPage with items."""
    await authed_client.post(
        "/api/v1/statuses", json={"content": "outbox page test", "visibility": "public"},
    )
    resp = await authed_client.get(
        "/users/testuser/outbox?page=true",
        headers={"Accept": "application/activity+json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "OrderedCollectionPage"
    assert len(data["orderedItems"]) >= 1


async def test_outbox_not_found(app_client, mock_valkey):
    resp = await app_client.get(
        "/users/nobody/outbox", headers={"Accept": "application/activity+json"},
    )
    assert resp.status_code == 404


async def test_featured_collection(app_client, test_user, mock_valkey):
    """Featured endpoint should return an OrderedCollection."""
    resp = await app_client.get(
        "/users/testuser/featured",
        headers={"Accept": "application/activity+json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "OrderedCollection"
    assert data["totalItems"] == 0
    assert data["orderedItems"] == []


async def test_featured_not_found(app_client, mock_valkey):
    resp = await app_client.get(
        "/users/nobody/featured", headers={"Accept": "application/activity+json"},
    )
    assert resp.status_code == 404


async def test_followers_collection_not_found(app_client, mock_valkey):
    resp = await app_client.get(
        "/users/nobody/followers", headers={"Accept": "application/activity+json"},
    )
    assert resp.status_code == 404


async def test_following_collection_not_found(app_client, mock_valkey):
    resp = await app_client.get(
        "/users/nobody/following", headers={"Accept": "application/activity+json"},
    )
    assert resp.status_code == 404


async def test_note_ap_not_found(app_client, mock_valkey):
    import uuid
    fake_id = str(uuid.uuid4())
    resp = await app_client.get(
        f"/notes/{fake_id}", headers={"Accept": "application/activity+json"},
    )
    assert resp.status_code == 404


async def test_note_ap_includes_hashtag_tags(authed_client, mock_valkey):
    """Note with hashtags should include Hashtag tags in AP output."""
    create_resp = await authed_client.post(
        "/api/v1/statuses",
        json={"content": "Testing #nekonoverse hashtag", "visibility": "public"},
    )
    note_id = create_resp.json()["id"]
    resp = await authed_client.get(
        f"/notes/{note_id}", headers={"Accept": "application/activity+json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    tags = data.get("tag", [])
    hashtag_tags = [t for t in tags if t.get("type") == "Hashtag"]
    assert len(hashtag_tags) >= 1, f"No Hashtag tags in {tags}"
    assert any("nekonoverse" in t.get("name", "").lower() for t in hashtag_tags)


async def test_note_ap_includes_emoji_tags(authed_client, db, mock_valkey):
    """Note with custom emoji should include Emoji tags in AP output."""
    from app.models.custom_emoji import CustomEmoji

    emoji = CustomEmoji(
        shortcode="test_ap_emoji",
        url="https://example.com/emoji/test_ap_emoji.png",
        domain=None,
        local_only=False,
    )
    db.add(emoji)
    await db.flush()

    create_resp = await authed_client.post(
        "/api/v1/statuses",
        json={"content": "Hello :test_ap_emoji: world", "visibility": "public"},
    )
    note_id = create_resp.json()["id"]
    resp = await authed_client.get(
        f"/notes/{note_id}", headers={"Accept": "application/activity+json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Verify @context includes "Emoji": "toot:Emoji" for JSON-LD compatibility
    ctx = data.get("@context", [])
    inline_ctx = next((c for c in ctx if isinstance(c, dict)), {})
    assert inline_ctx.get("Emoji") == "toot:Emoji", f"Missing Emoji term in context: {inline_ctx}"
    tags = data.get("tag", [])
    emoji_tags = [t for t in tags if t.get("type") == "Emoji"]
    assert len(emoji_tags) >= 1, f"No Emoji tags in {tags}"
    assert emoji_tags[0]["name"] == ":test_ap_emoji:"
    assert emoji_tags[0]["icon"]["url"] == "https://example.com/emoji/test_ap_emoji.png"
    assert "/emojis/test_ap_emoji" in emoji_tags[0]["id"]


async def test_actor_suspended(app_client, test_user, db, mock_valkey):
    """Suspended actor should return 410 Gone."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.models.actor import Actor
    result = await db.execute(select(Actor).where(Actor.id == test_user.actor_id))
    actor = result.scalar_one()
    actor.suspended_at = datetime.now(timezone.utc)
    await db.flush()

    resp = await app_client.get(
        "/users/testuser", headers={"Accept": "application/activity+json"},
    )
    assert resp.status_code == 410
