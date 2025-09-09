"""
WebTransport E2E test server for streams and datagrams.
Provides comprehensive echo functionality for various test scenarios.
"""

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Type

from pywebtransport import (
    ConnectionError,
    EventType,
    ServerApp,
    ServerConfig,
    StructuredStream,
    WebTransportReceiveStream,
    WebTransportSession,
    WebTransportStream,
)
from pywebtransport.serializer import JSONSerializer, MsgPackSerializer
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

JSON_SERIALIZER = JSONSerializer()
MSGPACK_SERIALIZER = MsgPackSerializer()


@dataclass(kw_only=True)
class UserData:
    """Represents user data structure."""

    id: int
    name: str
    email: str


@dataclass(kw_only=True)
class StatusUpdate:
    """Represents a status update message."""

    status: str
    timestamp: float


MESSAGE_REGISTRY: dict[int, Type[Any]] = {1: UserData, 2: StatusUpdate}


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

    def record_bytes(self, *, byte_count: int) -> None:
        """Adds to the total bytes transferred."""
        self.bytes_transferred += byte_count

    def record_connection(self) -> None:
        """Increments the total connections counter."""
        self.connections_total += 1

    def record_datagram(self) -> None:
        """Increments the total datagrams counter."""
        self.datagrams_total += 1

    def record_session_end(self, *, session_id: str) -> None:
        """Records the end of an active session."""
        self.active_sessions.discard(session_id)

    def record_session_start(self, *, session_id: str) -> None:
        """Records the start of a new session."""
        self.sessions_total += 1
        self.active_sessions.add(session_id)

    def record_stream_end(self, *, stream_id: int) -> None:
        """Records the end of an active stream."""
        self.active_streams.discard(stream_id)

    def record_stream_start(self, *, stream_id: int) -> None:
        """Records the start of a new stream."""
        self.streams_total += 1
        self.active_streams.add(stream_id)


class E2EServerApp(ServerApp):
    """E2E test server application with full test support."""

    def __init__(self, **kwargs: Any) -> None:
        """Initializes the E2E server application."""
        super().__init__(**kwargs)
        self.server.on(event_type=EventType.CONNECTION_ESTABLISHED, handler=self._on_connection_established)
        self.server.on(event_type=EventType.SESSION_REQUEST, handler=self._on_session_request)
        self._register_handlers()
        logger.info("E2E Server initialized with full test support")

    async def _on_connection_established(self, event: Any) -> None:
        """Handles connection established events."""
        server_stats.record_connection()
        logger.info("New connection established (total: %s)", server_stats.connections_total)

    async def _on_session_request(self, event: Any) -> None:
        """Handles session request events."""
        if isinstance(event.data, dict):
            session_id = event.data.get("session_id")
            path = event.data.get("path", "/")
            logger.info("Session request: %s for path '%s'", session_id, path)

    def _register_handlers(self) -> None:
        """Centralized method for registering all server routes."""
        self.route(path="/")(echo_handler)
        self.route(path="/echo")(echo_handler)
        self.route(path="/health")(health_handler)
        self.route(path="/stats")(stats_handler)
        self.route(path="/structured-echo/json")(structured_echo_json_handler)
        self.route(path="/structured-echo/msgpack")(structured_echo_msgpack_handler)


server_stats = ServerStatistics()


async def _structured_echo_base_handler(*, session: WebTransportSession, serializer: Any, serializer_name: str) -> None:
    """Base handler logic for structured echo."""
    session_id = session.session_id
    logger.info("Structured handler started for session %s (%s)", session_id, serializer_name)
    server_stats.record_session_start(session_id=session_id)

    try:
        s_stream_manager_task = asyncio.create_task(
            handle_all_structured_streams(session=session, serializer=serializer)
        )
        s_datagram_task = asyncio.create_task(handle_structured_datagram(session=session, serializer=serializer))
        await asyncio.gather(s_stream_manager_task, s_datagram_task, return_exceptions=True)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error("Structured handler error for session %s: %s", session_id, e, exc_info=True)
    finally:
        server_stats.record_session_end(session_id=session_id)
        logger.info("Structured handler finished for session %s", session_id)


