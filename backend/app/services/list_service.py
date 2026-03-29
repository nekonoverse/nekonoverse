"""ユーザーリストとリストタイムラインの管理サービス。"""

import logging
import uuid

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.actor import Actor
from app.models.list import List, ListMember
from app.models.note import Note
from app.models.user import User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CRUD操作
# ---------------------------------------------------------------------------


async def create_list(
    db: AsyncSession,
    user: User,
    title: str,
    replies_policy: str = "list",
    exclusive: bool = False,
) -> List:
    lst = List(
        user_id=user.id,
        title=title,
        replies_policy=replies_policy,
        exclusive=exclusive,
    )
    db.add(lst)
    await db.flush()
    return lst


async def get_list(db: AsyncSession, list_id: uuid.UUID) -> List | None:
    result = await db.execute(
        select(List)
        .options(selectinload(List.members).selectinload(ListMember.actor))
        .where(List.id == list_id)
    )
    return result.scalar_one_or_none()


async def get_user_lists(db: AsyncSession, user_id: uuid.UUID) -> list[List]:
    result = await db.execute(select(List).where(List.user_id == user_id).order_by(List.created_at))
    return list(result.scalars().all())


_VALID_REPLIES_POLICIES = frozenset({"followed", "list", "none"})


async def update_list(
    db: AsyncSession,
    lst: List,
    *,
    title: str | None = None,
    replies_policy: str | None = None,
    exclusive: bool | None = None,
) -> List:
    if title is not None:
        lst.title = title
    if replies_policy is not None:
        # L-2: サービス層でもreplies_policyを検証
        if replies_policy not in _VALID_REPLIES_POLICIES:
            raise ValueError(
                f"Invalid replies_policy: {replies_policy}. "
                f"Must be one of: {', '.join(sorted(_VALID_REPLIES_POLICIES))}"
            )
        lst.replies_policy = replies_policy
    if exclusive is not None:
        lst.exclusive = exclusive
    await db.flush()
    _invalidate_list_cache(lst.id)
    return lst


async def delete_list(db: AsyncSession, lst: List) -> None:
    list_id = lst.id
    await db.delete(lst)
    await db.flush()
    _invalidate_list_cache(list_id)


# ---------------------------------------------------------------------------
# メンバー管理
# ---------------------------------------------------------------------------


