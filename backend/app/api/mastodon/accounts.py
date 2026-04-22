import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.mastodon.statuses import _to_mastodon_datetime
from app.config import settings
from app.dependencies import get_current_user, get_db, get_optional_user, require_oauth_scope
from app.models.actor import Actor
from app.models.follow import Follow
from app.models.note import Note
from app.models.user import User
from app.services.follow_service import follow_actor, get_follow_counts, unfollow_actor
from app.services.note_service import get_statuses_count
from app.utils.media_proxy import media_proxy_url

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])
relationships_router = APIRouter(prefix="/api/v1", tags=["relationships"])


@router.post(
    "/{actor_id}/follow",
    dependencies=[Depends(require_oauth_scope("write:follows"))],
)
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


@router.post(
    "/{actor_id}/unfollow",
    dependencies=[Depends(require_oauth_scope("write:follows"))],
)
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


@router.get("")
async def get_accounts_batch(
    ids: list[str] = Query(alias="id[]", default=[]),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """複数アカウントを ID で一括取得する（Mastodon API v4.3.0）。"""
    if not ids:
        return []
    # 有効な UUID をパースして重複排除
    valid_ids: list[uuid.UUID] = []
    for raw in ids[:40]:  # 悪用防止のため40件に制限
        try:
            valid_ids.append(uuid.UUID(raw))
        except ValueError:
            continue
    if not valid_ids:
        return []
    result = await db.execute(select(Actor).where(Actor.id.in_(valid_ids)))
    actors = list(result.scalars().all())

    # カウントをバッチ取得（3N→3クエリ）
    from app.services.follow_service import get_follow_counts_batch
    from app.services.note_service import get_statuses_count_batch

    visible_ids = [a.id for a in actors if not (a.require_signin_to_view and not user)]
    follow_counts = await get_follow_counts_batch(db, visible_ids)
    statuses_counts = await get_statuses_count_batch(db, visible_ids)

    accounts = []
    for actor in actors:
        if actor.require_signin_to_view and not user:
            accounts.append(_actor_to_limited_account(actor))
        else:
            fc, fic = follow_counts.get(actor.id, (0, 0))
            sc = statuses_counts.get(actor.id, 0)
            accounts.append(
                await _actor_to_account(
                    actor, followers_count=fc, following_count=fic,
                    statuses_count=sc, db=db,
                )
            )
    return accounts


@router.get("/lookup")
async def lookup_account(
    acct: str,
    db: AsyncSession = Depends(get_db),
):
    """acct URI（user@domain）でアカウントを検索する。リモートアクターは WebFinger で解決する。"""
    if "@" in acct:
        username, domain = acct.split("@", 1)
    else:
        username = acct
        domain = None

    from app.services.actor_service import get_actor_by_username

    actor = await get_actor_by_username(db, username, domain)

    # ローカルに見つからずリモート acct の場合、WebFinger で解決
    if not actor and domain:
        from app.services.actor_service import resolve_webfinger

        actor = await resolve_webfinger(db, username, domain)

    if not actor:
        raise HTTPException(status_code=404, detail="Account not found")

    fc, fic = await get_follow_counts(db, actor.id)
    sc = await get_statuses_count(db, actor.id)
    return await _actor_to_account(
        actor, followers_count=fc, following_count=fic, statuses_count=sc, db=db
    )


@router.get("/search")
async def search_accounts(
    q: str,
    resolve: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """アカウントを検索する。resolve=true かつ user@domain 形式の場合、WebFinger で解決する。"""
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
    statuses_count: int | None = None,
    db: AsyncSession | None = None,
    resolve_emojis: bool = True,
) -> dict:
    """Actor を Mastodon 互換 account dict に変換する。

    Args:
        resolve_emojis: False を指定すると絵文字解決の per-actor クエリをスキップする。
            呼び出し側で ``_batch_resolve_actor_emojis`` により一括解決済みの場合に
            指定する。``moved`` フィールドの解決には影響しない (``db`` が渡されていれば
            引き続き行われる)。
    """
    import re

    avatar = (
        media_proxy_url(actor.avatar_url, variant="avatar")
        or f"{settings.server_url}/default-avatar.svg"
    )
    avatar_static = media_proxy_url(actor.avatar_url, variant="avatar", static=True) or avatar
    header = media_proxy_url(actor.header_url) or ""
    data = {
        "id": str(actor.id),
        "username": actor.username,
        "acct": f"{actor.username}@{actor.domain}" if actor.domain else actor.username,
        "display_name": actor.display_name or "",
        "note": actor.summary or "",
        "uri": actor.ap_id,
        "avatar": avatar,
        "avatar_static": avatar_static,
        "header": header,
        "header_static": header,
        "url": actor.ap_id,
        "created_at": _to_mastodon_datetime(actor.created_at),
        "bot": getattr(actor, "is_bot", False) or actor.type == "Service",
        "group": actor.type == "Group",
        "locked": actor.manually_approves_followers,
        "discoverable": actor.discoverable,
        "fields": [
            {"name": f.get("name", ""), "value": f.get("value", ""), "verified_at": None}
            for f in (actor.fields or [])
        ],
        "emojis": [],
        "followers_count": followers_count or 0,
        "following_count": following_count or 0,
        "statuses_count": statuses_count or 0,
        "last_status_at": None,
    }

    # display_name、summary、fields からカスタム絵文字を解決
    if db and resolve_emojis:
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
                    "url": media_proxy_url(e.url, variant="emoji"),
                    "static_url": media_proxy_url(e.static_url, variant="emoji", static=True)
                    if e.static_url
                    else media_proxy_url(e.url, variant="emoji", static=True),
                }
                for e in emoji_list
            ]

    # 移行先アカウント (Mastodon API 互換)
    if getattr(actor, "moved_to_ap_id", None) and db:
        from sqlalchemy import select as _sel

        result = await db.execute(
            _sel(Actor).where(Actor.ap_id == actor.moved_to_ap_id)
        )
        moved_actor = result.scalar_one_or_none()
        if moved_actor:
            # db=None で再帰防止 (moved 先の moved は展開しない)
            data["moved"] = await _actor_to_account(moved_actor)

    return data


