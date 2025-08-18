"""
WebTransport E2E test server for streams and datagrams.
Provides comprehensive echo functionality for various test scenarios.
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Final

from pywebtransport import (
    ConnectionError,
    EventType,
    ServerApp,
    ServerConfig,
    WebTransportReceiveStream,
    WebTransportSession,
    WebTransportStream,
)
from pywebtransport.utils import generate_self_signed_cert

CERT_PATH: Final[Path] = Path("localhost.crt")
KEY_PATH: Final[Path] = Path("localhost.key")
DEBUG_MODE: Final[bool] = "--debug" in sys.argv
SERVER_HOST: Final[str] = "::"
SERVER_PORT: Final[int] = 4433

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
if DEBUG_MODE:
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("aioquic").setLevel(logging.DEBUG)
    logging.getLogger("pywebtransport").setLevel(logging.DEBUG)

logger = logging.getLogger("e2e_server")


class ServerStatistics:
    """Collects and manages server statistics."""

    def __init__(self) -> None:
        """Initializes the statistics collector."""
        self.start_time = time.time()
        self.connections_total = 0
        self.sessions_total = 0
        self.streams_total = 0
        self.datagrams_total = 0
        self.bytes_transferred = 0
        self.active_sessions: set[str] = set()
        self.active_streams: set[int] = set()

    def get_stats(self) -> dict[str, Any]:
        """Returns a dictionary of all current server statistics."""
        uptime = time.time() - self.start_time
        return {
            "uptime": uptime,
            "connections_total": self.connections_total,
            "sessions_total": self.sessions_total,
            "sessions_active": len(self.active_sessions),
            "streams_total": self.streams_total,
            "streams_active": len(self.active_streams),
            "datagrams_total": self.datagrams_total,
            "bytes_transferred": self.bytes_transferred,
            "start_time": self.start_time,
        }

    def record_connection(self) -> None:
        """Increments the total connections counter."""
        self.connections_total += 1

    def record_session_start(self, session_id: str) -> None:
        """Records the start of a new session."""
        self.sessions_total += 1
        self.active_sessions.add(session_id)

    def record_session_end(self, session_id: str) -> None:
        """Records the end of an active session."""
        self.active_sessions.discard(session_id)

    def record_stream_start(self, stream_id: int) -> None:
        """Records the start of a new stream."""
        self.streams_total += 1
        self.active_streams.add(stream_id)

    def record_stream_end(self, stream_id: int) -> None:
        """Records the end of an active stream."""
        self.active_streams.discard(stream_id)

    def record_datagram(self) -> None:
        """Increments the total datagrams counter."""
        self.datagrams_total += 1

    def record_bytes(self, byte_count: int) -> None:
        """Adds to the total bytes transferred."""
        self.bytes_transferred += byte_count


class E2EServerApp(ServerApp):
    """E2E test server application with full test support."""

    def __init__(self, **kwargs: Any) -> None:
        """Initializes the E2E server application."""
        super().__init__(**kwargs)
        self.server.on(EventType.CONNECTION_ESTABLISHED, self._on_connection_established)
        self.server.on(EventType.SESSION_REQUEST, self._on_session_request)
        self._register_handlers()
        logger.info("E2E Server initialized with full test support")

    def _register_handlers(self) -> None:
        """Centralized method for registering all server routes."""
        self.route("/")(echo_handler)
        self.route("/echo")(echo_handler)
        self.route("/stats")(stats_handler)
        self.route("/health")(health_handler)

    async def _on_connection_established(self, event: Any) -> None:
        """Handles connection established events."""
        server_stats.record_connection()
        logger.info(f"New connection established (total: {server_stats.connections_total})")

    async def _on_session_request(self, event: Any) -> None:
        """Handles session request events."""
        if isinstance(event.data, dict):
            session_id = event.data.get("session_id")
            path = event.data.get("path", "/")
            logger.info(f"Session request: {session_id} for path '{path}'")


server_stats = ServerStatistics()


async def echo_handler(session: WebTransportSession) -> None:
    """Main handler for echoing streams and datagrams."""
    session_id = session.session_id
    logger.info(f"Handler started for session {session_id} on path {session.path}")
    server_stats.record_session_start(session_id)

    try:
        datagram_task = asyncio.create_task(handle_datagrams(session))
        stream_task = asyncio.create_task(handle_incoming_streams(session))
        await asyncio.gather(datagram_task, stream_task, return_exceptions=True)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Handler error for session {session_id}: {e}", exc_info=True)
    finally:
        server_stats.record_session_end(session_id)
        logger.info(f"Handler finished for session {session_id}")


async def stats_handler(session: WebTransportSession) -> None:
    """Handles requests for server statistics on the /stats path."""
    logger.info(f"Stats request from session {session.session_id}")
    try:
        stats = server_stats.get_stats()
        stats_json = json.dumps(stats, indent=2).encode("utf-8")
        stream = await session.create_bidirectional_stream()
        await stream.write_all(stats_json)
        logger.info(f"Sent stats: {len(stats_json)} bytes")
    except Exception as e:
        logger.error(f"Stats handler error: {e}")
    finally:
        if not session.is_closed:
            await session.close()


async def health_handler(session: WebTransportSession) -> None:
    """Handles health check requests on the /health path."""
    logger.info(f"Health check from session {session.session_id}")
    try:
        health_data = {
            "status": "healthy",
            "timestamp": time.time(),
            "uptime": time.time() - server_stats.start_time,
            "active_sessions": len(server_stats.active_sessions),
            "active_streams": len(server_stats.active_streams),
        }
        datagrams = await session.datagrams
        await datagrams.send_json(health_data)
        logger.info(f"Sent health status: {health_data['status']}")
    except Exception as e:
        logger.error(f"Health handler error: {e}")
    finally:
        if not session.is_closed:
            await session.close()


async def handle_datagrams(session: WebTransportSession) -> None:
    """Receives and echoes datagrams for a session."""
    session_id = session.session_id
    logger.debug(f"Starting datagram handler for session {session_id}")
    try:
        datagrams = await session.datagrams
        while not session.is_closed:
            try:
                data = await asyncio.wait_for(datagrams.receive(), timeout=1.0)
                server_stats.record_datagram()
                server_stats.record_bytes(len(data))
                echo_data = b"ECHO: " + data
                await datagrams.send(echo_data)
                server_stats.record_bytes(len(echo_data))
            except asyncio.TimeoutError:
                continue
    except (asyncio.CancelledError, ConnectionError):
        pass
    except Exception as e:
        logger.error(f"Datagram handler error for session {session_id}: {e}", exc_info=True)


async def handle_incoming_streams(session: WebTransportSession) -> None:
    """Listens for and handles all incoming streams for a session."""
    session_id = session.session_id
    logger.debug(f"Starting stream handler for session {session_id}")
    try:
        async for stream in session.incoming_streams():
            server_stats.record_stream_start(stream.stream_id)
            asyncio.create_task(handle_single_stream(stream, session_id))
    except (asyncio.CancelledError, ConnectionError):
        pass
    except Exception as e:
        logger.error(f"Stream handler error for session {session_id}: {e}", exc_info=True)


async def handle_single_stream(stream: Any, session_id: str) -> None:
    """Processes a single stream based on its type."""
    stream_id = stream.stream_id
    try:
        if isinstance(stream, WebTransportStream):
            await handle_bidirectional_stream(stream)
        elif isinstance(stream, WebTransportReceiveStream):
            await handle_receive_stream(stream)
        else:
            logger.warning(f"Unknown stream type for {stream_id}")
    except Exception as e:
        logger.error(f"Error processing stream {stream_id}: {e}", exc_info=True)
    finally:
        server_stats.record_stream_end(stream_id)


async def handle_bidirectional_stream(stream: WebTransportStream) -> None:
    """Handles echo logic for a bidirectional stream."""
    try:
        request_data = await stream.read_all()
        server_stats.record_bytes(len(request_data))
        echo_data = b"ECHO: " + request_data
        await stream.write_all(echo_data)
        server_stats.record_bytes(len(echo_data))
    except (asyncio.CancelledError, ConnectionError):
        pass
    except Exception as e:
        logger.error(f"Bidirectional stream {stream.stream_id} error: {e}", exc_info=True)
        await stream.abort(code=1)
    finally:
        if not stream.is_closed:
            await stream.close()


async def handle_receive_stream(stream: WebTransportReceiveStream) -> None:
    """Handles data from a receive-only stream."""
    try:
        all_data = await stream.read_all()
        server_stats.record_bytes(len(all_data))
    except (asyncio.CancelledError, ConnectionError):
        pass
    except Exception as e:
        logger.error(f"Receive stream {stream.stream_id} error: {e}", exc_info=True)


async def main() -> None:
    """Configures and starts the WebTransport E2E test server."""
    logger.info("Starting WebTransport E2E Test Server...")

    if not CERT_PATH.exists() or not KEY_PATH.exists():
        logger.info(f"Generating self-signed certificate for {CERT_PATH.stem}...")
        generate_self_signed_cert(CERT_PATH.stem, output_dir=".")

    config = ServerConfig.create(
        bind_host=SERVER_HOST,
        bind_port=SERVER_PORT,
        certfile=str(CERT_PATH),
        keyfile=str(KEY_PATH),
        debug=DEBUG_MODE,
        log_level="DEBUG" if DEBUG_MODE else "INFO",
    )
    app = E2EServerApp(config=config)

    logger.info(f"Server binding to {config.bind_host}:{config.bind_port}")
    if DEBUG_MODE:
        logger.info("Debug mode enabled - verbose logging active")
    logger.info("Ready for E2E tests!")

    try:
        async with app:
            await app.serve()
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped gracefully by user.")
    except Exception as e:
        logger.critical(f"Server crashed unexpectedly: {e}", exc_info=True)
        sys.exit(1)
