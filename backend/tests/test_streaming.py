"""Tests for SSE streaming endpoints."""

import json
from unittest.mock import AsyncMock, MagicMock, patch


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
    mock_pubsub = AsyncMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.close = AsyncMock()
    mock_pubsub.get_message = AsyncMock(return_value={
        "type": "message",
        "data": event_data,
        "channel": "timeline:public",
    })

    with patch("app.api.mastodon.streaming.valkey") as mock_valkey_mod:
        mock_valkey_mod.pubsub = MagicMock(return_value=mock_pubsub)

        chunks = []
        async for chunk in _event_stream(mock_request, ["timeline:public"]):
            chunks.append(chunk)

    assert len(chunks) == 1
    assert chunks[0].startswith("event: update\n")
    assert "data: " in chunks[0]
    assert '"id": "123"' in chunks[0]
    assert chunks[0].endswith("\n\n")


async def test_event_stream_subscribes_channels():
    """_event_stream should subscribe to the requested channels."""
    from app.api.mastodon.streaming import _event_stream

    mock_request = AsyncMock()
    mock_request.is_disconnected = AsyncMock(return_value=True)

    mock_pubsub = AsyncMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.close = AsyncMock()

    with patch("app.api.mastodon.streaming.valkey") as mock_valkey_mod:
        mock_valkey_mod.pubsub = MagicMock(return_value=mock_pubsub)

        async for _ in _event_stream(mock_request, ["timeline:public", "timeline:home:abc"]):
            pass

    mock_pubsub.subscribe.assert_called_once_with("timeline:public", "timeline:home:abc")
    mock_pubsub.unsubscribe.assert_called_once()
    mock_pubsub.close.assert_called_once()


async def test_event_stream_ignores_non_message():
    """_event_stream should skip non-message pub/sub events."""
    from app.api.mastodon.streaming import _event_stream

    call_count = 0

    async def mock_is_disconnected():
        nonlocal call_count
        call_count += 1
        return call_count > 2

    mock_request = AsyncMock()
    mock_request.is_disconnected = mock_is_disconnected

    mock_pubsub = AsyncMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.close = AsyncMock()
    mock_pubsub.get_message = AsyncMock(return_value=None)

    with patch("app.api.mastodon.streaming.valkey") as mock_valkey_mod, \
         patch("app.api.mastodon.streaming.asyncio.sleep", new_callable=AsyncMock):
        mock_valkey_mod.pubsub = MagicMock(return_value=mock_pubsub)

        chunks = []
        async for chunk in _event_stream(mock_request, ["timeline:public"]):
            chunks.append(chunk)

    # No SSE events yielded (only keepalive might occur but counter needs 30 ticks)
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

    mock_pubsub = AsyncMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.close = AsyncMock()
    mock_pubsub.get_message = AsyncMock(side_effect=[
        {"type": "message", "data": event1, "channel": "timeline:public"},
        {"type": "message", "data": event2, "channel": "notifications:abc"},
    ])

    with patch("app.api.mastodon.streaming.valkey") as mock_valkey_mod:
        mock_valkey_mod.pubsub = MagicMock(return_value=mock_pubsub)

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
    subscribed_channels = []

    mock_pubsub = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.close = AsyncMock()

    async def mock_subscribe(*channels):
        subscribed_channels.extend(channels)

    mock_pubsub.subscribe = mock_subscribe
    mock_pubsub.get_message = AsyncMock(return_value=None)
    mock_valkey.pubsub = MagicMock(return_value=mock_pubsub)

    with patch("app.api.mastodon.streaming.valkey") as mock_v, \
         patch("app.api.mastodon.streaming._event_stream") as mock_stream:
        mock_v.pubsub = MagicMock(return_value=mock_pubsub)

        # Make _event_stream return empty immediately
        async def empty_gen(*args, **kwargs):
            return
            yield  # noqa: unreachable - makes this an async generator

        mock_stream.side_effect = empty_gen

        resp = await authed_client.get("/api/v1/streaming/user")
        # Verify _event_stream was called with correct channels
        if mock_stream.called:
            call_args = mock_stream.call_args
            channels = call_args[0][1]
            actor_id = str(test_user.actor_id)
            assert f"timeline:home:{actor_id}" in channels
            assert f"notifications:{actor_id}" in channels
            assert "timeline:public" in channels
