"""ActivityPub コアルート: Actor エンドポイント、Inbox、Outbox。"""

import base64
import hashlib
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.dependencies import get_db
from app.models.note import Note
from app.services.actor_service import get_actor_by_username, get_actor_public_key

from .http_signature import parse_signature_header, verify_signature
from .renderer import (
    render_actor,
    render_create_activity,
    render_note,
    render_ordered_collection,
    render_ordered_collection_page,
)

logger = logging.getLogger(__name__)

router = APIRouter()

AP_CONTENT_TYPE = "application/activity+json; charset=utf-8"


def is_ap_request(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "application/activity+json" in accept or "application/ld+json" in accept


@router.get("/users/{username}")
async def get_actor(username: str, request: Request, db: AsyncSession = Depends(get_db)):
    actor = await get_actor_by_username(db, username, domain=None)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    # 凍結済みアクターは 410 Gone を返す
    if actor.is_suspended:
        raise HTTPException(status_code=410, detail="Gone")

    if not is_ap_request(request):
        # ブラウザにはプロフィールページへリダイレクト
        return Response(status_code=302, headers={"Location": f"/@{username}"})

    return Response(
        content=json.dumps(render_actor(actor)),
        media_type=AP_CONTENT_TYPE,
    )


@router.get("/users/{username}/outbox")
async def get_outbox(
    username: str,
    page: bool = False,
    db: AsyncSession = Depends(get_db),
):
    actor = await get_actor_by_username(db, username, domain=None)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    outbox_url = f"{settings.server_url}/users/{username}/outbox"

    if not page:
        count_result = await db.execute(
            select(func.count())
            .select_from(Note)
            .where(
                Note.actor_id == actor.id,
                Note.local.is_(True),
                Note.visibility == "public",
                Note.deleted_at.is_(None),
            )
        )
        total = count_result.scalar() or 0
        return Response(
            content=json.dumps(
                render_ordered_collection(outbox_url, total, f"{outbox_url}?page=true")
            ),
            media_type=AP_CONTENT_TYPE,
        )

    notes_result = await db.execute(
        select(Note)
        .options(selectinload(Note.actor))
        .where(
            Note.actor_id == actor.id,
            Note.local.is_(True),
            Note.visibility == "public",
            Note.deleted_at.is_(None),
        )
        .order_by(Note.published.desc())
        .limit(20)
    )
    notes = notes_result.scalars().all()

    items = [render_create_activity(n) for n in notes]
    return Response(
        content=json.dumps(
            render_ordered_collection_page(f"{outbox_url}?page=true", outbox_url, items)
        ),
        media_type=AP_CONTENT_TYPE,
    )


@router.get("/users/{username}/followers")
async def get_followers_collection(
    username: str,
    page: bool = False,
    db: AsyncSession = Depends(get_db),
):
    actor = await get_actor_by_username(db, username, domain=None)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    from app.models.follow import Follow

    followers_url = f"{settings.server_url}/users/{username}/followers"

    if not page:
        count_result = await db.execute(
            select(func.count())
            .select_from(Follow)
            .where(Follow.following_id == actor.id, Follow.accepted.is_(True))
        )
        total = count_result.scalar() or 0
        return Response(
            content=json.dumps(
                render_ordered_collection(followers_url, total, f"{followers_url}?page=true")
            ),
            media_type=AP_CONTENT_TYPE,
        )

    from app.models.actor import Actor

    # M-10: ページネーション追加 (40件ずつ)
    result = await db.execute(
        select(Actor.ap_id)
        .join(Follow, Follow.follower_id == Actor.id)
        .where(Follow.following_id == actor.id, Follow.accepted.is_(True))
        .order_by(Follow.created_at.desc())
        .limit(40)
    )
    items = [ap_id for (ap_id,) in result.all()]
    return Response(
        content=json.dumps(
            render_ordered_collection_page(f"{followers_url}?page=true", followers_url, items)
        ),
        media_type=AP_CONTENT_TYPE,
    )


@router.get("/users/{username}/following")
async def get_following_collection(
    username: str,
    page: bool = False,
    db: AsyncSession = Depends(get_db),
):
    actor = await get_actor_by_username(db, username, domain=None)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    from app.models.follow import Follow

    following_url = f"{settings.server_url}/users/{username}/following"

    if not page:
        count_result = await db.execute(
            select(func.count())
            .select_from(Follow)
            .where(Follow.follower_id == actor.id, Follow.accepted.is_(True))
        )
        total = count_result.scalar() or 0
        return Response(
            content=json.dumps(
                render_ordered_collection(following_url, total, f"{following_url}?page=true")
            ),
            media_type=AP_CONTENT_TYPE,
        )

    from app.models.actor import Actor

    # M-10: ページネーション追加 (40件ずつ)
    result = await db.execute(
        select(Actor.ap_id)
        .join(Follow, Follow.following_id == Actor.id)
        .where(Follow.follower_id == actor.id, Follow.accepted.is_(True))
        .order_by(Follow.created_at.desc())
        .limit(40)
    )
    items = [ap_id for (ap_id,) in result.all()]
    return Response(
        content=json.dumps(
            render_ordered_collection_page(f"{following_url}?page=true", following_url, items)
        ),
        media_type=AP_CONTENT_TYPE,
    )


@router.get("/users/{username}/featured")
async def get_featured(username: str, db: AsyncSession = Depends(get_db)):
    actor = await get_actor_by_username(db, username, domain=None)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    from app.services.pinned_note_service import get_pinned_notes

    pins = await get_pinned_notes(db, actor.id)
    items = [render_note(pin.note) for pin in pins if pin.note]

    featured_url = f"{settings.server_url}/users/{username}/featured"
    collection = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": featured_url,
        "type": "OrderedCollection",
        "totalItems": len(items),
        "orderedItems": items,
    }
    return Response(content=json.dumps(collection), media_type=AP_CONTENT_TYPE)


