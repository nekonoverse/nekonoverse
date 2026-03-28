"""通知サービス: 作成、一覧取得、既読化、全消去。"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.note import Note
from app.models.notification import Notification


async def create_notification(
    db: AsyncSession,
    type: str,
    recipient_id: uuid.UUID,
    sender_id: uuid.UUID | None = None,
    note_id: uuid.UUID | None = None,
    reaction_emoji: str | None = None,
) -> Notification | None:
    """通知を作成する。自己通知、ブロック、ミュートの場合はNoneを返す。"""
    # 自分自身には通知しない
    if sender_id and recipient_id == sender_id:
        return None

    # 受信者が送信者をブロックまたはミュートしているか確認
    if sender_id:
        from app.services.block_service import is_blocking
        from app.services.mute_service import is_muting

        if await is_blocking(db, recipient_id, sender_id):
            return None
        if await is_muting(db, recipient_id, sender_id):
            return None

    # 重複排除: 同一の通知が既に存在する場合はスキップ (既読・未読問わず)
    dedup_filters = [
        Notification.type == type,
        Notification.recipient_id == recipient_id,
    ]
    if sender_id:
        dedup_filters.append(Notification.sender_id == sender_id)
    if note_id:
        dedup_filters.append(Notification.note_id == note_id)
    if reaction_emoji:
        dedup_filters.append(Notification.reaction_emoji == reaction_emoji)
    existing = await db.execute(select(Notification).where(*dedup_filters).limit(1))
    if existing.scalar_one_or_none():
        return None

    notification = Notification(
        type=type,
        recipient_id=recipient_id,
        sender_id=sender_id,
        note_id=note_id,
        reaction_emoji=reaction_emoji,
    )
    db.add(notification)
    await db.flush()

    # Web Push通知を送信 (flush後で問題ない — push通知はDBクエリしない)
    try:
        from app.services.push_service import send_web_push

        sender_name = None
        if sender_id:
            from app.models.actor import Actor

            result = await db.execute(
                select(Actor).where(Actor.id == sender_id)
            )
            sender = result.scalar_one_or_none()
            if sender:
                sender_name = sender.display_name or sender.preferred_username

        await send_web_push(
            db=db,
            recipient_id=recipient_id,
            notification_type=type,
            sender_display_name=sender_name,
            notification_id=str(notification.id),
            sender_id=sender_id,
        )
    except Exception:
        pass  # プッシュ失敗で通知作成を失敗させない

    return notification


async def publish_notification(notification: Notification) -> None:
    """通知イベントをValkeyにパブリッシュする。db.commit()の後に呼び出すこと。"""
    try:
        import json

        from app.valkey_client import valkey

        event = json.dumps(
            {
                "event": "notification",
                "payload": {
                    "id": str(notification.id),
                    "type": notification.type,
                },
            }
        )
        await valkey.publish(f"notifications:{notification.recipient_id}", event)
    except Exception:
        pass


async def get_notifications(
    db: AsyncSession,
    actor_id: uuid.UUID,
    limit: int = 20,
    max_id: uuid.UUID | None = None,
    types: list[str] | None = None,
) -> list[Notification]:
    query = (
        select(Notification)
        .options(
            selectinload(Notification.sender),
            selectinload(Notification.note).selectinload(Note.actor),
        )
        .where(Notification.recipient_id == actor_id)
    )
    if types:
        query = query.where(Notification.type.in_(types))
    if max_id:
        sub = select(Notification.created_at).where(Notification.id == max_id).scalar_subquery()
        query = query.where(Notification.created_at < sub)
    query = query.order_by(Notification.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def mark_as_read(db: AsyncSession, notification_id: uuid.UUID, actor_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.recipient_id == actor_id,
        )
    )
    notif = result.scalar_one_or_none()
    if not notif:
        return False
    notif.read = True
    await db.flush()
    return True


async def mark_all_as_read(db: AsyncSession, actor_id: uuid.UUID) -> None:
    await db.execute(
        update(Notification)
        .where(Notification.recipient_id == actor_id, Notification.read.is_(False))
        .values(read=True)
    )
    await db.flush()


async def clear_notifications(db: AsyncSession, actor_id: uuid.UUID) -> None:
    from sqlalchemy import delete

    await db.execute(delete(Notification).where(Notification.recipient_id == actor_id))
    await db.flush()


async def get_unread_count(db: AsyncSession, actor_id: uuid.UUID) -> dict[str, int]:
    """未読通知数を返す: 合計、メンション、その他。"""
    total_q = (
        select(func.count())
        .select_from(Notification)
        .where(Notification.recipient_id == actor_id, Notification.read.is_(False))
    )
    total = (await db.execute(total_q)).scalar() or 0

    mentions_q = (
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.recipient_id == actor_id,
            Notification.read.is_(False),
            Notification.type.in_(["mention", "reply"]),
        )
    )
    mentions = (await db.execute(mentions_q)).scalar() or 0

    return {"total": total, "mentions": mentions, "other": total - mentions}
