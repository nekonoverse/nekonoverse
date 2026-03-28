"""Update activity を処理する (Person プロフィール更新、ノート編集)。"""

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.activitypub import extract_mfm_source
from app.services.actor_service import get_actor_by_ap_id, upsert_remote_actor
from app.services.note_service import get_note_by_ap_id
from app.utils.sanitize import sanitize_html

logger = logging.getLogger(__name__)


async def handle_update(db: AsyncSession, activity: dict):
    actor_ap_id = activity.get("actor")
    if not actor_ap_id:
        return

    obj = activity.get("object")
    if not isinstance(obj, dict):
        return

    obj_type = obj.get("type")

    if obj_type in ("Person", "Service", "Application", "Group", "Organization"):
        await _update_actor(db, actor_ap_id, obj)
    elif obj_type in ("Note", "Question"):
        await _update_note(db, actor_ap_id, obj)
    else:
        logger.info("Unhandled Update object type: %s", obj_type)


async def _update_actor(db: AsyncSession, actor_ap_id: str, data: dict):
    # 更新を行うアクターと更新対象のアクターが同一であることを検証
    obj_id = data.get("id")
    if obj_id != actor_ap_id:
        logger.warning("Update actor mismatch: actor=%s object.id=%s", actor_ap_id, obj_id)
        return

    await upsert_remote_actor(db, data)
    logger.info("Updated remote actor %s", actor_ap_id)


async def _update_note(db: AsyncSession, actor_ap_id: str, data: dict):
    ap_id = data.get("id")
    if not ap_id:
        return

    note = await get_note_by_ap_id(db, ap_id)
    if not note:
        logger.info("Update for unknown note %s, skipping", ap_id)
        return

    # 所有権を検証
    actor = await get_actor_by_ap_id(db, actor_ap_id)
    if not actor or note.actor_id != actor.id:
        logger.warning("Update note denied: actor %s does not own note %s", actor_ap_id, ap_id)
        return

    # コンテンツの変更を検出
    new_content = data.get("content")
    new_sanitized = sanitize_html(new_content) if new_content else None
    new_source = extract_mfm_source(data)
    new_spoiler = data.get("summary", note.spoiler_text)

    content_changed = (
        (new_sanitized is not None and new_sanitized != note.content)
        or (new_source is not None and new_source != note.source)
        or new_spoiler != note.spoiler_text
    )

    # 実際にコンテンツが変更された場合のみ編集履歴を作成 (投票の得票数更新だけでは作成しない)
    if content_changed:
        from app.models.note_edit import NoteEdit

        edit_record = NoteEdit(
            note_id=note.id,
            content=note.content,
            source=note.source,
            spoiler_text=note.spoiler_text,
        )
        db.add(edit_record)

        if new_sanitized:
            note.content = new_sanitized
        if new_source is not None:
            note.source = new_source
        note.spoiler_text = new_spoiler
        note.sensitive = data.get("sensitive", note.sensitive)
        note.updated_at = datetime.now(timezone.utc)

    # Question タイプの場合は投票データを更新
    if data.get("type") == "Question" and note.is_poll:
        one_of = data.get("oneOf")
        any_of = data.get("anyOf")
        choices = any_of or one_of or []
        if choices:
            poll_options = []
            for choice in choices:
                if isinstance(choice, dict):
                    title = choice.get("name", "")
                    replies = choice.get("replies", {})
                    votes = replies.get("totalItems", 0) if isinstance(replies, dict) else 0
                    poll_options.append({"title": title, "votes_count": votes})
            note.poll_options = poll_options
            from sqlalchemy.orm.attributes import flag_modified

            flag_modified(note, "poll_options")

    await db.commit()
    logger.info("Updated remote note %s", ap_id)
