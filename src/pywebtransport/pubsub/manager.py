"""Publish-Subscribe messaging pattern manager."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from types import TracebackType
from typing import Self

from pywebtransport.constants import ErrorCodes
from pywebtransport.exceptions import ConnectionError, StreamError
from pywebtransport.pubsub.exceptions import NotSubscribedError, PubSubError, SubscriptionFailedError
from pywebtransport.stream.stream import WebTransportStream
from pywebtransport.types import Data
from pywebtransport.utils import ensure_bytes, get_logger, get_timestamp

__all__: list[str] = ["PubSubManager", "PubSubStats", "Subscription"]

logger = get_logger(name=__name__)


@dataclass(kw_only=True)
class PubSubStats:
    """Represents statistics for the Pub/Sub manager."""

    created_at: float = field(default_factory=get_timestamp)
    topics_subscribed: int = 0
    messages_published: int = 0
    messages_received: int = 0
    subscription_errors: int = 0

    def to_dict(self) -> dict[str, float | int]:
        """Convert statistics to a dictionary."""
        return {
            "created_at": self.created_at,
            "topics_subscribed": self.topics_subscribed,
            "messages_published": self.messages_published,
            "messages_received": self.messages_received,
            "subscription_errors": self.subscription_errors,
        }


class Subscription:
    """Represents a subscription to a single topic."""

    def __init__(self, *, topic: str, manager: PubSubManager, max_queue_size: int) -> None:
        """Initialize the Subscription."""
        self._topic = topic
        self._manager = manager
        self._max_queue_size = max_queue_size
        self._queue: asyncio.Queue[bytes | None] | None = None

    async def __aenter__(self) -> Self:
        """Enter the async context and initialize the message queue."""
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=self._max_queue_size)
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        """Exit the async context and unsubscribe."""
        await self.unsubscribe()

    async def unsubscribe(self) -> None:
        """Unsubscribe from the topic."""
        await self._manager.unsubscribe(topic=self._topic)

    def __aiter__(self) -> AsyncIterator[bytes]:
        """Return self as the asynchronous iterator."""
        return self

    async def __anext__(self) -> bytes:
        """Get the next message in the async iteration."""
        if self._queue is None:
            raise PubSubError(
                message=(
                    "Subscription has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        try:
            message = await self._queue.get()
            if message is None:
                raise StopAsyncIteration
            return message
        except asyncio.CancelledError:
            raise StopAsyncIteration


class PubSubManager:
    """Manages the Pub/Sub lifecycle over a single WebTransport session."""

    def __init__(self, *, stream: WebTransportStream, max_queue_size: int) -> None:
        """Initialize the PubSubManager."""
        self._stream: WebTransportStream = stream
        self._default_max_queue_size = max_queue_size
        self._ingress_task: asyncio.Task[None] | None = None
        self._lock: asyncio.Lock | None = None
        self._subscriptions: dict[str, set[Subscription]] = defaultdict(set)
        self._pending_subscriptions: dict[str, tuple[asyncio.Future[Subscription], Subscription]] = {}
        self._stats = PubSubStats()
        self._is_closing = False

    @property
    def stats(self) -> PubSubStats:
        """Get the current statistics for the Pub/Sub manager."""
        return self._stats

    async def __aenter__(self) -> Self:
        """Enter the async context, ensuring the manager is initialized."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        if self._ingress_task is None:
            self._ingress_task = asyncio.create_task(coro=self._ingress_loop())
            self._ingress_task.add_done_callback(self._on_ingress_done)
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        """Exit the async context, closing the manager."""
        await self.close()

    async def close(self) -> None:
        """Close the Pub/Sub manager and its underlying resources."""
        if self._is_closing:
            return

        self._is_closing = True

        if self._ingress_task and not self._ingress_task.done():
            self._ingress_task.cancel()
        if self._stream and not self._stream.is_closed:
            await self._stream.close(error_code=ErrorCodes.APPLICATION_ERROR)

        for future, _ in self._pending_subscriptions.values():
            if not future.done():
                future.set_exception(PubSubError(message="PubSubManager is closing."))
        for subs in self._subscriptions.values():
            for sub in subs:
                if sub._queue and not sub._queue.full():
                    sub._queue.put_nowait(item=None)

        self._pending_subscriptions.clear()
        self._subscriptions.clear()

    async def publish(self, *, topic: str, data: Data) -> None:
        """Publish a message to a topic."""
        if self._lock is None:
            raise PubSubError(
                message=(
                    "PubSubManager has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        async with self._lock:
            if self._stream.is_closed:
                raise PubSubError(message="Pub/Sub stream is not available.")

            data_bytes = ensure_bytes(data=data)
            command = b"PUB %b %d\n" % (topic.encode(), len(data_bytes))

            await self._stream.write(data=command + data_bytes)
            self._stats.messages_published += 1

    async def subscribe(self, *, topic: str, timeout: float = 10.0, max_queue_size: int | None = None) -> Subscription:
        """Subscribe to a topic and return a subscription object."""
        if self._lock is None:
            raise PubSubError(
                message=(
                    "PubSubManager has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        actual_queue_size = max_queue_size if max_queue_size is not None else self._default_max_queue_size
        if actual_queue_size <= 0:
            raise ValueError("max_queue_size must be positive.")

        async with self._lock:
            if topic in self._pending_subscriptions:
                raise PubSubError(message=f"Subscription to topic '{topic}' is already pending.")

            future: asyncio.Future[Subscription] = asyncio.get_running_loop().create_future()
            subscription = Subscription(topic=topic, manager=self, max_queue_size=actual_queue_size)
            self._pending_subscriptions[topic] = (future, subscription)

        if self._stream.is_closed:
            raise PubSubError(message="Pub/Sub stream is not available.")
        await self._stream.write(data=b"SUB %b\n" % topic.encode())

        try:
            async with asyncio.timeout(delay=timeout):
                confirmed_subscription = await future
            async with self._lock:
                self._subscriptions[topic].add(confirmed_subscription)
                self._stats.topics_subscribed = len(self._subscriptions)
            return confirmed_subscription
        except asyncio.TimeoutError:
            self._stats.subscription_errors += 1
            async with self._lock:
                self._pending_subscriptions.pop(topic, None)
            future.cancel()
            raise SubscriptionFailedError(message=f"Subscription to topic '{topic}' timed out.") from None
        except Exception:
            self._stats.subscription_errors += 1
            async with self._lock:
                self._pending_subscriptions.pop(topic, None)
            raise

    async def unsubscribe(self, *, topic: str) -> None:
        """Unsubscribe from a topic."""
        if self._lock is None:
            raise PubSubError(
                message=(
                    "PubSubManager has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        async with self._lock:
            if not self._subscriptions.get(topic):
                return

            if self._stream.is_closed:
                raise NotSubscribedError(message="Pub/Sub stream is not available to unsubscribe.")

            await self._stream.write(data=b"UNSUB %b\n" % topic.encode())

            for sub in self._subscriptions.get(topic, set()):
                if sub._queue and not sub._queue.full():
                    sub._queue.put_nowait(item=None)

            self._subscriptions.pop(topic, None)
            self._stats.topics_subscribed = len(self._subscriptions)

    async def _ingress_loop(self) -> None:
        """Read and dispatch incoming messages and signals."""
        try:
            while not self._stream.is_closed:
                line = await self._stream.readline()
                if not line:
                    break

                parts = line.strip().split(b" ", 2)
                command = parts[0]

                if command == b"MSG" and len(parts) == 3:
                    topic, length_str = parts[1].decode(), parts[2]
                    length = int(length_str)
                    payload = await self._stream.readexactly(n=length)
                    if self._lock:
                        async with self._lock:
                            subs = self._subscriptions.get(topic)
                        if subs:
                            self._stats.messages_received += 1
                            for sub in subs.copy():
                                if sub._queue:
                                    try:
                                        sub._queue.put_nowait(item=payload)
                                    except asyncio.QueueFull:
                                        logger.warning(
                                            "Subscription queue for topic '%s' is full. Dropping message.", topic
                                        )
                elif command == b"SUB-OK" and len(parts) == 2:
                    topic = parts[1].decode()
                    if self._lock:
                        async with self._lock:
                            pending = self._pending_subscriptions.pop(topic, None)
                        if pending:
                            future, subscription = pending
                            if not future.done():
                                future.set_result(subscription)
                elif command == b"SUB-FAIL" and len(parts) == 3:
                    topic, reason = parts[1].decode(), parts[2].decode()
                    if self._lock:
                        async with self._lock:
                            pending = self._pending_subscriptions.pop(topic, None)
                        if pending:
                            future, _ = pending
                            if not future.done():
                                future.set_exception(SubscriptionFailedError(message=reason))
        except (ConnectionError, StreamError, asyncio.IncompleteReadError) as e:
            logger.info("Pub/Sub stream closed: %s", e)
        except Exception as e:
            if not self._is_closing:
                logger.error("Error in Pub/Sub ingress loop: %s", e, exc_info=True)
                raise

    def _on_ingress_done(self, task: asyncio.Task[None]) -> None:
        """Callback to trigger cleanup when the ingress task finishes."""
        if self._is_closing:
            return

        if not task.cancelled():
            if exc := task.exception():
                logger.error("Pub/Sub ingress task finished unexpectedly with an exception: %s.", exc, exc_info=exc)

        if not self._is_closing:
            asyncio.create_task(coro=self.close())
