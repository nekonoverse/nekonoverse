"""Extended tests for federation_service — federated server aggregation."""

from datetime import datetime, timezone

from app.models.delivery import DeliveryJob
from app.services.federation_service import (
    get_federated_server_detail,
    get_federated_servers,
)
from tests.conftest import make_note, make_remote_actor


async def _setup_federation_data(db):
    """Create test data for federation queries."""
    actor_a = await make_remote_actor(db, username="alice", domain="alpha.example")
    actor_b = await make_remote_actor(db, username="bob", domain="alpha.example")
    actor_c = await make_remote_actor(db, username="carol", domain="beta.example")

    await make_note(db, actor_a, content="note from alice", local=False)
    await make_note(db, actor_a, content="another from alice", local=False)
    await make_note(db, actor_c, content="note from carol", local=False)

    # Delivery jobs
    for s in ["delivered", "delivered", "dead"]:
        job = DeliveryJob(
            actor_id=actor_a.id,
            target_inbox_url="https://alpha.example/inbox",
            payload={"type": "Create"},
            status=s,
            created_at=datetime.now(timezone.utc),
        )
        db.add(job)

    await db.flush()
    return actor_a, actor_b, actor_c


# ── get_federated_servers ────────────────────────────────────────────────


async def test_federated_servers_returns_domains(db, mock_valkey):
    await _setup_federation_data(db)
    servers, total = await get_federated_servers(db)
    assert total >= 2
    domains = [s["domain"] for s in servers]
    assert "alpha.example" in domains
    assert "beta.example" in domains


async def test_federated_servers_user_count(db, mock_valkey):
    await _setup_federation_data(db)
    servers, _ = await get_federated_servers(db)
    alpha = next(s for s in servers if s["domain"] == "alpha.example")
    assert alpha["user_count"] == 2  # alice + bob


async def test_federated_servers_note_count(db, mock_valkey):
    await _setup_federation_data(db)
    servers, _ = await get_federated_servers(db)
    alpha = next(s for s in servers if s["domain"] == "alpha.example")
    assert alpha["note_count"] == 2


async def test_federated_servers_search(db, mock_valkey):
    await _setup_federation_data(db)
    servers, total = await get_federated_servers(db, search="alpha")
    assert total == 1
    assert servers[0]["domain"] == "alpha.example"


async def test_federated_servers_search_no_results(db, mock_valkey):
    await _setup_federation_data(db)
    servers, total = await get_federated_servers(db, search="nonexistent")
    assert total == 0


async def test_federated_servers_sort_by_domain_asc(db, mock_valkey):
    await _setup_federation_data(db)
    servers, _ = await get_federated_servers(db, sort="domain", order="asc")
    domains = [s["domain"] for s in servers]
    assert domains == sorted(domains)


async def test_federated_servers_status_active(db, mock_valkey):
    await _setup_federation_data(db)
    servers, _ = await get_federated_servers(db, status="active")
    for s in servers:
        assert s["status"] == "active"


async def test_federated_servers_status_suspended(db, mock_valkey):
    """Suspended filter returns only blocked domains."""
    await _setup_federation_data(db)
    from app.models.domain_block import DomainBlock

    block = DomainBlock(domain="alpha.example", severity="suspend", reason="spam")
    db.add(block)
    await db.flush()

    servers, total = await get_federated_servers(db, status="suspended")
    assert total >= 1
    assert all(s["status"] == "suspended" for s in servers)


async def test_federated_servers_pagination(db, mock_valkey):
    await _setup_federation_data(db)
    servers, total = await get_federated_servers(db, limit=1, offset=0)
    assert len(servers) == 1
    assert total >= 2


# ── get_federated_server_detail ──────────────────────────────────────────


async def test_federated_server_detail(db, mock_valkey):
    await _setup_federation_data(db)
    detail = await get_federated_server_detail(db, "alpha.example")
    assert detail is not None
    assert detail["domain"] == "alpha.example"
    assert detail["user_count"] == 2
    assert detail["note_count"] == 2
    assert detail["status"] == "active"
    assert "recent_actors" in detail
    assert len(detail["recent_actors"]) <= 10


async def test_federated_server_detail_not_found(db, mock_valkey):
    detail = await get_federated_server_detail(db, "nonexistent.example")
    assert detail is None


async def test_federated_server_detail_delivery_stats(db, mock_valkey):
    await _setup_federation_data(db)
    detail = await get_federated_server_detail(db, "alpha.example")
    stats = detail["delivery_stats"]
    assert stats["success"] == 2
    assert stats["dead"] == 1
