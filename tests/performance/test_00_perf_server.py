"""WebTransport performance test server."""

import asyncio
import json
import logging
import os
import sys
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, Final

import psutil

from pywebtransport import (
    ConnectionError,
    Event,
    ServerApp,
    ServerConfig,
    StreamError,
    WebTransportReceiveStream,
    WebTransportSendStream,
    WebTransportSession,
    WebTransportStream,
)
from pywebtransport.server import SessionHandler
from pywebtransport.types import ConnectionState, EventType
from pywebtransport.utils import generate_self_signed_cert

CERT_PATH: Final[Path] = Path("localhost.crt")
KEY_PATH: Final[Path] = Path("localhost.key")
DEBUG_MODE: Final[bool] = "--debug" in sys.argv
SERVER_HOST: Final[str] = "::"
SERVER_PORT: Final[int] = 4433

SERVER_PROCESS = psutil.Process(os.getpid())

StreamObject = WebTransportStream | WebTransportReceiveStream | WebTransportSendStream

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
if DEBUG_MODE:
    logging.getLogger("pywebtransport").setLevel(logging.DEBUG)
    logging.getLogger("pywebtransport.probe").setLevel(logging.INFO)

logger = logging.getLogger("perf_server")


class PerformanceServerApp(ServerApp):
    """Performance testing server application."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the performance server application."""
        super().__init__(**kwargs)
        self.server.on(event_type=EventType.CONNECTION_ESTABLISHED, handler=self._on_connection_established)
        self.server.on(event_type=EventType.SESSION_REQUEST, handler=self._on_session_request)
        self._register_handlers()

    async def _on_connection_established(self, event: Any) -> None:
        """Handles connection established events."""
        logger.debug("New connection established.")

    async def _on_session_request(self, event: Any) -> None:
        """Handles session request events."""
        if isinstance(event.data, dict):
            session_id = event.data.get("session_id")
            path = event.data.get("path", "/")
            logger.debug("Session request: %s for path '%s'", session_id, path)

    def create_long_running_stream_handler(
        self, stream_handler: Callable[[Any], Coroutine[Any, Any, None]]
    ) -> SessionHandler:
        """Create a session handler for long-running stream-based tests."""

        async def session_handler(session: WebTransportSession) -> None:
            async def stream_opened_handler(event: Event) -> None:
                if isinstance(event.data, dict):
                    stream = event.data.get("stream")
                    if stream:
                        asyncio.create_task(stream_handler(stream))

            session.events.on(event_type=EventType.STREAM_OPENED, handler=stream_opened_handler)
            try:
                await session.events.wait_for(event_type=EventType.SESSION_CLOSED)
            except ConnectionError:
                pass
            finally:
                session.events.off(event_type=EventType.STREAM_OPENED, handler=stream_opened_handler)

        return session_handler

    async def connection_test_handler(self, session: WebTransportSession) -> None:
        """Handle simple connection test sessions."""
        pass

    async def persistent_echo_handler(self, session: WebTransportSession) -> None:
        """Handle persistent echo sessions over a single stream."""
        try:
            stream_event = await session.events.wait_for(event_type=EventType.STREAM_OPENED, timeout=10.0)
            if not isinstance(stream_event.data, dict):
                return
            stream = stream_event.data.get("stream")

            if not isinstance(stream, WebTransportStream):
                return

            async def echo_worker() -> None:
                while True:
                    data = await stream.read(max_bytes=8192)
                    if not data:
                        break
                    await stream.write(data=b"ECHO: " + data)

            await echo_worker()
        except (ConnectionError, StreamError, asyncio.CancelledError, asyncio.TimeoutError):
            pass

    async def resource_usage_handler(self, session: WebTransportSession) -> None:
        """Handle requests for server resource usage statistics."""
        try:
            stream_event = await session.events.wait_for(event_type=EventType.STREAM_OPENED, timeout=10.0)
            if not isinstance(stream_event.data, dict):
                return
            stream = stream_event.data.get("stream")

            if not isinstance(stream, WebTransportStream):
                return

            await stream.read(max_bytes=1)
            diagnostics = await self.server.diagnostics()
            cpu_percent = SERVER_PROCESS.cpu_percent(interval=0.1)
            memory_info = SERVER_PROCESS.memory_info()
            usage_data = {
                "cpu_percent": cpu_percent,
                "memory_rss_bytes": memory_info.rss,
                "active_connections": diagnostics.connection_states.get(ConnectionState.CONNECTED, 0),
            }
            await stream.write_all(data=json.dumps(usage_data).encode())
            await stream.read_all()
        except (ConnectionError, StreamError, asyncio.CancelledError, asyncio.TimeoutError):
            pass
        except Exception as e:
            logger.error("Error in resource_usage_handler for session %s: %s", session.session_id, e)

    def _register_handlers(self) -> None:
        """Register session handlers for various performance test routes."""
        self.route(path="/echo")(combined_echo_handler)
        self.route(path="/connection_test")(self.connection_test_handler)
        self.route(path="/persistent_echo")(self.persistent_echo_handler)
        self.route(path="/discard")(self.create_long_running_stream_handler(handle_stream_discard))
        self.route(path="/produce")(self.create_long_running_stream_handler(handle_stream_produce))
        self.route(path="/request_response")(self.create_long_running_stream_handler(handle_stream_request_response))
        self.route(path="/resource_usage")(self.resource_usage_handler)


