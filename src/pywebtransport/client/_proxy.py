"""Low-level handshake logic for connecting via an HTTP/3 proxy."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.connection import QuicConnection
from aioquic.quic.events import QuicEvent

from pywebtransport.exceptions import ConfigurationError, HandshakeError
from pywebtransport.protocol.events import H3Event, HeadersReceived
from pywebtransport.protocol.h3_engine import WebTransportH3Engine
from pywebtransport.types import Address
from pywebtransport.utils import create_quic_configuration

if TYPE_CHECKING:
    from pywebtransport.config import ClientConfig


__all__: list[str] = []


class _ProxyHandshakeProtocol(QuicConnectionProtocol):
    """A specialized QUIC protocol for handling the proxy CONNECT handshake."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the proxy handshake protocol."""
        super().__init__(*args, **kwargs)
        self._event_queue: asyncio.Queue[QuicEvent] | None = None
        self._waiter: asyncio.Future[None] | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Initialize asyncio resources when the connection is established."""
        super().connection_made(transport)
        self._event_queue = asyncio.Queue()

    async def get_event(self) -> QuicEvent:
        """Get the next event from the queue."""
        if self._event_queue is None:
            raise HandshakeError(message="Event queue not initialized.")
        return await self._event_queue.get()

    def quic_event_received(self, event: QuicEvent) -> None:
        """Queue events to be processed by the handshake logic."""
        if self._waiter and not self._waiter.done() and self._event_queue:
            self._event_queue.put_nowait(event)

    def set_waiter(self, waiter: asyncio.Future[None]) -> None:
        """Set the future to be resolved upon handshake completion."""
        self._waiter = waiter


async def perform_proxy_handshake(
    *,
    config: ClientConfig,
    target_host: str,
    target_port: int,
) -> Address:
    """Perform the HTTP CONNECT handshake with the proxy server."""
    if not config.proxy:
        raise ConfigurationError(message="Proxy is not configured.")

    proxy_url = urlparse(config.proxy.url)
    proxy_host = proxy_url.hostname
    proxy_port = proxy_url.port
    if not proxy_host or not proxy_port:
        raise ConfigurationError(message="Invalid proxy URL.")

    proxy_addr: Address = (proxy_host, proxy_port)
    quic_config = create_quic_configuration(
        is_client=True,
        alpn_protocols=config.alpn_protocols,
        congestion_control_algorithm=config.congestion_control_algorithm,
        max_datagram_size=config.max_datagram_size,
    )
    quic_config.server_name = proxy_addr[0]
    if config.verify_mode is not None:
        quic_config.verify_mode = config.verify_mode

    quic_connection = QuicConnection(configuration=quic_config)
    h3_engine = WebTransportH3Engine(quic=quic_connection, config=config)
    waiter = asyncio.Future[None]()

    async def event_processor() -> None:
        while not waiter.done():
            event = await protocol.get_event()
            h3_events: list[H3Event] = await h3_engine.handle_event(event=event)
            for h3_event in h3_events:
                if isinstance(h3_event, HeadersReceived):
                    status_code = h3_event.headers.get(":status")
                    if status_code == "200":
                        waiter.set_result(None)
                    else:
                        reason = status_code if status_code is not None else "No status code received"
                        waiter.set_exception(HandshakeError(message=f"Proxy returned status {reason}"))

    protocol = _ProxyHandshakeProtocol(quic_connection)
    protocol.set_waiter(waiter)
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(lambda: protocol, remote_addr=proxy_addr)
    processor_task = asyncio.create_task(event_processor())

    try:
        quic_connection.connect(proxy_addr, now=loop.time())
        stream_id = quic_connection.get_next_available_stream_id()
        headers = {
            ":method": "CONNECT",
            ":authority": f"{target_host}:{target_port}",
            "user-agent": config.user_agent,
            **config.proxy.headers,
        }
        h3_engine.send_headers(stream_id=stream_id, headers=headers, end_stream=False)
        protocol.transmit()
        await asyncio.wait_for(waiter, timeout=config.proxy.connect_timeout)
    finally:
        processor_task.cancel()
        try:
            await processor_task
        except asyncio.CancelledError:
            pass
        transport.close()

    return proxy_addr
