"""WebTransport Datagram Transport."""

from __future__ import annotations

import asyncio
import json
import struct
import time
import weakref
from collections import deque
from dataclasses import dataclass, field
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self, cast

from pywebtransport.events import Event, EventEmitter, EventType
from pywebtransport.exceptions import DatagramError, TimeoutError, datagram_too_large
from pywebtransport.types import Data, SessionId
from pywebtransport.utils import calculate_checksum, ensure_bytes, get_logger, get_timestamp

if TYPE_CHECKING:
    from pywebtransport.session import WebTransportSession


__all__ = [
    "DatagramMessage",
    "DatagramQueue",
    "DatagramStats",
    "WebTransportDatagramTransport",
]

logger = get_logger(name="datagram.transport")


@dataclass(kw_only=True)
class DatagramMessage:
    """Represents a datagram message with metadata."""

    data: bytes
    timestamp: float = field(default_factory=get_timestamp)
    size: int = field(init=False)
    checksum: str | None = None
    sequence: int | None = None
    priority: int = 0
    ttl: float | None = None

    def __post_init__(self) -> None:
        """Initialize computed fields after object creation."""
        self.size = len(self.data)
        if self.checksum is None:
            self.checksum = calculate_checksum(data=self.data)[:8]

    @property
    def is_expired(self) -> bool:
        """Check if the datagram has expired based on its TTL."""
        if self.ttl is None:
            return False
        return (get_timestamp() - self.timestamp) > self.ttl

    @property
    def age(self) -> float:
        """Get the current age of the datagram in seconds."""
        return get_timestamp() - self.timestamp

    def to_dict(self) -> dict[str, Any]:
        """Convert the datagram message and its metadata to a dictionary."""
        return {
            "size": self.size,
            "timestamp": self.timestamp,
            "age": self.age,
            "checksum": self.checksum,
            "sequence": self.sequence,
            "priority": self.priority,
            "ttl": self.ttl,
            "is_expired": self.is_expired,
        }


@dataclass(kw_only=True)
class DatagramStats:
    """Provides statistics for datagram transport."""

    session_id: SessionId
    created_at: float
    datagrams_sent: int = 0
    bytes_sent: int = 0
    send_failures: int = 0
    send_drops: int = 0
    datagrams_received: int = 0
    bytes_received: int = 0
    receive_drops: int = 0
    receive_errors: int = 0
    total_send_time: float = 0.0
    total_receive_time: float = 0.0
    max_send_time: float = 0.0
    max_receive_time: float = 0.0
    min_datagram_size: float = float("inf")
    max_datagram_size: int = 0
    total_datagram_size: int = 0

    @property
    def avg_datagram_size(self) -> float:
        """Get the average size of all datagrams."""
        total_datagrams = self.datagrams_sent + self.datagrams_received
        return self.total_datagram_size / max(1, total_datagrams)

    @property
    def avg_receive_time(self) -> float:
        """Get the average receive time for datagrams."""
        return self.total_receive_time / max(1, self.datagrams_received)

    @property
    def avg_send_time(self) -> float:
        """Get the average send time for datagrams."""
        return self.total_send_time / max(1, self.datagrams_sent)

    @property
    def receive_success_rate(self) -> float:
        """Get the success rate of receiving datagrams."""
        total_received = self.datagrams_received + self.receive_errors
        if total_received == 0:
            return 1.0
        return self.datagrams_received / total_received

    @property
    def send_success_rate(self) -> float:
        """Get the success rate of sending datagrams."""
        total_attempts = self.datagrams_sent + self.send_failures
        if total_attempts == 0:
            return 1.0
        return self.datagrams_sent / total_attempts

    def to_dict(self) -> dict[str, Any]:
        """Convert statistics to a dictionary."""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "datagrams_sent": self.datagrams_sent,
            "bytes_sent": self.bytes_sent,
            "send_failures": self.send_failures,
            "send_drops": self.send_drops,
            "datagrams_received": self.datagrams_received,
            "bytes_received": self.bytes_received,
            "receive_drops": self.receive_drops,
            "receive_errors": self.receive_errors,
            "avg_send_time": self.avg_send_time,
            "avg_receive_time": self.avg_receive_time,
            "max_send_time": self.max_send_time,
            "max_receive_time": self.max_receive_time,
            "avg_datagram_size": self.avg_datagram_size,
            "min_datagram_size": self.min_datagram_size if self.min_datagram_size != float("inf") else 0,
            "max_datagram_size": self.max_datagram_size,
            "send_success_rate": self.send_success_rate,
            "receive_success_rate": self.receive_success_rate,
        }