async def handle_stream_echo(*, stream: WebTransportStream) -> None:
    """Read all data from a stream and echo it back prefixed."""
    try:
        request_data = await stream.read_all()
        if request_data:
            await stream.write_all(data=b"ECHO: " + request_data)
    except (ConnectionError, StreamError):
        pass
    finally:
        if not stream.is_closed:
            await stream.close()


async def handle_stream_discard(stream: WebTransportReceiveStream) -> None:
    """Read and discard all data from a receive stream."""
    try:
        await stream.read_all()
    except (ConnectionError, StreamError):
        pass


async def handle_stream_produce(stream: WebTransportStream) -> None:
    """Produce a specified amount of data on a stream."""
    try:
        control_message_bytes = await stream.read(max_bytes=128)
        control_message = control_message_bytes.decode()

        if not control_message.startswith("SEND:"):
            return

        size_to_send = int(control_message.split(":")[1])
        dummy_chunk = b"d" * 8192
        bytes_sent = 0
        while bytes_sent < size_to_send:
            chunk = dummy_chunk[: min(len(dummy_chunk), size_to_send - bytes_sent)]
            await stream.write(data=chunk)
            bytes_sent += len(chunk)

    except (ValueError, ConnectionError, StreamError):
        pass
    finally:
        if not stream.is_closed:
            await stream.close()


async def handle_stream_request_response(stream: WebTransportStream) -> None:
    """Handle a simple request-response pattern on a stream."""
    try:
        request = await stream.read_all()
        if request:
            response = b"R" * len(request)
            await stream.write_all(data=response)
    except (ConnectionError, StreamError):
        pass
    finally:
        if not stream.is_closed:
            await stream.close()


async def datagram_echo_task(*, session: WebTransportSession) -> None:
    """Receive datagrams and echo them back in a loop."""

    async def datagram_handler(event: Event) -> None:
        if isinstance(event.data, dict):
            data = event.data.get("data")
            if isinstance(data, bytes):
                try:
                    await session.send_datagram(data=b"ECHO: " + data)
                except ConnectionError:
                    pass

    session.events.on(event_type=EventType.DATAGRAM_RECEIVED, handler=datagram_handler)
    try:
        await session.events.wait_for(event_type=EventType.SESSION_CLOSED)
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        session.events.off(event_type=EventType.DATAGRAM_RECEIVED, handler=datagram_handler)


async def stream_handling_task(*, session: WebTransportSession) -> None:
    """Handle all incoming streams for a session's lifetime."""

    async def stream_opened_handler(event: Event) -> None:
        if isinstance(event.data, dict):
            stream = event.data.get("stream")
            if isinstance(stream, WebTransportStream):
                asyncio.create_task(handle_stream_echo(stream=stream))

    session.events.on(event_type=EventType.STREAM_OPENED, handler=stream_opened_handler)
    try:
        await session.events.wait_for(event_type=EventType.SESSION_CLOSED)
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        session.events.off(event_type=EventType.STREAM_OPENED, handler=stream_opened_handler)


async def combined_echo_handler(session: WebTransportSession) -> None:
    """Handle sessions by echoing both datagrams and streams, with robust task cleanup."""
    dgram_task = asyncio.create_task(datagram_echo_task(session=session))
    strm_task = asyncio.create_task(stream_handling_task(session=session))

    try:
        await session.events.wait_for(event_type=EventType.SESSION_CLOSED)
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        dgram_task.cancel()
        strm_task.cancel()
        await asyncio.gather(dgram_task, strm_task, return_exceptions=True)


async def main() -> None:
    """Set up and run the performance test server."""
    if not CERT_PATH.exists() or not KEY_PATH.exists():
        logger.info("Generating self-signed certificate for %s...", CERT_PATH.stem)
        generate_self_signed_cert(hostname=CERT_PATH.stem, output_dir=".")

    logger.info("Starting PyWebTransport Performance Test Server...")
    config = ServerConfig(
        bind_host=SERVER_HOST,
        bind_port=SERVER_PORT,
        certfile=str(CERT_PATH),
        keyfile=str(KEY_PATH),
        debug=DEBUG_MODE,
        log_level="DEBUG" if DEBUG_MODE else "INFO",
        max_connections=10000,
        initial_max_data=1024 * 1024 * 100,
        initial_max_streams_bidi=10000,
        initial_max_streams_uni=10000,
        flow_control_window_size=1024 * 1024 * 100,
        stream_flow_control_increment_bidi=1000,
        stream_flow_control_increment_uni=1000,
    )
    app = PerformanceServerApp(config=config)
    logger.info("Server binding to %s:%s", config.bind_host, config.bind_port)
    logger.info("Maximum connections (default): %s", config.max_connections)
    logger.info("Flow Control: initial_max_data=%d", config.initial_max_data)
    logger.info("Flow Control: initial_max_streams_bidi=%d", config.initial_max_streams_bidi)
    if DEBUG_MODE:
        logger.info("Debug mode enabled - verbose logging active")
    logger.info("Ready for performance tests!")

    async with app:
        await app.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped gracefully by user.")
    except Exception as e:
        logger.critical("Server crashed unexpectedly: %s", e, exc_info=True)
        sys.exit(1)
