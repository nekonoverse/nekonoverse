"""Tests for Discord-compatible webhook API endpoints."""

from unittest.mock import patch


async def test_create_and_list_webhook(authed_client, test_user):
    payload = {
        "name": "メイン",
        "webhook_url": "https://discord.com/api/webhooks/123/abcdefghijkl",
        "notify_mention": True,
        "notify_direct": False,
        "notify_quote": True,
        "notify_reaction": True,
        "notify_renote": False,
        "notify_follow": True,
        "notify_follow_request": False,
        "enabled": True,
    }
    resp = await authed_client.post("/api/v1/discord-webhooks", json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "メイン"
    assert body["notify_mention"] is True
    assert body["notify_direct"] is False
    assert body["enabled"] is True
    assert body["webhook_url_masked"].startswith(
        "https://discord.com/api/webhooks/123/abcd"
    )
    assert body["webhook_url_masked"].endswith("***")
    # 生 URL がレスポンスに含まれない
    assert "abcdefghijkl" not in body["webhook_url_masked"]
    webhook_id = body["id"]

    resp = await authed_client.get("/api/v1/discord-webhooks")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["id"] == webhook_id


async def test_duplicate_url_returns_409(authed_client, test_user):
    payload = {
        "name": "A",
        "webhook_url": "https://discord.com/api/webhooks/9/dup",
    }
    resp = await authed_client.post("/api/v1/discord-webhooks", json=payload)
    assert resp.status_code == 201

    payload["name"] = "B"
    resp2 = await authed_client.post("/api/v1/discord-webhooks", json=payload)
    assert resp2.status_code == 409


async def test_update_webhook_partial(authed_client, test_user):
    create = await authed_client.post(
        "/api/v1/discord-webhooks",
        json={
            "name": "old",
            "webhook_url": "https://example.com/webhook/u",
        },
    )
    assert create.status_code == 201
    webhook_id = create.json()["id"]

    resp = await authed_client.patch(
        f"/api/v1/discord-webhooks/{webhook_id}",
        json={"name": "new", "notify_mention": False, "enabled": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "new"
    assert body["notify_mention"] is False
    assert body["enabled"] is False
    # 触っていないフラグはデフォルト True のまま
    assert body["notify_reaction"] is True


async def test_delete_webhook(authed_client, test_user):
    create = await authed_client.post(
        "/api/v1/discord-webhooks",
        json={"name": "x", "webhook_url": "https://example.com/webhook/d"},
    )
    webhook_id = create.json()["id"]

    resp = await authed_client.delete(f"/api/v1/discord-webhooks/{webhook_id}")
    assert resp.status_code == 204

    get_resp = await authed_client.get(f"/api/v1/discord-webhooks/{webhook_id}")
    assert get_resp.status_code == 404


async def test_get_not_found(authed_client, test_user):
    import uuid

    resp = await authed_client.get(f"/api/v1/discord-webhooks/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_test_endpoint_invokes_send(authed_client, test_user):
    create = await authed_client.post(
        "/api/v1/discord-webhooks",
        json={"name": "t", "webhook_url": "https://example.com/webhook/t"},
    )
    webhook_id = create.json()["id"]

    async def fake_send(webhook):
        return True, 204, None

    with patch(
        "app.api.discord_webhooks.send_test_payload", side_effect=fake_send
    ) as mock:
        resp = await authed_client.post(
            f"/api/v1/discord-webhooks/{webhook_id}/test"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["status_code"] == 204
        mock.assert_called_once()


async def test_unauthorized_without_session(app_client):
    resp = await app_client.get("/api/v1/discord-webhooks")
    assert resp.status_code in (401, 403)
