"""E2E test server for WebTransport streams and datagrams."""

import asyncio
import json
import logging
import struct
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

from pywebtransport import (
    ConnectionError,
    Event,
    ServerApp,
    ServerConfig,
    SessionError,
    StreamError,
    StructuredDatagramTransport,
    StructuredStream,
    TimeoutError,
    WebTransportReceiveStream,
    WebTransportSession,
    WebTransportStream,
)
from pywebtransport.constants import DEFAULT_MAX_MESSAGE_SIZE
from pywebtransport.rpc import InvalidParamsError, MethodNotFoundError, RpcError
from pywebtransport.serializer import JSONSerializer, MsgPackSerializer
from pywebtransport.types import ConnectionState, EventType, SessionState
from pywebtransport.utils import generate_self_signed_cert, get_timestamp

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


class E2EServerApp(ServerApp):
    """E2E test server application with full test support."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the E2E server application."""
        super().__init__(**kwargs)
        self.server.on(event_type=EventType.CONNECTION_ESTABLISHED, handler=self._on_connection_established)
        self.server.on(event_type=EventType.SESSION_REQUEST, handler=self._on_session_request)
        self._register_handlers()
        logger.info("E2E Server initialized with full test support")

    async def _diagnostics_handler(self, session: WebTransportSession) -> None:
        """Handle requests for server statistics on the /diagnostics path."""
        logger.info("Diagnostics request from session %s", session.session_id)
        stream: WebTransportStream | None = None
        try:
            stream_event = await session.events.wait_for(event_type=EventType.STREAM_OPENED, timeout=5.0)
            if not isinstance(stream_event.data, dict):
                logger.warning("Diagnostics handler: Received invalid stream event data.")
                return

            stream = stream_event.data.get("stream")
            if not isinstance(stream, WebTransportStream):
                logger.warning("Diagnostics handler: Client opened a non-bidirectional stream.")
                return

            diagnostics = await self.server.diagnostics()
            stats_json = json.dumps(asdict(diagnostics), indent=2).encode("utf-8")
            await stream.write(data=stats_json, end_stream=True)
            logger.info("Sent diagnostics: %s bytes", len(stats_json))
        except asyncio.TimeoutError:
            logger.error("Diagnostics handler: Client connected but never opened a stream.")
        except Exception as e:
            logger.error("Diagnostics handler error: %s", e)
        finally:
            if not session.is_closed:
                await session.close()

    async def _health_handler(self, session: WebTransportSession) -> None:
        """Handle health check requests on the /health path."""
        logger.info("Health check from session %s", session.session_id)
        try:
            diagnostics = await self.server.diagnostics()
            stats = diagnostics.stats
            active_sessions = diagnostics.session_states.get(SessionState.CONNECTED, 0)
            active_connections = sum(v for k, v in diagnostics.connection_states.items() if k != ConnectionState.CLOSED)

            health_data = {
                "status": "healthy",
                "timestamp": time.time(),
                "uptime": (get_timestamp() - stats.start_time) if stats.start_time else 0.0,
                "active_sessions": active_sessions,
                "active_connections": active_connections,
            }
            await session.send_datagram(data=json.dumps(health_data).encode("utf-8"))
            logger.info("Sent health status: %s", health_data["status"])
        except Exception as e:
            logger.error("Health handler error: %s", e)
        finally:
            if not session.is_closed:
                await session.close()

    async def _on_connection_established(self, event: Any) -> None:
        """Handle connection established events."""
        logger.info("New connection established")

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
        self.route(path="/health")(self._health_handler)
        self.route(path="/pubsub")(pubsub_handler)
        self.route(path="/rpc")(rpc_handler)
        self.route(path="/diagnostics")(self._diagnostics_handler)
        self.route(path="/structured-echo/json")(structured_echo_json_handler)
        self.route(path="/structured-echo/msgpack")(structured_echo_msgpack_handler)


MESSAGE_REGISTRY: dict[int, type[Any]] = {1: UserData, 2: StatusUpdate}
GLOBAL_TOPICS: defaultdict[str, set[asyncio.Queue[tuple[str, bytes]]]] = defaultdict(set)


async def _structured_echo_base_handler(*, session: WebTransportSession, serializer: Any, serializer_name: str) -> None:
    """Provide the base handler logic for structured echo."""
    session_id = session.session_id
    logger.info("Structured handler started for session %s (%s)", session_id, serializer_name)

    try:
        s_stream_manager_task = asyncio.create_task(
            coro=handle_all_structured_streams(session=session, serializer=serializer)
        )
        s_datagram_task = asyncio.create_task(coro=handle_structured_datagram(session=session, serializer=serializer))
        await asyncio.gather(s_stream_manager_task, s_datagram_task, return_exceptions=True)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error("Structured handler error for session %s: %s", session_id, e, exc_info=True)
    finally:
        logger.info("Structured handler finished for session %s", session_id)