class DatagramQueue:
    """A priority queue for datagrams with size and TTL limits."""

    def __init__(self, *, max_size: int = 1000, max_age: float | None = None) -> None:
        """Initialize the datagram queue."""
        self._max_size = max_size
        self._max_age = max_age
        self._lock: asyncio.Lock | None = None
        self._not_empty: asyncio.Event | None = None
        self._size = 0
        self._priority_queues: dict[int, deque[DatagramMessage]] = {
            0: deque(),
            1: deque(),
            2: deque(),
        }
        self._cleanup_task: asyncio.Task[None] | None = None

    async def initialize(self) -> None:
        """Initialize asyncio resources for the queue."""
        self._lock = asyncio.Lock()
        self._not_empty = asyncio.Event()
        self._start_cleanup()

    async def close(self) -> None:
        """Close the queue and clean up background tasks."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        await self.clear()

    async def get(self, *, timeout: float | None = None) -> DatagramMessage:
        """Get a datagram from the queue, waiting if it's empty."""
        if self._lock is None or self._not_empty is None:
            raise DatagramError(
                message="DatagramQueue has not been initialized. Its owner must call 'await queue.initialize()'."
            )

        async def _wait_for_item() -> DatagramMessage:
            if self._lock is None or self._not_empty is None:
                raise DatagramError(
                    message="DatagramQueue has not been initialized. Its owner must call 'await queue.initialize()'."
                )

            while True:
                async with self._lock:
                    for priority in [2, 1, 0]:
                        if self._priority_queues[priority]:
                            datagram = self._priority_queues[priority].popleft()
                            self._size -= 1
                            if self._size == 0:
                                self._not_empty.clear()
                            return datagram
                await self._not_empty.wait()

        try:
            return await asyncio.wait_for(_wait_for_item(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(message=f"Datagram get timeout after {timeout}s") from None

    async def get_nowait(self) -> DatagramMessage | None:
        """Get a datagram from the queue without blocking."""
        if self._lock is None or self._not_empty is None:
            raise DatagramError(
                message="DatagramQueue has not been initialized. Its owner must call 'await queue.initialize()'."
            )

        async with self._lock:
            for priority in [2, 1, 0]:
                if self._priority_queues[priority]:
                    datagram = self._priority_queues[priority].popleft()
                    self._size -= 1
                    if self._size == 0:
                        self._not_empty.clear()
                    return datagram
            return None

    async def put(self, *, datagram: DatagramMessage) -> bool:
        """Add a datagram to the queue, applying priority and size limits."""
        if self._lock is None or self._not_empty is None:
            raise DatagramError(
                message="DatagramQueue has not been initialized. Its owner must call 'await queue.initialize()'."
            )

        if datagram.is_expired:
            return False

        async with self._lock:
            if self._size >= self._max_size:
                if self._priority_queues[0]:
                    self._priority_queues[0].popleft()
                    self._size -= 1
                else:
                    return False

            priority = min(max(datagram.priority, 0), 2)
            self._priority_queues[priority].append(datagram)
            self._size += 1
            self._not_empty.set()
            return True

    async def put_nowait(self, *, datagram: DatagramMessage) -> bool:
        """Add a datagram to the queue without blocking."""
        if self._lock is None or self._not_empty is None:
            raise DatagramError(
                message="DatagramQueue has not been initialized. Its owner must call 'await queue.initialize()'."
            )

        if datagram.is_expired:
            return False

        async with self._lock:
            if self._size >= self._max_size:
                if self._priority_queues[0]:
                    self._priority_queues[0].popleft()
                    self._size -= 1
                else:
                    return False

            priority = min(max(datagram.priority, 0), 2)
            self._priority_queues[priority].append(datagram)
            self._size += 1
            self._not_empty.set()
            return True

    async def clear(self) -> None:
        """Safely clear all items from the queue."""
        if self._lock is None or self._not_empty is None:
            raise DatagramError(
                message="DatagramQueue has not been initialized. Its owner must call 'await queue.initialize()'."
            )

        async with self._lock:
            for priority_queue in self._priority_queues.values():
                priority_queue.clear()
            self._size = 0
            self._not_empty.clear()

    def empty(self) -> bool:
        """Check if the queue is empty."""
        return self._size == 0

    def get_stats(self) -> dict[str, int]:
        """Get statistics about the queue's state."""
        return {
            "size": self._size,
            "max_size": self._max_size,
            "priority_0": len(self._priority_queues[0]),
            "priority_1": len(self._priority_queues[1]),
            "priority_2": len(self._priority_queues[2]),
        }

    def qsize(self) -> int:
        """Get the current size of the queue."""
        return self._size

    def _cleanup_expired(self) -> None:
        """Remove all expired datagrams from the queues."""
        if self._max_age is None:
            return

        current_time = get_timestamp()
        expired_count = 0

        for priority in [2, 1, 0]:
            queue = self._priority_queues[priority]
            while queue and (current_time - queue[0].timestamp > self._max_age):
                queue.popleft()
                self._size -= 1
                expired_count += 1

        if expired_count > 0:
            logger.debug("Cleaned up %d expired datagrams", expired_count)

    async def _cleanup_loop(self) -> None:
        """Periodically clean up expired datagrams from the queue."""
        if self._lock is None:
            return

        try:
            while True:
                await asyncio.sleep(self._max_age or 1.0)
                async with self._lock:
                    self._cleanup_expired()
        except asyncio.CancelledError:
            pass

    def _start_cleanup(self) -> None:
        """Start the background task to clean up expired datagrams."""
        if self._cleanup_task is None and self._max_age is not None:
            try:
                self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            except RuntimeError:
                self._cleanup_task = None


class WebTransportDatagramTransport(EventEmitter):
    """A duplex transport for sending and receiving WebTransport datagrams."""

    def __init__(
        self,
        session: WebTransportSession,
        *,
        high_water_mark: int = 100,
        sender_get_timeout: float = 1.0,
    ) -> None:
        """Initialize the datagram duplex transport."""
        super().__init__()
        self._session = weakref.ref(session)
        self._session_id = session.session_id
        self._closed = False
        self._is_initialized = False
        self._sender_get_timeout = sender_get_timeout
        self._outgoing_high_water_mark = high_water_mark
        self._outgoing_max_age: float | None = None
        self._incoming_max_age: float | None = None
        self._send_sequence = 0
        self._receive_sequence = 0
        self._sequence_lock: asyncio.Lock | None = None
        self._stats = DatagramStats(session_id=session.session_id, created_at=get_timestamp())
        self._outgoing_queue: DatagramQueue | None = None
        self._incoming_queue: DatagramQueue | None = None
        self._sender_task: asyncio.Task[None] | None = None

    @property
    def is_closed(self) -> bool:
        """Check if the transport is closed."""
        return self._closed

    @property
    def is_readable(self) -> bool:
        """Check if the readable side of the transport is open."""
        return not self._closed

    @property
    def is_writable(self) -> bool:
        """Check if the writable side of the transport is open."""
        return not self._closed

    @property
    def session(self) -> WebTransportSession | None:
        """Get the parent WebTransportSession instance."""
        return self._session()

    @property
    def session_id(self) -> SessionId:
        """Get the session ID associated with this transport."""
        return self._session_id

    @property
    def bytes_received(self) -> int:
        """Get the total number of bytes received."""
        return self._stats.bytes_received

    @property
    def bytes_sent(self) -> int:
        """Get the total number of bytes sent."""
        return self._stats.bytes_sent

    @property
    def datagrams_received(self) -> int:
        """Get the total number of datagrams received."""
        return self._stats.datagrams_received

    @property
    def datagrams_sent(self) -> int:
        """Get the total number of datagrams sent."""
        return self._stats.datagrams_sent

    @property
    def incoming_max_age(self) -> float | None:
        """Get the maximum age for incoming datagrams before being dropped."""
        return self._incoming_max_age

    @property
    def max_datagram_size(self) -> int:
        """Get the maximum datagram size allowed by the QUIC connection."""
        session = self._session()
        if session and session.protocol_handler:
            return cast(
                int,
                getattr(session.protocol_handler.quic_connection, "_max_datagram_size", 1200),
            )
        return 1200

    @property
    def outgoing_high_water_mark(self) -> int:
        """Get the high water mark for the outgoing buffer."""
        return self._outgoing_high_water_mark

    @property
    def outgoing_max_age(self) -> float | None:
        """Get the maximum age for outgoing datagrams before being dropped."""
        return self._outgoing_max_age

    @property
    def receive_sequence(self) -> int:
        """Get the current receive sequence number."""
        return self._receive_sequence

    @property
    def send_sequence(self) -> int:
        """Get the current send sequence number."""
        return self._send_sequence

    @property
    def stats(self) -> dict[str, Any]:
        """Get a dictionary of all datagram statistics."""
        return self._stats.to_dict()

    async def __aenter__(self) -> Self:
        """Enter the async context for the transport."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the async context, closing the transport."""
        await self.close()

    async def initialize(self) -> None:
        """Initialize the transport, preparing it for use."""
        if self._is_initialized:
            return

        self._sequence_lock = asyncio.Lock()
        self._outgoing_queue = DatagramQueue(max_size=self._outgoing_high_water_mark, max_age=self._outgoing_max_age)
        self._incoming_queue = DatagramQueue(max_size=self._outgoing_high_water_mark, max_age=self._incoming_max_age)
        await self._outgoing_queue.initialize()
        await self._incoming_queue.initialize()

        if session := self.session:
            session.on(event_type=EventType.DATAGRAM_RECEIVED, handler=self._on_datagram_received)

        self._start_background_tasks()
        self._is_initialized = True

    async def close(self) -> None:
        """Close the datagram transport and clean up resources."""
        if self._closed:
            return

        self._closed = True

        if self._sender_task:
            self._sender_task.cancel()
            try:
                await self._sender_task
            except asyncio.CancelledError:
                pass

        if self._outgoing_queue:
            await self._outgoing_queue.close()
        if self._incoming_queue:
            await self._incoming_queue.close()

        logger.debug("Datagram transport closed for session %s", self._session_id)

    async def receive(self, *, timeout: float | None = None) -> bytes:
        """Receive a single datagram."""
        if not self._is_initialized:
            raise DatagramError(
                message=(
                    "WebTransportDatagramTransport is not initialized. Its factory "
                    "should call 'await transport.initialize()' before use."
                )
            )
        if self.is_closed:
            raise DatagramError(message="Datagram transport is closed.")
        if self._incoming_queue is None:
            raise DatagramError(message="Internal state error: queue is None despite transport being initialized.")

        start_time = time.time()
        datagram = await self._incoming_queue.get(timeout=timeout)
        receive_time = time.time() - start_time

        self._update_receive_stats(datagram=datagram, receive_time=receive_time)
        await self.emit(
            event_type=EventType.DATAGRAM_RECEIVED,
            data={
                "size": datagram.size,
                "sequence": datagram.sequence,
                "age": datagram.age,
                "receive_time": receive_time,
            },
        )
        return datagram.data

    async def receive_json(self, *, timeout: float | None = None) -> Any:
        """Receive and parse a JSON-encoded datagram."""
        try:
            data = await self.receive(timeout=timeout)
            return json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise DatagramError(message=f"Failed to parse JSON datagram: {e}") from e
        except TimeoutError as e:
            raise e
        except Exception as e:
            raise DatagramError(message=f"Failed to receive JSON datagram: {e}") from e

    async def receive_multiple(self, *, max_count: int = 10, timeout: float | None = None) -> list[bytes]:
        """Receive multiple datagrams in a batch."""
        datagrams = []
        try:
            first_datagram = await self.receive(timeout=timeout)
            datagrams.append(first_datagram)
            for _ in range(max_count - 1):
                datagram = await self.try_receive()
                if datagram is None:
                    break
                datagrams.append(datagram)
        except TimeoutError:
            if not datagrams:
                raise
        return datagrams

    async def receive_with_metadata(self, *, timeout: float | None = None) -> dict[str, Any]:
        """Receive a datagram along with its metadata."""
        if not self._is_initialized:
            raise DatagramError(
                message=(
                    "WebTransportDatagramTransport is not initialized. Its factory "
                    "should call 'await transport.initialize()' before use."
                )
            )
        if self.is_closed:
            raise DatagramError(message="Datagram transport is closed.")
        if self._incoming_queue is None:
            raise DatagramError(message="Internal state error: queue is None despite transport being initialized.")

        try:
            start_time = time.time()
            datagram = await self._incoming_queue.get(timeout=timeout)
            receive_time = time.time() - start_time
        except TimeoutError as e:
            raise e
        except Exception as e:
            raise DatagramError(message=f"Failed to receive datagram with metadata: {e}") from e

        self._update_receive_stats(datagram=datagram, receive_time=receive_time)
        return {
            "data": datagram.data,
            "metadata": {**datagram.to_dict(), "receive_time": receive_time},
        }

    async def send(self, *, data: Data, priority: int = 0, ttl: float | None = None) -> None:
        """Send a datagram with a given priority and TTL."""
        if not self._is_initialized:
            raise DatagramError(
                message=(
                    "WebTransportDatagramTransport is not initialized. Its factory "
                    "should call 'await transport.initialize()' before use."
                )
            )
        if self.is_closed:
            raise DatagramError(message="Datagram transport is closed.")
        if self._sequence_lock is None or self._outgoing_queue is None:
            raise DatagramError(
                message="Internal state error: lock or queue is None despite transport being initialized."
            )

        data_bytes = ensure_bytes(data=data)
        if len(data_bytes) > self.max_datagram_size:
            raise datagram_too_large(size=len(data_bytes), max_size=self.max_datagram_size)

        async with self._sequence_lock:
            sequence = self._send_sequence
            self._send_sequence += 1

        datagram = DatagramMessage(data=data_bytes, sequence=sequence, priority=priority, ttl=ttl)
        success = await self._outgoing_queue.put(datagram=datagram)

        if not success:
            self._stats.send_drops += 1
            raise DatagramError(message="Outgoing datagram queue full or datagram expired")

        self._stats.datagrams_sent += 1
        self._stats.bytes_sent += datagram.size
        self._stats.total_datagram_size += datagram.size
        self._stats.min_datagram_size = min(self._stats.min_datagram_size, datagram.size)
        self._stats.max_datagram_size = max(self._stats.max_datagram_size, datagram.size)

    async def send_json(self, *, data: Any, priority: int = 0, ttl: float | None = None) -> None:
        """Send JSON-serializable data as a datagram."""
        try:
            json_data = json.dumps(obj=data, separators=(",", ":")).encode("utf-8")
            await self.send(data=json_data, priority=priority, ttl=ttl)
        except TypeError as e:
            raise DatagramError(message=f"Failed to serialize JSON datagram: {e}") from e

    async def send_multiple(self, *, datagrams: list[Data], priority: int = 0, ttl: float | None = None) -> int:
        """Send multiple datagrams and return the number successfully sent."""
        if not self._is_initialized:
            raise DatagramError(
                message=(
                    "WebTransportDatagramTransport is not initialized. Its factory "
                    "should call 'await transport.initialize()' before use."
                )
            )
        sent_count = 0
        for data in datagrams:
            try:
                await self.send(data=data, priority=priority, ttl=ttl)
                sent_count += 1
            except DatagramError as e:
                logger.warning("Failed to send datagram %d: %s", sent_count + 1, e, exc_info=True)
                break
        return sent_count

    async def clear_receive_buffer(self) -> int:
        """Clear the receive buffer and return the number of cleared datagrams."""
        if not self._is_initialized:
            raise DatagramError(
                message=(
                    "WebTransportDatagramTransport is not initialized. Its factory "
                    "should call 'await transport.initialize()' before use."
                )
            )
        if self._incoming_queue is None:
            return 0

        count = self._incoming_queue.qsize()
        await self._incoming_queue.clear()
        return count

    async def clear_send_buffer(self) -> int:
        """Clear the send buffer and return the number of cleared datagrams."""
        if not self._is_initialized:
            raise DatagramError(
                message=(
                    "WebTransportDatagramTransport is not initialized. Its factory "
                    "should call 'await transport.initialize()' before use."
                )
            )
        if self._outgoing_queue is None:
            return 0

        count = self._outgoing_queue.qsize()
        await self._outgoing_queue.clear()
        return count

    def debug_state(self) -> dict[str, Any]:
        """Get a detailed snapshot of the datagram transport's state."""
        stats = self.stats
        queue_stats = self.get_queue_stats()

        return {
            "transport": {
                "session_id": self.session_id,
                "is_readable": self.is_readable,
                "is_writable": self.is_writable,
                "is_closed": self.is_closed,
                "max_datagram_size": self.max_datagram_size,
            },
            "statistics": stats,
            "queues": queue_stats,
            "configuration": {
                "outgoing_high_water_mark": self.outgoing_high_water_mark,
                "outgoing_max_age": self.outgoing_max_age,
                "incoming_max_age": self.incoming_max_age,
            },
            "sequences": {
                "send_sequence": self.send_sequence,
                "receive_sequence": self.receive_sequence,
            },
        }

    async def diagnose_issues(self) -> list[str]:
        """Analyze transport statistics to identify potential issues."""
        issues = []
        stats = self.stats
        queue_stats = self.get_queue_stats()

        if stats["send_success_rate"] < 0.9:
            issues.append(f"Low send success rate: {stats['send_success_rate']:.2%}")

        total_drops = stats["send_drops"] + stats["receive_drops"]
        total_datagrams = stats["datagrams_sent"] + stats["datagrams_received"]
        if (total_drops / max(1, total_datagrams)) > 0.1:
            issues.append(f"High drop rate: {total_drops}/{total_datagrams}")

        if outgoing_q_stats := queue_stats.get("outgoing", {}):
            if outgoing_q_stats.get("max_size", 0) > 0:
                usage = outgoing_q_stats.get("size", 0) / outgoing_q_stats.get("max_size", 1)
                if usage > 0.9:
                    issues.append(f"Outgoing queue nearly full: {usage * 100:.1f}%")

        if incoming_q_stats := queue_stats.get("incoming", {}):
            if incoming_q_stats.get("max_size", 0) > 0:
                usage = incoming_q_stats.get("size", 0) / incoming_q_stats.get("max_size", 1)
                if usage > 0.9:
                    issues.append(f"Incoming queue nearly full: {usage * 100:.1f}%")

        if stats["avg_send_time"] > 0.1:
            issues.append(f"High send latency: {stats['avg_send_time'] * 1000:.1f}ms")

        if self.is_closed:
            issues.append("Datagram transport is closed")

        if not (session := self.session) or not session.is_ready:
            issues.append("Session not available or not ready")

        return issues

    def get_queue_stats(self) -> dict[str, dict[str, int]]:
        """Get detailed statistics for the outgoing and incoming queues."""
        return {
            "outgoing": self._outgoing_queue.get_stats() if self._outgoing_queue else {},
            "incoming": self._incoming_queue.get_stats() if self._incoming_queue else {},
        }

    def get_receive_buffer_size(self) -> int:
        """Get the current number of datagrams in the receive buffer."""
        return self._incoming_queue.qsize() if self._incoming_queue else 0

    def get_send_buffer_size(self) -> int:
        """Get the current number of datagrams in the send buffer."""
        return self._outgoing_queue.qsize() if self._outgoing_queue else 0

    def start_heartbeat(self, *, interval: float = 30.0) -> asyncio.Task[None]:
        """Run a task that sends periodic heartbeat datagrams."""
        if not self._is_initialized:
            raise DatagramError(
                message=(
                    "WebTransportDatagramTransport is not initialized. Its factory "
                    "should call 'await transport.initialize()' before use."
                )
            )
        return asyncio.create_task(self._heartbeat_loop(interval=interval))

    async def try_receive(self) -> bytes | None:
        """Try to receive a datagram without blocking."""
        if not self._is_initialized:
            raise DatagramError(
                message=(
                    "WebTransportDatagramTransport is not initialized. Its factory "
                    "should call 'await transport.initialize()' before use."
                )
            )
        if self.is_closed or self._incoming_queue is None:
            return None

        datagram = await self._incoming_queue.get_nowait()
        if datagram:
            self._update_receive_stats(datagram=datagram, receive_time=0.0)
            return datagram.data
        return None

    async def try_send(self, *, data: Data, priority: int = 0, ttl: float | None = None) -> bool:
        """Try to send a datagram without blocking."""
        if not self._is_initialized:
            raise DatagramError(
                message=(
                    "WebTransportDatagramTransport is not initialized. Its factory "
                    "should call 'await transport.initialize()' before use."
                )
            )
        if self.is_closed:
            return False
        if self._sequence_lock is None or self._outgoing_queue is None:
            return False

        data_bytes = ensure_bytes(data=data)
        if len(data_bytes) > self.max_datagram_size:
            self._stats.send_drops += 1
            return False

        async with self._sequence_lock:
            sequence = self._send_sequence
            self._send_sequence += 1

        datagram = DatagramMessage(data=data_bytes, sequence=sequence, priority=priority, ttl=ttl)
        success = await self._outgoing_queue.put_nowait(datagram=datagram)

        if not success:
            self._stats.send_drops += 1
        else:
            self._stats.datagrams_sent += 1
            self._stats.bytes_sent += datagram.size
            self._stats.total_datagram_size += datagram.size
            self._stats.min_datagram_size = min(self._stats.min_datagram_size, datagram.size)
            self._stats.max_datagram_size = max(self._stats.max_datagram_size, datagram.size)
        return success

    async def _heartbeat_loop(self, *, interval: float) -> None:
        """The implementation of the periodic heartbeat sender."""
        try:
            while not self.is_closed:
                heartbeat = f"HEARTBEAT:{int(get_timestamp())}".encode("utf-8")
                try:
                    await self.send(data=heartbeat, priority=1)
                    logger.debug("Sent heartbeat datagram")
                except DatagramError as e:
                    logger.warning("Failed to send heartbeat: %s", e, exc_info=True)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Heartbeat loop error: %s", e, exc_info=e)

    async def _on_datagram_received(self, event: Event) -> None:
        """Handle an incoming datagram event from the session."""
        if not self._is_initialized or self._sequence_lock is None or self._incoming_queue is None:
            return

        try:
            data = event.data.get("data") if isinstance(event.data, dict) else None
            if data:
                async with self._sequence_lock:
                    sequence = self._receive_sequence
                    self._receive_sequence += 1
                datagram = DatagramMessage(data=data, sequence=sequence)

                success = await self._incoming_queue.put(datagram=datagram)
                if not success:
                    self._stats.receive_drops += 1
                    logger.warning("Dropped incoming datagram due to full buffer or expiration")
        except Exception as e:
            logger.error("Error handling received datagram: %s", e, exc_info=e)
            self._stats.receive_errors += 1

    async def _receive_framed_data(self, *, timeout: float | None = None) -> tuple[str, bytes]:
        """Receive and parse a simple framed datagram for internal use."""
        try:
            data = await self.receive(timeout=timeout)
            if len(data) < 1:
                raise DatagramError(message="Datagram too short for frame header")

            type_length = data[0]
            if len(data) < 1 + type_length:
                raise DatagramError(message="Datagram too short for type header content")

            message_type = data[1 : 1 + type_length].decode("utf-8")
            payload = data[1 + type_length :]
            return message_type, payload
        except (UnicodeDecodeError, IndexError) as e:
            raise DatagramError(message=f"Failed to parse framed datagram: {e}") from e
        except TimeoutError as e:
            raise e
        except Exception as e:
            raise DatagramError(message=f"Failed to receive framed datagram: {e}") from e

    async def _sender_loop(self) -> None:
        """Continuously send datagrams from the outgoing queue."""
        if self._outgoing_queue is None:
            return

        try:
            while not self._closed:
                try:
                    datagram = await self._outgoing_queue.get(timeout=self._sender_get_timeout)
                except TimeoutError:
                    continue

                if not (session := self._session()) or not session.protocol_handler:
                    logger.warning("Cannot send datagram %s; session is gone.", datagram.sequence)
                    continue

                start_time = time.time()
                try:
                    session.protocol_handler.send_webtransport_datagram(session_id=self._session_id, data=datagram.data)
                    send_time = time.time() - start_time
                    self._update_send_stats(datagram=datagram, send_time=send_time)
                    await self.emit(
                        event_type=EventType.DATAGRAM_SENT,
                        data={
                            "size": datagram.size,
                            "sequence": datagram.sequence,
                            "send_time": send_time,
                        },
                    )
                except Exception as send_error:
                    self._stats.send_failures += 1
                    logger.warning(
                        "Failed to send datagram %s: %s",
                        datagram.sequence,
                        send_error,
                        exc_info=True,
                    )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Sender loop fatal error: %s", e, exc_info=e)

    async def _send_framed_data(
        self, *, message_type: str, payload: bytes, priority: int = 0, ttl: float | None = None
    ) -> None:
        """Send a simple length-prefixed datagram for internal use."""
        type_bytes = message_type.encode("utf-8")
        if len(type_bytes) > 255:
            raise DatagramError(message="Message type too long (max 255 bytes)")

        frame = struct.pack("!B", len(type_bytes)) + type_bytes + payload
        await self.send(data=frame, priority=priority, ttl=ttl)

    def _start_background_tasks(self) -> None:
        """Start all background tasks for the transport."""
        if self._outgoing_queue is None or self._incoming_queue is None:
            return

        try:
            self._outgoing_queue._start_cleanup()
            self._incoming_queue._start_cleanup()
            if self._sender_task is None:
                self._sender_task = asyncio.create_task(self._sender_loop())
        except RuntimeError:
            logger.warning("Could not start datagram background tasks. No running event loop.")

    def _update_receive_stats(self, *, datagram: DatagramMessage, receive_time: float) -> None:
        """Update statistics after receiving a datagram."""
        self._stats.datagrams_received += 1
        self._stats.bytes_received += datagram.size
        self._stats.total_receive_time += receive_time
        self._stats.max_receive_time = max(self._stats.max_receive_time, receive_time)
        self._stats.total_datagram_size += datagram.size
        self._stats.min_datagram_size = min(self._stats.min_datagram_size, datagram.size)
        self._stats.max_datagram_size = max(self._stats.max_datagram_size, datagram.size)

    def _update_send_stats(self, *, datagram: DatagramMessage, send_time: float) -> None:
        """Update statistics after sending a datagram."""
        self._stats.total_send_time += send_time
        self._stats.max_send_time = max(self._stats.max_send_time, send_time)

    def __str__(self) -> str:
        """Format a concise summary of datagram transport info for logging."""
        stats = self.stats

        return (
            f"DatagramTransport({self.session_id[:12]}..., "
            f"sent={stats['datagrams_sent']}, "
            f"received={stats['datagrams_received']}, "
            f"success_rate={stats['send_success_rate']:.2%}, "
            f"avg_size={stats['avg_datagram_size']:.0f}B)"
        )
