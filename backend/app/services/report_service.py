"""Report (moderation) service."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.actor import Actor
from app.models.note import Note
from app.models.report import Report
from app.models.user import User


async def create_report(
    db: AsyncSession,
    reporter_actor: Actor,
    target_actor: Actor,
    target_note: Note | None = None,
    comment: str | None = None,
    ap_id: str | None = None,
) -> Report:
    report = Report(
        ap_id=ap_id,
        reporter_actor_id=reporter_actor.id,
        target_actor_id=target_actor.id,
        target_note_id=target_note.id if target_note else None,
        comment=comment,
    )
    db.add(report)
    await db.flush()
    return report


async def list_reports(
    db: AsyncSession, status_filter: str | None = None
) -> list[Report]:
    query = (
        select(Report)
        .options(
            selectinload(Report.reporter_actor),
            selectinload(Report.target_actor),
        )
        .order_by(Report.created_at.desc())
    )
    if status_filter:
        query = query.where(Report.status == status_filter)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_report_by_id(db: AsyncSession, report_id: uuid.UUID) -> Report | None:
    result = await db.execute(
        select(Report)
        .options(
            selectinload(Report.reporter_actor),
            selectinload(Report.target_actor),
        )
        .where(Report.id == report_id)
    )
    return result.scalar_one_or_none()


async def resolve_report(
    db: AsyncSession, report: Report, moderator: User
) -> Report:
    report.status = "resolved"
    report.resolved_by_id = moderator.id
    report.resolved_at = datetime.now(timezone.utc)
    await db.flush()
    return report


async def reject_report(
    db: AsyncSession, report: Report, moderator: User
) -> Report:
    report.status = "rejected"
    report.resolved_by_id = moderator.id
    report.resolved_at = datetime.now(timezone.utc)
    await db.flush()
    return report
