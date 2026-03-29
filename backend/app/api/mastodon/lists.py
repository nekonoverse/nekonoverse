"""Mastodon 互換リスト API エンドポイント。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, require_oauth_scope
from app.models.user import User
from app.schemas.list import (
    ListCreateRequest,
    ListMemberAddRequest,
    ListUpdateRequest,
)
from app.services.list_service import (
    add_list_member,
    create_list,
    delete_list,
    get_list,
    get_user_lists,
    remove_list_member,
    update_list,
)

router = APIRouter(prefix="/api/v1/lists", tags=["lists"])


def _list_response(lst) -> dict:
    return {
        "id": str(lst.id),
        "title": lst.title,
        "replies_policy": lst.replies_policy,
        "exclusive": lst.exclusive,
    }


async def _get_owned_list(db: AsyncSession, list_id: uuid.UUID, user: User):
    """リストを取得し所有権を確認する。未検出または所有していない場合は 404 を返す。"""
    lst = await get_list(db, list_id)
    if not lst or lst.user_id != user.id:
        raise HTTPException(status_code=404, detail="List not found")
    return lst


@router.get(
    "",
    dependencies=[Depends(require_oauth_scope("read:lists"))],
)
async def get_lists(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lists = await get_user_lists(db, user.id)
    return [_list_response(lst) for lst in lists]


@router.post(
    "",
    dependencies=[Depends(require_oauth_scope("write:lists"))],
)
async def create_list_endpoint(
    body: ListCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lst = await create_list(
        db,
        user,
        title=body.title,
        replies_policy=body.replies_policy,
        exclusive=body.exclusive,
    )
    await db.commit()
    return _list_response(lst)


@router.get("/{list_id}")
async def get_list_endpoint(
    list_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lst = await _get_owned_list(db, list_id, user)
    return _list_response(lst)


@router.put(
    "/{list_id}",
    dependencies=[Depends(require_oauth_scope("write:lists"))],
)
async def update_list_endpoint(
    list_id: uuid.UUID,
    body: ListUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lst = await _get_owned_list(db, list_id, user)
    lst = await update_list(
        db,
        lst,
        title=body.title,
        replies_policy=body.replies_policy,
        exclusive=body.exclusive,
    )
    await db.commit()
    return _list_response(lst)


@router.delete(
    "/{list_id}",
    dependencies=[Depends(require_oauth_scope("write:lists"))],
)
async def delete_list_endpoint(
    list_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lst = await _get_owned_list(db, list_id, user)
    await delete_list(db, lst)
    await db.commit()
    return {}


@router.get("/{list_id}/accounts")
async def get_list_accounts(
    list_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lst = await _get_owned_list(db, list_id, user)
    from sqlalchemy import select as sel

    from app.api.mastodon.accounts import _actor_to_account
    from app.models.actor import Actor
    from app.models.list import ListMember

    result = await db.execute(
        sel(Actor)
        .join(ListMember, ListMember.actor_id == Actor.id)
        .where(ListMember.list_id == lst.id)
    )
    actors = result.scalars().all()
    return [await _actor_to_account(a, db=db) for a in actors]


@router.post(
    "/{list_id}/accounts",
    dependencies=[Depends(require_oauth_scope("write:lists"))],
)
async def add_list_accounts(
    list_id: uuid.UUID,
    body: ListMemberAddRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lst = await _get_owned_list(db, list_id, user)
    from sqlalchemy import select as sel

    from app.models.actor import Actor

    # L-1: 不正UUIDに対して422エラーを返す
    for account_id in body.account_ids:
        try:
            uuid.UUID(account_id)
        except (ValueError, AttributeError):
            raise HTTPException(status_code=422, detail=f"Invalid account ID: {account_id}")
    for account_id in body.account_ids:
        aid = uuid.UUID(account_id)
        result = await db.execute(sel(Actor).where(Actor.id == aid))
        actor = result.scalar_one_or_none()
        if actor:
            await add_list_member(db, lst, actor)
    await db.commit()
    return {}


@router.delete(
    "/{list_id}/accounts",
    dependencies=[Depends(require_oauth_scope("write:lists"))],
)
async def remove_list_accounts(
    list_id: uuid.UUID,
    body: ListMemberAddRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lst = await _get_owned_list(db, list_id, user)
    from sqlalchemy import select as sel

    from app.models.actor import Actor

    # L-1: 不正UUIDに対して422エラーを返す
    for account_id in body.account_ids:
        try:
            uuid.UUID(account_id)
        except (ValueError, AttributeError):
            raise HTTPException(status_code=422, detail=f"Invalid account ID: {account_id}")
    for account_id in body.account_ids:
        aid = uuid.UUID(account_id)
        result = await db.execute(sel(Actor).where(Actor.id == aid))
        actor = result.scalar_one_or_none()
        if actor:
            await remove_list_member(db, lst, actor)
    await db.commit()
    return {}
