"""
WebTransport Datagram Stream.
"""

import asyncio
import json
import struct
import time
import weakref
from collections import deque
from dataclasses import dataclass, field
from types import TracebackType
from typing import TYPE_CHECKING, Any, Deque, Dict, List, Optional, Tuple, Type, cast

from pywebtransport.events import Event, EventEmitter, EventType
from pywebtransport.exceptions import DatagramError, TimeoutError, datagram_too_large
from pywebtransport.types import Data, SessionId
from pywebtransport.utils import calculate_checksum, ensure_bytes, get_logger, get_timestamp

if TYPE_CHECKING:
    from pywebtransport.session import WebTransportSession


__all__ = [
    "DatagramStats",
    "DatagramMessage",
    "DatagramQueue",
    "WebTransportDatagramDuplexStream",
]

logger = get_logger("datagram.transport")


@dataclass
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
    def avg_send_time(self) -> float:
        """Get the average send time for datagrams."""
        return self.total_send_time / max(1, self.datagrams_sent)

    @property
    def avg_receive_time(self) -> float:
        """Get the average receive time for datagrams."""
        return self.total_receive_time / max(1, self.datagrams_received)

    @property
    def avg_datagram_size(self) -> float:
        """Get the average size of all datagrams."""
        total_datagrams = self.datagrams_sent + self.datagrams_received
        return self.total_datagram_size / max(1, total_datagrams)

    @property
    def send_success_rate(self) -> float:
        """Get the success rate of sending datagrams."""
        total_attempts = self.datagrams_sent + self.send_failures
        return self.datagrams_sent / max(1, total_attempts)

    @property
    def receive_success_rate(self) -> float:
        """Get the success rate of receiving datagrams."""
        total_received = self.datagrams_received + self.receive_errors
        return self.datagrams_received / max(1, total_received)

    def to_dict(self) -> Dict[str, Any]:
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


@dataclass
class DatagramMessage:
    """Represents a datagram message with metadata."""

    data: bytes
    timestamp: float = field(default_factory=get_timestamp)
    size: int = field(init=False)
    checksum: Optional[str] = None
    sequence: Optional[int] = None
    priority: int = 0
    ttl: Optional[float] = None

    def __post_init__(self) -> None:
        """Initialize computed fields after object creation."""
        self.size = len(self.data)
        if self.checksum is None:
            self.checksum = calculate_checksum(self.data)[:8]

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

    def to_dict(self) -> Dict[str, Any]:
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