@router.get("/notes/{note_id}")
async def get_note_ap(note_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)):
    import re

    from app.services.emoji_service import get_custom_emoji
    from app.services.hashtag_service import get_hashtags_for_notes
    from app.services.note_service import get_note_by_id

    note = await get_note_by_id(db, note_id)
    if not note or note.visibility not in ("public", "unlisted"):
        raise HTTPException(status_code=404, detail="Note not found")

    if not is_ap_request(request):
        raise HTTPException(status_code=404, detail="Not found")

    # AP レンダリング用にハッシュタグを読み込む
    hashtags_map = await get_hashtags_for_notes(db, [note.id])
    note._hashtag_names = hashtags_map.get(note.id, [])

    # AP レンダリング用にカスタム絵文字タグを読み込む
    shortcodes = set(re.findall(r":([a-zA-Z0-9_]+):", note.content or ""))
    if shortcodes:
        emoji_tags = []
        for sc in shortcodes:
            emoji = await get_custom_emoji(db, sc, None)
            if emoji and not emoji.local_only:
                emoji_tags.append(
                    {
                        "shortcode": emoji.shortcode,
                        "url": emoji.url,
                        "aliases": emoji.aliases,
                        "license": emoji.license,
                        "is_sensitive": emoji.is_sensitive,
                        "author": emoji.author,
                        "description": emoji.description,
                        "copy_permission": emoji.copy_permission,
                        "usage_info": emoji.usage_info,
                        "is_based_on": emoji.is_based_on,
                        "category": emoji.category,
                    }
                )
        if emoji_tags:
            note._emoji_tags = emoji_tags

    return Response(
        content=json.dumps(render_note(note)),
        media_type=AP_CONTENT_TYPE,
    )


async def verify_inbox_signature(request: Request, db: AsyncSession) -> tuple[bool, str]:
    """Inbox リクエストの HTTP Signature を検証する。(valid, key_id) を返す。"""
    sig_header = request.headers.get("signature")
    if not sig_header:
        return False, ""

    params = parse_signature_header(sig_header)
    key_id = params.get("keyId", "")
    if not key_id:
        return False, ""

    actor, public_key_pem = await get_actor_public_key(db, key_id)
    if not public_key_pem:
        return False, key_id

    headers_dict = {k.lower(): v for k, v in request.headers.items()}
    path = request.url.path
    if request.url.query:
        path += f"?{request.url.query}"

    valid = verify_signature(
        public_key_pem=public_key_pem,
        signature_header=sig_header,
        method=request.method,
        path=path,
        headers=headers_dict,
    )
    return valid, key_id


