"""E2E test server for WebTransport streams and datagrams."""

import asyncio
import json
import logging
import struct
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from pywebtransport import (
    ConnectionError,
    ServerApp,
    ServerConfig,
    StreamError,
    StructuredDatagramTransport,
    StructuredStream,
    WebTransportReceiveStream,
    WebTransportSession,
    WebTransportStream,
)
from pywebtransport.rpc import InvalidParamsError, MethodNotFoundError, RpcError
from pywebtransport.serializer import JSONSerializer, MsgPackSerializer
from pywebtransport.types import EventType
from pywebtransport.utils import generate_self_signed_cert

CERT_PATH: Final[Path] = Path("localhost.crt")
KEY_PATH: Final[Path] = Path("localhost.key")
DEBUG_MODE: Final[bool] = "--debug" in sys.argv
SERVER_HOST: Final[str] = "::"
SERVER_PORT: Final[int] = 4433
JSON_SERIALIZER = JSONSerializer()
MSGPACK_SERIALIZER = MsgPackSerializer()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
if DEBUG_MODE:
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("aioquic").setLevel(logging.DEBUG)
    logging.getLogger("pywebtransport").setLevel(logging.DEBUG)

logger = logging.getLogger("e2e_server")


@dataclass(kw_only=True)
class RpcUserData:
    """Represents user data structure for RPC tests."""

    id: int
    name: str


@dataclass(kw_only=True)
class StatusUpdate:
    """Represents a status update message."""

    status: str
    timestamp: float


@dataclass(kw_only=True)
class UserData:
    """Represents user data structure."""

    id: int
    name: str
    email: str


class ServerStatistics:
    """Collects and manages server statistics."""

    def __init__(self) -> None:
        """Initialize the statistics collector."""
        self.start_time = time.time()
        self.connections_total = 0
        self.sessions_total = 0
        self.streams_total = 0
        self.datagrams_total = 0
        self.bytes_transferred = 0
        self.active_sessions: set[str] = set()
        self.active_streams: set[int] = set()

    def get_stats(self) -> dict[str, Any]:
        """Return a dictionary of all current server statistics."""
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
        """Add to the total bytes transferred."""
        self.bytes_transferred += byte_count

    def record_connection(self) -> None:
        """Increment the total connections counter."""
        self.connections_total += 1

    def record_datagram(self) -> None:
        """Increment the total datagrams counter."""
        self.datagrams_total += 1

    def record_session_end(self, *, session_id: str) -> None:
        """Record the end of an active session."""
        self.active_sessions.discard(session_id)

    def record_session_start(self, *, session_id: str) -> None:
        """Record the start of a new session."""
        self.sessions_total += 1
        self.active_sessions.add(session_id)

    def record_stream_end(self, *, stream_id: int) -> None:
        """Record the end of an active stream."""
        self.active_streams.discard(stream_id)

    def record_stream_start(self, *, stream_id: int) -> None:
        """Record the start of a new stream."""
        self.streams_total += 1
        self.active_streams.add(stream_id)


class E2EServerApp(ServerApp):
    """E2E test server application with full test support."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the E2E server application."""
        super().__init__(**kwargs)
        self.server.on(event_type=EventType.CONNECTION_ESTABLISHED, handler=self._on_connection_established)
        self.server.on(event_type=EventType.SESSION_REQUEST, handler=self._on_session_request)
        self._register_handlers()
        logger.info("E2E Server initialized with full test support")

    async def _on_connection_established(self, event: Any) -> None:
        """Handle connection established events."""
        server_stats.record_connection()
        logger.info("New connection established (total: %s)", server_stats.connections_total)

    async def _on_session_request(self, event: Any) -> None:
        """Handle session request events."""
        if isinstance(event.data, dict):
            session_id = event.data.get("session_id")
            path = event.data.get("path", "/")
            logger.info("Session request: %s for path '%s'", session_id, path)

    def _register_handlers(self) -> None:
        """Centralize registration for all server routes."""
        self.route(path="/")(echo_handler)
        self.route(path="/echo")(echo_handler)
        self.route(path="/health")(health_handler)
        self.route(path="/pubsub")(pubsub_handler)
        self.route(path="/rpc")(rpc_handler)
        self.route(path="/stats")(stats_handler)
        self.route(path="/structured-echo/json")(structured_echo_json_handler)
        self.route(path="/structured-echo/msgpack")(structured_echo_msgpack_handler)


