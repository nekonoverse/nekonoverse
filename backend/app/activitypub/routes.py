"""ActivityPub core routes: Actor endpoint, Inbox, Outbox."""

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

    # Suspended actors return 410 Gone
    if actor.is_suspended:
        raise HTTPException(status_code=410, detail="Gone")

    if not is_ap_request(request):
        # Redirect to profile page for browsers
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
async def get_followers_collection(username: str, db: AsyncSession = Depends(get_db)):
    actor = await get_actor_by_username(db, username, domain=None)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    from app.models.follow import Follow

    count_result = await db.execute(
        select(func.count())
        .select_from(Follow)
        .where(Follow.following_id == actor.id, Follow.accepted.is_(True))
    )
    total = count_result.scalar() or 0
    followers_url = f"{settings.server_url}/users/{username}/followers"

    return Response(
        content=json.dumps(render_ordered_collection(followers_url, total, followers_url)),
        media_type=AP_CONTENT_TYPE,
    )


@router.get("/users/{username}/following")
async def get_following_collection(username: str, db: AsyncSession = Depends(get_db)):
    actor = await get_actor_by_username(db, username, domain=None)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    from app.models.follow import Follow

    count_result = await db.execute(
        select(func.count())
        .select_from(Follow)
        .where(Follow.follower_id == actor.id, Follow.accepted.is_(True))
    )
    total = count_result.scalar() or 0
    following_url = f"{settings.server_url}/users/{username}/following"

    return Response(
        content=json.dumps(render_ordered_collection(following_url, total, following_url)),
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
    from app.services.note_service import get_note_by_id

    note = await get_note_by_id(db, note_id)
    if not note or note.visibility not in ("public", "unlisted"):
        raise HTTPException(status_code=404, detail="Note not found")

    if not is_ap_request(request):
        raise HTTPException(status_code=404, detail="Not found")

    return Response(
        content=json.dumps(render_note(note)),
        media_type=AP_CONTENT_TYPE,
    )


async def verify_inbox_signature(request: Request, db: AsyncSession) -> tuple[bool, str]:
    """Verify HTTP Signature on an inbox request. Returns (valid, key_id)."""
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
    """Verify that the Digest header matches the actual request body hash."""
    if not digest_header:
        return False
    # SHA-256=<base64> 形式をパース
    if not digest_header.startswith("SHA-256="):
        return False
    expected_b64 = digest_header[len("SHA-256=") :]
    actual_hash = base64.b64encode(hashlib.sha256(body).digest()).decode()
    return actual_hash == expected_b64


@router.post("/users/{username}/inbox")
async def user_inbox(username: str, request: Request, db: AsyncSession = Depends(get_db)):
    actor = await get_actor_by_username(db, username, domain=None)
    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found")

    body = await request.body()

    # Digestヘッダーの検証
    digest_header = request.headers.get("digest")
    if not _verify_digest(body, digest_header):
        logger.warning("Invalid or missing Digest header")
        raise HTTPException(status_code=400, detail="Invalid Digest header")

    # Verify HTTP Signature
    valid, key_id = await verify_inbox_signature(request, db)
    if not valid:
        logger.warning("Invalid HTTP Signature from key_id=%s", key_id)
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        activity = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # 署名鍵のアクターとactivityのactorが一致するか検証
    _verify_key_actor_match(key_id, activity)

    await process_inbox_activity(db, activity)
    return Response(status_code=202)


@router.post("/inbox")
async def shared_inbox(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.body()

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

    # 署名鍵のアクターとactivityのactorが一致するか検証
    _verify_key_actor_match(key_id, activity)

    await process_inbox_activity(db, activity)
    return Response(status_code=202)


def _verify_key_actor_match(key_id: str, activity: dict):
    """Verify that the HTTP Signature key owner matches the activity actor.

    key_id is typically like "https://example.com/users/alice#main-key".
    The actor portion is the URL before the fragment.
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
    """Route an incoming activity to the appropriate handler."""
    activity_type = activity.get("type", "")
    logger.info("Processing inbox activity: type=%s id=%s", activity_type, activity.get("id"))

    # Domain block check
    actor_id_str = activity.get("actor", "")
    if actor_id_str:
        from urllib.parse import urlparse

        from app.services.domain_block_service import is_domain_blocked

        domain = urlparse(actor_id_str).hostname
        if domain and await is_domain_blocked(db, domain):
            logger.info("Rejected activity from blocked domain: %s", domain)
            return

    # Idempotency check via Valkey
    activity_id = activity.get("id")
    if activity_id:
        from app.valkey_client import valkey

        already_seen = await valkey.set(f"seen_activity:{activity_id}", "1", nx=True, ex=86400)
        if not already_seen:
            logger.info("Duplicate activity %s, skipping", activity_id)
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