async def echo_handler(session: WebTransportSession) -> None:
    """Main handler for echoing streams and datagrams."""
    session_id = session.session_id
    logger.info("Handler started for session %s on path %s", session_id, session.path)
    server_stats.record_session_start(session_id=session_id)

    try:
        datagram_task = asyncio.create_task(handle_datagrams(session=session))
        stream_task = asyncio.create_task(handle_incoming_streams(session=session))
        await asyncio.gather(datagram_task, stream_task, return_exceptions=True)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error("Handler error for session %s: %s", session_id, e, exc_info=True)
    finally:
        server_stats.record_session_end(session_id=session_id)
        logger.info("Handler finished for session %s", session_id)


async def handle_all_structured_streams(*, session: WebTransportSession, serializer: Any) -> None:
    """Listens for and handles all incoming streams for a structured session."""
    try:
        async for stream in session.incoming_streams():
            if isinstance(stream, WebTransportStream):
                server_stats.record_stream_start(stream_id=stream.stream_id)
                asyncio.create_task(handle_structured_stream(stream=stream, serializer=serializer))
    except (asyncio.CancelledError, ConnectionError):
        pass
    except Exception as e:
        logger.error("Structured stream manager for session %s error: %s", session.session_id, e, exc_info=True)


async def handle_bidirectional_stream(*, stream: WebTransportStream) -> None:
    """Handles echo logic for a bidirectional stream."""
    try:
        request_data = await stream.read_all()
        server_stats.record_bytes(byte_count=len(request_data))
        echo_data = b"ECHO: " + request_data
        await stream.write_all(data=echo_data)
        server_stats.record_bytes(byte_count=len(echo_data))
    except (asyncio.CancelledError, ConnectionError):
        pass
    except Exception as e:
        logger.error("Bidirectional stream %s error: %s", stream.stream_id, e, exc_info=True)
        await stream.abort(code=1)
    finally:
        if not stream.is_closed:
            await stream.close()


async def handle_datagrams(*, session: WebTransportSession) -> None:
    """Receives and echoes datagrams for a session."""
    session_id = session.session_id
    logger.debug("Starting datagram handler for session %s", session_id)

    try:
        datagrams = await session.datagrams
        while not session.is_closed:
            try:
                data = await asyncio.wait_for(datagrams.receive(), timeout=1.0)
                server_stats.record_datagram()
                server_stats.record_bytes(byte_count=len(data))
                echo_data = b"ECHO: " + data
                await datagrams.send(data=echo_data)
                server_stats.record_bytes(byte_count=len(echo_data))
            except asyncio.TimeoutError:
                continue
    except (asyncio.CancelledError, ConnectionError):
        pass
    except Exception as e:
        logger.error("Datagram handler error for session %s: %s", session_id, e, exc_info=True)


async def handle_incoming_streams(*, session: WebTransportSession) -> None:
    """Listens for and handles all incoming streams for a session."""
    session_id = session.session_id
    logger.debug("Starting stream handler for session %s", session_id)

    try:
        async for stream in session.incoming_streams():
            server_stats.record_stream_start(stream_id=stream.stream_id)
            asyncio.create_task(handle_single_stream(stream=stream, session_id=session_id))
    except (asyncio.CancelledError, ConnectionError):
        pass
    except Exception as e:
        logger.error("Stream handler error for session %s: %s", session_id, e, exc_info=True)


async def handle_receive_stream(*, stream: WebTransportReceiveStream) -> None:
    """Handles data from a receive-only stream."""
    try:
        all_data = await stream.read_all()
        server_stats.record_bytes(byte_count=len(all_data))
    except (asyncio.CancelledError, ConnectionError):
        pass
    except Exception as e:
        logger.error("Receive stream %s error: %s", stream.stream_id, e, exc_info=True)


async def handle_single_stream(*, stream: Any, session_id: str) -> None:
    """Processes a single stream based on its type."""
    stream_id = stream.stream_id

    try:
        if isinstance(stream, WebTransportStream):
            await handle_bidirectional_stream(stream=stream)
        elif isinstance(stream, WebTransportReceiveStream):
            await handle_receive_stream(stream=stream)
        else:
            logger.warning("Unknown stream type for %s", stream_id)
    except Exception as e:
        logger.error("Error processing stream %s: %s", stream_id, e, exc_info=True)
    finally:
        server_stats.record_stream_end(stream_id=stream_id)


