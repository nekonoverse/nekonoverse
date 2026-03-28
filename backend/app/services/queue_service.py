"""管理ダッシュボード用キュー管理サービス。"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery import DeliveryJob


async def get_queue_stats(db: AsyncSession) -> dict:
    """キュー全体の統計情報を取得する。"""
    result = await db.execute(
        select(DeliveryJob.status, func.count(DeliveryJob.id)).group_by(DeliveryJob.status)
    )
    counts = {row[0]: row[1] for row in result.all()}

    # 直近1時間の配信成功・失敗数
    one_hour_ago = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    recent_result = await db.execute(
        select(DeliveryJob.status, func.count(DeliveryJob.id))
        .where(DeliveryJob.last_attempted_at >= one_hour_ago)
        .group_by(DeliveryJob.status)
    )
    recent = {row[0]: row[1] for row in recent_result.all()}

    pending = counts.get("pending", 0)
    processing = counts.get("processing", 0)
    delivered = counts.get("delivered", 0)
    dead = counts.get("dead", 0)

    return {
        "pending": pending,
        "processing": processing,
        "delivered": delivered,
        "dead": dead,
        "total": pending + processing + delivered + dead,
        "recent_delivered": recent.get("delivered", 0),
        "recent_dead": recent.get("dead", 0),
    }


async def get_queue_jobs(
    db: AsyncSession,
    status: str | None = None,
    domain: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[DeliveryJob], int]:
    """フィルタリング対応のページネーション付きキュージョブ一覧を取得する。"""
    query = select(DeliveryJob)
    count_query = select(func.count(DeliveryJob.id))

    if status:
        query = query.where(DeliveryJob.status == status)
        count_query = count_query.where(DeliveryJob.status == status)

    if domain:
        pattern = f"%://{domain}/%"
        query = query.where(DeliveryJob.target_inbox_url.ilike(pattern))
        count_query = count_query.where(DeliveryJob.target_inbox_url.ilike(pattern))

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    result = await db.execute(
        query.order_by(DeliveryJob.created_at.desc()).limit(limit).offset(offset)
    )
    jobs = list(result.scalars().all())

    return jobs, total


async def retry_job(db: AsyncSession, job_id: uuid.UUID) -> bool:
    """単一のデッドジョブをリトライする。"""
    result = await db.execute(
        update(DeliveryJob)
        .where(DeliveryJob.id == job_id, DeliveryJob.status == "dead")
        .values(
            status="pending",
            next_retry_at=None,
            attempts=0,
            error_message=None,
        )
    )
    await db.commit()
    return result.rowcount > 0


async def retry_all_dead(db: AsyncSession, domain: str | None = None) -> int:
    """全デッドジョブをリトライする。ドメインでフィルタリング可能。"""
    query = (
        update(DeliveryJob)
        .where(DeliveryJob.status == "dead")
        .values(
            status="pending",
            next_retry_at=None,
            attempts=0,
            error_message=None,
        )
    )
    if domain:
        pattern = f"%://{domain}/%"
        query = query.where(DeliveryJob.target_inbox_url.ilike(pattern))

    result = await db.execute(query)
    await db.commit()
    return result.rowcount


async def purge_delivered(db: AsyncSession, older_than_hours: int = 24) -> int:
    """指定時間以上前の配信済みジョブを削除する。"""
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=older_than_hours)

    result = await db.execute(
        delete(DeliveryJob).where(
            DeliveryJob.status == "delivered",
            DeliveryJob.created_at < cutoff,
        )
    )
    await db.commit()
    return result.rowcount
