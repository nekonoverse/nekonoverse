"""投票サービス: 投票ノートの作成、投票、結果取得。"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note
from app.models.poll_vote import PollVote
from app.models.user import User
from app.services.note_service import get_note_by_id

logger = logging.getLogger(__name__)


async def vote_on_poll(
    db: AsyncSession,
    user: User,
    note_id: uuid.UUID,
    choices: list[int],
) -> None:
    """投票する。入力が無効な場合はValueErrorを送出。"""
    note = await get_note_by_id(db, note_id)
    if not note:
        raise ValueError("Note not found")
    if not note.is_poll:
        raise ValueError("Not a poll")

    options = note.poll_options or []
    if not options:
        raise ValueError("Poll has no options")

    # 期限の確認
    if note.poll_expires_at and note.poll_expires_at < datetime.now(timezone.utc):
        raise ValueError("Poll has expired")

    # 選択肢の検証
    if not note.poll_multiple and len(choices) > 1:
        raise ValueError("Multiple choices not allowed")

    for idx in choices:
        if idx < 0 or idx >= len(options):
            raise ValueError(f"Invalid choice index: {idx}")

    actor = user.actor

    # 既存の投票を確認
    existing = await db.execute(
        select(PollVote).where(
            PollVote.note_id == note_id,
            PollVote.actor_id == actor.id,
        )
    )
    if existing.scalars().first():
        raise ValueError("Already voted")

    # 投票を作成し、カウントを更新
    for idx in choices:
        vote = PollVote(
            note_id=note_id,
            actor_id=actor.id,
            choice_index=idx,
        )
        db.add(vote)

        # poll_options JSONB 内の投票数を更新
        options[idx]["votes_count"] = options[idx].get("votes_count", 0) + 1

    # JSONB の更新検出を強制
    from sqlalchemy.orm.attributes import flag_modified

    note.poll_options = list(options)
    flag_modified(note, "poll_options")
    await db.flush()

    # 投票を連合配信
    try:
        await _federate_vote(db, user, note, choices)
    except Exception:
        logger.debug("Failed to federate vote for %s", note_id, exc_info=True)


async def _federate_vote(
    db: AsyncSession,
    user: User,
    note: Note,
    choices: list[int],
) -> None:
    """投票後に AP Activity を送信する。"""
    actor = user.actor
    options = note.poll_options or []

    if note.local:
        # ローカル投票: 更新されたカウントで Update(Question) をフォロワーに送信
        from app.activitypub.renderer import render_poll_update_activity
        from app.services.delivery_service import enqueue_delivery
        from app.services.follow_service import get_follower_inboxes

        activity = render_poll_update_activity(note)
        inboxes = await get_follower_inboxes(db, actor_id=note.actor_id)
        for inbox_url in inboxes:
            await enqueue_delivery(db, note.actor_id, inbox_url, activity)
    else:
        # リモート投票: Create(Note with name) を投票作成者の inbox に送信
        from app.activitypub.renderer import render_vote_activity
        from app.services.delivery_service import enqueue_delivery

        poll_actor = note.actor
        if not poll_actor or not poll_actor.inbox_url:
            return

        for idx in choices:
            if idx < len(options):
                option_name = options[idx].get("title", "")
                activity = render_vote_activity(note, actor, option_name)
                await enqueue_delivery(db, actor.id, poll_actor.inbox_url, activity)


async def get_poll_data(
    db: AsyncSession,
    note_id: uuid.UUID,
    current_actor_id: uuid.UUID | None = None,
    note: Note | None = None,
) -> dict | None:
    """ノートの投票データを取得する。投票でない場合はNoneを返す。"""
    if note is None:
        note = await get_note_by_id(db, note_id)
    if not note or not note.is_poll:
        return None

    options = note.poll_options or []

    # ローカル投票の場合、PollVote テーブルから投票数を計算する (信頼できる情報源)
    if note.local:
        vote_counts_result = await db.execute(
            select(PollVote.choice_index, func.count(PollVote.id))
            .where(PollVote.note_id == note_id)
            .group_by(PollVote.choice_index)
        )
        vote_counts = dict(vote_counts_result.all())

        response_options = [
            {
                "title": opt.get("title", ""),
                "votes_count": vote_counts.get(i, 0),
            }
            for i, opt in enumerate(options)
        ]
        votes_count = sum(vc for vc in vote_counts.values())
    else:
        # リモート投票: JSONB のカウントを使用 (リモートサーバーが信頼できる情報源)
        response_options = [
            {"title": opt.get("title", ""), "votes_count": opt.get("votes_count", 0)}
            for opt in options
        ]
        votes_count = sum(opt.get("votes_count", 0) for opt in options)

    # ユニーク投票者数をカウント
    voters_result = await db.execute(
        select(func.count(func.distinct(PollVote.actor_id))).where(
            PollVote.note_id == note_id
        )
    )
    voters_count = voters_result.scalar() or 0

    expired = False
    if note.poll_expires_at:
        expired = note.poll_expires_at < datetime.now(timezone.utc)

    own_votes: list[int] = []
    voted = False
    if current_actor_id:
        result = await db.execute(
            select(PollVote.choice_index).where(
                PollVote.note_id == note_id,
                PollVote.actor_id == current_actor_id,
            )
        )
        own_votes = [row[0] for row in result.all()]
        voted = len(own_votes) > 0

    return {
        "id": str(note_id),
        "expires_at": note.poll_expires_at.isoformat() if note.poll_expires_at else None,
        "expired": expired,
        "multiple": note.poll_multiple,
        "votes_count": votes_count,
        "voters_count": voters_count,
        "options": response_options,
        "voted": voted,
        "own_votes": own_votes,
    }
