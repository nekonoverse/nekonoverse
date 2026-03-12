"""Shared Valkey Pub/Sub hub that fans out messages to per-client queues.

Instead of creating one Valkey pubsub connection per SSE client,
PubSubHub maintains a single shared connection and routes messages
to asyncio.Queue instances registered by each client.
"""

import asyncio
import logging

from valkey.asyncio.client import PubSub

from app.valkey_client import valkey

logger = logging.getLogger(__name__)

# キューが溢れた場合に古いメッセージを捨てるための上限
_QUEUE_MAXSIZE = 256


class PubSubHub:
    """Singleton hub managing a single Valkey pubsub connection."""

    def __init__(self) -> None:
        # channel -> set of asyncio.Queue
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._pubsub: PubSub | None = None
        self._reader_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the background reader task."""
        self._pubsub = valkey.pubsub()
        self._reader_task = asyncio.create_task(self._reader_loop())
        logger.info("PubSubHub started")

    async def stop(self) -> None:
        """Stop the background reader and close the pubsub connection."""
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()
            self._pubsub = None

        self._subscribers.clear()
        logger.info("PubSubHub stopped")

    async def subscribe(self, channels: list[str]) -> asyncio.Queue:
        """Register a new listener for the given channels.

        Returns an asyncio.Queue that will receive messages
        as dicts with 'channel' and 'data' keys.
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        async with self._lock:
            new_channels = []
            for ch in channels:
                if ch not in self._subscribers:
                    self._subscribers[ch] = set()
                    new_channels.append(ch)
                self._subscribers[ch].add(queue)

            if new_channels and self._pubsub:
                await self._pubsub.subscribe(*new_channels)

        return queue

    async def unsubscribe(self, queue: asyncio.Queue, channels: list[str]) -> None:
        """Remove a listener from the given channels.

        Unsubscribes from Valkey when the last listener leaves a channel.
        """
        async with self._lock:
            orphaned_channels = []
            for ch in channels:
                subs = self._subscribers.get(ch)
                if subs is None:
                    continue
                subs.discard(queue)
                if not subs:
                    del self._subscribers[ch]
                    orphaned_channels.append(ch)

            if orphaned_channels and self._pubsub:
                await self._pubsub.unsubscribe(*orphaned_channels)

    async def _reader_loop(self) -> None:
        """Background loop: read from Valkey pubsub and dispatch to queues."""
        while True:
            try:
                await self._read_messages()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("PubSubHub reader error, reconnecting in 1s")
                await asyncio.sleep(1)
                await self._reconnect()

    async def _read_messages(self) -> None:
        """Read messages from the shared pubsub connection."""
        while True:
            if not self._pubsub:
                await asyncio.sleep(0.1)
                continue

            msg = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg is None or msg["type"] != "message":
                continue

            channel = msg["channel"]
            data = msg["data"]

            async with self._lock:
                queues = self._subscribers.get(channel)
                if not queues:
                    continue
                # コピーしてロック外でも安全にイテレートする
                queues_snapshot = list(queues)

            for q in queues_snapshot:
                try:
                    q.put_nowait({"channel": channel, "data": data})
                except asyncio.QueueFull:
                    # 遅いクライアントは最新メッセージを優先するためスキップ
                    pass

    async def _reconnect(self) -> None:
        """Reconnect to Valkey and re-subscribe to all active channels."""
        try:
            if self._pubsub:
                await self._pubsub.close()
        except Exception:
            pass

        self._pubsub = valkey.pubsub()
        async with self._lock:
            channels = list(self._subscribers.keys())
        if channels:
            await self._pubsub.subscribe(*channels)
            logger.info("PubSubHub reconnected, re-subscribed to %d channels", len(channels))


# グローバルインスタンス
pubsub_hub = PubSubHub()
