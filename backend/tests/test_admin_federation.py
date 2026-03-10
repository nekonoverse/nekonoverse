"""Tests for admin federation API endpoints."""

from unittest.mock import AsyncMock

import pytest

from app.models.delivery import DeliveryJob
from tests.conftest import make_note, make_remote_actor


async def make_admin_user(db):
    """Create a user with admin role."""
    from app.services.user_service import create_user
    user = await create_user(
        db, "adminuser", "admin@example.com", "password1234",
        display_name="Admin",
    )
    user.role = "admin"
    await db.flush()
    return user


def authed_client_for(app_client, mock_valkey, user):
    """Set up app_client cookies for a specific user."""
    mock_valkey.get = AsyncMock(return_value=str(user.id))
    app_client.cookies.set("nekonoverse_session", "test-session-id")
    return app_client


@pytest.mark.anyio
async def test_federation_list_empty(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.get("/api/v1/admin/federation")
    assert resp.status_code == 200
    data = resp.json()
    assert data["servers"] == []
    assert data["total"] == 0


@pytest.mark.anyio
async def test_federation_list_with_remote_actors(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    # リモートアクターを作成
    actor1 = await make_remote_actor(db, username="user1", domain="misskey.io")
    await make_remote_actor(db, username="user2", domain="misskey.io")
    actor3 = await make_remote_actor(db, username="user3", domain="mastodon.social")
    await db.flush()

    # ノートを作成
    await make_note(db, actor1, content="Hello", local=False)
    await make_note(db, actor3, content="World", local=False)
    await db.flush()

    resp = await client.get("/api/v1/admin/federation")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2

    domains = {s["domain"] for s in data["servers"]}
    assert "misskey.io" in domains
    assert "mastodon.social" in domains

    # misskey.ioにはuser_count=2のはず
    misskey = next(s for s in data["servers"] if s["domain"] == "misskey.io")
    assert misskey["user_count"] == 2
    assert misskey["note_count"] == 1
    assert misskey["status"] == "active"
    assert misskey["delivery_stats"]["success"] == 0


@pytest.mark.anyio
async def test_federation_list_search(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    await make_remote_actor(db, username="u1", domain="misskey.io")
    await make_remote_actor(db, username="u2", domain="mastodon.social")
    await db.flush()

    resp = await client.get("/api/v1/admin/federation?search=misskey")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["servers"][0]["domain"] == "misskey.io"


@pytest.mark.anyio
async def test_federation_list_status_filter(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    await make_remote_actor(db, username="u1", domain="misskey.io")
    await make_remote_actor(db, username="u2", domain="blocked.example")
    await db.flush()

    # ドメインブロックを作成
    from app.services.domain_block_service import create_domain_block
    await create_domain_block(db, "blocked.example", "suspend", None, admin)
    await db.flush()

    # activeフィルタ
    resp = await client.get("/api/v1/admin/federation?status=active")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["servers"][0]["domain"] == "misskey.io"

    # suspendedフィルタ
    resp = await client.get("/api/v1/admin/federation?status=suspended")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["servers"][0]["domain"] == "blocked.example"
    assert data["servers"][0]["status"] == "suspended"


@pytest.mark.anyio
async def test_federation_detail(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    actor = await make_remote_actor(db, username="testuser", domain="example.com")
    await make_note(db, actor, content="Test", local=False)
    await db.flush()

    resp = await client.get("/api/v1/admin/federation/example.com")
    assert resp.status_code == 200
    data = resp.json()
    assert data["domain"] == "example.com"
    assert data["user_count"] == 1
    assert data["note_count"] == 1
    assert data["status"] == "active"
    assert len(data["recent_actors"]) == 1
    assert data["recent_actors"][0]["username"] == "testuser"


@pytest.mark.anyio
async def test_federation_detail_not_found(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    resp = await client.get("/api/v1/admin/federation/nonexistent.example")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_federation_forbidden_for_regular_user(
    db, app_client, mock_valkey, test_user,
):
    client = authed_client_for(app_client, mock_valkey, test_user)
    resp = await client.get("/api/v1/admin/federation")
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_federation_list_sort_domain_asc(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    await make_remote_actor(db, username="u1", domain="beta.example")
    await make_remote_actor(db, username="u2", domain="alpha.example")
    await make_remote_actor(db, username="u3", domain="gamma.example")
    await db.flush()

    resp = await client.get("/api/v1/admin/federation?sort=domain&order=asc")
    assert resp.status_code == 200
    domains = [s["domain"] for s in resp.json()["servers"]]
    assert domains == ["alpha.example", "beta.example", "gamma.example"]

    # desc
    resp = await client.get("/api/v1/admin/federation?sort=domain&order=desc")
    domains_desc = [s["domain"] for s in resp.json()["servers"]]
    assert domains_desc == ["gamma.example", "beta.example", "alpha.example"]


@pytest.mark.anyio
async def test_federation_list_pagination(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    # 5ドメイン作成
    for i in range(5):
        await make_remote_actor(
            db, username=f"u{i}", domain=f"d{i}.example",
        )
    await db.flush()

    # limit=2, offset=0 → 先頭2件
    resp = await client.get(
        "/api/v1/admin/federation?limit=2&offset=0&sort=domain&order=asc",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["servers"]) == 2
    assert data["servers"][0]["domain"] == "d0.example"
    assert data["servers"][1]["domain"] == "d1.example"

    # limit=2, offset=2 → 次の2件
    resp = await client.get(
        "/api/v1/admin/federation?limit=2&offset=2&sort=domain&order=asc",
    )
    data = resp.json()
    assert data["total"] == 5
    assert len(data["servers"]) == 2
    assert data["servers"][0]["domain"] == "d2.example"

    # limit=2, offset=4 → 残り1件
    resp = await client.get(
        "/api/v1/admin/federation?limit=2&offset=4&sort=domain&order=asc",
    )
    data = resp.json()
    assert len(data["servers"]) == 1


@pytest.mark.anyio
async def test_federation_list_delivery_stats(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    actor = await make_remote_actor(db, username="u1", domain="target.example")
    await db.flush()

    # 配信ジョブを作成(delivered x 3, dead x 1, pending x 2)
    statuses = ["delivered", "delivered", "delivered", "dead", "pending", "pending"]
    for st in statuses:
        job = DeliveryJob(
            actor_id=actor.id,
            target_inbox_url="https://target.example/inbox",
            payload={"type": "Create"},
            status=st,
        )
        db.add(job)
    await db.flush()

    resp = await client.get("/api/v1/admin/federation")
    assert resp.status_code == 200
    srv = resp.json()["servers"][0]
    assert srv["domain"] == "target.example"
    assert srv["delivery_stats"]["success"] == 3
    assert srv["delivery_stats"]["dead"] == 1
    assert srv["delivery_stats"]["pending"] == 2


@pytest.mark.anyio
async def test_federation_detail_with_block_info(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    await make_remote_actor(db, username="u1", domain="bad.example")
    await db.flush()

    from app.services.domain_block_service import create_domain_block
    await create_domain_block(
        db, "bad.example", "suspend", "spam server", admin,
    )
    await db.flush()

    resp = await client.get("/api/v1/admin/federation/bad.example")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "suspended"
    assert data["block_severity"] == "suspend"
    assert data["block_reason"] == "spam server"


@pytest.mark.anyio
async def test_federation_list_silenced_filter(db, app_client, mock_valkey):
    admin = await make_admin_user(db)
    client = authed_client_for(app_client, mock_valkey, admin)

    await make_remote_actor(db, username="u1", domain="good.example")
    await make_remote_actor(db, username="u2", domain="quiet.example")
    await db.flush()

    from app.services.domain_block_service import create_domain_block
    await create_domain_block(
        db, "quiet.example", "silence", "noisy", admin,
    )
    await db.flush()

    resp = await client.get("/api/v1/admin/federation?status=silenced")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["servers"][0]["domain"] == "quiet.example"
    assert data["servers"][0]["status"] == "silenced"
    assert data["servers"][0]["block_severity"] == "silence"
