"""Tests for emoji update SSE events via Valkey pub/sub."""

import json

import pytest


async def test_create_emoji_publishes_event(db, test_user, mock_valkey):
    """create_local_emoji should publish emoji_update event."""
    from app.services.emoji_service import create_local_emoji

    await create_local_emoji(db, "test_emoji", "https://example.com/emoji.png")

    calls = mock_valkey.publish.call_args_list
    channels = [c.args[0] for c in calls]
    assert "emoji:update" in channels

    for call in calls:
        if call.args[0] == "emoji:update":
            event = json.loads(call.args[1])
            assert event["event"] == "emoji_update"
            assert event["payload"] == {}


async def test_update_emoji_publishes_event(db, test_user, mock_valkey):
    """update_emoji should publish emoji_update event."""
    from app.services.emoji_service import create_local_emoji, update_emoji

    emoji = await create_local_emoji(db, "update_test", "https://example.com/emoji.png")
    mock_valkey.publish.reset_mock()

    await update_emoji(db, emoji.id, {"category": "test"})

    calls = mock_valkey.publish.call_args_list
    channels = [c.args[0] for c in calls]
    assert "emoji:update" in channels


async def test_delete_emoji_publishes_event(db, test_user, mock_valkey):
    """delete_emoji should publish emoji_update event."""
    from app.services.emoji_service import create_local_emoji, delete_emoji

    emoji = await create_local_emoji(db, "delete_test", "https://example.com/emoji.png")
    mock_valkey.publish.reset_mock()

    await delete_emoji(db, emoji.id)

    calls = mock_valkey.publish.call_args_list
    channels = [c.args[0] for c in calls]
    assert "emoji:update" in channels


async def test_streaming_user_subscribes_emoji_channel(authed_client, test_user, mock_valkey):
    """User stream should subscribe to emoji:update channel."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    with (
        patch("app.api.mastodon.streaming.pubsub_hub") as mock_hub,
        patch("app.api.mastodon.streaming._event_stream") as mock_stream,
    ):
        mock_hub.subscribe = AsyncMock(return_value=asyncio.Queue())
        mock_hub.unsubscribe = AsyncMock()

        async def empty_gen(*args, **kwargs):
            return
            yield

        mock_stream.side_effect = empty_gen

        await authed_client.get("/api/v1/streaming/user")
        if mock_stream.called:
            channels = mock_stream.call_args[0][1]
            assert "emoji:update" in channels


async def test_streaming_public_subscribes_emoji_channel(app_client, mock_valkey):
    """Public stream should subscribe to emoji:update channel."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    with (
        patch("app.api.mastodon.streaming.pubsub_hub") as mock_hub,
        patch("app.api.mastodon.streaming._event_stream") as mock_stream,
    ):
        mock_hub.subscribe = AsyncMock(return_value=asyncio.Queue())
        mock_hub.unsubscribe = AsyncMock()

        async def empty_gen(*args, **kwargs):
            return
            yield

        mock_stream.side_effect = empty_gen

        await app_client.get("/api/v1/streaming/public")
        if mock_stream.called:
            channels = mock_stream.call_args[0][1]
            assert "emoji:update" in channels
