"""
WebTransport Server Utilities.
"""

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

logger = get_logger("server.utils")


def create_development_server(*, host: str = "localhost", port: int = 4433, generate_certs: bool = True) -> ServerApp:
    """Create a development server application with self-signed certificates."""
    cert_path = Path(f"{host}.crt")
    key_path = Path(f"{host}.key")

    if generate_certs or not (cert_path.exists() and key_path.exists()):
        logger.info(f"Generating self-signed certificate for {host}...")
        generate_self_signed_cert(host)

    config = ServerConfig.create_for_development(host=host, port=port, certfile=str(cert_path), keyfile=str(key_path))

    return ServerApp(config=config)


def create_echo_server_app(*, config: ServerConfig | None = None) -> ServerApp:
    """Create a simple echo server application."""
    app = ServerApp(config=config)
    app.route("/")(echo_handler)
    return app


def create_simple_app() -> ServerApp:
    """Create a simple application with basic health and echo routes."""
    app = ServerApp()
    app.route("/health")(health_check_handler)
    app.route("/echo")(echo_handler)
    return app


async def echo_handler(session: WebTransportSession) -> None:
    """Echo all received datagrams and stream data back to the client."""
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_echo_datagrams(session))
            tg.create_task(_echo_streams(session))
    except* Exception as eg:
        logger.error(f"Echo handler error for session {session.session_id}: {eg.exceptions}", exc_info=eg)


async def health_check_handler(session: WebTransportSession) -> None:
    """Send a simple health status datagram and close the session."""
    try:
        datagrams = await session.datagrams
        await datagrams.send(b'{"status": "healthy"}')
    except Exception as e:
        logger.error(f"Health check datagram send failed: {e}")
    finally:
        await session.close()


async def _echo_datagrams(session: WebTransportSession) -> None:
    """Echo datagrams received on a session."""
    try:
        datagrams = await session.datagrams
        while not session.is_closed:
            data = await datagrams.receive()
            if data:
                await datagrams.send(b"ECHO: " + data)
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


async def _echo_streams(session: WebTransportSession) -> None:
    """Accept and handle all incoming streams for echoing."""
    try:
        async for stream in session.incoming_streams():
            if isinstance(stream, WebTransportStream):
                asyncio.create_task(_echo_single_stream(stream))
    except asyncio.CancelledError:
        pass


async def _echo_single_stream(stream: WebTransportStream) -> None:
    """Echo data for a single bidirectional stream."""
    try:
        async for data in stream.read_iter():
            await stream.write(b"ECHO: " + data)
        await stream.close()
    except Exception as e:
        logger.error(f"Error echoing stream {stream.stream_id}: {e}")
