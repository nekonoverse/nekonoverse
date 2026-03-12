"""SSE streaming endpoints for real-time timeline and notification updates."""

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.dependencies import get_current_user
from app.models.user import User
from app.pubsub_hub import pubsub_hub

router = APIRouter(prefix="/api/v1/streaming", tags=["streaming"])

KEEPALIVE_INTERVAL = 30  # seconds


async def _event_stream(request: Request, channels: list[str]):
    """Generic SSE event stream using the shared PubSubHub."""
    queue = await pubsub_hub.subscribe(channels)
    keepalive_counter = 0
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                msg = queue.get_nowait()
                data = json.loads(msg["data"])
                event_type = data.get("event", "update")
                payload = json.dumps(data.get("payload", {}))
                yield f"event: {event_type}\ndata: {payload}\n\n"
                keepalive_counter = 0
            except asyncio.QueueEmpty:
                keepalive_counter += 1
                if keepalive_counter >= KEEPALIVE_INTERVAL:
                    yield ":\n\n"
                    keepalive_counter = 0
                await asyncio.sleep(1)
    finally:
        await pubsub_hub.unsubscribe(queue, channels)


def _sse_response(request: Request, channels: list[str]):
    return StreamingResponse(
        _event_stream(request, channels),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/user")
async def stream_user(request: Request, user: User = Depends(get_current_user)):
    """SSE stream for authenticated user: home timeline + notifications."""
    actor_id = str(user.actor_id)
    return _sse_response(
        request,
        [
            f"timeline:home:{actor_id}",
            f"notifications:{actor_id}",
            "timeline:public",
        ],
    )


@router.get("/public")
async def stream_public(request: Request):
    """SSE stream for public timeline (no auth required)."""
    return _sse_response(request, ["timeline:public"])