class DatagramQueue:
    """A priority queue for datagrams with size and TTL limits."""

    def __init__(self, max_size: int = 1000, max_age: Optional[float] = None):
        """Initialize the datagram queue."""
        self._max_size = max_size
        self._max_age = max_age
        self._lock = asyncio.Lock()
        self._not_empty = asyncio.Event()
        self._size = 0
        self._priority_queues: Dict[int, Deque["DatagramMessage"]] = {
            0: deque(),
            1: deque(),
            2: deque(),
        }
        self._cleanup_task: Optional[asyncio.Task[None]] = None

    async def close(self) -> None:
        """Close the queue and clean up background tasks."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        await self.clear()

    async def put(self, datagram: DatagramMessage) -> bool:
        """Add a datagram to the queue, blocking if necessary."""
        async with self._lock:
            if datagram.is_expired:
                return False

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

    def put_nowait(self, datagram: DatagramMessage) -> bool:
        """Add a datagram to the queue without blocking."""
        if datagram.is_expired:
            return False

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

    async def get(self, *, timeout: Optional[float] = None) -> DatagramMessage:
        """Get a datagram from the queue, waiting if it's empty."""

        async def _wait_for_item() -> DatagramMessage:
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
            return await asyncio.wait_for(_wait_for_item(), timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Datagram get timeout after {timeout}s") from None

    def get_nowait(self) -> Optional[DatagramMessage]:
        """Get a datagram from the queue without blocking."""
        for priority in [2, 1, 0]:
            if self._priority_queues[priority]:
                datagram = self._priority_queues[priority].popleft()
                self._size -= 1
                if self._size == 0:
                    self._not_empty.clear()
                return datagram
        return None

    async def clear(self) -> None:
        """Safely clear all items from the queue."""
        async with self._lock:
            for priority_queue in self._priority_queues.values():
                priority_queue.clear()
            self._size = 0
            self._not_empty.clear()

    def qsize(self) -> int:
        """Get the current size of the queue."""
        return self._size

    def empty(self) -> bool:
        """Check if the queue is empty."""
        return self._size == 0

    def get_stats(self) -> Dict[str, int]:
        """Get statistics about the queue's state."""
        return {
            "size": self._size,
            "max_size": self._max_size,
            "priority_0": len(self._priority_queues[0]),
            "priority_1": len(self._priority_queues[1]),
            "priority_2": len(self._priority_queues[2]),
        }

    def _start_cleanup(self) -> None:
        """Start the background task to clean up expired datagrams."""
        if self._cleanup_task is None and self._max_age is not None:
            try:
                self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            except RuntimeError:
                self._cleanup_task = None

    async def _cleanup_loop(self) -> None:
        """Periodically clean up expired datagrams from the queue."""
        try:
            while True:
                await asyncio.sleep(self._max_age or 1.0)
                async with self._lock:
                    self._cleanup_expired()
        except asyncio.CancelledError:
            pass

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
            logger.debug(f"Cleaned up {expired_count} expired datagrams")


class WebTransportDatagramDuplexStream(EventEmitter):
    """A duplex stream for sending and receiving WebTransport datagrams."""

    def __init__(
        self,
        session: "WebTransportSession",
        *,
        high_water_mark: int = 100,
        sender_get_timeout: float = 1.0,
    ):
        """Initialize the datagram duplex stream."""
        super().__init__()
        self._session = weakref.ref(session)
        self._session_id = session.session_id
        self._closed = False
        self._sender_get_timeout = sender_get_timeout
        self._outgoing_high_water_mark = high_water_mark
        self._outgoing_max_age: Optional[float] = None
        self._incoming_max_age: Optional[float] = None
        self._send_sequence = 0
        self._receive_sequence = 0
        self._sequence_lock = asyncio.Lock()
        self._stats = DatagramStats(session_id=session.session_id, created_at=get_timestamp())
        self._outgoing_queue = DatagramQueue(max_size=self._outgoing_high_water_mark, max_age=self._outgoing_max_age)
        self._incoming_queue = DatagramQueue(max_size=self._outgoing_high_water_mark, max_age=self._incoming_max_age)
        self._sender_task: Optional[asyncio.Task[None]] = None
        session.on(EventType.DATAGRAM_RECEIVED, self._on_datagram_received)
        self._start_background_tasks()

    @property
    def is_readable(self) -> bool:
        """Check if the readable side of the stream is open."""
        return not self._closed

    @property
    def is_writable(self) -> bool:
        """Check if the writable side of the stream is open."""
        return not self._closed

    @property
    def is_closed(self) -> bool:
        """Check if the stream is closed."""
        return self._closed

    @property
    def session_id(self) -> SessionId:
        """Get the session ID associated with this stream."""
        return self._session_id

    @property
    def session(self) -> Optional["WebTransportSession"]:
        """Get the parent WebTransportSession instance."""
        return self._session()

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
    def outgoing_max_age(self) -> Optional[float]:
        """Get the maximum age for outgoing datagrams before being dropped."""
        return self._outgoing_max_age

    @property
    def incoming_max_age(self) -> Optional[float]:
        """Get the maximum age for incoming datagrams before being dropped."""
        return self._incoming_max_age

    @property
    def datagrams_sent(self) -> int:
        """Get the total number of datagrams sent."""
        return self._stats.datagrams_sent

    @property
    def datagrams_received(self) -> int:
        """Get the total number of datagrams received."""
        return self._stats.datagrams_received

    @property
    def bytes_sent(self) -> int:
        """Get the total number of bytes sent."""
        return self._stats.bytes_sent

    @property
    def bytes_received(self) -> int:
        """Get the total number of bytes received."""
        return self._stats.bytes_received

    @property
    def stats(self) -> Dict[str, Any]:
        """Get a dictionary of all datagram statistics."""
        return self._stats.to_dict()

    @property
    def send_sequence(self) -> int:
        """Get the current send sequence number."""
        return self._send_sequence

    @property
    def receive_sequence(self) -> int:
        """Get the current receive sequence number."""
        return self._receive_sequence

    async def __aenter__(self) -> "WebTransportDatagramDuplexStream":
        """Enter the async context for the stream."""
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Exit the async context, closing the stream."""
        await self.close()

    async def close(self) -> None:
        """Close the datagram stream and clean up resources."""
        if self._closed:
            return
        self._closed = True

        if self._sender_task:
            self._sender_task.cancel()
            try:
                await self._sender_task
            except asyncio.CancelledError:
                pass

        await self._outgoing_queue.close()
        await self._incoming_queue.close()
        logger.debug(f"Datagram stream closed for session {self._session_id}")

    def start_heartbeat(self, *, interval: float = 30.0) -> asyncio.Task[None]:
        """Run a task that sends periodic heartbeat datagrams."""
        return asyncio.create_task(self._heartbeat_loop(interval=interval))

    async def send(self, data: Data, *, priority: int = 0, ttl: Optional[float] = None) -> None:
        """Send a datagram with a given priority and TTL."""
        if self._closed:
            raise DatagramError("Datagram stream is closed")

        data_bytes = ensure_bytes(data)
        if len(data_bytes) > self.max_datagram_size:
            raise datagram_too_large(len(data_bytes), self.max_datagram_size)

        async with self._sequence_lock:
            sequence = self._send_sequence
            self._send_sequence += 1

        datagram = DatagramMessage(data=data_bytes, sequence=sequence, priority=priority, ttl=ttl)
        success = await self._outgoing_queue.put(datagram)
        if not success:
            self._stats.send_drops += 1
            raise DatagramError("Outgoing datagram queue full or datagram expired")

        self._stats.datagrams_sent += 1
        self._stats.bytes_sent += datagram.size
        self._stats.total_datagram_size += datagram.size
        self._stats.min_datagram_size = min(self._stats.min_datagram_size, datagram.size)
        self._stats.max_datagram_size = max(self._stats.max_datagram_size, datagram.size)

    async def try_send(self, data: Data, *, priority: int = 0, ttl: Optional[float] = None) -> bool:
        """Try to send a datagram without blocking."""
        if self._closed:
            return False

        data_bytes = ensure_bytes(data)
        if len(data_bytes) > self.max_datagram_size:
            self._stats.send_drops += 1
            return False

        async with self._sequence_lock:
            sequence = self._send_sequence
            self._send_sequence += 1

        datagram = DatagramMessage(data=data_bytes, sequence=sequence, priority=priority, ttl=ttl)
        success = self._outgoing_queue.put_nowait(datagram)
        if not success:
            self._stats.send_drops += 1
        else:
            self._stats.datagrams_sent += 1
            self._stats.bytes_sent += datagram.size
            self._stats.total_datagram_size += datagram.size
            self._stats.min_datagram_size = min(self._stats.min_datagram_size, datagram.size)
            self._stats.max_datagram_size = max(self._stats.max_datagram_size, datagram.size)
        return success

    async def send_multiple(self, datagrams: List[Data], *, priority: int = 0, ttl: Optional[float] = None) -> int:
        """Send multiple datagrams and return the number successfully sent."""
        sent_count = 0
        for data in datagrams:
            try:
                await self.send(data, priority=priority, ttl=ttl)
                sent_count += 1
            except DatagramError as e:
                logger.warning(f"Failed to send datagram {sent_count + 1}: {e}")
                break
        return sent_count

    async def send_json(self, data: Any, *, priority: int = 0, ttl: Optional[float] = None) -> None:
        """Send JSON-serializable data as a datagram."""
        try:
            json_data = json.dumps(data, separators=(",", ":")).encode("utf-8")
            await self.send(json_data, priority=priority, ttl=ttl)
        except TypeError as e:
            raise DatagramError(f"Failed to serialize JSON datagram: {e}") from e

    async def send_structured(
        self, message_type: str, payload: bytes, *, priority: int = 0, ttl: Optional[float] = None
    ) -> None:
        """Send a structured datagram with a type header."""
        type_bytes = message_type.encode("utf-8")
        if len(type_bytes) > 255:
            raise DatagramError("Message type too long (max 255 bytes)")

        frame = struct.pack("!B", len(type_bytes)) + type_bytes + payload
        await self.send(frame, priority=priority, ttl=ttl)

    async def receive(self, *, timeout: Optional[float] = None) -> bytes:
        """Receive a single datagram."""
        if self._closed:
            raise DatagramError("Datagram stream is closed")

        start_time = time.time()
        datagram = await self._incoming_queue.get(timeout=timeout)
        receive_time = time.time() - start_time
        self._update_receive_stats(datagram, receive_time)
        await self.emit(
            EventType.DATAGRAM_RECEIVED,
            data={
                "size": datagram.size,
                "sequence": datagram.sequence,
                "age": datagram.age,
                "receive_time": receive_time,
            },
        )
        return datagram.data

    def try_receive(self) -> Optional[bytes]:
        """Try to receive a datagram without blocking."""
        if self._closed:
            return None
        datagram = self._incoming_queue.get_nowait()
        if datagram:
            self._update_receive_stats(datagram, 0.0)
            return datagram.data
        return None

    async def receive_multiple(self, *, max_count: int = 10, timeout: Optional[float] = None) -> List[bytes]:
        """Receive multiple datagrams in a batch."""
        datagrams = []
        try:
            first_datagram = await self.receive(timeout=timeout)
            datagrams.append(first_datagram)
            for _ in range(max_count - 1):
                datagram = self.try_receive()
                if datagram is None:
                    break
                datagrams.append(datagram)
        except TimeoutError:
            if not datagrams:
                raise
        return datagrams

    async def receive_with_metadata(self, *, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Receive a datagram along with its metadata."""
        if self._closed:
            raise DatagramError("Datagram stream is closed")

        start_time = time.time()
        datagram = await self._incoming_queue.get(timeout=timeout)
        receive_time = time.time() - start_time
        self._update_receive_stats(datagram, receive_time)
        return {"data": datagram.data, "metadata": {**datagram.to_dict(), "receive_time": receive_time}}

    async def receive_json(self, *, timeout: Optional[float] = None) -> Any:
        """Receive and parse a JSON-encoded datagram."""
        try:
            data = await self.receive(timeout=timeout)
            return json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise DatagramError(f"Failed to parse JSON datagram: {e}") from e
        except TimeoutError as e:
            raise e
        except Exception as e:
            raise DatagramError(f"Failed to receive JSON datagram: {e}") from e

    async def receive_structured(self, *, timeout: Optional[float] = None) -> Tuple[str, bytes]:
        """Receive and parse a structured datagram."""
        try:
            data = await self.receive(timeout=timeout)
            if len(data) < 1:
                raise DatagramError("Datagram too short for structured format header")

            type_length = data[0]
            if len(data) < 1 + type_length:
                raise DatagramError("Datagram too short for type header content")

            message_type = data[1 : 1 + type_length].decode("utf-8")
            payload = data[1 + type_length :]
            return message_type, payload
        except (UnicodeDecodeError, IndexError) as e:
            raise DatagramError(f"Failed to parse structured datagram: {e}") from e
        except TimeoutError as e:
            raise e
        except Exception as e:
            raise DatagramError(f"Failed to receive structured datagram: {e}") from e

    def get_send_buffer_size(self) -> int:
        """Get the current number of datagrams in the send buffer."""
        return self._outgoing_queue.qsize()

    def get_receive_buffer_size(self) -> int:
        """Get the current number of datagrams in the receive buffer."""
        return self._incoming_queue.qsize()

    async def clear_send_buffer(self) -> int:
        """Clear the send buffer and return the number of cleared datagrams."""
        count = self._outgoing_queue.qsize()
        await self._outgoing_queue.clear()
        return count

    async def clear_receive_buffer(self) -> int:
        """Clear the receive buffer and return the number of cleared datagrams."""
        count = self._incoming_queue.qsize()
        await self._incoming_queue.clear()
        return count

    def get_queue_stats(self) -> Dict[str, Dict[str, int]]:
        """Get detailed statistics for the outgoing and incoming queues."""
        return {
            "outgoing": self._outgoing_queue.get_stats(),
            "incoming": self._incoming_queue.get_stats(),
        }

    def debug_state(self) -> Dict[str, Any]:
        """Get a detailed snapshot of the datagram stream's state."""
        stats = self.stats
        queue_stats = self.get_queue_stats()
        return {
            "stream": {
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

    async def diagnose_issues(self) -> List[str]:
        """Analyze stream statistics to identify potential issues."""
        issues = []
        stats = self.stats
        queue_stats = self.get_queue_stats()

        if stats["send_success_rate"] < 0.9:
            issues.append(f"Low send success rate: {stats['send_success_rate']:.2%}")

        total_drops = stats["send_drops"] + stats["receive_drops"]
        total_datagrams = stats["datagrams_sent"] + stats["datagrams_received"]
        if (total_drops / max(1, total_datagrams)) > 0.1:
            issues.append(f"High drop rate: {total_drops}/{total_datagrams}")

        outgoing_q_stats = queue_stats.get("outgoing", {})
        if outgoing_q_stats.get("max_size", 0) > 0:
            usage = outgoing_q_stats.get("size", 0) / outgoing_q_stats.get("max_size", 1)
            if usage > 0.9:
                issues.append(f"Outgoing queue nearly full: {usage*100:.1f}%")

        incoming_q_stats = queue_stats.get("incoming", {})
        if incoming_q_stats.get("max_size", 0) > 0:
            usage = incoming_q_stats.get("size", 0) / incoming_q_stats.get("max_size", 1)
            if usage > 0.9:
                issues.append(f"Incoming queue nearly full: {usage*100:.1f}%")

        if stats["avg_send_time"] > 0.1:
            issues.append(f"High send latency: {stats['avg_send_time']*1000:.1f}ms")

        if self.is_closed:
            issues.append("Datagram stream is closed")

        session = self.session
        if not session or not session.is_ready:
            issues.append("Session not available or not ready")

        return issues

    def _start_background_tasks(self) -> None:
        """Start all background tasks for the stream."""
        try:
            self._outgoing_queue._start_cleanup()
            self._incoming_queue._start_cleanup()
            if self._sender_task is None:
                self._sender_task = asyncio.create_task(self._sender_loop())
        except RuntimeError:
            logger.warning("Could not start datagram background tasks. No running event loop.")

    async def _sender_loop(self) -> None:
        """Continuously send datagrams from the outgoing queue."""
        try:
            while not self._closed:
                try:
                    datagram = await self._outgoing_queue.get(timeout=self._sender_get_timeout)
                except TimeoutError:
                    continue

                session = self._session()
                if not session or not session.protocol_handler:
                    logger.warning(f"Cannot send datagram {datagram.sequence}; session is gone.")
                    continue

                start_time = time.time()
                try:
                    session.protocol_handler.send_webtransport_datagram(self._session_id, datagram.data)
                    send_time = time.time() - start_time
                    self._update_send_stats(datagram, send_time)
                    await self.emit(
                        EventType.DATAGRAM_SENT,
                        data={"size": datagram.size, "sequence": datagram.sequence, "send_time": send_time},
                    )
                except Exception as send_error:
                    self._stats.send_failures += 1
                    logger.warning(f"Failed to send datagram {datagram.sequence}: {send_error}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Sender loop fatal error: {e}", exc_info=e)

    async def _on_datagram_received(self, event: "Event") -> None:
        """Handle an incoming datagram event from the session."""
        try:
            data = event.data.get("data") if isinstance(event.data, dict) else None
            if data:
                async with self._sequence_lock:
                    sequence = self._receive_sequence
                    self._receive_sequence += 1
                datagram = DatagramMessage(data=data, sequence=sequence)

                success = await self._incoming_queue.put(datagram)
                if not success:
                    self._stats.receive_drops += 1
                    logger.warning("Dropped incoming datagram due to full buffer or expiration")
        except Exception as e:
            logger.error(f"Error handling received datagram: {e}", exc_info=e)
            self._stats.receive_errors += 1

    async def _heartbeat_loop(self, interval: float) -> None:
        """The implementation of the periodic heartbeat sender."""
        try:
            while not self.is_closed:
                heartbeat = f"HEARTBEAT:{int(get_timestamp())}".encode("utf-8")
                try:
                    await self.send(heartbeat, priority=1)
                    logger.debug("Sent heartbeat datagram")
                except DatagramError as e:
                    logger.warning(f"Failed to send heartbeat: {e}")
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Heartbeat loop error: {e}", exc_info=e)

    def _update_send_stats(self, datagram: DatagramMessage, send_time: float) -> None:
        """Update statistics after sending a datagram."""
        self._stats.total_send_time += send_time
        self._stats.max_send_time = max(self._stats.max_send_time, send_time)

    def _update_receive_stats(self, datagram: DatagramMessage, receive_time: float) -> None:
        """Update statistics after receiving a datagram."""
        self._stats.datagrams_received += 1
        self._stats.bytes_received += datagram.size
        self._stats.total_receive_time += receive_time
        self._stats.max_receive_time = max(self._stats.max_receive_time, receive_time)
        self._stats.total_datagram_size += datagram.size
        self._stats.min_datagram_size = min(self._stats.min_datagram_size, datagram.size)
        self._stats.max_datagram_size = max(self._stats.max_datagram_size, datagram.size)

    def __str__(self) -> str:
        """Format a concise summary of datagram stream info for logging."""
        stats = self.stats
        return (
            f"DatagramStream({self.session_id[:12]}..., "
            f"sent={stats['datagrams_sent']}, "
            f"received={stats['datagrams_received']}, "
            f"success_rate={stats['send_success_rate']:.2%}, "
            f"avg_size={stats['avg_datagram_size']:.0f}B)"
        )
