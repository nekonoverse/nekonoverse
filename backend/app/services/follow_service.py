import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.actor import Actor
from app.models.follow import Follow
from app.models.user import User
from app.services.actor_service import actor_uri
from app.services.delivery_service import enqueue_delivery


async def _invalidate_follow_counts(*actor_ids: uuid.UUID) -> None:
    """指定されたアクターのフォロー数キャッシュを無効化する。"""
    from app.valkey_client import valkey

    try:
        keys = [f"perf:follow_counts:{aid}" for aid in actor_ids]
        await valkey.delete(*keys)
    except Exception:
        pass


async def follow_actor(db: AsyncSession, user: User, target_actor: Actor) -> Follow:
    """ローカルユーザーからターゲットアクターへのフォローリクエストを作成する。"""
    actor = user.actor

    # 既にフォロー済みか確認
    existing = await db.execute(
        select(Follow).where(
            Follow.follower_id == actor.id,
            Follow.following_id == target_actor.id,
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("Already following")

    follow_id = uuid.uuid4()
    ap_id = f"{settings.server_url}/activities/{follow_id}"

    # ロックアカウントへのローカルフォローはペンディング状態にする
    auto_accept = target_actor.is_local and not target_actor.manually_approves_followers

    follow = Follow(
        id=follow_id,
        ap_id=ap_id,
        follower_id=actor.id,
        following_id=target_actor.id,
        accepted=auto_accept,
    )
    db.add(follow)
    await db.commit()

    await _invalidate_follow_counts(actor.id, target_actor.id)

    # ローカルターゲットにフォロー通知を送信
    if target_actor.is_local:
        from app.services.notification_service import create_notification, publish_notification

        notif_type = "follow" if auto_accept else "follow_request"
        notif = await create_notification(db, notif_type, target_actor.id, actor.id)
        await db.commit()
        if notif:
            await publish_notification(notif)

    # リモートサーバーに Follow Activity を送信
    if not target_actor.is_local:
        from app.activitypub.renderer import render_follow_activity

        activity = render_follow_activity(ap_id, actor_uri(actor), target_actor.ap_id)
        await enqueue_delivery(db, actor.id, target_actor.inbox_url, activity)

    return follow


async def unfollow_actor(db: AsyncSession, user: User, target_actor: Actor):
    """ターゲットアクターのフォローを解除する。"""
    actor = user.actor

    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == actor.id,
            Follow.following_id == target_actor.id,
        )
    )
    follow = result.scalar_one_or_none()
    if not follow:
        raise ValueError("Not following")

    await db.delete(follow)
    await db.commit()

    await _invalidate_follow_counts(actor.id, target_actor.id)

    # リモートサーバーに Undo(Follow) を送信
    if not target_actor.is_local:
        from app.activitypub.renderer import render_follow_activity, render_undo_activity

        follow_activity = render_follow_activity(
            follow.ap_id or f"{settings.server_url}/activities/{uuid.uuid4()}",
            actor_uri(actor),
            target_actor.ap_id,
        )
        undo_id = f"{settings.server_url}/activities/{uuid.uuid4()}"
        undo_activity = render_undo_activity(undo_id, actor_uri(actor), follow_activity)
        await enqueue_delivery(db, actor.id, target_actor.inbox_url, undo_activity)


async def get_follower_ids(db: AsyncSession, actor_id: uuid.UUID) -> list[uuid.UUID]:
    """指定アクターをフォローしているアクターのIDを取得する (承認済みフォローのみ)。"""
    result = await db.execute(
        select(Follow.follower_id).where(
            Follow.following_id == actor_id,
            Follow.accepted.is_(True),
        )
    )
    return list(result.scalars().all())


async def get_following_ids(db: AsyncSession, actor_id: uuid.UUID) -> list[uuid.UUID]:
    """指定アクターがフォローしているアクターのIDを取得する (承認済みフォローのみ)。"""
    result = await db.execute(
        select(Follow.following_id).where(
            Follow.follower_id == actor_id,
            Follow.accepted.is_(True),
        )
    )
    return list(result.scalars().all())


async def get_followers(db: AsyncSession, actor_id: uuid.UUID, limit: int = 40) -> list[Actor]:
    """指定アクターをフォローしているアクターを取得する (承認済みフォローのみ)。"""
    result = await db.execute(
        select(Actor)
        .join(Follow, Follow.follower_id == Actor.id)
        .where(Follow.following_id == actor_id, Follow.accepted.is_(True))
        .order_by(Follow.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_following(db: AsyncSession, actor_id: uuid.UUID, limit: int = 40) -> list[Actor]:
    """指定アクターがフォローしているアクターを取得する (承認済みフォローのみ)。"""
    result = await db.execute(
        select(Actor)
        .join(Follow, Follow.following_id == Actor.id)
        .where(Follow.follower_id == actor_id, Follow.accepted.is_(True))
        .order_by(Follow.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_follow_counts(db: AsyncSession, actor_id: uuid.UUID) -> tuple[int, int]:
    """指定アクターの (followers_count, following_count) を返す。

    Valkey で5分間キャッシュされる。
    """
    import json

    from app.valkey_client import valkey

    cache_key = f"perf:follow_counts:{actor_id}"
    try:
        cached = await valkey.get(cache_key)
        if cached:
            data = json.loads(cached)
            return data[0], data[1]
    except Exception:
        pass

    from sqlalchemy import func

    followers = await db.execute(
        select(func.count())
        .select_from(Follow)
        .where(Follow.following_id == actor_id, Follow.accepted.is_(True))
    )
    following = await db.execute(
        select(func.count())
        .select_from(Follow)
        .where(Follow.follower_id == actor_id, Follow.accepted.is_(True))
    )
    fc = followers.scalar() or 0
    fic = following.scalar() or 0

    try:
        await valkey.set(cache_key, json.dumps([fc, fic]), ex=300)
    except Exception:
        pass

    return fc, fic


async def get_follower_inboxes(db: AsyncSession, actor_id: uuid.UUID) -> list[str]:
    """アクターの全フォロワーの一意な inbox URL を取得する (配送用)。"""
    result = await db.execute(
        select(Actor.shared_inbox_url, Actor.inbox_url)
        .join(Follow, Follow.follower_id == Actor.id)
        .where(Follow.following_id == actor_id, Follow.accepted.is_(True))
    )

    inboxes = set()
    for shared_inbox, inbox in result.all():
        # 効率のため shared inbox を優先
        inboxes.add(shared_inbox or inbox)
    return list(inboxes)