def _verify_digest(body: bytes, digest_header: str | None) -> bool:
    """Digest ヘッダーが実際のリクエストボディのハッシュと一致するか検証する。"""
    import hmac as _hmac

    if not digest_header:
        return False
    # SHA-256=<base64> 形式をパース
    if not digest_header.startswith("SHA-256="):
        return False
    expected_b64 = digest_header[len("SHA-256=") :]
    # L-7: 空のbase64値を明示的に拒否
    if not expected_b64:
        return False
    actual_hash = base64.b64encode(hashlib.sha256(body).digest()).decode()
    # L-6: タイミングセーフ比較
    return _hmac.compare_digest(actual_hash, expected_b64)


# H-4: Inboxリクエストのボディサイズ上限 (1MB)
MAX_INBOX_BODY_SIZE = 1 * 1024 * 1024

# H-5: Inboxレート制限
INBOX_MAX_REQUESTS = 200
INBOX_RATE_TTL = 60  # 1分あたり


async def _check_inbox_rate_limit(request: Request) -> None:
    """H-5: Inboxエンドポイントのドメイン/IPベースレート制限"""
    from app.valkey_client import valkey

    client_ip = request.client.host if request.client else "unknown"
    key = f"inbox_rate:{client_ip}"
    try:
        attempts = await valkey.get(key)
        if attempts is not None and int(attempts) >= INBOX_MAX_REQUESTS:
            raise HTTPException(status_code=429, detail="Too many requests")
        await valkey.incr(key)
        await valkey.expire(key, INBOX_RATE_TTL)
    except HTTPException:
        raise
    except Exception:
        pass


async def _read_inbox_body(request: Request) -> bytes:
    """H-4: サイズ制限付きInboxボディ読み取り"""
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_INBOX_BODY_SIZE:
        raise HTTPException(status_code=413, detail="Request body too large")
    body = await request.body()
    if len(body) > MAX_INBOX_BODY_SIZE:
        raise HTTPException(status_code=413, detail="Request body too large")
    return body


@router.post("/users/{username}/inbox")
async def user_inbox(username: str, request: Request, db: AsyncSession = Depends(get_db)):
    actor = await get_actor_by_username(db, username, domain=None)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    await _check_inbox_rate_limit(request)
    body = await _read_inbox_body(request)

    # Digestヘッダーの検証
    digest_header = request.headers.get("digest")
    if not _verify_digest(body, digest_header):
        logger.warning("Invalid or missing Digest header")
        raise HTTPException(status_code=400, detail="Invalid Digest header")

    # HTTP Signature を検証
    valid, key_id = await verify_inbox_signature(request, db)
    if not valid:
        logger.warning("Invalid HTTP Signature from key_id=%s", key_id)
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        activity = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # JSON-LD expanded form (Pleroma/Akkoma): トップレベルが配列の場合は先頭要素を取り出す
    if isinstance(activity, list):
        if not activity:
            raise HTTPException(status_code=400, detail="Empty activity array")
        activity = activity[0]

    # 署名鍵のアクターとactivityのactorが一致するか検証
    _verify_key_actor_match(key_id, activity)

    await process_inbox_activity(db, activity)
    return Response(status_code=202)


@router.post("/inbox")
async def shared_inbox(request: Request, db: AsyncSession = Depends(get_db)):
    await _check_inbox_rate_limit(request)
    body = await _read_inbox_body(request)

    # Digestヘッダーの検証
    digest_header = request.headers.get("digest")
    if not _verify_digest(body, digest_header):
        logger.warning("Invalid or missing Digest header on shared inbox")
        raise HTTPException(status_code=400, detail="Invalid Digest header")

    valid, key_id = await verify_inbox_signature(request, db)
    if not valid:
        logger.warning("Invalid HTTP Signature on shared inbox from key_id=%s", key_id)
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        activity = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # JSON-LD expanded form (Pleroma/Akkoma): トップレベルが配列の場合は先頭要素を取り出す
    if isinstance(activity, list):
        if not activity:
            raise HTTPException(status_code=400, detail="Empty activity array")
        activity = activity[0]

    # 署名鍵のアクターとactivityのactorが一致するか検証
    _verify_key_actor_match(key_id, activity)

    await process_inbox_activity(db, activity)
    return Response(status_code=202)


