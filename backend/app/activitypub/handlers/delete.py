"""Delete activity を処理する。"""

import logging
from datetime import datetime, timezone

from sqlalchemy import delete as sa_delete
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.actor_service import get_actor_by_ap_id
from app.services.note_service import get_note_by_ap_id

logger = logging.getLogger(__name__)

# Delete(Person) 判定に使う AP タイプ
_PERSON_TYPES = {"Person", "Service", "Group", "Organization", "Application"}


async def handle_delete(db: AsyncSession, activity: dict):
    actor_ap_id = activity.get("actor")
    obj = activity.get("object")

    if not actor_ap_id:
        return

    # オブジェクトは文字列 (ID) または Tombstone/Person dict のどちらかを取る
    if isinstance(obj, dict):
        object_id = obj.get("id")
        object_type = obj.get("type")
    elif isinstance(obj, str):
        object_id = obj
        object_type = None
    else:
        return

    if not object_id:
        return

    # Delete(Person): actor 自身の削除、またはオブジェクトが Person 系
    if object_id == actor_ap_id or object_type in _PERSON_TYPES:
        await _handle_delete_actor(db, actor_ap_id)
        return

    # アクターがオブジェクトの所有者であることを検証
    actor = await get_actor_by_ap_id(db, actor_ap_id)
    if not actor:
        return

    note = await get_note_by_ap_id(db, object_id)
    if not note:
        return

    if note.actor_id != actor.id:
        logger.warning("Delete denied: actor %s does not own note %s", actor_ap_id, object_id)
        return

    note.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("Deleted note %s by %s", object_id, actor_ap_id)

    # 検索インデックスから削除
    if settings.neko_search_enabled:
        from app.services.search_queue import enqueue_delete

        await enqueue_delete(note.id)


async def _handle_delete_actor(db: AsyncSession, actor_ap_id: str) -> None:
    """リモートアクターの Delete(Person) を処理する。

    ローカルアクターの削除はこのハンドラーでは行わない（ローカル削除は
    account_deletion_service 経由で処理する）。
    """
    from app.models.follow import Follow
    from app.models.note import Note
    from app.models.notification import Notification
    from app.models.reaction import Reaction

    actor = await get_actor_by_ap_id(db, actor_ap_id)
    if not actor:
        logger.debug("Delete(Person) ignored: unknown actor %s", actor_ap_id)
        return

    # ローカルアクターの削除はリモートから受け取らない
    if actor.domain is None:
        logger.warning("Delete(Person) ignored: local actor %s", actor_ap_id)
        return

    if actor.is_deleted:
        logger.debug("Delete(Person) ignored: already deleted %s", actor_ap_id)
        return

    now = datetime.now(timezone.utc)

    # 全ノートを論理削除
    await db.execute(
        update(Note)
        .where(Note.actor_id == actor.id, Note.deleted_at.is_(None))
        .values(deleted_at=now)
    )

    # フォロー関係をクリア
    await db.execute(
        sa_delete(Follow).where(
            (Follow.follower_id == actor.id) | (Follow.following_id == actor.id)
        )
    )

    # リアクションを削除
    await db.execute(sa_delete(Reaction).where(Reaction.actor_id == actor.id))

    # 通知を削除
    await db.execute(sa_delete(Notification).where(Notification.sender_id == actor.id))

    # アクターを削除済みにする
    actor.deleted_at = now
    actor.display_name = None
    actor.summary = None
    actor.avatar_url = None
    actor.header_url = None

    await db.commit()
    logger.info("Processed Delete(Person) for remote actor %s", actor_ap_id)
