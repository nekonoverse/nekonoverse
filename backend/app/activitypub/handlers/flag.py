"""受信した Flag (通報) activity を処理する。"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.actor_service import fetch_remote_actor, get_actor_by_ap_id
from app.services.note_service import get_note_by_ap_id

logger = logging.getLogger(__name__)


async def handle_flag(db: AsyncSession, activity: dict):
    """Flag activity を処理する -- リモートサーバーからの通報を作成する。"""
    actor_ap_id = activity.get("actor")
    if not actor_ap_id:
        return

    # 通報者アクターを解決
    reporter = await get_actor_by_ap_id(db, actor_ap_id)
    if not reporter:
        reporter = await fetch_remote_actor(db, actor_ap_id)
    if not reporter:
        logger.warning("Could not resolve reporter actor %s", actor_ap_id)
        return

    # ターゲットを特定
    obj = activity.get("object")
    target_ap_ids = []
    if isinstance(obj, str):
        target_ap_ids = [obj]
    elif isinstance(obj, list):
        target_ap_ids = [o for o in obj if isinstance(o, str)]

    if not target_ap_ids:
        return

    # 最初のターゲットは通報対象のアクターであるべき
    target_actor = await get_actor_by_ap_id(db, target_ap_ids[0])
    if not target_actor:
        logger.info("Flag target actor not found: %s", target_ap_ids[0])
        return

    # 残りのターゲットにノートがあるかチェック
    target_note = None
    for ap_id in target_ap_ids[1:]:
        note = await get_note_by_ap_id(db, ap_id)
        if note:
            target_note = note
            break

    comment = activity.get("content", "")

    from app.services.report_service import create_report

    await create_report(
        db,
        reporter_actor=reporter,
        target_actor=target_actor,
        target_note=target_note,
        comment=comment,
        ap_id=activity.get("id"),
    )
    await db.commit()

    logger.info("Report received from %s about %s", actor_ap_id, target_ap_ids[0])
