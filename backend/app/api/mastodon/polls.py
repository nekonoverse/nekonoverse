"""投票 API: 投票データの取得と投票の実行。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_optional_user
from app.models.note import Note
from app.models.user import User

router = APIRouter(prefix="/api/v1/polls", tags=["polls"])


class VoteRequest(BaseModel):
    choices: list[int] = Field(min_length=1)


async def _get_visible_poll_note(db: AsyncSession, note_id: uuid.UUID, user: User | None) -> Note:
    """閲覧権限のある投票ノートを返す。見えない投票は存在しないものとして 404 にする。"""
    from app.services.note_service import check_note_visible, get_note_by_id

    note = await get_note_by_id(db, note_id)
    actor_id = user.actor_id if user else None
    if not note or not note.is_poll or not await check_note_visible(db, note, actor_id):
        raise HTTPException(status_code=404, detail="Poll not found")
    return note


@router.get("/{note_id}")
async def get_poll(
    note_id: uuid.UUID,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.poll_service import get_poll_data

    note = await _get_visible_poll_note(db, note_id, user)
    actor_id = user.actor_id if user else None
    poll = await get_poll_data(db, note_id, actor_id, note=note)
    if not poll:
        raise HTTPException(status_code=404, detail="Poll not found")
    return poll


@router.post("/{note_id}/votes")
async def vote_on_poll(
    note_id: uuid.UUID,
    body: VoteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.poll_service import get_poll_data, vote_on_poll

    await _get_visible_poll_note(db, note_id, user)
    try:
        await vote_on_poll(db, user, note_id, body.choices)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    actor_id = user.actor_id
    poll = await get_poll_data(db, note_id, actor_id)
    return poll
