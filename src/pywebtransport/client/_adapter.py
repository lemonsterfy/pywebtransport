"""Internal aioquic protocol adapter and connection factory for the client-side."""

from __future__ import annotations

import asyncio
from typing import Any

from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
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
from pywebtransport.config import ClientConfig
from pywebtransport.connection.connection import WebTransportConnection
from pywebtransport.constants import ErrorCodes
from pywebtransport.utils import create_quic_configuration, get_logger

__all__: list[str] = []

logger = get_logger(name=__name__)


class WebTransportClientProtocol(QuicConnectionProtocol):
    """Adapt aioquic client events and actions for the WebTransportEngine."""

    _quic_logger: QuicLoggerTrace | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the client protocol adapter."""
        super().__init__(*args, **kwargs)
        self._engine_queue: asyncio.Queue[ProtocolEvent] | None = None
        self._pending_events: list[ProtocolEvent] = []
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

        if not isinstance(exc, ConnectionTerminated):
            if not already_closing_locally:
                if exc is not None:
                    code = getattr(exc, "error_code", ErrorCodes.INTERNAL_ERROR)
                    reason = str(exc)
                else:
                    code = ErrorCodes.NO_ERROR
                    reason = "Connection closed"
                event_to_send = TransportConnectionTerminated(error_code=code, reason_phrase=reason)

        if event_to_send:
            if self._engine_queue:
                self._engine_queue.put_nowait(item=event_to_send)
            else:
                self._pending_events.append(event_to_send)

        super().connection_lost(exc)

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Handle connection establishment."""
        super().connection_made(transport)

    def get_next_available_stream_id(self, *, is_unidirectional: bool) -> int:
        """Get the next available stream ID from the QUIC connection."""
        return self._quic.get_next_available_stream_id(is_unidirectional=is_unidirectional)

    def get_server_name(self) -> str | None:
        """Get the server name (SNI) from the QUIC configuration."""
        return self._quic.configuration.server_name

    def reset_stream(self, *, stream_id: int, error_code: int) -> None:
        """Reset the sending side of a QUIC stream."""
        if self._quic._close_event is not None:
            return

        try:
            self._quic.reset_stream(stream_id=stream_id, error_code=error_code)
            self.transmit()
        except AssertionError:
            logger.debug("Dropping ResetQuicStream for stream %d: I/O state conflict.", stream_id)

    def send_datagram_frame(self, *, data: bytes) -> None:
        """Send a QUIC datagram frame."""
        if self._quic._close_event is not None:
            logger.warning("Attempted to send datagram while connection is closing.")
            return

        self._quic.send_datagram_frame(data=data)
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
                self._engine_queue.put_nowait(item=event)
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
        if self._transport is not None and hasattr(self._transport, "is_closing") and not self._transport.is_closing():
            packets = self._quic.datagrams_to_send(now=self._loop.time())
            for data, addr in packets:
                try:
                    self._transport.sendto(data, addr)
                except (ConnectionRefusedError, OSError) as e:
                    logger.debug("Failed to send UDP packet: %s", e)
                except Exception as e:
                    logger.error("Unexpected error during transmit: %s", e, exc_info=True)

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
        events_to_send: list[ProtocolEvent] = []
        match event:
            case HandshakeCompleted():
                logger.debug("QUIC HandshakeCompleted event received.")
                events_to_send.append(TransportHandshakeCompleted())
                remote_max_dg_size = self._quic._remote_max_datagram_frame_size
                events_to_send.append(
                    TransportQuicParametersReceived(
                        remote_max_datagram_frame_size=remote_max_dg_size if remote_max_dg_size is not None else 0
                    )
                )
            case ConnectionTerminated(error_code=error_code, reason_phrase=reason_phrase):
                logger.debug(
                    "QUIC ConnectionTerminated event received: code=%#x reason='%s'", error_code, reason_phrase
                )
                events_to_send.append(TransportConnectionTerminated(error_code=error_code, reason_phrase=reason_phrase))
            case DatagramFrameReceived(data=data):
                events_to_send.append(TransportDatagramFrameReceived(data=data))
            case StreamDataReceived(data=data, end_stream=end_stream, stream_id=stream_id):
                events_to_send.append(
                    TransportStreamDataReceived(data=data, end_stream=end_stream, stream_id=stream_id)
                )
            case StreamReset(error_code=error_code, stream_id=stream_id):
                events_to_send.append(TransportStreamReset(error_code=error_code, stream_id=stream_id))
            case _:
                pass

        if self._engine_queue is not None:
            for internal_event in events_to_send:
                self._engine_queue.put_nowait(item=internal_event)
        else:
            self._pending_events.extend(events_to_send)

    def schedule_timer_now(self) -> None:
        """Schedule the next QUIC timer callback."""
        if self._timer_handle:
            self._timer_handle.cancel()

        timer_at = self._quic.get_timer()
        if timer_at is not None:
            self._timer_handle = self._loop.call_at(timer_at, self._handle_timer)

    def _handle_timer(self) -> None:
        """Handle the QUIC timer expiry by injecting an event."""
        self._timer_handle = None
        if self._engine_queue:
            self._engine_queue.put_nowait(item=TransportQuicTimerFired())


async def create_connection(
    *, host: str, port: int, config: ClientConfig, loop: asyncio.AbstractEventLoop
) -> WebTransportConnection:
    """Establish the underlying QUIC connection and transport."""
    quic_config: QuicConfiguration = create_quic_configuration(
        alpn_protocols=config.alpn_protocols,
        congestion_control_algorithm=config.congestion_control_algorithm,
        idle_timeout=config.connection_idle_timeout,
        is_client=True,
        max_datagram_size=config.max_datagram_size,
    )
    quic_config.server_name = host
    if config.ca_certs:
        quic_config.load_verify_locations(cafile=config.ca_certs)
    if config.certfile and config.keyfile:
        quic_config.load_cert_chain(certfile=config.certfile, keyfile=config.keyfile)
    if config.verify_mode is not None:
        quic_config.verify_mode = config.verify_mode

    quic_connection = QuicConnection(configuration=quic_config)

    def protocol_factory() -> WebTransportClientProtocol:
        proto = WebTransportClientProtocol(quic_connection)
        return proto

    logger.debug("Creating datagram endpoint to %s:%d", host, port)
    transport, protocol = await loop.create_datagram_endpoint(
        protocol_factory=protocol_factory, remote_addr=(host, port)
    )
    logger.debug("Datagram endpoint created.")

    protocol._quic.connect(addr=(host, port), now=loop.time())
    protocol.transmit()

    connection = WebTransportConnection(config=config, protocol=protocol, transport=transport, is_client=True)
    await connection.initialize()

    return connection