async def echo_handler(session: WebTransportSession) -> None:
    """Handle echoing streams and datagrams."""
    session_id = session.session_id
    logger.info("Handler started for session %s on path %s", session_id, session.path)

    try:
        datagram_task = asyncio.create_task(coro=handle_datagrams(session=session))
        stream_task = asyncio.create_task(coro=handle_incoming_streams(session=session))
        await asyncio.gather(datagram_task, stream_task, return_exceptions=True)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error("Handler error for session %s: %s", session_id, e, exc_info=True)
    finally:
        logger.info("Handler finished for session %s", session_id)


async def handle_all_structured_streams(*, session: WebTransportSession, serializer: Any) -> None:
    """Listen for and handle all incoming streams for a structured session."""
    session_id = session.session_id

    async def stream_opened_handler(event: Event) -> None:
        if not isinstance(event.data, dict):
            return
        stream = event.data.get("stream")
        if isinstance(stream, WebTransportStream):
            asyncio.create_task(coro=handle_structured_stream(stream=stream, serializer=serializer))

    session.events.on(event_type=EventType.STREAM_OPENED, handler=stream_opened_handler)
    try:
        await session.events.wait_for(event_type=EventType.SESSION_CLOSED)
    except (asyncio.CancelledError, ConnectionError):
        pass
    except Exception as e:
        logger.error("Structured stream manager for session %s error: %s", session_id, e, exc_info=True)
    finally:
        session.events.off(event_type=EventType.STREAM_OPENED, handler=stream_opened_handler)


async def handle_bidirectional_stream(*, stream: WebTransportStream) -> None:
    """Handle echo logic for a bidirectional stream."""
    try:
        request_data = await stream.read_all()
        echo_data = b"ECHO: " + request_data
        await stream.write_all(data=echo_data)
    except (asyncio.CancelledError, ConnectionError, StreamError):
        pass
    except Exception as e:
        logger.error("Bidirectional stream %s error: %s", stream.stream_id, e, exc_info=True)
        await stream.close(error_code=1)


async def handle_datagrams(*, session: WebTransportSession) -> None:
    """Receive and echo datagrams for a session."""
    session_id = session.session_id
    logger.debug("Starting datagram handler for session %s", session_id)

    async def datagram_handler(event: Event) -> None:
        if not isinstance(event.data, dict):
            return
        data = event.data.get("data")
        if not isinstance(data, bytes):
            return

        try:
            echo_data = b"ECHO: " + data
            await session.send_datagram(data=echo_data)
        except (asyncio.CancelledError, ConnectionError, SessionError) as e:
            logger.warning("Datagram handler error for session %s: %s", session_id, e)

    session.events.on(event_type=EventType.DATAGRAM_RECEIVED, handler=datagram_handler)
    try:
        await session.events.wait_for(event_type=EventType.SESSION_CLOSED)
    except (asyncio.CancelledError, ConnectionError):
        pass
    except Exception as e:
        logger.error("Datagram handler error for session %s: %s", session_id, e, exc_info=True)
    finally:
        session.events.off(event_type=EventType.DATAGRAM_RECEIVED, handler=datagram_handler)


async def handle_incoming_streams(*, session: WebTransportSession) -> None:
    """Listen for and handle all incoming streams for a session."""
    session_id = session.session_id
    logger.debug("Starting stream handler for session %s", session_id)

    async def stream_opened_handler(event: Event) -> None:
        if not isinstance(event.data, dict):
            return
        stream = event.data.get("stream")
        if stream:
            asyncio.create_task(coro=handle_single_stream(stream=stream, session_id=session_id))

    session.events.on(event_type=EventType.STREAM_OPENED, handler=stream_opened_handler)
    try:
        await session.events.wait_for(event_type=EventType.SESSION_CLOSED)
    except (asyncio.CancelledError, ConnectionError):
        pass
    except Exception as e:
        logger.error("Stream handler error for session %s: %s", session_id, e, exc_info=True)
    finally:
        session.events.off(event_type=EventType.STREAM_OPENED, handler=stream_opened_handler)


async def handle_receive_stream(*, stream: WebTransportReceiveStream) -> None:
    """Handle data from a receive-only stream."""
    try:
        await stream.read_all()
    except (asyncio.CancelledError, ConnectionError, StreamError):
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
        pass


