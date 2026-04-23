"""delivery_purge_worker の動作テスト。"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.models.delivery import DeliveryJob
from app.worker.delivery_purge_worker import HEARTBEAT_KEY, _run_once


def _patch_async_session(db):
    """`async_session()` を指定したテスト用 session に差し替える context manager。"""

    @asynccontextmanager
    async def fake_session():
        yield db

    return patch("app.database.async_session", fake_session)


async def test_run_once_deletes_old_delivered(db, mock_valkey, test_user):
    """24h より古い delivered ジョブが削除されること。"""
    old = DeliveryJob(
        actor_id=test_user.actor_id,
        target_inbox_url="https://remote.example/inbox",
        payload={"type": "Create"},
        status="delivered",
        created_at=datetime.now(timezone.utc) - timedelta(hours=48),
    )
    recent = DeliveryJob(
        actor_id=test_user.actor_id,
        target_inbox_url="https://remote.example/inbox",
        payload={"type": "Create"},
        status="delivered",
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db.add_all([old, recent])
    await db.flush()

    with _patch_async_session(db):
        count = await _run_once()
    assert count == 1


async def test_run_once_does_not_touch_dead_or_pending(db, mock_valkey, test_user):
    """dead / pending は purge 対象外 (retry 用途で保持)。"""
    dead = DeliveryJob(
        actor_id=test_user.actor_id,
        target_inbox_url="https://remote.example/inbox",
        payload={"type": "Create"},
        status="dead",
        created_at=datetime.now(timezone.utc) - timedelta(hours=48),
    )
    pending = DeliveryJob(
        actor_id=test_user.actor_id,
        target_inbox_url="https://remote.example/inbox",
        payload={"type": "Create"},
        status="pending",
        created_at=datetime.now(timezone.utc) - timedelta(hours=48),
    )
    db.add_all([dead, pending])
    await db.flush()

    with _patch_async_session(db):
        count = await _run_once()
    assert count == 0


async def test_run_once_updates_heartbeat(db, mock_valkey):
    """heartbeat が更新されること。"""
    with _patch_async_session(db):
        await _run_once()
    mock_valkey.set.assert_any_call(HEARTBEAT_KEY, "alive", ex=3600 * 3)