def _actor_to_limited_account(actor: Actor) -> dict:
    """require_signin_to_view が設定されたアクターの最小限のアカウント情報を返す。"""
    return {
        "id": str(actor.id),
        "username": actor.username,
        "acct": f"{actor.username}@{actor.domain}" if actor.domain else actor.username,
        "display_name": actor.display_name or "",
        "note": "",
        "uri": actor.ap_id,
        "avatar": f"{settings.server_url}/default-avatar.svg",
        "avatar_static": f"{settings.server_url}/default-avatar.svg",
        "header": "",
        "header_static": "",
        "url": actor.ap_id,
        "created_at": _to_mastodon_datetime(actor.created_at),
        "bot": getattr(actor, "is_bot", False) or actor.type == "Service",
        "group": actor.type == "Group",
        "locked": actor.manually_approves_followers,
        "discoverable": actor.discoverable,
        "fields": [],
        "emojis": [],
        "followers_count": 0,
        "following_count": 0,
        "statuses_count": 0,
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
    max_id: uuid.UUID | None = None,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    actor = result.scalar_one_or_none()
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    # Misskey の require_signin_to_view を尊重
    if actor.require_signin_to_view and not user:
        return []

    from datetime import datetime, timezone

    from app.api.mastodon.statuses import notes_to_responses
    from app.services.note_service import (
        _note_load_options,
        get_reaction_summaries,
    )

    # リレーションに基づいて表示する公開範囲を決定
    visible = ["public", "unlisted"]
    if user:
        if user.actor_id == actor_id:
            # 自分のプロフィール: すべて表示
            visible = ["public", "unlisted", "followers", "direct"]
        else:
            # 現在のユーザーがこのアクターをフォローしているか確認
            follow_check = await db.execute(
                select(Follow.id)
                .where(
                    Follow.follower_id == user.actor_id,
                    Follow.following_id == actor_id,
                    Follow.accepted.is_(True),
                )
                .limit(1)
            )
            if follow_check.scalar_one_or_none() is not None:
                visible = ["public", "unlisted", "followers"]

    query = (
        select(Note)
        .options(*_note_load_options())
        .where(
            Note.actor_id == actor_id,
            Note.visibility.in_(visible),
            Note.deleted_at.is_(None),
        )
    )

    # しきい値より前の非表示ノートをフィルタ
    if actor.make_notes_hidden_before:
        threshold = datetime.fromtimestamp(
            actor.make_notes_hidden_before / 1000.0,
            tz=timezone.utc,
        )
        query = query.where(Note.published > threshold)

    # しきい値より前のフォロワー限定ノートをフィルタ（未認証時のみ）
    if actor.make_notes_followers_only_before and not user:
        threshold = datetime.fromtimestamp(
            actor.make_notes_followers_only_before / 1000.0, tz=timezone.utc
        )
        query = query.where(Note.published > threshold)

    # このアクターのピン留めノート ID をバッチ取得
    from app.models.pinned_note import PinnedNote

    pinned_result = await db.execute(
        select(PinnedNote.note_id).where(PinnedNote.actor_id == actor_id)
    )
    pinned_ids = {row[0] for row in pinned_result.all()}

    # 1ページ目ではピン留めノートを必ず含める
    pinned_notes: list[Note] = []
    if not max_id and pinned_ids:
        pinned_query = (
            select(Note)
            .options(*_note_load_options())
            .where(
                Note.id.in_(pinned_ids),
                Note.visibility.in_(visible),
                Note.deleted_at.is_(None),
            )
            .order_by(Note.published.desc())
        )
        pinned_result2 = await db.execute(pinned_query)
        pinned_notes = list(pinned_result2.scalars().all())

    if max_id:
        # カーソルベースのページネーション: max_id ノートの published タイムスタンプを取得
        cursor_result = await db.execute(select(Note.published).where(Note.id == max_id))
        cursor_ts = cursor_result.scalar_one_or_none()
        if cursor_ts:
            query = query.where(Note.published < cursor_ts)

    query = query.order_by(Note.published.desc()).limit(min(limit, 40))
    notes_result = await db.execute(query)
    notes = list(notes_result.scalars().all())

    # ピン留めノートを先頭に追加（重複排除）
    if pinned_notes:
        timeline_ids = {n.id for n in notes}
        for pn in reversed(pinned_notes):
            if pn.id not in timeline_ids:
                notes.insert(0, pn)

    note_ids = [n.id for n in notes]
    current_actor_id = user.actor_id if user else None
    reactions_map = await get_reaction_summaries(db, note_ids, current_actor_id)

    return await notes_to_responses(
        notes, reactions_map, db, actor_id=current_actor_id, pinned_ids=pinned_ids
    )


async def _batch_resolve_actor_emojis(
    db: AsyncSession,
    actors: list[Actor],
) -> dict[uuid.UUID, list[dict]]:
    """複数アクターのカスタム絵文字を最大2クエリでバッチ解決する。"""
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
                        "url": media_proxy_url(e.url, variant="emoji"),
                        "static_url": media_proxy_url(e.static_url, variant="emoji", static=True)
                        if e.static_url
                        else media_proxy_url(e.url, variant="emoji", static=True),
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
    """指定アカウントをフォローしているアカウント一覧を返す。"""
    from app.services.follow_service import get_followers

    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Actor not found")

    actors = await get_followers(db, actor_id, min(limit, 80))
    emoji_map = await _batch_resolve_actor_emojis(db, actors)
    results = []
    for a in actors:
        # db は moved フィールド解決のために渡す。絵文字は emoji_map で差し込む。
        account = await _actor_to_account(a, db=db, resolve_emojis=False)
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
    """指定アカウントがフォローしているアカウント一覧を返す。"""
    from app.services.follow_service import get_following

    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Actor not found")

    actors = await get_following(db, actor_id, min(limit, 80))
    emoji_map = await _batch_resolve_actor_emojis(db, actors)
    results = []
    for a in actors:
        account = await _actor_to_account(a, db=db, resolve_emojis=False)
        if a.id in emoji_map:
            account["emojis"] = emoji_map[a.id]
        results.append(account)
    return results


@router.get("/{actor_id}/lists")
async def get_account_lists(
    actor_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """指定アカウントを含む、現在のユーザーが所有するリスト一覧を返す。"""
    result = await db.execute(select(Actor).where(Actor.id == actor_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Actor not found")

    from app.services.list_service import get_user_lists_for_actor

    lists = await get_user_lists_for_actor(db, user.id, actor_id)
    return [
        {
            "id": str(lst.id),
            "title": lst.title,
            "replies_policy": lst.replies_policy,
            "exclusive": lst.exclusive,
        }
        for lst in lists
    ]


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
    sc = await get_statuses_count(db, actor.id)
    return await _actor_to_account(
        actor, followers_count=fc, following_count=fic, statuses_count=sc, db=db
    )


@router.get("/{actor_id}/relationship")
async def get_relationship(
    actor_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """他のアクターとのフォロー/ブロック/ミュート状態を確認する。"""
    from datetime import datetime, timezone

    from sqlalchemy import literal, union_all

    from app.models.user_block import UserBlock
    from app.models.user_mute import UserMute

    following = False
    followed_by = False
    blocking = False
    muting = False
    requested = False

    # フォロー状態の確認（双方向を1クエリで取得）
    result = await db.execute(
        select(Follow.follower_id, Follow.following_id, Follow.accepted).where(
            ((Follow.follower_id == user.actor_id) & (Follow.following_id == actor_id))
            | ((Follow.follower_id == actor_id) & (Follow.following_id == user.actor_id))
        )
    )
    for row in result.all():
        if row.follower_id == user.actor_id:
            following = row.accepted
            requested = not row.accepted
        else:
            if row.accepted:
                followed_by = True

    # ブロック/ミュートを1クエリで確認
    now = datetime.now(timezone.utc)
    block_mute_q = union_all(
        select(literal("block").label("type")).where(
            select(UserBlock.id).where(
                UserBlock.actor_id == user.actor_id, UserBlock.target_id == actor_id,
            ).exists()
        ),
        select(literal("mute").label("type")).where(
            select(UserMute.id).where(
                UserMute.actor_id == user.actor_id, UserMute.target_id == actor_id,
                (UserMute.expires_at.is_(None)) | (UserMute.expires_at > now),
            ).exists()
        ),
    )
    bm_result = await db.execute(select(block_mute_q.c.type))
    for row in bm_result.all():
        if row[0] == "block":
            blocking = True
        elif row[0] == "mute":
            muting = True

    return {
        "id": str(actor_id),
        "following": following,
        "followed_by": followed_by,
        "blocking": blocking,
        "muting": muting,
        "requested": requested,
        "showing_reblogs": True,
        "notifying": False,
        "domain_blocking": False,
        "endorsed": False,
        "muting_notifications": False,
        "note": "",
        "languages": None,
    }


@relationships_router.get("/accounts/relationships")
async def get_relationships_batch(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    ids: list[str] = Query(default=[], alias="id[]"),
):
    """複数アカウントとのフォロー/ブロック/ミュート状態を一括チェックする。"""
    if not ids:
        return []

    # UUIDへの変換 (無効なIDは無視)
    actor_ids: list[uuid.UUID] = []
    for id_str in ids[:40]:  # 最大40件
        try:
            actor_ids.append(uuid.UUID(id_str))
        except ValueError:
            continue

    if not actor_ids:
        return []

    from app.services.block_service import get_blocked_ids
    from app.services.mute_service import get_muted_ids

    # 一括クエリでFollow, Block, Mute状態を取得
    follow_out_result = await db.execute(
        select(Follow).where(
            Follow.follower_id == user.actor_id,
            Follow.following_id.in_(actor_ids),
        )
    )
    outgoing_follows = {f.following_id: f for f in follow_out_result.scalars().all()}

    follow_in_result = await db.execute(
        select(Follow.follower_id).where(
            Follow.follower_id.in_(actor_ids),
            Follow.following_id == user.actor_id,
            Follow.accepted.is_(True),
        )
    )
    followed_by_ids = {row[0] for row in follow_in_result.all()}

    blocked_ids = set(await get_blocked_ids(db, user.actor_id))
    muted_ids = set(await get_muted_ids(db, user.actor_id))

    results = []
    for aid in actor_ids:
        outgoing = outgoing_follows.get(aid)
        following = outgoing.accepted if outgoing else False
        requested = (not outgoing.accepted) if outgoing else False

        results.append(
            {
                "id": str(aid),
                "following": following,
                "followed_by": aid in followed_by_ids,
                "blocking": aid in blocked_ids,
                "muting": aid in muted_ids,
                "requested": requested,
                "showing_reblogs": True,
                "notifying": False,
                "domain_blocking": False,
                "endorsed": False,
                "muting_notifications": False,
                "note": "",
                "languages": None,
            }
        )

    return results


class MoveRequest(BaseModel):
    target_ap_id: str


@router.post("/move")
async def move_account(
    body: MoveRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """ターゲットアクターへのアカウント引っ越しを開始する。"""
    from app.services.move_service import initiate_move

    try:
        await initiate_move(db, user, body.target_ap_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True}


# --- フォロー中 ID（軽量） ---


@relationships_router.get("/following_ids")
async def list_following_ids(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.follow_service import get_following_ids

    ids = await get_following_ids(db, user.actor_id)
    return [str(i) for i in ids]


# --- ブロック/ミュート一覧（別プレフィックス） ---


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
    actors = list(result.scalars().all())
    emoji_map = await _batch_resolve_actor_emojis(db, actors)
    results = []
    for a in actors:
        account = await _actor_to_account(a, db=db, resolve_emojis=False)
        if a.id in emoji_map:
            account["emojis"] = emoji_map[a.id]
        results.append(account)
    return results


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
    actors = list(result.scalars().all())
    emoji_map = await _batch_resolve_actor_emojis(db, actors)
    results = []
    for a in actors:
        account = await _actor_to_account(a, db=db, resolve_emojis=False)
        if a.id in emoji_map:
            account["emojis"] = emoji_map[a.id]
        results.append(account)
    return results
