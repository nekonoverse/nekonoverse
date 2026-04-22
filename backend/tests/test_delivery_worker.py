"""Tests for app.worker.delivery_worker."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.delivery import DeliveryJob
from app.worker.delivery_worker import (
    ORPHAN_RECLAIM_THRESHOLD,
    _deliver_one,
    deliver_activity,
    get_actor_with_key,
    get_pending_jobs,
    reclaim_orphan_jobs,
)
from tests.conftest import make_remote_actor


@pytest.fixture
async def pending_job(db, test_user, mock_valkey):
    job = DeliveryJob(
        actor_id=test_user.actor_id,
        target_inbox_url="http://remote.example/inbox",
        payload={"type": "Create", "id": "https://localhost/activities/1"},
        status="pending",
    )
    db.add(job)
    await db.flush()
    return job


@pytest.fixture
async def processing_job(db, test_user, mock_valkey):
    """A job already marked as processing (as run_delivery_loop would do)."""
    job = DeliveryJob(
        actor_id=test_user.actor_id,
        target_inbox_url="http://remote.example/inbox",
        payload={"type": "Create", "id": "https://localhost/activities/1"},
        status="processing",
        attempts=1,
        last_attempted_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.flush()
    return job


# ── get_pending_jobs ──


async def test_get_pending_jobs_returns_pending(db, pending_job):
    jobs = await get_pending_jobs(db, limit=16)
    assert len(jobs) >= 1
    assert any(j.id == pending_job.id for j in jobs)


async def test_get_pending_jobs_skips_non_pending(db, pending_job):
    pending_job.status = "delivered"
    await db.flush()

    jobs = await get_pending_jobs(db, limit=16)
    assert all(j.id != pending_job.id for j in jobs)


async def test_get_pending_jobs_skips_future_retry(db, pending_job):
    pending_job.next_retry_at = datetime.now(timezone.utc) + timedelta(hours=1)
    await db.flush()

    jobs = await get_pending_jobs(db, limit=16)
    assert all(j.id != pending_job.id for j in jobs)


async def test_get_pending_jobs_returns_past_retry(db, pending_job):
    pending_job.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    await db.flush()

    jobs = await get_pending_jobs(db, limit=16)
    assert any(j.id == pending_job.id for j in jobs)


async def test_get_pending_jobs_empty_queue(db, mock_valkey):
    jobs = await get_pending_jobs(db, limit=16)
    assert jobs == []


async def test_get_pending_jobs_orders_by_created_at(db, test_user, mock_valkey):
    job_old = DeliveryJob(
        actor_id=test_user.actor_id,
        target_inbox_url="http://remote.example/inbox",
        payload={"type": "Old"},
        status="pending",
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    job_new = DeliveryJob(
        actor_id=test_user.actor_id,
        target_inbox_url="http://remote.example/inbox",
        payload={"type": "New"},
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    db.add_all([job_new, job_old])
    await db.flush()

    jobs = await get_pending_jobs(db, limit=16)
    assert len(jobs) >= 2
    # First job should be the older one
    assert jobs[0].id == job_old.id


async def test_get_pending_jobs_respects_limit(db, test_user, mock_valkey):
    for i in range(5):
        db.add(DeliveryJob(
            actor_id=test_user.actor_id,
            target_inbox_url=f"http://remote{i}.example/inbox",
            payload={"type": "Create"},
            status="pending",
        ))
    await db.flush()

    jobs = await get_pending_jobs(db, limit=3)
    assert len(jobs) == 3


# ── get_actor_with_key ──


async def test_get_actor_with_key_local(db, test_user, mock_valkey):
    found_actor, found_key = await get_actor_with_key(db, test_user.actor_id)
    assert found_actor is not None
    assert found_actor.id == test_user.actor_id
    assert "PRIVATE KEY" in found_key


async def test_get_actor_with_key_remote_no_key(db, mock_valkey):
    remote = await make_remote_actor(db, username="nokey")
    found_actor, found_key = await get_actor_with_key(db, remote.id)
    assert found_actor is not None
    assert found_key == ""


async def test_get_actor_with_key_nonexistent(db, mock_valkey):
    found_actor, found_key = await get_actor_with_key(db, uuid.uuid4())
    assert found_actor is None
    assert found_key == ""


# ── deliver_activity ──


def _mock_httpx_client(status_code=202, side_effect=None, text=""):
    """Helper to create a mocked httpx client for _get_http_client."""
    mock_client = AsyncMock()
    if side_effect:
        mock_client.post = AsyncMock(side_effect=side_effect)
    else:
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.text = text
        mock_client.post = AsyncMock(return_value=mock_response)
    return mock_client


async def test_deliver_activity_success(db, test_user, pending_job, mock_valkey):
    actor = test_user.actor
    mock_client = _mock_httpx_client(202)

    with (
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
        patch("app.utils.network.is_private_host", return_value=False),
    ):
        success, status_code, error_detail = await deliver_activity(
            pending_job, actor, test_user.private_key_pem
        )

    assert success is True
    assert status_code == 202
    assert error_detail == ""
    mock_client.post.assert_called_once()


async def test_deliver_activity_failure_500(db, test_user, pending_job, mock_valkey):
    actor = test_user.actor
    mock_client = _mock_httpx_client(500, text="upstream exploded")

    with (
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
        patch("app.utils.network.is_private_host", return_value=False),
    ):
        success, status_code, error_detail = await deliver_activity(
            pending_job, actor, test_user.private_key_pem
        )

    assert success is False
    assert status_code == 500
    assert "HTTP 500" in error_detail
    assert "upstream exploded" in error_detail


async def test_deliver_activity_error_detail_truncates_body(
    db, test_user, pending_job, mock_valkey
):
    huge_body = "x" * 10_000
    mock_client = _mock_httpx_client(400, text=huge_body)

    with (
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
        patch("app.utils.network.is_private_host", return_value=False),
    ):
        _, _, error_detail = await deliver_activity(
            pending_job, test_user.actor, test_user.private_key_pem
        )

    # 先頭 300 文字 + "HTTP 400: " のプレフィックスで十分短い
    assert len(error_detail) < 400


async def test_deliver_activity_network_exception_returns_type_name(
    db, test_user, pending_job, mock_valkey
):
    import httpx

    mock_client = _mock_httpx_client(side_effect=httpx.ConnectError("all attempts failed"))

    with (
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
        patch("app.utils.network.is_private_host", return_value=False),
    ):
        success, status_code, error_detail = await deliver_activity(
            pending_job, test_user.actor, test_user.private_key_pem
        )

    assert success is False
    assert status_code == 0
    assert "ConnectError" in error_detail
    assert "all attempts failed" in error_detail


async def test_deliver_activity_private_host_blocked(
    db, test_user, pending_job, mock_valkey
):
    with patch("app.utils.network.is_private_host", return_value=True):
        success, status_code, error_detail = await deliver_activity(
            pending_job, test_user.actor, test_user.private_key_pem
        )

    assert success is False
    assert status_code == 0
    assert "private host" in error_detail


async def test_deliver_activity_accepts_200(db, test_user, pending_job, mock_valkey):
    actor = test_user.actor
    mock_client = _mock_httpx_client(200)

    with (
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
        patch("app.utils.network.is_private_host", return_value=False),
    ):
        success, _, _ = await deliver_activity(
            pending_job, actor, test_user.private_key_pem
        )

    assert success is True


async def test_deliver_activity_accepts_204(db, test_user, pending_job, mock_valkey):
    actor = test_user.actor
    mock_client = _mock_httpx_client(204)

    with (
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
        patch("app.utils.network.is_private_host", return_value=False),
    ):
        success, _, _ = await deliver_activity(
            pending_job, actor, test_user.private_key_pem
        )

    assert success is True


async def test_deliver_activity_sends_signed_headers(db, test_user, pending_job, mock_valkey):
    actor = test_user.actor
    mock_client = _mock_httpx_client(202)

    with (
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
        patch("app.utils.network.is_private_host", return_value=False),
    ):
        await deliver_activity(pending_job, actor, test_user.private_key_pem)

    call_kwargs = mock_client.post.call_args
    headers = call_kwargs[1]["headers"]
    assert "Signature" in headers
    assert "Digest" in headers
    assert "Content-Type" in headers
    assert "activity" in headers["Content-Type"]


# ── _deliver_one ──


async def test_deliver_one_successful(db, test_user, processing_job, mock_valkey):
    mock_client = _mock_httpx_client(202)
    sem = asyncio.Semaphore(1)

    with (
        patch("app.worker.delivery_worker.async_session") as mock_session_ctx,
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
        patch("app.utils.network.is_private_host", return_value=False),
    ):
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await _deliver_one(processing_job.id, sem)

    assert processing_job.status == "delivered"


async def test_deliver_one_failed_retries(db, test_user, processing_job, mock_valkey):
    mock_client = _mock_httpx_client(500)
    sem = asyncio.Semaphore(1)

    with (
        patch("app.worker.delivery_worker.async_session") as mock_session_ctx,
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
        patch("app.utils.network.is_private_host", return_value=False),
    ):
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await _deliver_one(processing_job.id, sem)

    assert processing_job.status == "pending"
    assert processing_job.next_retry_at is not None
    assert processing_job.error_message is not None


async def test_deliver_one_max_attempts_marks_dead(db, test_user, mock_valkey):
    job = DeliveryJob(
        actor_id=test_user.actor_id,
        target_inbox_url="http://remote.example/inbox",
        payload={"type": "Create"},
        status="processing",
        attempts=10,
        last_attempted_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.flush()

    mock_client = _mock_httpx_client(500)
    sem = asyncio.Semaphore(1)

    with (
        patch("app.worker.delivery_worker.async_session") as mock_session_ctx,
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
        patch("app.utils.network.is_private_host", return_value=False),
    ):
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await _deliver_one(job.id, sem)

    assert job.status == "dead"


async def test_deliver_one_remote_actor_no_key_marks_dead(db, test_user, mock_valkey):
    remote = await make_remote_actor(db, username="nokey_delivery")
    job = DeliveryJob(
        actor_id=remote.id,
        target_inbox_url="http://remote.example/inbox",
        payload={"type": "Create"},
        status="processing",
        attempts=1,
        last_attempted_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.flush()

    sem = asyncio.Semaphore(1)

    with patch("app.worker.delivery_worker.async_session") as mock_session_ctx:
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await _deliver_one(job.id, sem)

    assert job.status == "dead"
    assert "not found" in job.error_message.lower()


async def test_deliver_one_exponential_backoff(db, test_user, mock_valkey):
    job = DeliveryJob(
        actor_id=test_user.actor_id,
        target_inbox_url="http://remote.example/inbox",
        payload={"type": "Create"},
        status="processing",
        attempts=3,  # delay = min(60 * 2^3, 21600) = 480s
        last_attempted_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.flush()

    mock_client = _mock_httpx_client(500)
    sem = asyncio.Semaphore(1)

    with (
        patch("app.worker.delivery_worker.async_session") as mock_session_ctx,
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
    ):
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        before = datetime.now(timezone.utc)
        await _deliver_one(job.id, sem)

    assert job.next_retry_at is not None
    delta = (job.next_retry_at - before).total_seconds()
    # delay = min(60 * 2^3, 21600) = 480s, allow some tolerance
    assert 470 < delta < 500


async def test_deliver_one_backoff_capped_at_6_hours(db, test_user, mock_valkey):
    job = DeliveryJob(
        actor_id=test_user.actor_id,
        target_inbox_url="http://remote.example/inbox",
        payload={"type": "Create"},
        status="processing",
        attempts=9,  # 60 * 2^9 = 30720 > 21600, capped
        last_attempted_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.flush()

    mock_client = _mock_httpx_client(500)
    sem = asyncio.Semaphore(1)

    with (
        patch("app.worker.delivery_worker.async_session") as mock_session_ctx,
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
    ):
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        before = datetime.now(timezone.utc)
        await _deliver_one(job.id, sem)

    delta = (job.next_retry_at - before).total_seconds()
    # Capped at 21600s (6 hours)
    assert 21590 < delta < 21610


async def test_deliver_one_network_error_retries(db, test_user, processing_job, mock_valkey):
    mock_client = _mock_httpx_client(side_effect=Exception("Connection refused"))
    sem = asyncio.Semaphore(1)

    with (
        patch("app.worker.delivery_worker.async_session") as mock_session_ctx,
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
        patch("app.utils.network.is_private_host", return_value=False),
    ):
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await _deliver_one(processing_job.id, sem)

    assert processing_job.status == "pending"
    assert "Connection refused" in processing_job.error_message


async def test_deliver_one_skips_non_processing_job(db, pending_job, mock_valkey):
    """Jobs not in 'processing' state should be skipped."""
    sem = asyncio.Semaphore(1)

    with patch("app.worker.delivery_worker.async_session") as mock_session_ctx:
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await _deliver_one(pending_job.id, sem)

    # Job should remain in pending state, untouched
    assert pending_job.status == "pending"


# ── reclaim_orphan_jobs ──


async def test_reclaim_orphan_jobs_recovers_old_processing(db, test_user, mock_valkey):
    old_job = DeliveryJob(
        actor_id=test_user.actor_id,
        target_inbox_url="http://remote.example/inbox",
        payload={"type": "Create"},
        status="processing",
        attempts=3,
        last_attempted_at=datetime.now(timezone.utc) - ORPHAN_RECLAIM_THRESHOLD - timedelta(
            minutes=5
        ),
    )
    db.add(old_job)
    await db.flush()

    count = await reclaim_orphan_jobs(db)

    assert count == 1
    await db.refresh(old_job)
    assert old_job.status == "pending"
    # attempts は保持されるべき (次回バックオフが引き続き効く)
    assert old_job.attempts == 3


async def test_reclaim_orphan_jobs_leaves_fresh_processing(db, test_user, mock_valkey):
    fresh_job = DeliveryJob(
        actor_id=test_user.actor_id,
        target_inbox_url="http://remote.example/inbox",
        payload={"type": "Create"},
        status="processing",
        attempts=1,
        last_attempted_at=datetime.now(timezone.utc) - timedelta(seconds=30),
    )
    db.add(fresh_job)
    await db.flush()

    count = await reclaim_orphan_jobs(db)

    assert count == 0
    await db.refresh(fresh_job)
    assert fresh_job.status == "processing"


async def test_reclaim_orphan_jobs_ignores_other_statuses(db, test_user, mock_valkey):
    old_ts = datetime.now(timezone.utc) - ORPHAN_RECLAIM_THRESHOLD - timedelta(hours=1)
    pending = DeliveryJob(
        actor_id=test_user.actor_id,
        target_inbox_url="http://remote.example/inbox",
        payload={"type": "Create"},
        status="pending",
        last_attempted_at=old_ts,
    )
    delivered = DeliveryJob(
        actor_id=test_user.actor_id,
        target_inbox_url="http://remote.example/inbox",
        payload={"type": "Create"},
        status="delivered",
        last_attempted_at=old_ts,
    )
    dead = DeliveryJob(
        actor_id=test_user.actor_id,
        target_inbox_url="http://remote.example/inbox",
        payload={"type": "Create"},
        status="dead",
        last_attempted_at=old_ts,
    )
    db.add_all([pending, delivered, dead])
    await db.flush()

    count = await reclaim_orphan_jobs(db)

    assert count == 0
    for job in (pending, delivered, dead):
        await db.refresh(job)
    assert pending.status == "pending"
    assert delivered.status == "delivered"
    assert dead.status == "dead"