def _verify_key_actor_match(key_id: str, activity: dict):
    """HTTP Signature の鍵所有者と activity の actor が一致するか検証する。

    key_id は通常 "https://example.com/users/alice#main-key" のような形式。
    アクター部分はフラグメントより前の URL。
    """
    activity_actor = activity.get("actor", "")
    if not activity_actor or not key_id:
        raise HTTPException(status_code=401, detail="Missing actor or key_id")

    # key_idからアクターURLを抽出 (フラグメント部分を除去)
    key_actor = key_id.split("#")[0]

    if key_actor != activity_actor:
        logger.warning(
            "Key actor mismatch: key_id actor=%s, activity actor=%s",
            key_actor,
            activity_actor,
        )
        raise HTTPException(status_code=401, detail="Key owner does not match activity actor")


async def process_inbox_activity(db: AsyncSession, activity: dict):
    """受信した activity を適切なハンドラーにルーティングする。"""
    activity_type = activity.get("type", "")
    logger.info("Processing inbox activity: type=%s id=%s", activity_type, activity.get("id"))

    # ドメインブロックチェック
    actor_id_str = activity.get("actor", "")
    if actor_id_str:
        from urllib.parse import urlparse

        from app.services.domain_block_service import is_domain_blocked

        domain = urlparse(actor_id_str).hostname
        if domain and await is_domain_blocked(db, domain):
            logger.info("Rejected activity from blocked domain: %s", domain)
            return

    # M-15: ユーザーレベルのブロックチェック
    if actor_id_str:
        from app.services.actor_service import get_actor_by_ap_id

        remote_actor = await get_actor_by_ap_id(db, actor_id_str)
        if remote_actor:
            from app.models.user_block import UserBlock

            block_result = await db.execute(
                select(UserBlock)
                .where(
                    UserBlock.target_id == remote_actor.id,
                )
                .limit(1)
            )
            if block_result.scalar_one_or_none():
                logger.info("Rejected activity from user-blocked actor: %s", actor_id_str)
                return

    # Valkey による冪等性チェック
    activity_id = activity.get("id")
    if activity_id:
        from app.valkey_client import valkey

        already_seen = await valkey.set(f"seen_activity:{activity_id}", "1", nx=True, ex=86400)
        if not already_seen:
            logger.info("Duplicate activity %s, skipping", activity_id)
            return
    else:
        # M-11: IDなしの活動はボディハッシュで冪等性チェック
        from app.valkey_client import valkey

        body_hash = hashlib.sha256(json.dumps(activity, sort_keys=True).encode()).hexdigest()
        already_seen = await valkey.set(f"seen_activity:hash:{body_hash}", "1", nx=True, ex=86400)
        if not already_seen:
            logger.info("Duplicate activity (by hash), skipping")
            return

    from app.activitypub.handlers import (
        announce,
        block,
        create,
        delete,
        flag,
        follow,
        like,
        move,
        undo,
        update,
    )

    handler_map = {
        "Create": create.handle_create,
        "Follow": follow.handle_follow,
        "Accept": follow.handle_accept,
        "Reject": follow.handle_reject,
        "Like": like.handle_like,
        "EmojiReact": like.handle_emoji_react,
        "Undo": undo.handle_undo,
        "Delete": delete.handle_delete,
        "Announce": announce.handle_announce,
        "Update": update.handle_update,
        "Flag": flag.handle_flag,
        "Block": block.handle_block,
        "Move": move.handle_move,
    }

    handler = handler_map.get(activity_type)
    if handler:
        await handler(db, activity)
    else:
        logger.info("Unhandled activity type: %s", activity_type)
