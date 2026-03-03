import json

import pytest


async def test_webfinger_success(app_client, test_user):
    resp = await app_client.get(
        "/.well-known/webfinger",
        params={"resource": "acct:testuser@localhost"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/jrd+json"
    data = json.loads(resp.text)
    assert data["subject"] == "acct:testuser@localhost"
    assert len(data["aliases"]) == 2
    assert any("testuser" in alias for alias in data["aliases"])
    links = data["links"]
    self_link = next(l for l in links if l["rel"] == "self")
    assert self_link["type"] == "application/activity+json"


async def test_webfinger_invalid_resource_format(app_client):
    resp = await app_client.get(
        "/.well-known/webfinger",
        params={"resource": "invalid:something"},
    )
    assert resp.status_code == 400
    assert "Invalid resource format" in resp.json()["detail"]


async def test_webfinger_invalid_acct_format(app_client):
    resp = await app_client.get(
        "/.well-known/webfinger",
        params={"resource": "acct:nodomainnobody"},
    )
    assert resp.status_code == 400
    assert "Invalid acct format" in resp.json()["detail"]


async def test_webfinger_wrong_domain(app_client):
    resp = await app_client.get(
        "/.well-known/webfinger",
        params={"resource": "acct:user@wrong.example"},
    )
    assert resp.status_code == 404


async def test_webfinger_user_not_found(app_client):
    resp = await app_client.get(
        "/.well-known/webfinger",
        params={"resource": "acct:nonexistent@localhost"},
    )
    assert resp.status_code == 404


async def test_webfinger_missing_resource(app_client):
    resp = await app_client.get("/.well-known/webfinger")
    assert resp.status_code == 422
