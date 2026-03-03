import pytest

from tests.conftest import make_note


async def test_nodeinfo_discovery(app_client):
    resp = await app_client.get("/.well-known/nodeinfo")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["links"]) == 1
    link = data["links"][0]
    assert link["rel"] == "http://nodeinfo.diaspora.software/ns/schema/2.0"
    assert link["href"].endswith("/nodeinfo/2.0")


async def test_nodeinfo(app_client):
    resp = await app_client.get("/nodeinfo/2.0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "2.0"
    assert data["software"]["name"] == "nekonoverse"
    assert data["protocols"] == ["activitypub"]
    assert "usage" in data
    assert "users" in data["usage"]
    assert "localPosts" in data["usage"]


async def test_nodeinfo_user_count(app_client, test_user):
    resp = await app_client.get("/nodeinfo/2.0")
    data = resp.json()
    assert data["usage"]["users"]["total"] >= 1


async def test_nodeinfo_post_count(app_client, test_user, db):
    await make_note(db, test_user.actor, content="nodeinfo test note")
    resp = await app_client.get("/nodeinfo/2.0")
    data = resp.json()
    assert data["usage"]["localPosts"] >= 1


async def test_nodeinfo_metadata(app_client):
    resp = await app_client.get("/nodeinfo/2.0")
    data = resp.json()
    assert data["metadata"]["nodeName"] == "Nekonoverse"
    assert "emoji_reactions" in data["metadata"]["features"]
