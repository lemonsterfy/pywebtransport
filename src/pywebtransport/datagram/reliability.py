"""
WebTransport Datagram Reliability Layer.
"""

from __future__ import annotations

import asyncio
import struct
import weakref
from collections import deque
from types import TracebackType
from typing import TYPE_CHECKING, Self, Type

from pywebtransport.datagram.transport import DatagramMessage, WebTransportDatagramTransport
from pywebtransport.events import EventType
from pywebtransport.exceptions import DatagramError, TimeoutError
from pywebtransport.types import Data
from pywebtransport.utils import ensure_bytes, get_logger, get_timestamp

if TYPE_CHECKING:
    from pywebtransport.events import Event


__all__ = ["DatagramReliabilityLayer"]

logger = get_logger(name="datagram.reliability")


class _ReliableDatagram(DatagramMessage):
    """An internal datagram message with added reliability metadata."""

    retry_count: int = 0


class DatagramReliabilityLayer:
    """Adds a TCP-like reliability layer over an unreliable datagram transport."""

    def __init__(
        self,
        datagram_transport: WebTransportDatagramTransport,
        *,
        ack_timeout: float = 2.0,
        max_retries: int = 5,
    ):
        """Initialize the datagram reliability layer."""
        self._transport = weakref.ref(datagram_transport)
        self._ack_timeout = ack_timeout
        self._max_retries = max_retries
        self._closed = False
        self._send_sequence = 0
        self._receive_sequence = 0
        self._pending_acks: dict[int, _ReliableDatagram] = {}
        self._received_sequences: deque[int] = deque(maxlen=1024)
        self._incoming_queue: asyncio.Queue[bytes] | None = None
        self._lock: asyncio.Lock | None = None
        self._retry_task: asyncio.Task[None] | None = None

    @classmethod
    def create(
        cls,
        *,
        datagram_transport: WebTransportDatagramTransport,
        ack_timeout: float = 1.0,
        max_retries: int = 3,
    ) -> Self:
        """Factory method to create a new datagram reliability layer for a transport."""
        return cls(
            datagram_transport=datagram_transport,
            ack_timeout=ack_timeout,
            max_retries=max_retries,
        )

    async def __aenter__(self) -> Self:
        """Enter the async context and start background tasks."""
        self._lock = asyncio.Lock()
        self._incoming_queue = asyncio.Queue()
        if transport := self._transport():
            transport.on(event_type=EventType.DATAGRAM_RECEIVED, handler=self._on_datagram_received)
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

        if transport := self._transport():
            transport.off(event_type=EventType.DATAGRAM_RECEIVED, handler=self._on_datagram_received)

        if self._retry_task:
            self._retry_task.cancel()
            try:
                await self._retry_task
            except asyncio.CancelledError:
                pass

        if self._lock:
            async with self._lock:
                self._pending_acks.clear()

        self._received_sequences.clear()
        logger.debug("Reliability layer closed")

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
            return await asyncio.wait_for(self._incoming_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Receive timeout after {timeout}s") from None

    async def send(self, *, data: Data) -> None:
        """Send a datagram with guaranteed delivery."""
        if self._lock is None:
            raise DatagramError("Reliability layer has not been activated.")

        transport = self._get_transport()
        data_bytes = ensure_bytes(data=data)

        async with self._lock:
            seq = self._send_sequence
            self._send_sequence += 1
            data_payload = struct.pack("!I", seq) + data_bytes
            datagram = _ReliableDatagram(data=data_payload, sequence=seq)
            self._pending_acks[seq] = datagram

        await transport._send_framed_data(message_type="DATA", payload=data_payload)
        logger.debug("Sent reliable datagram with sequence %d", seq)

    def _get_transport(self) -> WebTransportDatagramTransport:
        """Get the underlying transport or raise an error if it is gone or closed."""
        transport = self._transport()
        if self._closed or not transport or transport.is_closed:
            raise DatagramError("Reliability layer or underlying transport is closed.")
        return transport

    async def _handle_ack_message(self, *, payload: bytes) -> None:
        """Handle an incoming ACK message."""
        if self._lock is None:
            return
        try:
            seq = int(payload.decode("utf-8"))
            async with self._lock:
                if seq in self._pending_acks:
                    del self._pending_acks[seq]
                    logger.debug("Received ACK for sequence %d", seq)
        except (ValueError, UnicodeDecodeError):
            logger.warning("Received malformed ACK: %r", payload)

    async def _handle_data_message(self, *, payload: bytes) -> None:
        """Handle an incoming DATA message."""
        if self._incoming_queue is None:
            return
        if len(payload) < 4:
            return

        seq = struct.unpack("!I", payload[:4])[0]
        data = payload[4:]

        try:
            transport = self._get_transport()
            await transport._send_framed_data(message_type="ACK", payload=str(seq).encode("utf-8"))
        except DatagramError as e:
            logger.warning("Failed to send ACK for sequence %d: %s", seq, e, exc_info=True)
            return

        if seq in self._received_sequences:
            logger.debug("Ignoring duplicate reliable datagram with sequence %d", seq)
            return

        self._received_sequences.append(seq)
        await self._incoming_queue.put(data)

    async def _on_datagram_received(self, event: Event) -> None:
        """Handle all incoming datagrams from the underlying transport."""
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

            match message_type:
                case "ACK":
                    await self._handle_ack_message(payload=payload)
                case "DATA":
                    await self._handle_data_message(payload=payload)
        except (IndexError, UnicodeDecodeError):
            pass
        except Exception as e:
            logger.error(
                "Error processing received datagram for reliability: %s",
                e,
                exc_info=e,
            )

    async def _retry_loop(self) -> None:
        """Periodically check for and retry unacknowledged datagrams."""
        if self._lock is None:
            return
        try:
            while not self._closed:
                await asyncio.sleep(self._ack_timeout)
                current_time = get_timestamp()
                to_retry: list[_ReliableDatagram] = []

                async with self._lock:
                    for datagram in list(self._pending_acks.values()):
                        if current_time - datagram.timestamp > self._ack_timeout:
                            if datagram.retry_count >= self._max_retries:
                                if datagram.sequence is not None and datagram.sequence in self._pending_acks:
                                    del self._pending_acks[datagram.sequence]
                                logger.warning(
                                    "Gave up on sequence %s after %d retries.",
                                    datagram.sequence,
                                    datagram.retry_count,
                                )
                            else:
                                to_retry.append(datagram)

                if not to_retry:
                    continue

                try:
                    transport = self._get_transport()
                except DatagramError:
                    logger.warning("Could not retry datagrams, transport is closed.")
                    self._closed = True
                    return

                try:
                    async with asyncio.TaskGroup() as tg:
                        for datagram in to_retry:
                            async with self._lock:
                                datagram.retry_count += 1
                                datagram.timestamp = get_timestamp()
                            tg.create_task(transport._send_framed_data(message_type="DATA", payload=datagram.data))
                            logger.debug(
                                "Retrying sequence %s, attempt %d",
                                datagram.sequence,
                                datagram.retry_count,
                            )
                except* Exception as eg:
                    logger.warning(
                        "Errors occurred during datagram retry: %s",
                        eg.exceptions,
                        exc_info=eg,
                    )

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Reliability retry loop crashed: %s", e, exc_info=e)

    def _start_background_tasks(self) -> None:
        """Start the background retry task if it is not already running."""
        if self._retry_task is None:
            try:
                self._retry_task = asyncio.create_task(self._retry_loop())
            except RuntimeError:
                logger.warning("Could not start reliability layer tasks: No running event loop.")
