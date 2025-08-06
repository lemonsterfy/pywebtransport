"""
WebTransport Datagram Reliability Layer.
"""

from __future__ import annotations

import asyncio
import struct
from collections import deque
from types import TracebackType
from typing import TYPE_CHECKING, Self, Type
import weakref

from pywebtransport.datagram.transport import DatagramMessage, WebTransportDatagramDuplexStream
from pywebtransport.events import EventType
from pywebtransport.exceptions import DatagramError, TimeoutError
from pywebtransport.types import Data
from pywebtransport.utils import ensure_bytes, get_logger, get_timestamp

if TYPE_CHECKING:
    from pywebtransport.events import Event


__all__ = ["DatagramReliabilityLayer"]

logger = get_logger("datagram.reliability")


class _ReliableDatagram(DatagramMessage):
    """An internal datagram message with added reliability metadata."""

    retry_count: int = 0


class DatagramReliabilityLayer:
    """Adds a TCP-like reliability layer over an unreliable datagram stream."""

    def __init__(
        self,
        datagram_stream: WebTransportDatagramDuplexStream,
        *,
        ack_timeout: float = 2.0,
        max_retries: int = 5,
    ):
        """Initialize the datagram reliability layer."""
        self._stream = weakref.ref(datagram_stream)
        self._ack_timeout = ack_timeout
        self._max_retries = max_retries
        self._closed = False
        self._send_sequence = 0
        self._receive_sequence = 0
        self._pending_acks: dict[int, _ReliableDatagram] = {}
        self._received_sequences: deque[int] = deque(maxlen=1024)
        self._incoming_queue: asyncio.Queue[bytes] | None = None
        self._retry_task: asyncio.Task[None] | None = None

    @classmethod
    def create(
        cls,
        datagram_stream: WebTransportDatagramDuplexStream,
        *,
        ack_timeout: float = 1.0,
        max_retries: int = 3,
    ) -> Self:
        """Factory method to create a new datagram reliability layer for a stream."""
        return cls(datagram_stream, ack_timeout=ack_timeout, max_retries=max_retries)

    async def __aenter__(self) -> Self:
        """Enter the async context and start background tasks."""
        self._incoming_queue = asyncio.Queue()
        stream = self._stream()
        if stream:
            stream.on(EventType.DATAGRAM_RECEIVED, self._on_datagram_received)
        self._start_background_tasks()
        return self

    async def __aexit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the async context and close the reliability layer."""
        await self.close()

    async def close(self) -> None:
        """Gracefully close the reliability layer and clean up resources."""
        if self._closed:
            return
        self._closed = True

        stream = self._stream()
        if stream:
            stream.off(EventType.DATAGRAM_RECEIVED, self._on_datagram_received)

        if self._retry_task:
            self._retry_task.cancel()
            try:
                await self._retry_task
            except asyncio.CancelledError:
                pass

        self._pending_acks.clear()
        self._received_sequences.clear()
        logger.debug("Reliability layer closed")

    async def send(self, data: Data) -> None:
        """Send a datagram with guaranteed delivery."""
        stream = self._get_stream()
        data_bytes = ensure_bytes(data)
        seq = self._send_sequence
        self._send_sequence += 1

        data_payload = struct.pack("!I", seq) + data_bytes
        datagram = _ReliableDatagram(data=data_payload, sequence=seq)
        self._pending_acks[seq] = datagram

        await stream.send_structured("DATA", data_payload)
        logger.debug(f"Sent reliable datagram with sequence {seq}")

    async def receive(self, *, timeout: float | None = None) -> bytes:
        """Receive a reliable datagram, waiting if necessary."""
        if self._incoming_queue is None:
            raise DatagramError(
                "DatagramReliabilityLayer has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        if self._closed:
            raise DatagramError("Reliability layer is closed.")
        try:
            return await asyncio.wait_for(self._incoming_queue.get(), timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Receive timeout after {timeout}s") from None

    def _start_background_tasks(self) -> None:
        """Start the background retry task if it is not already running."""
        if self._retry_task is None:
            try:
                self._retry_task = asyncio.create_task(self._retry_loop())
            except RuntimeError:
                logger.warning("Could not start reliability layer tasks: No running event loop.")

    async def _retry_loop(self) -> None:
        """Periodically check for and retry unacknowledged datagrams."""
        try:
            while not self._closed:
                await asyncio.sleep(self._ack_timeout)
                current_time = get_timestamp()
                to_retry: list[_ReliableDatagram] = []

                for datagram in list(self._pending_acks.values()):
                    if current_time - datagram.timestamp > self._ack_timeout:
                        to_retry.append(datagram)

                for datagram in to_retry:
                    seq = datagram.sequence
                    if seq is None:
                        continue

                    if datagram.retry_count < self._max_retries:
                        datagram.retry_count += 1
                        datagram.timestamp = current_time
                        try:
                            stream = self._get_stream()
                            await stream.send_structured("DATA", datagram.data)
                            logger.debug(f"Retrying sequence {seq}, attempt {datagram.retry_count + 1}")
                        except DatagramError:
                            logger.warning(f"Could not retry sequence {seq}, stream is closed.")
                            self._closed = True
                            return
                    else:
                        if seq in self._pending_acks:
                            del self._pending_acks[seq]
                        logger.warning(f"Gave up on sequence {seq} after {datagram.retry_count} retries.")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Reliability retry loop crashed: {e}", exc_info=e)

    async def _on_datagram_received(self, event: Event) -> None:
        """Handle all incoming datagrams from the underlying stream."""
        if self._incoming_queue is None:
            return
        if not isinstance(event.data, dict):
            return

        raw_data = event.data.get("data")
        if not isinstance(raw_data, bytes):
            return

        try:
            type_len = raw_data[0]
            if len(raw_data) < 1 + type_len:
                return
            message_type = raw_data[1 : 1 + type_len].decode("utf-8")
            payload = raw_data[1 + type_len :]

            if message_type == "ACK":
                await self._handle_ack_message(payload)
            elif message_type == "DATA":
                await self._handle_data_message(payload)
        except (IndexError, UnicodeDecodeError):
            pass
        except Exception as e:
            logger.error(f"Error processing received datagram for reliability: {e}", exc_info=e)

    async def _handle_ack_message(self, payload: bytes) -> None:
        """Handle an incoming ACK message."""
        try:
            seq = int(payload.decode("utf-8"))
            if seq in self._pending_acks:
                del self._pending_acks[seq]
                logger.debug(f"Received ACK for sequence {seq}")
        except (ValueError, UnicodeDecodeError):
            logger.warning(f"Received malformed ACK: {payload!r}")

    async def _handle_data_message(self, payload: bytes) -> None:
        """Handle an incoming DATA message."""
        if self._incoming_queue is None:
            return
        if len(payload) < 4:
            return

        seq = struct.unpack("!I", payload[:4])[0]
        data = payload[4:]

        try:
            stream = self._get_stream()
            await stream.send_structured("ACK", str(seq).encode("utf-8"))
        except DatagramError as e:
            logger.warning(f"Failed to send ACK for sequence {seq}: {e}")
            return

        if seq in self._received_sequences:
            logger.debug(f"Ignoring duplicate reliable datagram with sequence {seq}")
            return

        self._received_sequences.append(seq)
        await self._incoming_queue.put(data)

    def _get_stream(self) -> WebTransportDatagramDuplexStream:
        """Get the underlying stream or raise an error if it is gone or closed."""
        stream = self._stream()
        if self._closed or not stream or stream.is_closed:
            raise DatagramError("Reliability layer or underlying stream is closed.")
        return stream
