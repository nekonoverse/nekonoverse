"""お知らせサービス: CRUD、アクティブ一覧、既読化、未読数。"""

import json
import uuid
from datetime import datetime, timezone

import bleach
import markdown
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.announcement import Announcement, AnnouncementDismissal

_ALLOWED_TAGS = [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "br", "hr",
    "strong", "em", "code", "pre", "blockquote",
    "ul", "ol", "li",
    "a",
    "table", "thead", "tbody", "tr", "th", "td",
]


def _render_content(raw: str) -> str:
    """MarkdownコンテンツをサニタイズされたHTMLにレンダリングする。"""
    html = markdown.markdown(raw, extensions=["tables", "fenced_code"])
    return bleach.clean(html, tags=_ALLOWED_TAGS, attributes={"a": ["href"]}, strip=True)


async def create_announcement(
    db: AsyncSession,
    *,
    title: str,
    content: str,
    published: bool = False,
    all_day: bool = False,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> Announcement:
    announcement = Announcement(
        title=title,
        content=content,
        content_html=_render_content(content),
        published=published,
        all_day=all_day,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    db.add(announcement)
    await db.flush()
    return announcement


async def update_announcement(
    db: AsyncSession,
    announcement_id: uuid.UUID,
    **updates: object,
) -> Announcement | None:
    result = await db.execute(
        select(Announcement).where(Announcement.id == announcement_id)
    )
    announcement = result.scalar_one_or_none()
    if not announcement:
        return None

    for key, value in updates.items():
        if value is not None:
            setattr(announcement, key, value)

    # コンテンツが変更された場合はHTMLを再レンダリング
    if "content" in updates and updates["content"] is not None:
        announcement.content_html = _render_content(announcement.content)

    announcement.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return announcement


async def delete_announcement(db: AsyncSession, announcement_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(Announcement).where(Announcement.id == announcement_id)
    )
    announcement = result.scalar_one_or_none()
    if not announcement:
        return False
    await db.delete(announcement)
    await db.flush()
    return True


async def get_announcement(
    db: AsyncSession, announcement_id: uuid.UUID
) -> Announcement | None:
    result = await db.execute(
        select(Announcement).where(Announcement.id == announcement_id)
    )
    return result.scalar_one_or_none()


async def list_announcements_admin(db: AsyncSession) -> list[Announcement]:
    result = await db.execute(
        select(Announcement).order_by(Announcement.created_at.desc())
    )
    return list(result.scalars().all())


def _active_filter() -> list:
    """アクティブなお知らせ用のSQLAlchemyフィルタ条件を返す。"""
    now = datetime.now(timezone.utc)
    return [
        Announcement.published.is_(True),
        or_(Announcement.starts_at.is_(None), Announcement.starts_at <= now),
        or_(Announcement.ends_at.is_(None), Announcement.ends_at > now),
    ]


async def list_active_announcements(db: AsyncSession) -> list[Announcement]:
    result = await db.execute(
        select(Announcement)
        .where(and_(*_active_filter()))
        .order_by(Announcement.created_at.desc())
    )
    return list(result.scalars().all())


async def dismiss_announcement(
    db: AsyncSession, announcement_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    stmt = (
        pg_insert(AnnouncementDismissal)
        .values(
            announcement_id=announcement_id,
            user_id=user_id,
        )
        .on_conflict_do_nothing(constraint="uq_announcement_dismissal")
    )
    await db.execute(stmt)
    await db.flush()
    return True


async def get_dismissed_ids(
    db: AsyncSession, user_id: uuid.UUID
) -> set[uuid.UUID]:
    result = await db.execute(
        select(AnnouncementDismissal.announcement_id).where(
            AnnouncementDismissal.user_id == user_id
        )
    )
    return set(result.scalars().all())


async def get_unread_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    dismissed_subq = (
        select(AnnouncementDismissal.announcement_id)
        .where(AnnouncementDismissal.user_id == user_id)
        .scalar_subquery()
    )
    result = await db.execute(
        select(func.count())
        .select_from(Announcement)
        .where(
            and_(
                *_active_filter(),
                Announcement.id.not_in(dismissed_subq),
            )
        )
    )
    return result.scalar_one()


async def publish_announcement_event(announcement: Announcement) -> None:
    """SSE用にお知らせイベントをValkeyにパブリッシュする。"""
    from app.valkey_client import valkey as valkey_client

    event = json.dumps({
        "event": "announcement",
        "payload": json.dumps({
            "id": str(announcement.id),
            "content": announcement.content_html,
            "starts_at": announcement.starts_at.isoformat() if announcement.starts_at else None,
            "ends_at": announcement.ends_at.isoformat() if announcement.ends_at else None,
            "all_day": announcement.all_day,
            "published_at": announcement.created_at.isoformat(),
            "updated_at": announcement.updated_at.isoformat(),
        }),
    })
    await valkey_client.publish("announcements", event)
