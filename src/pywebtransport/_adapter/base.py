"""Shared protocol adapter logic for client and server."""

from __future__ import annotations

import asyncio
from typing import Any

from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.connection import QuicConnection
from aioquic.quic.events import (
    ConnectionTerminated,
    DatagramFrameReceived,
    HandshakeCompleted,
    QuicEvent,
    StreamDataReceived,
    StreamReset,
)
from aioquic.quic.logger import QuicLoggerTrace

from pywebtransport._protocol.events import (
    ProtocolEvent,
    TransportConnectionTerminated,
    TransportDatagramFrameReceived,
    TransportHandshakeCompleted,
    TransportQuicParametersReceived,
    TransportQuicTimerFired,
    TransportStreamDataReceived,
    TransportStreamReset,
)
from pywebtransport.constants import DEFAULT_MAX_EVENT_QUEUE_SIZE, ErrorCodes
from pywebtransport.types import Buffer
from pywebtransport.utils import get_logger

__all__: list[str] = []

logger = get_logger(name=__name__)


class WebTransportCommonProtocol(QuicConnectionProtocol):
    """Base adapter translating aioquic events to internal protocol events."""

    _quic_logger: QuicLoggerTrace | None = None

    def __init__(
        self,
        *,
        quic: QuicConnection,
        stream_handler: Any = None,
        loop: asyncio.AbstractEventLoop | None = None,
        max_event_queue_size: int = DEFAULT_MAX_EVENT_QUEUE_SIZE,
    ) -> None:
        """Initialize the common protocol adapter."""
        super().__init__(quic=quic, stream_handler=stream_handler)
        self._loop = loop or asyncio.get_running_loop()
        self._engine_queue: asyncio.Queue[ProtocolEvent] | None = None
        self._pending_events: list[ProtocolEvent] = []
        self._max_event_queue_size = max_event_queue_size
        self._timer_handle: asyncio.TimerHandle | None = None

    def close_connection(self, *, error_code: int, reason_phrase: str | None = None) -> None:
        """Close the QUIC connection."""
        if self._quic._close_event is not None:
            return

        self._quic.close(error_code=error_code, reason_phrase=reason_phrase or "")
        self.transmit()

    def connection_lost(self, exc: Exception | None) -> None:
        """Handle connection loss."""
        if self._timer_handle:
            self._timer_handle.cancel()
            self._timer_handle = None

        event_to_send: TransportConnectionTerminated | None = None
        already_closing_locally = self._quic._close_event is not None

        if exc is None and already_closing_locally:
            pass
        else:
            if exc is not None:
                code = getattr(exc, "error_code", ErrorCodes.INTERNAL_ERROR)
                reason = str(exc)
            else:
                code = ErrorCodes.NO_ERROR
                reason = "Connection closed"
            event_to_send = TransportConnectionTerminated(error_code=code, reason_phrase=reason)

        if event_to_send:
            self._push_event_to_engine(event=event_to_send)

        super().connection_lost(exc)

    def get_next_available_stream_id(self, *, is_unidirectional: bool) -> int:
        """Get the next available stream ID from the QUIC connection."""
        return self._quic.get_next_available_stream_id(is_unidirectional=is_unidirectional)

    def get_server_name(self) -> str | None:
        """Get the server name (SNI) from the QUIC configuration."""
        return self._quic.configuration.server_name

    def handle_timer_now(self) -> None:
        """Handle the QUIC timer expiry."""
        self._quic.handle_timer(now=self._loop.time())

        event = self._quic.next_event()
        while event is not None:
            self.quic_event_received(event=event)
            event = self._quic.next_event()

        self.transmit()

    def log_event(self, *, category: str, event: str, data: dict[str, Any]) -> None:
        """Log an H3 event via the QUIC logger."""
        if self._quic_logger:
            self._quic_logger.log_event(category=category, event=event, data=data)

    def quic_event_received(self, event: QuicEvent) -> None:
        """Translate aioquic events into internal ProtocolEvents."""
        match event:
            case HandshakeCompleted():
                logger.debug("QUIC HandshakeCompleted event received.")
                self._push_event_to_engine(event=TransportHandshakeCompleted())
                remote_max_dg_size = self._quic._remote_max_datagram_frame_size
                self._push_event_to_engine(
                    event=TransportQuicParametersReceived(
                        remote_max_datagram_frame_size=remote_max_dg_size if remote_max_dg_size is not None else 0
                    )
                )
            case ConnectionTerminated(error_code=error_code, reason_phrase=reason_phrase):
                logger.debug(
                    "QUIC ConnectionTerminated event received: code=%#x reason='%s'", error_code, reason_phrase
                )
                self._push_event_to_engine(
                    event=TransportConnectionTerminated(error_code=error_code, reason_phrase=reason_phrase)
                )
            case DatagramFrameReceived(data=data):
                self._push_event_to_engine(event=TransportDatagramFrameReceived(data=data))
            case StreamDataReceived(data=data, end_stream=end_stream, stream_id=stream_id):
                self._push_event_to_engine(
                    event=TransportStreamDataReceived(data=data, end_stream=end_stream, stream_id=stream_id)
                )
            case StreamReset(error_code=error_code, stream_id=stream_id):
                self._push_event_to_engine(event=TransportStreamReset(error_code=error_code, stream_id=stream_id))
            case _:
                pass

    def reset_stream(self, *, stream_id: int, error_code: int) -> None:
        """Reset the sending side of a QUIC stream."""
        if self._quic._close_event is not None:
            return

        try:
            self._quic.reset_stream(stream_id=stream_id, error_code=error_code)
            self.transmit()
        except AssertionError:
            logger.debug("Dropping ResetQuicStream for stream %d: I/O state conflict.", stream_id)

    def schedule_timer_now(self) -> None:
        """Schedule the next QUIC timer callback."""
        if self._timer_handle:
            self._timer_handle.cancel()

        timer_at = self._quic.get_timer()
        if timer_at is not None:
            self._timer_handle = self._loop.call_at(timer_at, self._handle_timer)

    def send_datagram_frame(self, *, data: Buffer | list[Buffer]) -> None:
        """Send a QUIC datagram frame (supports Scatter/Gather)."""
        if self._quic._close_event is not None:
            logger.warning("Attempted to send datagram while connection is closing.")
            return

        bytes_data: bytes
        if isinstance(data, list):
            bytes_data = b"".join(data)
        else:
            bytes_data = bytes(data)

        self._quic.send_datagram_frame(data=bytes_data)
        self.transmit()

    def send_stream_data(self, *, stream_id: int, data: bytes, end_stream: bool = False) -> None:
        """Send data on a QUIC stream."""
        if self._quic._close_event is not None:
            if data or not end_stream:
                logger.warning("Attempted to send stream data while connection is closing (stream %d).", stream_id)
                return

        try:
            self._quic.send_stream_data(stream_id=stream_id, data=data, end_stream=end_stream)
            self.transmit()
        except AssertionError:
            logger.debug("Dropping SendQuicData for stream %d: I/O state conflict.", stream_id)

    def set_engine_queue(self, *, engine_queue: asyncio.Queue[ProtocolEvent]) -> None:
        """Provide the queue for sending events to the engine."""
        self._engine_queue = engine_queue

        if self._pending_events:
            logger.debug("Flushing %d buffered early events to engine.", len(self._pending_events))
            for event in self._pending_events:
                self._push_event_to_engine(event=event)
            self._pending_events.clear()

        self.schedule_timer_now()

    def stop_stream(self, *, stream_id: int, error_code: int) -> None:
        """Stop the receiving side of a QUIC stream."""
        try:
            self._quic.stop_stream(stream_id=stream_id, error_code=error_code)
        except AssertionError:
            logger.debug("Dropping StopQuicStream for stream %d: I/O state conflict.", stream_id)

    def transmit(self) -> None:
        """Transmit pending QUIC packets."""
        transport = self._transport
        if (
            transport is not None
            and hasattr(transport, "is_closing")
            and not transport.is_closing()
            and hasattr(transport, "sendto")
        ):
            packets = self._quic.datagrams_to_send(now=self._loop.time())
            is_client = self._quic.configuration.is_client
            for data, addr in packets:
                try:
                    if is_client:
                        transport.sendto(data)
                    else:
                        transport.sendto(data, addr)
                except (ConnectionRefusedError, OSError) as e:
                    logger.debug("Failed to send UDP packet: %s", e)
                except Exception as e:
                    logger.error("Unexpected error during transmit: %s", e, exc_info=True)

    def _handle_timer(self) -> None:
        """Handle the QUIC timer expiry by injecting an event."""
        self._timer_handle = None
        self._push_event_to_engine(event=TransportQuicTimerFired())

    def _push_event_to_engine(self, *, event: ProtocolEvent) -> None:
        """Push an event to the engine queue with backpressure and circuit breaking."""
        if self._engine_queue is not None:
            try:
                self._engine_queue.put_nowait(event)
            except asyncio.QueueFull:
                if isinstance(event, TransportDatagramFrameReceived):
                    logger.warning("Engine queue full (%d), dropping incoming datagram.", self._max_event_queue_size)
                else:
                    logger.critical(
                        "Engine queue full (%d), critical event %s lost. Closing connection.",
                        self._max_event_queue_size,
                        type(event).__name__,
                    )
                    self.close_connection(error_code=ErrorCodes.INTERNAL_ERROR, reason_phrase="Engine overload")
        else:
            if len(self._pending_events) >= self._max_event_queue_size:
                logger.warning(
                    "Pending event buffer full (%d), closing connection to prevent OOM.", self._max_event_queue_size
                )
                self.close_connection(error_code=ErrorCodes.INTERNAL_ERROR, reason_phrase="Handshake overload")
                return
            self._pending_events.append(event)