MESSAGE_REGISTRY: dict[int, type[Any]] = {1: UserData, 2: StatusUpdate}
GLOBAL_TOPICS: defaultdict[str, set[asyncio.Queue[tuple[str, bytes]]]] = defaultdict(set)
server_stats = ServerStatistics()


async def _structured_echo_base_handler(*, session: WebTransportSession, serializer: Any, serializer_name: str) -> None:
    """Provide the base handler logic for structured echo."""
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
    """Handle echoing streams and datagrams."""
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
    """Listen for and handle all incoming streams for a structured session."""
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
    """Handle echo logic for a bidirectional stream."""
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
    """Receive and echo datagrams for a session."""
    session_id = session.session_id
    logger.debug("Starting datagram handler for session %s", session_id)

    try:
        datagram_transport = await session.create_datagram_transport()
        while not session.is_closed:
            try:
                data = await asyncio.wait_for(datagram_transport.receive(), timeout=1.0)
                server_stats.record_datagram()
                server_stats.record_bytes(byte_count=len(data))
                echo_data = b"ECHO: " + data
                await datagram_transport.send(data=echo_data)
                server_stats.record_bytes(byte_count=len(echo_data))
            except asyncio.TimeoutError:
                continue
    except (asyncio.CancelledError, ConnectionError):
        pass
    except Exception as e:
        logger.error("Datagram handler error for session %s: %s", session_id, e, exc_info=True)


async def handle_incoming_streams(*, session: WebTransportSession) -> None:
    """Listen for and handle all incoming streams for a session."""
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
    """Handle data from a receive-only stream."""
    try:
        all_data = await stream.read_all()
        server_stats.record_bytes(byte_count=len(all_data))
    except (asyncio.CancelledError, ConnectionError):
        pass
    except Exception as e:
        logger.error("Receive stream %s error: %s", stream.stream_id, e, exc_info=True)


async def handle_single_stream(*, stream: Any, session_id: str) -> None:
    """Process a single stream based on its type."""
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
    """Receive and echo structured datagrams for a session."""
    session_id = session.session_id
    logger.debug("Starting structured datagram handler for session %s", session_id)

    try:
        raw_datagram_transport = await session.create_datagram_transport()
        structured_datagram_transport = StructuredDatagramTransport(
            datagram_transport=raw_datagram_transport, serializer=serializer, registry=MESSAGE_REGISTRY
        )
        while not session.is_closed:
            try:
                obj = await asyncio.wait_for(structured_datagram_transport.receive_obj(), timeout=1.0)
                server_stats.record_datagram()
                await structured_datagram_transport.send_obj(obj=obj)
            except asyncio.TimeoutError:
                continue
    except (asyncio.CancelledError, ConnectionError):
        pass
    except Exception as e:
        logger.error("Structured datagram handler error for session %s: %s", session_id, e, exc_info=True)


async def handle_structured_stream(*, stream: WebTransportStream, serializer: Any) -> None:
    """Handle echoing structured objects on a single, existing bidirectional stream."""
    raw_stream = stream
    stream_id = raw_stream.stream_id
    logger.debug("Handling structured stream %s", stream_id)

    try:
        structured_stream = StructuredStream(stream=raw_stream, serializer=serializer, registry=MESSAGE_REGISTRY)
        async for obj in structured_stream:
            logger.debug("Echoing object on stream %s: %s", stream_id, obj)
            await structured_stream.send_obj(obj=obj)
    except (asyncio.CancelledError, ConnectionError):
        pass
    except Exception as e:
        logger.error("Structured stream %s error: %s", stream_id, e, exc_info=True)
    finally:
        if not raw_stream.is_closed:
            await raw_stream.close()
        server_stats.record_stream_end(stream_id=stream_id)


