"""WebTransport Server Utilities."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pywebtransport.config import ServerConfig
from pywebtransport.server.app import ServerApp
from pywebtransport.session import WebTransportSession
from pywebtransport.stream import WebTransportStream
from pywebtransport.utils import generate_self_signed_cert, get_logger

__all__ = [
    "create_development_server",
    "create_echo_server_app",
    "create_simple_app",
    "echo_handler",
    "health_check_handler",
]

logger = get_logger(name="server.utils")


def create_development_server(*, host: str = "localhost", port: int = 4433, generate_certs: bool = True) -> ServerApp:
    """Create a development server application with self-signed certificates."""
    cert_path = Path(f"{host}.crt")
    key_path = Path(f"{host}.key")

    if generate_certs or not (cert_path.exists() and key_path.exists()):
        logger.info("Generating self-signed certificate for %s...", host)
        generate_self_signed_cert(hostname=host)

    config = ServerConfig.create_for_development(host=host, port=port, certfile=str(cert_path), keyfile=str(key_path))

    return ServerApp(config=config)


def create_echo_server_app(*, config: ServerConfig | None = None) -> ServerApp:
    """Create a simple echo server application."""
    app = ServerApp(config=config)
    app.route(path="/")(echo_handler)
    return app


def create_simple_app() -> ServerApp:
    """Create a simple application with basic health and echo routes."""
    app = ServerApp()
    app.route(path="/health")(health_check_handler)
    app.route(path="/echo")(echo_handler)
    return app


async def echo_handler(session: WebTransportSession) -> None:
    """Echo all received datagrams and stream data back to the client."""
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_echo_datagrams(session=session))
            tg.create_task(_echo_streams(session=session))
    except* Exception as eg:
        logger.error("Echo handler error for session %s: %s", session.session_id, eg.exceptions, exc_info=True)


async def health_check_handler(session: WebTransportSession) -> None:
    """Send a simple health status datagram and close the session."""
    try:
        datagram_transport = await session.datagrams
        await datagram_transport.send(data=b'{"status": "healthy"}')
    except Exception as e:
        logger.error("Health check datagram send failed: %s", e, exc_info=True)
    finally:
        await session.close()


async def _echo_datagrams(*, session: WebTransportSession) -> None:
    """Echo datagrams received on a session."""
    try:
        datagram_transport = await session.datagrams
        while not session.is_closed:
            data = await datagram_transport.receive()
            if data:
                await datagram_transport.send(data=b"ECHO: " + data)
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


async def _echo_streams(*, session: WebTransportSession) -> None:
    """Accept and handle all incoming streams for echoing."""
    try:
        async for stream in session.incoming_streams():
            if isinstance(stream, WebTransportStream):
                asyncio.create_task(_echo_single_stream(stream=stream))
    except asyncio.CancelledError:
        pass


async def _echo_single_stream(*, stream: WebTransportStream) -> None:
    """Echo data for a single bidirectional stream."""
    try:
        async for data in stream.read_iter():
            await stream.write(data=b"ECHO: " + data)
        await stream.close()
    except Exception as e:
        logger.error("Error echoing stream %d: %s", stream.stream_id, e, exc_info=True)