async def handle_structured_datagram(*, session: WebTransportSession, serializer: Any) -> None:
    """Receive and echo structured datagrams for a session."""
    session_id = session.session_id
    logger.debug("Starting structured datagram handler for session %s", session_id)

    try:
        structured_datagram_transport = StructuredDatagramTransport(
            session=session, serializer=serializer, registry=MESSAGE_REGISTRY
        )
        await structured_datagram_transport.initialize()

        while not session.is_closed:
            obj = await structured_datagram_transport.receive_obj()
            await structured_datagram_transport.send_obj(obj=obj)

    except (asyncio.CancelledError, ConnectionError, SessionError, TimeoutError):
        logger.debug("Structured datagram handler for session %s closing.", session_id)
    except Exception as e:
        logger.error("Structured datagram handler error for session %s: %s", session_id, e, exc_info=True)
    finally:
        logger.debug("Structured datagram handler for session %s finished.", session_id)


async def handle_structured_stream(*, stream: WebTransportStream, serializer: Any) -> None:
    """Handle echoing structured objects on a single, existing bidirectional stream."""
    raw_stream = stream
    stream_id = raw_stream.stream_id
    logger.debug("Handling structured stream %s", stream_id)

    try:
        structured_stream = StructuredStream(
            stream=raw_stream,
            serializer=serializer,
            registry=MESSAGE_REGISTRY,
            max_message_size=DEFAULT_MAX_MESSAGE_SIZE,
        )
        async for obj in structured_stream:
            logger.debug("Echoing object on stream %s: %s", stream_id, obj)
            await structured_stream.send_obj(obj=obj)
    except (asyncio.CancelledError, ConnectionError, StreamError):
        pass
    except Exception as e:
        logger.error("Structured stream %s error: %s", stream_id, e, exc_info=True)
    finally:
        if not raw_stream.is_closed:
            await raw_stream.close()


async def pubsub_handler(session: WebTransportSession) -> None:
    """Handle the Pub/Sub test logic."""
    session_id = session.session_id
    logger.info("Pub/Sub handler started for session %s", session_id)

    my_queue: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue()
    subscribed_topics: set[str] = set()

    try:
        stream_fut: asyncio.Future[WebTransportStream] = asyncio.Future()

        async def first_stream_handler(event: Event) -> None:
            if not stream_fut.done() and isinstance(event.data, dict):
                stream = event.data.get("stream")
                if isinstance(stream, WebTransportStream):
                    stream_fut.set_result(stream)

        session.events.on(event_type=EventType.STREAM_OPENED, handler=first_stream_handler)

        try:
            async with asyncio.timeout(delay=10.0):
                stream = await stream_fut
        except asyncio.TimeoutError:
            stream_fut.cancel()
            logger.warning("Pub/Sub session %s timed out waiting for stream.", session_id)
            return
        finally:
            session.events.off(event_type=EventType.STREAM_OPENED, handler=first_stream_handler)

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
    except (StopAsyncIteration, asyncio.CancelledError, ConnectionError):
        pass
    except Exception as e:
        logger.error("Pub/Sub handler error for session %s: %s", session_id, e, exc_info=True)
    finally:
        for topic in subscribed_topics:
            GLOBAL_TOPICS[topic].discard(my_queue)
        logger.info("Pub/Sub handler finished for session %s", session_id)


async def rpc_handler(session: WebTransportSession) -> None:
    """Handle the RPC test logic."""
    session_id = session.session_id
    logger.info("RPC handler started for session %s", session_id)

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
        await asyncio.sleep(delay=delay)
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
            await stream.close(error_code=1)

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
        stream_fut: asyncio.Future[WebTransportStream] = asyncio.Future()

        async def first_stream_handler(event: Event) -> None:
            if not stream_fut.done() and isinstance(event.data, dict):
                stream = event.data.get("stream")
                if isinstance(stream, WebTransportStream):
                    stream_fut.set_result(stream)

        session.events.on(event_type=EventType.STREAM_OPENED, handler=first_stream_handler)

        try:
            async with asyncio.timeout(delay=10.0):
                stream = await stream_fut
        except asyncio.TimeoutError:
            stream_fut.cancel()
            logger.warning("RPC session %s timed out waiting for stream.", session_id)
            return
        finally:
            session.events.off(event_type=EventType.STREAM_OPENED, handler=first_stream_handler)

        while not stream.is_closed:
            header = await stream.readexactly(n=4)
            length = struct.unpack("!I", header)[0]
            payload = await stream.readexactly(n=length)
            message = json.loads(payload.decode("utf-8"))
            asyncio.create_task(coro=process_request(stream, message))
    except (StopAsyncIteration, asyncio.CancelledError, ConnectionError, StreamError, asyncio.IncompleteReadError):
        pass
    except Exception as e:
        logger.error("RPC handler error for session %s: %s", session_id, e, exc_info=True)
    finally:
        logger.info("RPC handler finished for session %s", session_id)


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
        flow_control_window_auto_scale=True,
        flow_control_window_size=65536,
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
