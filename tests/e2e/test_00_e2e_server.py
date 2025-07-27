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
from typing import Any, Dict, Set

from pywebtransport.config import ServerConfig
from pywebtransport.server import ServerApp
from pywebtransport.session import WebTransportSession
from pywebtransport.stream import WebTransportReceiveStream, WebTransportStream
from pywebtransport.types import EventType
from pywebtransport.utils import generate_self_signed_cert

# Module-level constants
DEBUG_MODE = "--debug" in sys.argv

# Module-level configuration and variables
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
        self.active_sessions: Set[str] = set()
        self.active_streams: Set[int] = set()

    def get_stats(self) -> Dict[str, Any]:
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


server_stats = ServerStatistics()


class E2EServerApp(ServerApp):
    """E2E test server application with full test support."""

    def __init__(self, **kwargs: Any) -> None:
        """Initializes the E2E server application."""
        super().__init__(**kwargs)
        self.server.on(EventType.CONNECTION_ESTABLISHED, self._on_connection_established)
        self.server.on(EventType.SESSION_REQUEST, self._on_session_request)
        logger.info("E2E Server initialized with full test support")

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


async def echo_handler(session: WebTransportSession) -> None:
    """Main handler for echoing streams and datagrams."""
    session_id = session.session_id
    logger.info(f"Handler started for session {session_id} on path {session.path}")
    server_stats.record_session_start(session_id)

    try:
        datagram_task = asyncio.create_task(handle_datagrams(session))
        stream_task = asyncio.create_task(handle_incoming_streams(session))
        await asyncio.gather(datagram_task, stream_task, return_exceptions=True)
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
        await session.datagrams.send_json(health_data)
        logger.info(f"Sent health status: {health_data['status']}")
    except Exception as e:
        logger.error(f"Health handler error: {e}")
    finally:
        await session.close()


async def handle_datagrams(session: WebTransportSession) -> None:
    """Receives and echoes datagrams for a session."""
    session_id = session.session_id
    logger.info(f"Starting datagram handler for session {session_id}")
    try:
        while not session.is_closed:
            try:
                data = await asyncio.wait_for(session.datagrams.receive(), timeout=1.0)
                if not data:
                    continue

                server_stats.record_datagram()
                server_stats.record_bytes(len(data))
                logger.info(f"Received datagram: {len(data)} bytes")

                echo_data = b"ECHO: " + data
                await session.datagrams.send(echo_data)
                server_stats.record_bytes(len(echo_data))
                logger.info(f"Echoed datagram: {len(echo_data)} bytes")

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Datagram handling error: {e}")
                break
    except asyncio.CancelledError:
        logger.info(f"Datagram handler cancelled for session {session_id}")
    except Exception as e:
        logger.error(f"Datagram handler error for session {session_id}: {e}")


async def handle_incoming_streams(session: WebTransportSession) -> None:
    """Listens for and handles all incoming streams for a session."""
    session_id = session.session_id
    logger.info(f"Starting stream handler for session {session_id}")
    try:
        async for stream in session.incoming_streams():
            logger.info(f"New incoming stream: {stream.stream_id}")
            server_stats.record_stream_start(stream.stream_id)
            asyncio.create_task(handle_single_stream(stream, session_id))
    except asyncio.CancelledError:
        logger.info(f"Stream handler cancelled for session {session_id}")
    except Exception as e:
        logger.error(f"Stream handler error for session {session_id}: {e}")


async def handle_single_stream(stream: Any, session_id: str) -> None:
    """Processes a single stream based on its type."""
    stream_id = stream.stream_id
    logger.info(f"Processing stream {stream_id} for session {session_id}")
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
        logger.info(f"Stream {stream_id} processing completed")


async def handle_bidirectional_stream(stream: WebTransportStream) -> None:
    """Handles echo logic for a bidirectional stream."""
    stream_id = stream.stream_id
    total_bytes_received = 0
    total_bytes_sent = 0

    try:
        logger.info(f"Reading all data from bidirectional stream {stream_id}.")
        request_data = await stream.read_all()
        total_bytes_received = len(request_data)
        server_stats.record_bytes(total_bytes_received)
        logger.info(f"Stream {stream_id}: received a total of {total_bytes_received} bytes.")

        echo_data = b"ECHO: " + request_data
        await stream.write_all(echo_data)
        total_bytes_sent = len(echo_data)
        server_stats.record_bytes(total_bytes_sent)
        logger.info(f"Stream {stream_id} finished processing {total_bytes_received} -> {total_bytes_sent} bytes")
    except Exception as e:
        logger.error(f"Bidirectional stream {stream_id} error: {e}", exc_info=True)
        try:
            await stream.abort(code=1)
        except Exception:
            pass
    finally:
        server_stats.record_stream_end(stream_id)


async def handle_receive_stream(stream: WebTransportReceiveStream) -> None:
    """Handles data from a receive-only stream."""
    stream_id = stream.stream_id
    total_bytes = 0
    try:
        logger.info(f"Reading from receive-only stream {stream_id}")
        all_data = await stream.read_all()
        total_bytes = len(all_data)
        logger.info(f"Receive-only stream {stream_id}: total received {total_bytes} bytes")
        server_stats.record_bytes(total_bytes)
    except Exception as e:
        logger.error(f"Receive stream {stream_id} error: {e}")


async def main() -> None:
    """Configures and starts the WebTransport E2E test server."""
    logger.info("Starting WebTransport E2E Server")
    cert_path = Path("localhost.crt")
    key_path = Path("localhost.key")
    hostname = "localhost"

    if not cert_path.exists() or not key_path.exists():
        logger.info("Generating self-signed certificate...")
        generate_self_signed_cert(hostname)

    config = ServerConfig.create(
        bind_host="::",
        bind_port=4433,
        certfile=str(cert_path),
        keyfile=str(key_path),
        debug=DEBUG_MODE,
        log_level="DEBUG" if DEBUG_MODE else "INFO",
    )

    app = E2EServerApp(config=config)
    app.route("/")(echo_handler)
    app.route("/echo")(echo_handler)
    app.route("/stats")(stats_handler)
    app.route("/health")(health_handler)

    logger.info(f"Server binding to {config.bind_host}:{config.bind_port}")
    if DEBUG_MODE:
        logger.info("Debug mode enabled - verbose logging active")
    logger.info("Ready for E2E tests!")

    try:
        async with app:
            await app.serve()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Failed to start server: {e}", exc_info=True)
        sys.exit(1)
