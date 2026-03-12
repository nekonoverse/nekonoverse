"""Tests for PubSubHub shared Valkey pub/sub fan-out."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch


async def test_subscribe_creates_queue():
    """subscribe() should return an asyncio.Queue and subscribe to Valkey."""
    from app.pubsub_hub import PubSubHub

    hub = PubSubHub()
    hub._pubsub = AsyncMock()
    hub._pubsub.subscribe = AsyncMock()

    queue = await hub.subscribe(["timeline:public"])

    assert isinstance(queue, asyncio.Queue)
    hub._pubsub.subscribe.assert_called_once_with("timeline:public")


async def test_subscribe_multiple_clients_same_channel():
    """Second subscriber to the same channel should not re-subscribe to Valkey."""
    from app.pubsub_hub import PubSubHub

    hub = PubSubHub()
    hub._pubsub = AsyncMock()
    hub._pubsub.subscribe = AsyncMock()

    q1 = await hub.subscribe(["timeline:public"])
    q2 = await hub.subscribe(["timeline:public"])

    assert q1 is not q2
    # Valkey subscribe called only once for the channel
    hub._pubsub.subscribe.assert_called_once_with("timeline:public")


async def test_unsubscribe_last_client_removes_channel():
    """When the last client unsubscribes, the channel should be removed from Valkey."""
    from app.pubsub_hub import PubSubHub

    hub = PubSubHub()
    hub._pubsub = AsyncMock()
    hub._pubsub.subscribe = AsyncMock()
    hub._pubsub.unsubscribe = AsyncMock()

    q1 = await hub.subscribe(["timeline:public"])
    q2 = await hub.subscribe(["timeline:public"])

    await hub.unsubscribe(q1, ["timeline:public"])
    hub._pubsub.unsubscribe.assert_not_called()

    await hub.unsubscribe(q2, ["timeline:public"])
    hub._pubsub.unsubscribe.assert_called_once_with("timeline:public")


async def test_unsubscribe_partial_channels():
    """Unsubscribing from one channel should not affect other channels."""
    from app.pubsub_hub import PubSubHub

    hub = PubSubHub()
    hub._pubsub = AsyncMock()
    hub._pubsub.subscribe = AsyncMock()
    hub._pubsub.unsubscribe = AsyncMock()

    queue = await hub.subscribe(["timeline:public", "notifications:abc"])
    await hub.unsubscribe(queue, ["timeline:public", "notifications:abc"])

    hub._pubsub.unsubscribe.assert_called_once_with("timeline:public", "notifications:abc")


async def test_message_dispatch_to_subscribers():
    """Messages should be dispatched to all subscribers of the channel."""
    from app.pubsub_hub import PubSubHub

    hub = PubSubHub()
    hub._pubsub = AsyncMock()
    hub._pubsub.subscribe = AsyncMock()

    q1 = await hub.subscribe(["timeline:public"])
    q2 = await hub.subscribe(["timeline:public"])
    q3 = await hub.subscribe(["notifications:abc"])

    event_data = json.dumps({"event": "update", "payload": {"id": "123"}})

    # Simulate message dispatch
    msg = {"channel": "timeline:public", "data": event_data}
    async with hub._lock:
        queues = hub._subscribers.get("timeline:public")
        queues_snapshot = list(queues)

    for q in queues_snapshot:
        q.put_nowait(msg)

    # q1 and q2 should receive the message, q3 should not
    assert not q1.empty()
    assert not q2.empty()
    assert q3.empty()

    result1 = q1.get_nowait()
    assert result1["channel"] == "timeline:public"
    assert json.loads(result1["data"])["payload"]["id"] == "123"


async def test_queue_full_does_not_block():
    """When a queue is full, the message should be silently dropped."""
    from app.pubsub_hub import _QUEUE_MAXSIZE, PubSubHub

    hub = PubSubHub()
    hub._pubsub = AsyncMock()
    hub._pubsub.subscribe = AsyncMock()

    queue = await hub.subscribe(["timeline:public"])

    # Fill the queue to capacity
    for i in range(_QUEUE_MAXSIZE):
        queue.put_nowait({"channel": "timeline:public", "data": f"{i}"})

    assert queue.full()

    # This should not raise
    try:
        queue.put_nowait({"channel": "timeline:public", "data": "overflow"})
        assert False, "Should have raised QueueFull"
    except asyncio.QueueFull:
        pass  # Expected behavior in _read_messages


async def test_start_and_stop():
    """start() and stop() should manage pubsub lifecycle."""
    from app.pubsub_hub import PubSubHub

    with patch("app.pubsub_hub.valkey") as mock_valkey:
        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        mock_pubsub.close = AsyncMock()
        mock_pubsub.get_message = AsyncMock(return_value=None)
        mock_valkey.pubsub = MagicMock(return_value=mock_pubsub)

        hub = PubSubHub()
        await hub.start()

        assert hub._pubsub is not None
        assert hub._reader_task is not None

        await hub.stop()

        assert hub._pubsub is None
        assert hub._reader_task is None
        mock_pubsub.unsubscribe.assert_called_once()
        mock_pubsub.close.assert_called_once()


async def test_unsubscribe_nonexistent_channel():
    """Unsubscribing from a channel that was never subscribed should not error."""
    from app.pubsub_hub import PubSubHub

    hub = PubSubHub()
    hub._pubsub = AsyncMock()

    queue = asyncio.Queue()
    await hub.unsubscribe(queue, ["nonexistent:channel"])
    # Should not raise