async def health_handler(session: WebTransportSession) -> None:
    """Handle health check requests on the /health path."""
    logger.info("Health check from session %s", session.session_id)
    try:
        health_data = {
            "status": "healthy",
            "timestamp": time.time(),
            "uptime": time.time() - server_stats.start_time,
            "active_sessions": len(server_stats.active_sessions),
            "active_streams": len(server_stats.active_streams),
        }
        datagram_transport = await session.create_datagram_transport()
        await datagram_transport.send_json(data=health_data)
        logger.info("Sent health status: %s", health_data["status"])
    except Exception as e:
        logger.error("Health handler error: %s", e)
    finally:
        if not session.is_closed:
            await session.close()


async def pubsub_handler(session: WebTransportSession) -> None:
    """Handle the Pub/Sub test logic."""
    session_id = session.session_id
    logger.info("Pub/Sub handler started for session %s", session_id)
    server_stats.record_session_start(session_id=session_id)

    my_queue: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue()
    subscribed_topics: set[str] = set()

    try:
        stream = await session.incoming_streams().__anext__()
        if not isinstance(stream, WebTransportStream):
            logger.warning("Pub/Sub handler expected a bidirectional stream, but got another type.")
            return

        server_stats.record_stream_start(stream_id=stream.stream_id)

        async def reader() -> None:
            try:
                while not stream.is_closed:
                    line = await stream.readline()
                    if not line:
                        break
                    parts = line.strip().split(b" ", 2)
                    command = parts[0]
                    if command == b"SUB" and len(parts) == 2:
                        topic = parts[1].decode()
                        subscribed_topics.add(topic)
                        GLOBAL_TOPICS[topic].add(my_queue)
                        await stream.write(data=b"SUB-OK %s\n" % parts[1])
                    elif command == b"UNSUB" and len(parts) == 2:
                        topic = parts[1].decode()
                        subscribed_topics.discard(topic)
                        GLOBAL_TOPICS[topic].discard(my_queue)
                    elif command == b"PUB" and len(parts) == 3:
                        topic, length = parts[1].decode(), int(parts[2])
                        payload = await stream.readexactly(n=length)
                        for q in GLOBAL_TOPICS.get(topic, set()).copy():
                            q.put_nowait((topic, payload))
            except (asyncio.CancelledError, ConnectionError, StreamError, asyncio.IncompleteReadError):
                pass

        async def writer() -> None:
            try:
                while not stream.is_closed:
                    topic, payload = await my_queue.get()
                    msg = b"MSG %s %d\n" % (topic.encode(), len(payload))
                    await stream.write(data=msg + payload)
                    my_queue.task_done()
            except (asyncio.CancelledError, ConnectionError, StreamError):
                pass

        await asyncio.gather(reader(), writer())
    except StopAsyncIteration:
        logger.info("Pub/Sub session %s ended without creating a stream.", session_id)
    except (asyncio.CancelledError, ConnectionError):
        pass
    except Exception as e:
        logger.error("Pub/Sub handler error for session %s: %s", session_id, e, exc_info=True)
    finally:
        for topic in subscribed_topics:
            GLOBAL_TOPICS[topic].discard(my_queue)

        server_stats.record_session_end(session_id=session_id)
        logger.info("Pub/Sub handler finished for session %s", session_id)


