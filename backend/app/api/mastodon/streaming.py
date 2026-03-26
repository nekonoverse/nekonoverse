"""SSE streaming endpoints for real-time timeline and notification updates."""

import asyncio
import collections
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.pubsub_hub import pubsub_hub

router = APIRouter(prefix="/api/v1/streaming", tags=["streaming"])

KEEPALIVE_INTERVAL = 30  # seconds

_EVENT_TYPE_RE = re.compile(r"^[a-zA-Z0-9_.]+$")

# H-2: IPあたり・ユーザーあたりのSSE同時接続数制限
MAX_SSE_PER_IP = 10
MAX_SSE_PER_USER = 5
_sse_ip_counts: dict[str, int] = collections.defaultdict(int)
_sse_user_counts: dict[str, int] = collections.defaultdict(int)


async def _event_stream(request: Request, channels: list[str]):
    """Generic SSE event stream using the shared PubSubHub."""
    queue = await pubsub_hub.subscribe(channels)
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                # L-7: ポーリングからイベント駆動に変更
                msg = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_INTERVAL)
                data = json.loads(msg["data"])
                event_type = data.get("event", "update")
                if not _EVENT_TYPE_RE.match(event_type):
                    event_type = "update"
                payload = json.dumps(data.get("payload", {}))
                yield f"event: {event_type}\ndata: {payload}\n\n"
            except asyncio.TimeoutError:
                yield ":\n\n"  # keepalive
    finally:
        await pubsub_hub.unsubscribe(queue, channels)


def _sse_response(request: Request, channels: list[str], *, user_id: str | None = None):
    client_ip = request.client.host if request.client else "unknown"
    if _sse_ip_counts[client_ip] >= MAX_SSE_PER_IP:
        raise HTTPException(status_code=429, detail="Too many SSE connections")
    if user_id and _sse_user_counts[user_id] >= MAX_SSE_PER_USER:
        raise HTTPException(status_code=429, detail="Too many SSE connections")

    async def _tracked_stream():
        _sse_ip_counts[client_ip] += 1
        if user_id:
            _sse_user_counts[user_id] += 1
        try:
            async for chunk in _event_stream(request, channels):
                yield chunk
        finally:
            _sse_ip_counts[client_ip] -= 1
            if _sse_ip_counts[client_ip] <= 0:
                _sse_ip_counts.pop(client_ip, None)
            if user_id:
                _sse_user_counts[user_id] -= 1
                if _sse_user_counts[user_id] <= 0:
                    _sse_user_counts.pop(user_id, None)

    return StreamingResponse(
        _tracked_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/user")
async def stream_user(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE stream for authenticated user: home timeline + notifications + lists."""
    from app.services.list_service import get_user_lists

    actor_id = str(user.actor_id)
    channels = [
        f"timeline:home:{actor_id}",
        f"notifications:{actor_id}",
        "timeline:public",
        "emoji:update",
    ]
    user_lists = await get_user_lists(db, user.id)
    for lst in user_lists:
        channels.append(f"timeline:list:{lst.id}")
    return _sse_response(request, channels, user_id=str(user.id))


@router.get("/list")
async def stream_list(
    request: Request,
    list: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE stream for a specific list timeline."""
    import uuid as _uuid

    from app.services.list_service import get_list as get_list_

    try:
        list_id = _uuid.UUID(list)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid list ID")
    lst = await get_list_(db, list_id)
    if not lst or lst.user_id != user.id:
        raise HTTPException(status_code=404, detail="List not found")
    return _sse_response(request, [f"timeline:list:{list}"], user_id=str(user.id))


@router.get("/public")
async def stream_public(request: Request):
    """SSE stream for public timeline (no auth required)."""
    return _sse_response(request, ["timeline:public", "emoji:update"])