async def handle_structured_datagram(*, session: WebTransportSession, serializer: Any) -> None:
    """Receives and echoes structured datagrams for a session."""
    session_id = session.session_id
    logger.debug("Starting structured datagram handler for session %s", session_id)

    try:
        s_datagram = await session.create_structured_datagram_stream(serializer=serializer, registry=MESSAGE_REGISTRY)
        while not session.is_closed:
            try:
                obj = await asyncio.wait_for(s_datagram.receive_obj(), timeout=1.0)
                server_stats.record_datagram()
                await s_datagram.send_obj(obj=obj)
            except asyncio.TimeoutError:
                continue
    except (asyncio.CancelledError, ConnectionError):
        pass
    except Exception as e:
        logger.error("Structured datagram handler error for session %s: %s", session_id, e, exc_info=True)


async def handle_structured_stream(*, stream: WebTransportStream, serializer: Any) -> None:
    """Handles echoing structured objects on a single, existing bidirectional stream."""
    stream_id = stream.stream_id
    logger.debug("Handling structured stream %s", stream_id)

    try:
        s_stream = StructuredStream(stream=stream, serializer=serializer, registry=MESSAGE_REGISTRY)
        async for obj in s_stream:
            logger.debug("Echoing object on stream %s: %s", stream_id, obj)
            await s_stream.send_obj(obj=obj)
    except (asyncio.CancelledError, ConnectionError):
        pass
    except Exception as e:
        logger.error("Structured stream %s error: %s", stream_id, e, exc_info=True)
    finally:
        if not stream.is_closed:
            await stream.close()
        server_stats.record_stream_end(stream_id=stream_id)


async def health_handler(session: WebTransportSession) -> None:
    """Handles health check requests on the /health path."""
    logger.info("Health check from session %s", session.session_id)

    try:
        health_data = {
            "status": "healthy",
            "timestamp": time.time(),
            "uptime": time.time() - server_stats.start_time,
            "active_sessions": len(server_stats.active_sessions),
            "active_streams": len(server_stats.active_streams),
        }
        datagrams = await session.datagrams
        await datagrams.send_json(data=health_data)
        logger.info("Sent health status: %s", health_data["status"])
    except Exception as e:
        logger.error("Health handler error: %s", e)
    finally:
        if not session.is_closed:
            await session.close()


async def stats_handler(session: WebTransportSession) -> None:
    """Handles requests for server statistics on the /stats path."""
    logger.info("Stats request from session %s", session.session_id)

    try:
        stats = server_stats.get_stats()
        stats_json = json.dumps(stats, indent=2).encode("utf-8")
        stream = await session.create_bidirectional_stream()
        await stream.write_all(data=stats_json)
        logger.info("Sent stats: %s bytes", len(stats_json))
    except Exception as e:
        logger.error("Stats handler error: %s", e)
    finally:
        if not session.is_closed:
            await session.close()


async def structured_echo_json_handler(session: WebTransportSession) -> None:
    """Handler for echoing structured objects using JSON."""
    await _structured_echo_base_handler(session=session, serializer=JSON_SERIALIZER, serializer_name="JSON")


async def structured_echo_msgpack_handler(session: WebTransportSession) -> None:
    """Handler for echoing structured objects using MsgPack."""
    await _structured_echo_base_handler(session=session, serializer=MSGPACK_SERIALIZER, serializer_name="MsgPack")


async def main() -> None:
    """Configures and starts the WebTransport E2E test server."""
    logger.info("Starting WebTransport E2E Test Server...")

    if not CERT_PATH.exists() or not KEY_PATH.exists():
        logger.info("Generating self-signed certificate for %s...", CERT_PATH.stem)
        generate_self_signed_cert(hostname=CERT_PATH.stem, output_dir=".")

    config = ServerConfig.create(
        bind_host=SERVER_HOST,
        bind_port=SERVER_PORT,
        certfile=str(CERT_PATH),
        keyfile=str(KEY_PATH),
        debug=DEBUG_MODE,
        log_level="DEBUG" if DEBUG_MODE else "INFO",
    )
    app = E2EServerApp(config=config)

    logger.info("Server binding to %s:%s", config.bind_host, config.bind_port)
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
        logger.critical("Server crashed unexpectedly: %s", e, exc_info=True)
        sys.exit(1)