async def rpc_handler(session: WebTransportSession) -> None:
    """Handle the RPC test logic."""
    session_id = session.session_id
    logger.info("RPC handler started for session %s", session_id)
    server_stats.record_session_start(session_id=session_id)

    handlers: dict[str, Callable[..., Any]] = {}

    def add(a: int, b: int) -> int:
        return a + b

    def get_user(user_id: int) -> dict[str, Any]:
        return {"id": user_id, "name": f"User {user_id}"}

    def log_message(message: str) -> None:
        logger.info("RPC log_message from %s: %s", session_id, message)

    def divide(a: int, b: int) -> float:
        return a / b

    async def slow_operation(delay: float) -> str:
        await asyncio.sleep(delay)
        return f"Completed after {delay} seconds."

    handlers["add"] = add
    handlers["get_user"] = get_user
    handlers["log_message"] = log_message
    handlers["divide"] = divide
    handlers["slow_operation"] = slow_operation

    async def send_message(stream: WebTransportStream, message: dict[str, Any]) -> None:
        try:
            payload = json.dumps(message).encode("utf-8")
            header = struct.pack("!I", len(payload))
            await stream.write(data=header + payload)
        except Exception:
            await stream.abort()

    async def process_request(stream: WebTransportStream, request: dict[str, Any]) -> None:
        request_id = request.get("id")
        method_name = request.get("method")
        params = request.get("params", [])
        response: dict[str, Any] | None = None

        if method_name not in handlers:
            if request_id is not None:
                error = MethodNotFoundError(message=f"Method '{method_name}' not found.").to_dict()
                response = {"id": request_id, "error": error}
        else:
            try:
                if not isinstance(params, list):
                    raise InvalidParamsError(message="Parameters must be a list.")
                result = handlers[method_name](*params)
                if asyncio.iscoroutine(result):
                    result = await result
                if request_id is not None:
                    response = {"id": request_id, "result": result}
            except Exception as e:
                if request_id is not None:
                    error = RpcError(message=f"Error executing '{method_name}': {e}").to_dict()
                    response = {"id": request_id, "error": error}
        if response:
            await send_message(stream, response)

    try:
        stream = await session.incoming_streams().__anext__()
        if not isinstance(stream, WebTransportStream):
            return

        server_stats.record_stream_start(stream_id=stream.stream_id)

        while not stream.is_closed:
            header = await stream.readexactly(n=4)
            length = struct.unpack("!I", header)[0]
            payload = await stream.readexactly(n=length)
            message = json.loads(payload.decode("utf-8"))
            asyncio.create_task(process_request(stream, message))
    except (StopAsyncIteration, asyncio.CancelledError, ConnectionError, StreamError, asyncio.IncompleteReadError):
        pass
    except Exception as e:
        logger.error("RPC handler error for session %s: %s", session_id, e, exc_info=True)
    finally:
        server_stats.record_session_end(session_id=session_id)
        logger.info("RPC handler finished for session %s", session_id)


async def stats_handler(session: WebTransportSession) -> None:
    """Handle requests for server statistics on the /stats path."""
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
    """Handle echoing structured objects using JSON."""
    await _structured_echo_base_handler(session=session, serializer=JSON_SERIALIZER, serializer_name="JSON")


async def structured_echo_msgpack_handler(session: WebTransportSession) -> None:
    """Handle echoing structured objects using MsgPack."""
    await _structured_echo_base_handler(session=session, serializer=MSGPACK_SERIALIZER, serializer_name="MsgPack")


async def main() -> None:
    """Configure and start the WebTransport E2E test server."""
    logger.info("Starting WebTransport E2E Test Server...")

    if not CERT_PATH.exists() or not KEY_PATH.exists():
        logger.info("Generating self-signed certificate for %s...", CERT_PATH.stem)
        generate_self_signed_cert(hostname=CERT_PATH.stem, output_dir=".")

    config = ServerConfig(
        bind_host=SERVER_HOST,
        bind_port=SERVER_PORT,
        certfile=str(CERT_PATH),
        keyfile=str(KEY_PATH),
        debug=DEBUG_MODE,
        log_level="DEBUG" if DEBUG_MODE else "INFO",
        initial_max_data=16 * 1024,
        initial_max_streams_bidi=5,
        initial_max_streams_uni=5,
        flow_control_window_size=65536,
        flow_control_window_auto_scale=False,
        stream_flow_control_increment_bidi=5,
        stream_flow_control_increment_uni=5,
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