async def add_list_member(
    db: AsyncSession,
    lst: List,
    actor: Actor,
) -> ListMember:
    # 重複チェック
    result = await db.execute(
        select(ListMember).where(
            ListMember.list_id == lst.id,
            ListMember.actor_id == actor.id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    member = ListMember(list_id=lst.id, actor_id=actor.id)
    db.add(member)
    await db.flush()

    # リモートアクターにローカルフォロワーがいない場合、プロキシ購読を開始
    if not actor.is_local:
        from app.services.proxy_service import has_real_local_follower

        if not await has_real_local_follower(db, actor.id):
            from app.services.proxy_service import proxy_subscribe

            await proxy_subscribe(db, actor)

    _invalidate_list_cache(lst.id)
    return member


async def remove_list_member(
    db: AsyncSession,
    lst: List,
    actor: Actor,
) -> None:
    result = await db.execute(
        select(ListMember).where(
            ListMember.list_id == lst.id,
            ListMember.actor_id == actor.id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        return

    await db.delete(member)
    await db.flush()

    # リモートアクターがどのリストにも属さず、ローカルフォロワーもいなければプロキシ購読を解除
    if not actor.is_local:
        if not await is_actor_in_any_list(db, actor.id):
            from app.services.proxy_service import has_real_local_follower

            if not await has_real_local_follower(db, actor.id):
                from app.services.proxy_service import proxy_unsubscribe

                await proxy_unsubscribe(db, actor)

    _invalidate_list_cache(lst.id)


async def get_list_member_ids(db: AsyncSession, list_id: uuid.UUID) -> list[uuid.UUID]:
    result = await db.execute(select(ListMember.actor_id).where(ListMember.list_id == list_id))
    return list(result.scalars().all())


async def is_actor_in_any_list(db: AsyncSession, actor_id: uuid.UUID) -> bool:
    result = await db.execute(select(exists().where(ListMember.actor_id == actor_id)))
    return result.scalar() or False


# ---------------------------------------------------------------------------
# タイムライン
# ---------------------------------------------------------------------------


async def get_list_timeline(
    db: AsyncSession,
    lst: List,
    user: User,
    limit: int = 20,
    max_id: uuid.UUID | None = None,
) -> list[Note]:
    from app.services.note_service import _get_excluded_ids, _note_load_options

    member_ids = await get_list_member_ids(db, lst.id)
    if not member_ids:
        return []

    query = (
        select(Note)
        .options(*_note_load_options())
        .where(
            Note.actor_id.in_(member_ids),
            Note.deleted_at.is_(None),
            Note.visibility.in_(["public", "unlisted", "followers"]),
        )
    )

    # replies_policy filter
    if lst.replies_policy == "none":
        query = query.where(Note.in_reply_to_id.is_(None))
    elif lst.replies_policy == "list":
        # 非リプライ、またはリストメンバーのノートへのリプライのみ許可
        member_note_ids = select(Note.id).where(Note.actor_id.in_(member_ids))
        query = query.where(
            or_(
                Note.in_reply_to_id.is_(None),
                Note.in_reply_to_id.in_(member_note_ids),
            )
        )
    elif lst.replies_policy == "followed":
        # 非リプライ、またはリストオーナーがフォロー中のユーザーのノートへのリプライのみ許可
        from app.services.follow_service import get_following_ids

        following_ids = await get_following_ids(db, user.actor_id)
        following_ids.append(user.actor_id)
        reply_target_note_ids = select(Note.id).where(Note.actor_id.in_(following_ids))
        query = query.where(
            or_(
                Note.in_reply_to_id.is_(None),
                Note.in_reply_to_id.in_(reply_target_note_ids),
            )
        )

    # ブロック・ミュート済みを除外
    excluded = await _get_excluded_ids(db, user.actor_id)
    if excluded:
        query = query.where(Note.actor_id.not_in(excluded))

    # カーソルページネーション
    if max_id:
        sub = select(Note.published).where(Note.id == max_id).scalar_subquery()
        query = query.where(Note.published < sub)

    query = query.order_by(Note.published.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# 排他リスト + ストリーミング用ヘルパー
# ---------------------------------------------------------------------------


async def get_exclusive_list_actor_ids(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """排他リストに含まれるアクターIDを取得（ホームTLからの除外用）。"""
    result = await db.execute(
        select(ListMember.actor_id)
        .join(List, ListMember.list_id == List.id)
        .where(List.user_id == user_id, List.exclusive.is_(True))
    )
    return set(result.scalars().all())


async def get_list_ids_for_actor(db: AsyncSession, actor_id: uuid.UUID) -> list[uuid.UUID]:
    """指定アクターが所属する全リストIDを取得（ストリーミング配信用）。"""
    result = await db.execute(select(ListMember.list_id).where(ListMember.actor_id == actor_id))
    return list(result.scalars().all())


async def get_user_lists_for_actor(
    db: AsyncSession, user_id: uuid.UUID, actor_id: uuid.UUID
) -> list[List]:
    """user_idが所有するリストのうち、actor_idが所属するものを取得。"""
    result = await db.execute(
        select(List)
        .join(ListMember, List.id == ListMember.list_id)
        .where(List.user_id == user_id, ListMember.actor_id == actor_id)
        .order_by(List.created_at)
    )
    return list(result.scalars().all())


async def get_exclusive_list_user_actor_ids(
    db: AsyncSession, member_actor_id: uuid.UUID
) -> set[uuid.UUID]:
    """このアクターを排他リストに含むユーザーのactor_idを取得。

    これらのユーザーにはホームタイムラインSSEでこのアクターのノートを配信しない。
    """
    result = await db.execute(
        select(User.actor_id)
        .join(List, List.user_id == User.id)
        .join(ListMember, ListMember.list_id == List.id)
        .where(
            ListMember.actor_id == member_actor_id,
            List.exclusive.is_(True),
        )
    )
    return set(result.scalars().all())


# ---------------------------------------------------------------------------
# キャッシュ無効化（Valkey TTLキャッシュ用プレースホルダー）
# ---------------------------------------------------------------------------


def _invalidate_list_cache(list_id: uuid.UUID) -> None:
    """リスト関連のキャッシュを無効化する。現在はno-opプレースホルダー。"""
    pass
