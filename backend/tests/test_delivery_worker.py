"""Tests for app.worker.delivery_worker."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.models.delivery import DeliveryJob
from app.worker.delivery_worker import (
    deliver_activity,
    get_actor_with_key,
    get_next_job,
    process_jobs,
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


# ── get_next_job ──


async def test_get_next_job_returns_pending(db, pending_job):
    job = await get_next_job(db)
    assert job is not None
    assert job.id == pending_job.id


async def test_get_next_job_skips_non_pending(db, pending_job):
    pending_job.status = "delivered"
    await db.flush()

    job = await get_next_job(db)
    assert job is None


async def test_get_next_job_skips_future_retry(db, pending_job):
    pending_job.next_retry_at = datetime.now(timezone.utc) + timedelta(hours=1)
    await db.flush()

    job = await get_next_job(db)
    assert job is None


async def test_get_next_job_returns_past_retry(db, pending_job):
    pending_job.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    await db.flush()

    job = await get_next_job(db)
    assert job is not None
    assert job.id == pending_job.id


async def test_get_next_job_empty_queue(db, mock_valkey):
    job = await get_next_job(db)
    assert job is None


async def test_get_next_job_orders_by_created_at(db, test_user, mock_valkey):
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

    job = await get_next_job(db)
    assert job.id == job_old.id


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


def _mock_httpx_client(status_code=202, side_effect=None):
    """Helper to create a mocked httpx client for _get_http_client."""
    mock_client = AsyncMock()
    if side_effect:
        mock_client.post = AsyncMock(side_effect=side_effect)
    else:
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_client.post = AsyncMock(return_value=mock_response)
    return mock_client


async def test_deliver_activity_success(db, test_user, pending_job, mock_valkey):
    actor = test_user.actor
    mock_client = _mock_httpx_client(202)

    with (
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
        patch("app.utils.network.is_private_host", return_value=False),
    ):
        result = await deliver_activity(pending_job, actor, test_user.private_key_pem)

    assert result is True
    mock_client.post.assert_called_once()


async def test_deliver_activity_failure_500(db, test_user, pending_job, mock_valkey):
    actor = test_user.actor
    mock_client = _mock_httpx_client(500)

    with (
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
        patch("app.utils.network.is_private_host", return_value=False),
    ):
        result = await deliver_activity(pending_job, actor, test_user.private_key_pem)

    assert result is False


async def test_deliver_activity_accepts_200(db, test_user, pending_job, mock_valkey):
    actor = test_user.actor
    mock_client = _mock_httpx_client(200)

    with (
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
        patch("app.utils.network.is_private_host", return_value=False),
    ):
        result = await deliver_activity(pending_job, actor, test_user.private_key_pem)

    assert result is True


async def test_deliver_activity_accepts_204(db, test_user, pending_job, mock_valkey):
    actor = test_user.actor
    mock_client = _mock_httpx_client(204)

    with (
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
        patch("app.utils.network.is_private_host", return_value=False),
    ):
        result = await deliver_activity(pending_job, actor, test_user.private_key_pem)

    assert result is True


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


# ── process_jobs ──


async def test_process_jobs_no_jobs():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("app.worker.delivery_worker.async_session") as mock_session_ctx:
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await process_jobs()

    assert result is False


async def test_process_jobs_successful_delivery(db, test_user, pending_job, mock_valkey):
    mock_client = _mock_httpx_client(202)

    with (
        patch("app.worker.delivery_worker.async_session") as mock_session_ctx,
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
        patch("app.utils.network.is_private_host", return_value=False),
    ):
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await process_jobs()

    assert result is True
    assert pending_job.status == "delivered"
    assert pending_job.attempts == 1


async def test_process_jobs_failed_delivery_retries(db, test_user, pending_job, mock_valkey):
    mock_client = _mock_httpx_client(500)

    with (
        patch("app.worker.delivery_worker.async_session") as mock_session_ctx,
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
        patch("app.utils.network.is_private_host", return_value=False),
    ):
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await process_jobs()

    assert result is True
    assert pending_job.status == "pending"
    assert pending_job.attempts == 1
    assert pending_job.next_retry_at is not None
    assert pending_job.error_message is not None


async def test_process_jobs_max_attempts_marks_dead(db, test_user, pending_job, mock_valkey):
    pending_job.attempts = 9  # Will become 10 (== max_attempts)
    await db.flush()

    mock_client = _mock_httpx_client(500)

    with (
        patch("app.worker.delivery_worker.async_session") as mock_session_ctx,
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
        patch("app.utils.network.is_private_host", return_value=False),
    ):
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await process_jobs()

    assert result is True
    assert pending_job.status == "dead"
    assert pending_job.attempts == 10


async def test_process_jobs_remote_actor_no_key_marks_dead(db, test_user, mock_valkey):
    # Create a job for a remote actor (has no private key)
    remote = await make_remote_actor(db, username="nokey_delivery")
    job = DeliveryJob(
        actor_id=remote.id,
        target_inbox_url="http://remote.example/inbox",
        payload={"type": "Create"},
        status="pending",
    )
    db.add(job)
    await db.flush()

    with patch("app.worker.delivery_worker.async_session") as mock_session_ctx:
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await process_jobs()

    assert result is True
    assert job.status == "dead"
    assert "not found" in job.error_message.lower()


async def test_process_jobs_exponential_backoff(db, test_user, pending_job, mock_valkey):
    pending_job.attempts = 2  # Will become 3 → delay = 60 * 2^3 = 480s
    await db.flush()

    mock_client = _mock_httpx_client(500)

    with (
        patch("app.worker.delivery_worker.async_session") as mock_session_ctx,
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
    ):
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        before = datetime.now(timezone.utc)
        result = await process_jobs()

    assert pending_job.next_retry_at is not None
    delta = (pending_job.next_retry_at - before).total_seconds()
    # delay = min(60 * 2^3, 21600) = 480s, allow some tolerance
    assert 470 < delta < 500


async def test_process_jobs_backoff_capped_at_6_hours(db, test_user, pending_job, mock_valkey):
    pending_job.attempts = 8  # Will become 9 → 60 * 2^9 = 30720 > 21600, capped
    await db.flush()

    mock_client = _mock_httpx_client(500)

    with (
        patch("app.worker.delivery_worker.async_session") as mock_session_ctx,
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
    ):
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        before = datetime.now(timezone.utc)
        result = await process_jobs()

    delta = (pending_job.next_retry_at - before).total_seconds()
    # Capped at 21600s (6 hours)
    assert 21590 < delta < 21610


async def test_process_jobs_network_error_retries(db, test_user, pending_job, mock_valkey):
    mock_client = _mock_httpx_client(side_effect=Exception("Connection refused"))

    with (
        patch("app.worker.delivery_worker.async_session") as mock_session_ctx,
        patch("app.worker.delivery_worker._get_http_client", return_value=mock_client),
        patch("app.utils.network.is_private_host", return_value=False),
    ):
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await process_jobs()

    assert result is True
    assert pending_job.status == "pending"
    assert "Connection refused" in pending_job.error_message
