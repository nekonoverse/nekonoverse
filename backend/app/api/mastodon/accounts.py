import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_optional_user
from app.models.actor import Actor
from app.models.follow import Follow
from app.models.note import Note
from app.models.user import User
from app.services.follow_service import follow_actor, get_follow_counts, unfollow_actor
from app.utils.media_proxy import media_proxy_url

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])
relationships_router = APIRouter(prefix="/api/v1", tags=["relationships"])


@router.post("/{actor_id}/follow")
async def follow(
    actor_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Actor not found")

    if target.id == user.actor_id:
        raise HTTPException(status_code=422, detail="Cannot follow yourself")

    try:
        await follow_actor(db, user, target)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True}


@router.post("/{actor_id}/unfollow")
async def unfollow(
    actor_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Actor not found")

    try:
        await unfollow_actor(db, user, target)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True}


@router.get("/lookup")
async def lookup_account(
    acct: str,
    db: AsyncSession = Depends(get_db),
):
    """Lookup an account by acct URI (user@domain). Resolves remote actors via WebFinger."""
    if "@" in acct:
        username, domain = acct.split("@", 1)
    else:
        username = acct
        domain = None

    from app.services.actor_service import get_actor_by_username

    actor = await get_actor_by_username(db, username, domain)

    # If not found locally and it's a remote acct, resolve via WebFinger
    if not actor and domain:
        from app.services.actor_service import resolve_webfinger

        actor = await resolve_webfinger(db, username, domain)

    if not actor:
        raise HTTPException(status_code=404, detail="Account not found")

    fc, fic = await get_follow_counts(db, actor.id)
    return await _actor_to_account(actor, followers_count=fc, following_count=fic, db=db)


