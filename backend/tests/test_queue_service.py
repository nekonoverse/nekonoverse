"""Tests for queue_service — delivery queue management."""

import uuid
from datetime import datetime, timedelta, timezone

from app.models.delivery import DeliveryJob
from app.services.queue_service import (
    get_queue_jobs,
    get_queue_stats,
    purge_delivered,
    retry_all_dead,
    retry_job,
)


async def _make_job(db, actor, *, status="pending", domain="remote.example", error=None):
    job = DeliveryJob(
        actor_id=actor.id,
        target_inbox_url=f"https://{domain}/inbox",
        payload={"type": "Create"},
        status=status,
        attempts=3 if status == "dead" else 0,
        error_message=error,
        last_attempted_at=datetime.now(timezone.utc) if status != "pending" else None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.flush()
    return job


# ── get_queue_stats ──────────────────────────────────────────────────────


async def test_queue_stats_empty(db, mock_valkey, test_user):
    stats = await get_queue_stats(db)
    assert stats["pending"] == 0
    assert stats["total"] == 0


async def test_queue_stats_counts(db, mock_valkey, test_user):
    actor = test_user.actor
    await _make_job(db, actor, status="pending")
    await _make_job(db, actor, status="pending")
    await _make_job(db, actor, status="delivered")
    await _make_job(db, actor, status="dead", error="timeout")
    await db.flush()

    stats = await get_queue_stats(db)
    assert stats["pending"] == 2
    assert stats["delivered"] == 1
    assert stats["dead"] == 1
    assert stats["total"] == 4


# ── get_queue_jobs ───────────────────────────────────────────────────────


async def test_queue_jobs_all(db, mock_valkey, test_user):
    actor = test_user.actor
    await _make_job(db, actor, status="pending")
    await _make_job(db, actor, status="dead")
    await db.flush()

    jobs, total = await get_queue_jobs(db)
    assert total == 2
    assert len(jobs) == 2


async def test_queue_jobs_filter_by_status(db, mock_valkey, test_user):
    actor = test_user.actor
    await _make_job(db, actor, status="pending")
    await _make_job(db, actor, status="dead")
    await db.flush()

    jobs, total = await get_queue_jobs(db, status="dead")
    assert total == 1
    assert all(j.status == "dead" for j in jobs)


async def test_queue_jobs_filter_by_domain(db, mock_valkey, test_user):
    actor = test_user.actor
    await _make_job(db, actor, status="pending", domain="alpha.example")
    await _make_job(db, actor, status="pending", domain="beta.example")
    await db.flush()

    jobs, total = await get_queue_jobs(db, domain="alpha.example")
    assert total == 1
    assert "alpha.example" in jobs[0].target_inbox_url


async def test_queue_jobs_pagination(db, mock_valkey, test_user):
    actor = test_user.actor
    for _ in range(5):
        await _make_job(db, actor, status="pending")
    await db.flush()

    jobs, total = await get_queue_jobs(db, limit=2, offset=0)
    assert total == 5
    assert len(jobs) == 2


# ── retry_job ────────────────────────────────────────────────────────────


async def test_retry_job_resets_dead_to_pending(db, mock_valkey, test_user):
    actor = test_user.actor
    job = await _make_job(db, actor, status="dead", error="timeout")

    result = await retry_job(db, job.id)
    assert result is True

    await db.refresh(job)
    assert job.status == "pending"
    assert job.attempts == 0
    assert job.error_message is None


async def test_retry_job_non_dead_returns_false(db, mock_valkey, test_user):
    actor = test_user.actor
    job = await _make_job(db, actor, status="pending")

    result = await retry_job(db, job.id)
    assert result is False


async def test_retry_job_nonexistent_returns_false(db, mock_valkey, test_user):
    result = await retry_job(db, uuid.uuid4())
    assert result is False


# ── retry_all_dead ───────────────────────────────────────────────────────


async def test_retry_all_dead(db, mock_valkey, test_user):
    actor = test_user.actor
    await _make_job(db, actor, status="dead", error="err1")
    await _make_job(db, actor, status="dead", error="err2")
    await _make_job(db, actor, status="pending")
    await db.flush()

    count = await retry_all_dead(db)
    assert count == 2


async def test_retry_all_dead_domain_filter(db, mock_valkey, test_user):
    actor = test_user.actor
    await _make_job(db, actor, status="dead", domain="alpha.example")
    await _make_job(db, actor, status="dead", domain="beta.example")
    await db.flush()

    count = await retry_all_dead(db, domain="alpha.example")
    assert count == 1


# ── purge_delivered ──────────────────────────────────────────────────────


async def test_purge_delivered(db, mock_valkey, test_user):
    actor = test_user.actor
    old_job = DeliveryJob(
        actor_id=actor.id,
        target_inbox_url="https://remote.example/inbox",
        payload={"type": "Create"},
        status="delivered",
        created_at=datetime.now(timezone.utc) - timedelta(hours=48),
    )
    db.add(old_job)
    await _make_job(db, actor, status="delivered")
    await db.flush()

    count = await purge_delivered(db, older_than_hours=24)
    assert count == 1
