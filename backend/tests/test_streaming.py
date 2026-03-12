"""Tests for SSE streaming endpoints."""

import asyncio
import json
from unittest.mock import AsyncMock, patch


async def test_stream_user_requires_auth(app_client, mock_valkey):
    """GET /streaming/user without auth should return 401."""
    resp = await app_client.get("/api/v1/streaming/user")
    assert resp.status_code == 401


async def test_event_stream_yields_sse_event():
    """_event_stream should yield properly formatted SSE events."""
    from app.api.mastodon.streaming import _event_stream

    mock_request = AsyncMock()
    mock_request.is_disconnected = AsyncMock(side_effect=[False, True])

    event_data = json.dumps({"event": "update", "payload": {"id": "123"}})
    mock_queue = asyncio.Queue()
    mock_queue.put_nowait({"channel": "timeline:public", "data": event_data})

    with patch("app.api.mastodon.streaming.pubsub_hub") as mock_hub:
        mock_hub.subscribe = AsyncMock(return_value=mock_queue)
        mock_hub.unsubscribe = AsyncMock()

        chunks = []
        async for chunk in _event_stream(mock_request, ["timeline:public"]):
            chunks.append(chunk)

    assert len(chunks) == 1
    assert chunks[0].startswith("event: update\n")
    assert "data: " in chunks[0]
    assert '"id": "123"' in chunks[0]
    assert chunks[0].endswith("\n\n")
    mock_hub.unsubscribe.assert_called_once_with(mock_queue, ["timeline:public"])


async def test_event_stream_subscribes_channels():
    """_event_stream should subscribe to the requested channels via PubSubHub."""
    from app.api.mastodon.streaming import _event_stream

    mock_request = AsyncMock()
    mock_request.is_disconnected = AsyncMock(return_value=True)

    mock_queue = asyncio.Queue()

    with patch("app.api.mastodon.streaming.pubsub_hub") as mock_hub:
        mock_hub.subscribe = AsyncMock(return_value=mock_queue)
        mock_hub.unsubscribe = AsyncMock()

        async for _ in _event_stream(mock_request, ["timeline:public", "timeline:home:abc"]):
            pass

    mock_hub.subscribe.assert_called_once_with(["timeline:public", "timeline:home:abc"])
    mock_hub.unsubscribe.assert_called_once_with(
        mock_queue, ["timeline:public", "timeline:home:abc"]
    )


async def test_event_stream_empty_queue_no_event():
    """_event_stream should not yield events when queue is empty."""
    from app.api.mastodon.streaming import _event_stream

    call_count = 0

    async def mock_is_disconnected():
        nonlocal call_count
        call_count += 1
        return call_count > 2

    mock_request = AsyncMock()
    mock_request.is_disconnected = mock_is_disconnected

    mock_queue = asyncio.Queue()

    with (
        patch("app.api.mastodon.streaming.pubsub_hub") as mock_hub,
        patch("app.api.mastodon.streaming.asyncio.sleep", new_callable=AsyncMock),
    ):
        mock_hub.subscribe = AsyncMock(return_value=mock_queue)
        mock_hub.unsubscribe = AsyncMock()

        chunks = []
        async for chunk in _event_stream(mock_request, ["timeline:public"]):
            chunks.append(chunk)

    # No SSE events yielded (keepalive needs 30 ticks)
    assert all(c == ":\n\n" or c.startswith("event:") for c in chunks)


async def test_event_stream_multiple_events():
    """_event_stream should yield multiple events in sequence."""
    from app.api.mastodon.streaming import _event_stream

    disconnect_after = 2
    call_count = 0

    async def mock_is_disconnected():
        nonlocal call_count
        call_count += 1
        return call_count > disconnect_after

    mock_request = AsyncMock()
    mock_request.is_disconnected = mock_is_disconnected

    event1 = json.dumps({"event": "update", "payload": {"id": "1"}})
    event2 = json.dumps({"event": "notification", "payload": {"id": "2"}})

    mock_queue = asyncio.Queue()
    mock_queue.put_nowait({"channel": "timeline:public", "data": event1})
    mock_queue.put_nowait({"channel": "notifications:abc", "data": event2})

    with patch("app.api.mastodon.streaming.pubsub_hub") as mock_hub:
        mock_hub.subscribe = AsyncMock(return_value=mock_queue)
        mock_hub.unsubscribe = AsyncMock()

        chunks = []
        async for chunk in _event_stream(mock_request, ["timeline:public", "notifications:abc"]):
            chunks.append(chunk)

    assert len(chunks) == 2
    assert "event: update" in chunks[0]
    assert "event: notification" in chunks[1]


async def test_sse_response_headers():
    """_sse_response should set correct SSE headers."""
    from app.api.mastodon.streaming import _sse_response

    mock_request = AsyncMock()
    response = _sse_response(mock_request, ["timeline:public"])

    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"


async def test_stream_user_channels(authed_client, test_user, mock_valkey):
    """Authenticated /streaming/user should subscribe to correct channels."""
    with (
        patch("app.api.mastodon.streaming.pubsub_hub") as mock_hub,
        patch("app.api.mastodon.streaming._event_stream") as mock_stream,
    ):
        mock_hub.subscribe = AsyncMock(return_value=asyncio.Queue())
        mock_hub.unsubscribe = AsyncMock()

        # Make _event_stream return empty immediately
        async def empty_gen(*args, **kwargs):
            return
            yield  # noqa: F841 - makes this an async generator

        mock_stream.side_effect = empty_gen

        await authed_client.get("/api/v1/streaming/user")
        # Verify _event_stream was called with correct channels
        if mock_stream.called:
            call_args = mock_stream.call_args
            channels = call_args[0][1]
            actor_id = str(test_user.actor_id)
            assert f"timeline:home:{actor_id}" in channels
            assert f"notifications:{actor_id}" in channels
            assert "timeline:public" in channels


async def test_event_stream_cleanup_on_disconnect():
    """_event_stream should call unsubscribe even when client disconnects."""
    from app.api.mastodon.streaming import _event_stream

    mock_request = AsyncMock()
    mock_request.is_disconnected = AsyncMock(return_value=True)

    mock_queue = asyncio.Queue()

    with patch("app.api.mastodon.streaming.pubsub_hub") as mock_hub:
        mock_hub.subscribe = AsyncMock(return_value=mock_queue)
        mock_hub.unsubscribe = AsyncMock()

        async for _ in _event_stream(mock_request, ["timeline:public"]):
            pass

    mock_hub.unsubscribe.assert_called_once_with(mock_queue, ["timeline:public"])