@router.get("/search")
async def search_accounts(
    q: str,
    resolve: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Search for accounts. If resolve=true and q looks like user@domain, resolve via WebFinger."""
    acct = q.lstrip("@")

    if "@" in acct:
        username, domain = acct.split("@", 1)
    else:
        username = acct
        domain = None

    from app.services.actor_service import get_actor_by_username

    actor = await get_actor_by_username(db, username, domain)

    if not actor and domain and resolve:
        from app.services.actor_service import resolve_webfinger

        actor = await resolve_webfinger(db, username, domain)

    if not actor:
        return []

    return [await _actor_to_account(actor, db=db)]


async def _actor_to_account(
    actor: Actor,
    followers_count: int | None = None,
    following_count: int | None = None,
    db: AsyncSession | None = None,
) -> dict:
    import re

    data = {
        "id": str(actor.id),
        "username": actor.username,
        "acct": f"{actor.username}@{actor.domain}" if actor.domain else actor.username,
        "display_name": actor.display_name,
        "note": actor.summary or "",
        "avatar": media_proxy_url(actor.avatar_url) or "/default-avatar.svg",
        "header": media_proxy_url(actor.header_url),
        "url": actor.ap_id,
        "created_at": actor.created_at.isoformat() if actor.created_at else None,
        "bot": getattr(actor, "is_bot", False) or actor.type == "Service",
        "locked": actor.manually_approves_followers,
        "discoverable": actor.discoverable,
        "fields": [
            {"name": f.get("name", ""), "value": f.get("value", ""), "verified_at": None}
            for f in (actor.fields or [])
        ],
        "emojis": [],
    }
    if followers_count is not None:
        data["followers_count"] = followers_count
    if following_count is not None:
        data["following_count"] = following_count

    # Resolve custom emoji from display_name, summary, and fields
    if db:
        shortcode_re = re.compile(r":([a-zA-Z0-9_]+):")
        texts = [data["display_name"] or "", data["note"]]
        for f in actor.fields or []:
            texts.append(f.get("name", ""))
            texts.append(f.get("value", ""))
        shortcodes = set()
        for text in texts:
            shortcodes.update(shortcode_re.findall(text))
        if shortcodes:
            from app.services.emoji_service import get_emojis_by_shortcodes

            emoji_list = await get_emojis_by_shortcodes(db, shortcodes, actor.domain)
            if actor.domain is not None:
                found = {e.shortcode for e in emoji_list}
                missing = shortcodes - found
                if missing:
                    local_emojis = await get_emojis_by_shortcodes(db, missing, None)
                    emoji_list.extend(local_emojis)
            data["emojis"] = [
                {
                    "shortcode": e.shortcode,
                    "url": media_proxy_url(e.url),
                    "static_url": media_proxy_url(e.static_url)
                    if e.static_url
                    else media_proxy_url(e.url),
                }
                for e in emoji_list
            ]

    return data


def _actor_to_limited_account(actor: Actor) -> dict:
    """Return minimal account info for actors with require_signin_to_view."""
    return {
        "id": str(actor.id),
        "username": actor.username,
        "acct": f"{actor.username}@{actor.domain}" if actor.domain else actor.username,
        "display_name": actor.display_name,
        "note": "",
        "avatar": "/default-avatar.svg",
        "header": "",
        "url": actor.ap_id,
        "created_at": actor.created_at.isoformat() if actor.created_at else None,
        "bot": getattr(actor, "is_bot", False) or actor.type == "Service",
        "locked": actor.manually_approves_followers,
        "discoverable": actor.discoverable,
        "fields": [],
        "limited": True,
    }


@router.post("/{actor_id}/block")
async def block_account(
    actor_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.block_service import block_actor

    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Actor not found")
    if target.id == user.actor_id:
        raise HTTPException(status_code=422, detail="Cannot block yourself")

    try:
        await block_actor(db, user, target)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True}


@router.post("/{actor_id}/unblock")
async def unblock_account(
    actor_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.block_service import unblock_actor

    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Actor not found")

    try:
        await unblock_actor(db, user, target)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True}


@router.post("/{actor_id}/mute")
async def mute_account(
    actor_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.mute_service import mute_actor

    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Actor not found")
    if target.id == user.actor_id:
        raise HTTPException(status_code=422, detail="Cannot mute yourself")

    try:
        await mute_actor(db, user, target)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True}


@router.post("/{actor_id}/unmute")
async def unmute_account(
    actor_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.mute_service import unmute_actor

    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Actor not found")

    try:
        await unmute_actor(db, user, target)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True}


@router.get("/{actor_id}/statuses")
async def get_account_statuses(
    actor_id: uuid.UUID,
    limit: int = 20,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    actor = result.scalar_one_or_none()
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    # Respect Misskey require_signin_to_view
    if actor.require_signin_to_view and not user:
        return []

    from datetime import datetime, timezone

    from app.api.mastodon.statuses import notes_to_responses
    from app.services.note_service import (
        _note_load_options,
        get_reaction_summaries,
    )

    query = (
        select(Note)
        .options(*_note_load_options())
        .where(
            Note.actor_id == actor_id,
            Note.visibility.in_(["public", "unlisted"]),
            Note.deleted_at.is_(None),
        )
    )

    # Filter notes hidden before threshold
    if actor.make_notes_hidden_before:
        threshold = datetime.fromtimestamp(
            actor.make_notes_hidden_before / 1000.0,
            tz=timezone.utc,
        )
        query = query.where(Note.published > threshold)

    # Filter notes followers-only before threshold (unauthenticated only)
    if actor.make_notes_followers_only_before and not user:
        threshold = datetime.fromtimestamp(
            actor.make_notes_followers_only_before / 1000.0, tz=timezone.utc
        )
        query = query.where(Note.published > threshold)

    query = query.order_by(Note.published.desc()).limit(min(limit, 40))
    notes_result = await db.execute(query)
    notes = list(notes_result.scalars().all())

    note_ids = [n.id for n in notes]
    reactions_map = await get_reaction_summaries(db, note_ids)
    return await notes_to_responses(notes, reactions_map, db)


async def _batch_resolve_actor_emojis(
    db: AsyncSession,
    actors: list[Actor],
) -> dict[uuid.UUID, list[dict]]:
    """Batch-resolve custom emoji for multiple actors in 2 queries max."""
    import re

    shortcode_re = re.compile(r":([a-zA-Z0-9_]+):")

    # アクターごとのshortcode収集
    actor_shortcodes: dict[uuid.UUID, set[str]] = {}
    all_shortcodes: set[str] = set()
    for actor in actors:
        texts = [actor.display_name or "", actor.summary or ""]
        for f in actor.fields or []:
            texts.append(f.get("name", ""))
            texts.append(f.get("value", ""))
        codes = set()
        for text in texts:
            codes.update(shortcode_re.findall(text))
        actor_shortcodes[actor.id] = codes
        all_shortcodes.update(codes)

    if not all_shortcodes:
        return {}

    from app.services.emoji_service import get_emojis_by_shortcodes

    # ローカル絵文字を一括取得
    local_emojis = await get_emojis_by_shortcodes(db, all_shortcodes, None)
    local_map = {e.shortcode: e for e in local_emojis}

    # リモート絵文字(ローカルにないもの)を一括取得
    missing = all_shortcodes - set(local_map.keys())
    remote_map: dict[str, "CustomEmoji"] = {}
    if missing:
        from app.models.custom_emoji import CustomEmoji

        result = await db.execute(
            select(CustomEmoji).where(
                CustomEmoji.shortcode.in_(missing),
                CustomEmoji.domain.isnot(None),
            )
        )
        for e in result.scalars().all():
            if e.shortcode not in remote_map:
                remote_map[e.shortcode] = e

    # アクターごとの絵文字リスト構築
    emoji_map: dict[uuid.UUID, list[dict]] = {}
    for actor in actors:
        codes = actor_shortcodes.get(actor.id, set())
        if not codes:
            continue
        emojis = []
        for sc in codes:
            e = local_map.get(sc) or remote_map.get(sc)
            if e:
                emojis.append(
                    {
                        "shortcode": e.shortcode,
                        "url": media_proxy_url(e.url),
                        "static_url": media_proxy_url(e.static_url)
                        if e.static_url
                        else media_proxy_url(e.url),
                    }
                )
        if emojis:
            emoji_map[actor.id] = emojis

    return emoji_map


@router.get("/{actor_id}/followers")
async def list_followers(
    actor_id: uuid.UUID,
    limit: int = 40,
    db: AsyncSession = Depends(get_db),
):
    """List accounts that follow the given account."""
    from app.services.follow_service import get_followers

    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Actor not found")

    actors = await get_followers(db, actor_id, min(limit, 80))
    emoji_map = await _batch_resolve_actor_emojis(db, actors)
    results = []
    for a in actors:
        account = await _actor_to_account(a)
        if a.id in emoji_map:
            account["emojis"] = emoji_map[a.id]
        results.append(account)
    return results


@router.get("/{actor_id}/following")
async def list_following(
    actor_id: uuid.UUID,
    limit: int = 40,
    db: AsyncSession = Depends(get_db),
):
    """List accounts the given account is following."""
    from app.services.follow_service import get_following

    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Actor not found")

    actors = await get_following(db, actor_id, min(limit, 80))
    emoji_map = await _batch_resolve_actor_emojis(db, actors)
    results = []
    for a in actors:
        account = await _actor_to_account(a)
        if a.id in emoji_map:
            account["emojis"] = emoji_map[a.id]
        results.append(account)
    return results


@router.get("/{actor_id}")
async def get_account(
    actor_id: uuid.UUID,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    actor = result.scalar_one_or_none()
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    if actor.require_signin_to_view and not user:
        return _actor_to_limited_account(actor)

    fc, fic = await get_follow_counts(db, actor.id)
    return await _actor_to_account(actor, followers_count=fc, following_count=fic, db=db)


@router.get("/{actor_id}/relationship")
async def get_relationship(
    actor_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check follow/block/mute status with another actor."""
    from app.services.block_service import is_blocking
    from app.services.mute_service import is_muting

    following = False
    followed_by = False
    blocking = False
    muting = False

    # フォロー状態の確認 (accepted / pending)
    requested = False
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == user.actor_id,
            Follow.following_id == actor_id,
        )
    )
    outgoing_follow = result.scalar_one_or_none()
    if outgoing_follow:
        following = outgoing_follow.accepted
        requested = not outgoing_follow.accepted
    else:
        following = False

    result2 = await db.execute(
        select(Follow).where(
            Follow.follower_id == actor_id,
            Follow.following_id == user.actor_id,
            Follow.accepted.is_(True),
        )
    )
    followed_by = result2.scalar_one_or_none() is not None

    blocking = await is_blocking(db, user.actor_id, actor_id)
    muting = await is_muting(db, user.actor_id, actor_id)

    return {
        "id": str(actor_id),
        "following": following,
        "followed_by": followed_by,
        "blocking": blocking,
        "muting": muting,
        "requested": requested,
    }


class MoveRequest(BaseModel):
    target_ap_id: str


@router.post("/move")
async def move_account(
    body: MoveRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Initiate account migration to a target actor."""
    from app.services.move_service import initiate_move

    try:
        await initiate_move(db, user, body.target_ap_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True}


# --- Following IDs (lightweight) ---


@relationships_router.get("/following_ids")
async def list_following_ids(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.follow_service import get_following_ids

    ids = await get_following_ids(db, user.actor_id)
    return [str(i) for i in ids]


# --- Block/Mute lists (different prefix) ---


@relationships_router.get("/blocks")
async def list_blocks(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.block_service import get_blocked_ids

    blocked_ids = await get_blocked_ids(db, user.actor_id)
    if not blocked_ids:
        return []

    result = await db.execute(select(Actor).where(Actor.id.in_(blocked_ids)))
    actors = result.scalars().all()
    return [await _actor_to_account(a, db=db) for a in actors]


@relationships_router.get("/mutes")
async def list_mutes(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.mute_service import get_muted_ids

    muted_ids = await get_muted_ids(db, user.actor_id)
    if not muted_ids:
        return []

    result = await db.execute(select(Actor).where(Actor.id.in_(muted_ids)))
    actors = result.scalars().all()
    return [await _actor_to_account(a, db=db) for a in actors]
