"""Unit tests for the pywebtransport.session.session module."""

import asyncio
import weakref
from collections.abc import AsyncGenerator
from typing import Any, cast
from unittest import mock
from unittest.mock import AsyncMock, PropertyMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport import (
    ClientConfig,
    Event,
    EventType,
    FlowControlError,
    Serializer,
    ServerConfig,
    SessionError,
    SessionState,
    StreamDirection,
    StreamError,
    TimeoutError,
    WebTransportReceiveStream,
    WebTransportSendStream,
    WebTransportSession,
    WebTransportStream,
)
from pywebtransport.connection import WebTransportConnection
from pywebtransport.protocol import WebTransportProtocolHandler
from pywebtransport.session import SessionStats
from pywebtransport.stream import StreamManager


class TestSessionStats:
    def test_properties(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.session.session.get_timestamp", return_value=1200.0)
        stats = SessionStats(session_id="session-1", created_at=1000.0)

        assert stats.uptime == 0.0
        assert stats.active_streams == 0

        stats.ready_at = 1100.0
        stats.streams_created = 10
        stats.streams_closed = 4
        stats.closed_at = 1300.0

        assert stats.uptime == 200.0
        assert stats.active_streams == 6

    def test_uptime_not_ready(self) -> None:
        stats = SessionStats(session_id="session-1", created_at=1000.0)

        assert stats.ready_at is None
        assert stats.uptime == 0.0

    def test_to_dict(self) -> None:
        stats = SessionStats(
            session_id="session-1",
            created_at=1000.0,
            ready_at=1100.0,
            closed_at=1200.0,
            streams_created=5,
            streams_closed=2,
        )

        stats_dict = stats.to_dict()

        assert stats_dict["session_id"] == "session-1"
        assert stats_dict["uptime"] == 100.0
        assert stats_dict["active_streams"] == 3
        assert stats_dict["streams_created"] == 5


class TestWebTransportSession:
    @pytest.fixture
    def mock_connection(self, mocker: MockerFixture, mock_protocol_handler: Any) -> Any:
        connection = mocker.create_autospec(WebTransportConnection, instance=True)
        connection.protocol_handler = mock_protocol_handler
        connection.config = ClientConfig()
        connection.connection_id = "conn-123"
        connection.state = SessionState.CONNECTED
        type(connection).is_connected = PropertyMock(return_value=True)
        connection.is_closed = False
        connection.info = mocker.MagicMock()
        connection.info.last_activity = 1000.0
        connection.on = mocker.MagicMock()
        connection.off = mocker.MagicMock()
        connection.once = mocker.MagicMock()
        connection.close = mocker.AsyncMock()
        return connection

    @pytest.fixture
    def mock_datagram_transport_class(self, mocker: MockerFixture) -> Any:
        mock_class = mocker.patch("pywebtransport.session.session.WebTransportDatagramTransport", autospec=True)
        mock_instance = mock_class.return_value
        mock_instance.initialize = mock.AsyncMock()
        mock_instance.close = mock.AsyncMock()
        mock_instance.stats = {"datagrams_sent": 0, "datagrams_received": 0}
        mock_instance.get_receive_buffer_size.return_value = 0
        return mock_class

    @pytest.fixture
    def mock_protocol_handler(self, mocker: MockerFixture) -> Any:
        handler = mocker.create_autospec(WebTransportProtocolHandler, instance=True)
        handler.on = mocker.MagicMock()
        handler.off = mocker.MagicMock()
        handler.get_session_info.return_value = None
        handler.create_webtransport_stream.return_value = 101
        handler.close_webtransport_session = mocker.Mock()
        return handler

    @pytest.fixture
    async def session(
        self,
        mock_connection: Any,
        mock_datagram_transport_class: Any,
        mocker: MockerFixture,
    ) -> AsyncGenerator[WebTransportSession, None]:
        mocker.patch("pywebtransport.session.session.get_timestamp", return_value=1000.0)
        manager = mocker.create_autospec(StreamManager, instance=True)
        manager.__aenter__ = mocker.AsyncMock(return_value=manager)
        manager.__aexit__ = mocker.AsyncMock()
        manager.create_bidirectional_stream = mocker.AsyncMock(
            return_value=mocker.create_autospec(WebTransportStream, instance=True)
        )
        manager.create_unidirectional_stream = mocker.AsyncMock(
            return_value=mocker.create_autospec(WebTransportSendStream, instance=True)
        )
        manager.shutdown = mocker.AsyncMock()
        manager.add_stream = mocker.AsyncMock()
        manager.get_stats = mocker.AsyncMock(return_value={"total_created": 0, "total_closed": 0})
        manager.get_all_streams = mocker.AsyncMock(return_value=[])
        mocker.patch("pywebtransport.session.session.StreamManager.create", return_value=manager)
        session_instance = WebTransportSession(connection=mock_connection, session_id="session-1")
        await session_instance.initialize()
        session_instance._incoming_streams = mocker.create_autospec(asyncio.Queue, instance=True)

        yield session_instance

        if not session_instance.is_closed and session_instance.stream_manager:
            await session_instance.close(close_connection=False)

    @pytest.mark.asyncio
    async def test_initialization(
        self,
        session: WebTransportSession,
        mock_connection: Any,
        mock_protocol_handler: Any,
        mocker: MockerFixture,
    ) -> None:
        assert session.session_id == "session-1"
        assert session.state == SessionState.CONNECTING
        assert session.connection is mock_connection
        assert session.protocol_handler is mock_protocol_handler

        expected_calls = [
            mocker.call(event_type=EventType.SESSION_READY, handler=session._on_session_ready),
            mocker.call(event_type=EventType.SESSION_CLOSED, handler=session._on_session_closed),
            mocker.call(event_type=EventType.STREAM_OPENED, handler=session._on_stream_opened),
            mocker.call(event_type=EventType.DATAGRAM_RECEIVED, handler=session._on_datagram_received),
            mocker.call(event_type=EventType.SESSION_MAX_DATA_UPDATED, handler=session._on_max_data_updated),
            mocker.call(
                event_type=EventType.SESSION_MAX_STREAMS_BIDI_UPDATED,
                handler=session._on_max_streams_bidi_updated,
            ),
            mocker.call(
                event_type=EventType.SESSION_MAX_STREAMS_UNI_UPDATED,
                handler=session._on_max_streams_uni_updated,
            ),
        ]
        mock_protocol_handler.on.assert_has_calls(expected_calls, any_order=True)
        mock_connection.once.assert_called_once_with(
            event_type=EventType.CONNECTION_CLOSED, handler=session._on_connection_closed
        )
        mock_protocol_handler.get_session_info.assert_called_once_with(session_id="session-1")

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, session: WebTransportSession) -> None:
        assert session._is_initialized

        await session.initialize()

        assert session.stream_manager is not None
        cast(AsyncMock, session.stream_manager.__aenter__).assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sync_protocol_state_on_init(
        self, mock_connection: Any, mock_protocol_handler: Any, mocker: MockerFixture
    ) -> None:
        mock_session_info = mocker.MagicMock()
        mock_session_info.state = SessionState.CONNECTED
        mock_session_info.ready_at = 999.0
        mock_session_info.path = "/synced"
        mock_session_info.headers = {"x-synced": "true"}
        mock_session_info.stream_id = 42
        mock_protocol_handler.get_session_info.return_value = mock_session_info
        session = WebTransportSession(connection=mock_connection, session_id="session-1")

        await session.initialize()

        assert session.state == SessionState.CONNECTED
        assert session.is_ready
        assert session.path == "/synced"
        assert session.headers == {"x-synced": "true"}
        assert session._ready_event is not None
        assert session._ready_event.is_set()

    @pytest.mark.asyncio
    async def test_sync_protocol_state_no_headers(
        self, mock_connection: Any, mock_protocol_handler: Any, mocker: MockerFixture
    ) -> None:
        mock_session_info = mocker.MagicMock()
        mock_session_info.state = SessionState.CONNECTED
        mock_session_info.ready_at = 999.0
        mock_session_info.path = "/synced"
        mock_session_info.headers = None
        mock_session_info.stream_id = 42
        mock_protocol_handler.get_session_info.return_value = mock_session_info
        session = WebTransportSession(connection=mock_connection, session_id="session-1")

        await session.initialize()

        assert session.state == SessionState.CONNECTED
        assert session.is_ready
        assert session.headers == {}

    @pytest.mark.asyncio
    async def test_properties(self, session: WebTransportSession) -> None:
        session._state = SessionState.CONNECTED

        assert (session.is_ready, session.is_closed) == (True, False)

        session._state = SessionState.CLOSED

        assert (session.is_ready, session.is_closed) == (False, True)

    @pytest.mark.asyncio
    async def test_connection_property_is_none(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        mock_ref = mocker.MagicMock(spec=weakref.ref)
        mock_ref.return_value = None
        session._connection = mock_ref

        assert session.connection is None

    @pytest.mark.asyncio
    async def test_str_representation(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        session._session_id = "long-session-id-that-will-be-truncated"
        mocker.patch("pywebtransport.session.session.format_duration", return_value="1m 30s")
        session._stats.streams_created = 8
        session._stats.streams_closed = 2
        session._stats.datagrams_sent = 100
        session._stats.datagrams_received = 200
        session._path = "/test"

        representation = str(session)

        assert representation == (
            "Session(long-session..., state=connecting, path=/test, " "uptime=1m 30s, streams=6/8, datagrams=100/200)"
        )

    @pytest.mark.asyncio
    async def test_datagrams_property_lazy_creation(
        self, session: WebTransportSession, mock_datagram_transport_class: Any
    ) -> None:
        assert session._datagram_transport is None

        datagram_transport = await session.datagrams

        mock_datagram_transport_class.assert_called_once_with(session=session)
        assert datagram_transport is not None
        cast(mock.AsyncMock, datagram_transport.initialize).assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_context_manager(self, mock_connection: Any, mocker: MockerFixture) -> None:
        session = WebTransportSession(connection=mock_connection, session_id="session-1")
        mocker.patch("pywebtransport.session.session.StreamManager.create", return_value=mocker.AsyncMock())
        ready_mock = mocker.patch.object(session, "ready", new_callable=mocker.AsyncMock)
        close_mock = mocker.patch.object(session, "close", new_callable=mocker.AsyncMock)

        async def initialize_side_effect(*args: Any, **kwargs: Any) -> None:
            session._is_initialized = True

        initialize_mock = mocker.patch.object(
            session, "initialize", new_callable=mocker.AsyncMock, side_effect=initialize_side_effect
        )

        async with session:
            initialize_mock.assert_awaited_once()
            ready_mock.assert_awaited_once()
            close_mock.assert_not_awaited()
        close_mock.assert_awaited_once()

        async with session:
            assert initialize_mock.call_count == 1
            assert ready_mock.call_count == 2
            assert close_mock.call_count == 1
        assert close_mock.call_count == 2

    @pytest.mark.asyncio
    async def test_ready_already_connected(self, session: WebTransportSession) -> None:
        session._state = SessionState.CONNECTED

        await session.ready(timeout=0.1)

    @pytest.mark.asyncio
    async def test_ready_waits_for_event(self, session: WebTransportSession) -> None:
        session._state = SessionState.CONNECTING
        assert session._ready_event is not None
        session._ready_event.set()

        await session.ready()

    @pytest.mark.asyncio
    async def test_wait_closed(self, session: WebTransportSession) -> None:
        assert session._closed_event is not None
        session._closed_event.set()

        await session.wait_closed()

    @pytest.mark.asyncio
    async def test_close_without_datagram_transport(
        self, session: WebTransportSession, mock_datagram_transport_class: Any
    ) -> None:
        assert session._datagram_transport is None

        await session.close(close_connection=False)

        cast(AsyncMock, mock_datagram_transport_class.return_value.close).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_close_idempotent(self, session: WebTransportSession, mock_protocol_handler: Any) -> None:
        session._state = SessionState.CONNECTING

        await session.close(close_connection=False)

        assert mock_protocol_handler.close_webtransport_session.call_count == 1

        await session.close()

        assert mock_protocol_handler.close_webtransport_session.call_count == 1
        assert session.state == SessionState.CLOSED

    @pytest.mark.asyncio
    async def test_close_with_connection_already_closed(
        self, session: WebTransportSession, mock_connection: Any
    ) -> None:
        mock_connection.is_closed = True

        await session.close(close_connection=True)

        cast(AsyncMock, mock_connection.close).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_structured_datagram_transport(
        self, session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        mock_serializer = mocker.Mock(spec=Serializer)
        mock_registry: dict[int, type[Any]] = {1: int}
        mock_struct_class = mocker.patch(
            "pywebtransport.datagram.structured.StructuredDatagramTransport", autospec=True
        )
        datagram_transport = await session.datagrams

        structured_transport = await session.create_structured_datagram_transport(
            serializer=mock_serializer, registry=mock_registry
        )

        mock_struct_class.assert_called_once_with(
            datagram_transport=datagram_transport, serializer=mock_serializer, registry=mock_registry
        )
        assert structured_transport is mock_struct_class.return_value

    @pytest.mark.asyncio
    async def test_create_structured_stream(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        session._state = SessionState.CONNECTED
        mock_serializer = mocker.Mock(spec=Serializer)
        mock_registry: dict[int, type[Any]] = {1: int}
        mock_struct_class = mocker.patch("pywebtransport.stream.structured.StructuredStream", autospec=True)
        mock_raw_stream = mocker.create_autospec(WebTransportStream, instance=True)
        mock_create_bidi = mocker.patch.object(
            session, "create_bidirectional_stream", new_callable=AsyncMock, return_value=mock_raw_stream
        )

        structured_stream = await session.create_structured_stream(
            serializer=mock_serializer, registry=mock_registry, timeout=5.0
        )

        mock_create_bidi.assert_awaited_once_with(timeout=5.0)
        mock_struct_class.assert_called_once_with(
            stream=mock_raw_stream, serializer=mock_serializer, registry=mock_registry
        )
        assert structured_stream is mock_struct_class.return_value

    @pytest.mark.asyncio
    async def test_incoming_streams(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        session._state = SessionState.CONNECTED
        mock_stream1 = mocker.create_autospec(WebTransportStream, instance=True)
        mock_stream1.initialize = mock.AsyncMock()
        mock_stream2 = mocker.create_autospec(WebTransportStream, instance=True)
        mock_stream2.initialize = mock.AsyncMock()
        assert session._incoming_streams is not None
        cast(AsyncMock, session._incoming_streams.get).side_effect = [mock_stream1, mock_stream2, None]

        streams = [s async for s in session.incoming_streams()]

        assert streams == [mock_stream1, mock_stream2]
        session._state = SessionState.CLOSED

    @pytest.mark.asyncio
    async def test_on_session_ready(self, session: WebTransportSession) -> None:
        event = Event(
            type=EventType.SESSION_READY,
            data={
                "session_id": "session-1",
                "path": "/ready",
                "headers": {"content-type": "application/json"},
                "stream_id": 101,
            },
        )

        await session._on_session_ready(event=event)

        assert session.is_ready
        assert session.path == "/ready"
        assert session.headers == {"content-type": "application/json"}
        assert session._ready_event is not None
        assert session._ready_event.is_set()

    @pytest.mark.asyncio
    async def test_on_session_closed_remotely(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        close_mock = mocker.patch.object(session, "close", new_callable=mocker.AsyncMock)
        event = Event(
            type=EventType.SESSION_CLOSED, data={"session_id": "session-1", "code": 404, "reason": "Not Found"}
        )
        session._state = SessionState.CONNECTED

        await session._on_session_closed(event=event)

        cast(AsyncMock, close_mock).assert_awaited_once_with(code=404, reason="Not Found")

    @pytest.mark.asyncio
    async def test_on_connection_closed(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        close_mock = mocker.patch.object(session, "close", new_callable=mocker.AsyncMock)
        event = Event(type=EventType.CONNECTION_CLOSED, data={})
        session._state = SessionState.CONNECTED

        await session._on_connection_closed(event=event)
        await asyncio.sleep(0)

        cast(AsyncMock, close_mock).assert_awaited_once_with(
            reason="Underlying connection closed", close_connection=False
        )

    @pytest.mark.asyncio
    async def test_on_datagram_received(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        datagram_transport = await session.datagrams
        mock_handler = mocker.patch.object(datagram_transport, "_on_datagram_received")
        event = Event(type=EventType.DATAGRAM_RECEIVED, data={"session_id": "session-1", "data": b"ping"})

        await session._on_datagram_received(event=event)

        cast(AsyncMock, mock_handler).assert_awaited_once_with(event=event)

    @pytest.mark.asyncio
    async def test_get_summary(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        stats_data = {
            "bytes_sent": 1024,
            "bytes_received": 2048,
            "datagrams_sent": 100,
            "datagrams_received": 200,
            "stream_errors": 5,
            "protocol_errors": 1,
            "uptime": 60,
            "streams_created": 10,
            "active_streams": 2,
            "bidirectional_streams": 1,
            "unidirectional_streams": 1,
        }
        mocker.patch.object(session, "get_session_stats", return_value=stats_data)
        session._path = "/summary"

        summary = await session.get_summary()

        assert summary["session_id"] == "session-1"
        assert summary["path"] == "/summary"
        assert summary["data"]["bytes_sent"] == 1024
        assert summary["errors"]["stream_errors"] == 5

    @pytest.mark.asyncio
    async def test_get_summary_no_stats(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        mocker.patch.object(session, "get_session_stats", return_value={})

        summary = await session.get_summary()

        assert summary["streams"]["total_created"] == 0
        assert summary["data"]["datagrams_sent"] == 0
        assert summary["errors"]["stream_errors"] == 0

    @pytest.mark.asyncio
    async def test_get_session_stats_with_datagrams(
        self, session: WebTransportSession, mocker: MockerFixture, mock_datagram_transport_class: Any
    ) -> None:
        type(mock_datagram_transport_class.return_value).stats = PropertyMock(
            return_value={"datagrams_sent": 50, "datagrams_received": 60}
        )
        session._datagram_transport = None

        stats = await session.get_session_stats()

        assert stats["datagrams_sent"] == 50
        assert stats["datagrams_received"] == 60

    @pytest.mark.asyncio
    async def test_get_session_stats_no_datagrams(self, session: WebTransportSession) -> None:
        assert session._datagram_transport is None

        stats = await session.get_session_stats()

        assert stats["datagrams_sent"] == 0

    @pytest.mark.asyncio
    async def test_get_session_stats_no_stream_manager(self, mock_connection: Any) -> None:
        session = WebTransportSession(connection=mock_connection, session_id="session-1")
        await session.initialize()
        session.stream_manager = None

        stats = await session.get_session_stats()

        assert stats["streams_created"] == 0

    @pytest.mark.asyncio
    async def test_debug_state_no_stream_manager(self, session: WebTransportSession) -> None:
        assert session.stream_manager is not None
        cast(AsyncMock, session.stream_manager.get_all_streams).return_value = []
        session.stream_manager = None

        debug_info = await session.debug_state()

        assert debug_info["streams"] == []

    @pytest.mark.asyncio
    async def test_debug_state_no_connection(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        mocker.patch.object(WebTransportSession, "connection", new_callable=mock.PropertyMock, return_value=None)

        debug_info = await session.debug_state()

        assert debug_info["connection"]["id"] is None
        assert debug_info["connection"]["state"] == "N/A"

    @pytest.mark.asyncio
    async def test_debug_state_no_datagrams(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        future: asyncio.Future[Any] = asyncio.Future()
        future.set_result(None)
        mocker.patch.object(WebTransportSession, "datagrams", new_callable=mocker.PropertyMock, return_value=future)

        debug_info = await session.debug_state()

        assert debug_info["datagrams"]["available"] is False

    @pytest.mark.asyncio
    async def test_monitor_health_handles_exception(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        error = ValueError("Test Error")
        mock_sleep = mocker.patch("pywebtransport.session.session.asyncio.sleep", side_effect=error)
        mock_logger = mocker.patch("pywebtransport.session.session.logger")

        await session.monitor_health()

        mock_sleep.assert_awaited_once()
        mock_logger.error.assert_called_once_with("Session health monitoring error: %s", error, exc_info=True)

    @pytest.mark.asyncio
    async def test_monitor_health_active_connection(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.session.session.get_timestamp", return_value=1100.0)
        assert session.connection is not None
        session.connection.info.last_activity = 1000.0
        mocker.patch("pywebtransport.session.session.asyncio.sleep", side_effect=asyncio.CancelledError)
        mock_logger = mocker.patch("pywebtransport.session.session.logger")
        session._state = SessionState.CONNECTED

        await session.monitor_health()

        session._state = SessionState.CLOSED
        mock_logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_monitor_health_inactive_warning(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.session.session.get_timestamp", return_value=1400.0)
        assert session.connection is not None
        session.connection.info.last_activity = 1000.0
        mocker.patch("pywebtransport.session.session.asyncio.sleep", side_effect=asyncio.CancelledError)
        mock_logger = mocker.patch("pywebtransport.session.session.logger")
        session._state = SessionState.CONNECTED

        await session.monitor_health()

        session._state = SessionState.CLOSED
        mock_logger.warning.assert_called_once_with("Session %s appears inactive (no connection activity)", "session-1")

    @pytest.mark.asyncio
    async def test_teardown_no_connection(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        mocker.patch.object(WebTransportSession, "connection", new_callable=mock.PropertyMock, return_value=None)

        session._teardown_event_handlers()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("close_connection", [True, False])
    async def test_close_session(
        self,
        session: WebTransportSession,
        mock_connection: Any,
        mock_protocol_handler: Any,
        mocker: MockerFixture,
        close_connection: bool,
    ) -> None:
        datagram_transport = await session.datagrams
        mocker.patch("pywebtransport.session.session.get_timestamp", return_value=2000.0)

        await session.close(code=123, reason="test", close_connection=close_connection)

        assert session.state == SessionState.CLOSED
        assert session._closed_at == 2000.0
        assert session.is_closed
        assert session.stream_manager is not None
        cast(AsyncMock, session.stream_manager.shutdown).assert_awaited_once()
        cast(AsyncMock, datagram_transport.close).assert_awaited_once()
        assert session._incoming_streams is not None
        cast(AsyncMock, session._incoming_streams.put).assert_awaited_once_with(None)
        mock_protocol_handler.close_webtransport_session.assert_called_once_with(
            session_id="session-1", code=123, reason="test"
        )
        assert session._closed_event is not None
        assert session._closed_event.is_set()

        mock_protocol_handler.off.assert_has_calls(
            [
                mocker.call(event_type=EventType.SESSION_READY, handler=session._on_session_ready),
                mocker.call(event_type=EventType.SESSION_CLOSED, handler=session._on_session_closed),
                mocker.call(event_type=EventType.STREAM_OPENED, handler=session._on_stream_opened),
                mocker.call(event_type=EventType.DATAGRAM_RECEIVED, handler=session._on_datagram_received),
                mocker.call(event_type=EventType.SESSION_MAX_DATA_UPDATED, handler=session._on_max_data_updated),
                mocker.call(
                    event_type=EventType.SESSION_MAX_STREAMS_BIDI_UPDATED,
                    handler=session._on_max_streams_bidi_updated,
                ),
                mocker.call(
                    event_type=EventType.SESSION_MAX_STREAMS_UNI_UPDATED,
                    handler=session._on_max_streams_uni_updated,
                ),
            ],
            any_order=True,
        )
        mock_connection.off.assert_called_once_with(
            event_type=EventType.CONNECTION_CLOSED, handler=session._on_connection_closed
        )
        if close_connection:
            cast(AsyncMock, mock_connection.close).assert_awaited_once()
        else:
            cast(AsyncMock, mock_connection.close).assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("resource_error", ["stream_manager", "datagrams", "connection", "multiple"])
    async def test_close_handles_resource_errors(
        self, session: WebTransportSession, mocker: MockerFixture, resource_error: str
    ) -> None:
        datagram_transport = await session.datagrams
        error = ValueError("Resource failed to close")
        if resource_error == "stream_manager":
            assert session.stream_manager is not None
            cast(AsyncMock, session.stream_manager.shutdown).side_effect = error
        elif resource_error == "datagrams":
            cast(AsyncMock, datagram_transport.close).side_effect = error
        elif resource_error == "connection":
            assert session.connection is not None
            cast(AsyncMock, session.connection.close).side_effect = error
        elif resource_error == "multiple":
            assert session.stream_manager is not None
            cast(AsyncMock, session.stream_manager.shutdown).side_effect = ValueError("Streams failed")
            cast(AsyncMock, datagram_transport.close).side_effect = ValueError("Datagrams failed")
            assert session.connection is not None
            cast(AsyncMock, session.connection.close).side_effect = ValueError("Connection failed")
        expected_exception = (
            ExceptionGroup if resource_error in ("stream_manager", "datagrams", "multiple") else ValueError
        )

        with pytest.raises(expected_exception):
            await session.close()

        assert session.is_closed

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method_name", ["create_bidirectional_stream", "create_unidirectional_stream"])
    async def test_create_stream_no_connection(
        self, session: WebTransportSession, method_name: str, mocker: MockerFixture
    ) -> None:
        session._state = SessionState.CONNECTED
        mocker.patch.object(WebTransportSession, "connection", new_callable=mock.PropertyMock, return_value=None)

        with pytest.raises(SessionError, match="has no active connection"):
            await getattr(session, method_name)()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method_name", ["create_bidirectional_stream", "create_unidirectional_stream"])
    async def test_create_stream_no_stream_manager(self, session: WebTransportSession, method_name: str) -> None:
        session._state = SessionState.CONNECTED
        session.stream_manager = None

        with pytest.raises(SessionError, match="StreamManager is not available"):
            await getattr(session, method_name)()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method_name", ["create_bidirectional_stream", "create_unidirectional_stream"])
    async def test_create_stream_with_explicit_timeout(self, session: WebTransportSession, method_name: str) -> None:
        session._state = SessionState.CONNECTED
        assert session.stream_manager is not None
        manager_method = getattr(session.stream_manager, method_name)
        cast(AsyncMock, manager_method).side_effect = asyncio.TimeoutError()

        with pytest.raises(StreamError, match="Timed out creating .* stream after 0.1s"):
            await getattr(session, method_name)(timeout=0.1)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method_name", ["create_bidirectional_stream", "create_unidirectional_stream"])
    async def test_create_stream_default_timeout(self, session: WebTransportSession, method_name: str) -> None:
        session._state = SessionState.CONNECTED
        session._config = ServerConfig()
        assert session.stream_manager is not None
        manager_method = getattr(session.stream_manager, method_name)
        cast(AsyncMock, manager_method).side_effect = asyncio.TimeoutError()

        with pytest.raises(StreamError, match="Timed out creating .* stream after 10.0s"):
            await getattr(session, method_name)()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method_name", ["create_bidirectional_stream", "create_unidirectional_stream"])
    async def test_create_stream_with_client_config(self, session: WebTransportSession, method_name: str) -> None:
        session._state = SessionState.CONNECTED
        session._config = ClientConfig(stream_creation_timeout=0.01)
        assert session.stream_manager is not None
        manager_method = getattr(session.stream_manager, method_name)
        cast(AsyncMock, manager_method).side_effect = asyncio.TimeoutError()

        with pytest.raises(StreamError, match="Timed out creating .* stream after 0.01s"):
            await getattr(session, method_name)()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("start_state", [SessionState.CLOSING, SessionState.CLOSED])
    async def test_incoming_streams_on_closed_session(
        self, session: WebTransportSession, start_state: SessionState
    ) -> None:
        session._state = start_state

        streams = [s async for s in session.incoming_streams()]

        assert streams == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("direction", [StreamDirection.BIDIRECTIONAL, StreamDirection.RECEIVE_ONLY])
    @pytest.mark.parametrize("with_payload", [True, False])
    async def test_on_stream_opened(
        self, session: WebTransportSession, mocker: MockerFixture, direction: StreamDirection, with_payload: bool
    ) -> None:
        expected_class = WebTransportStream if direction == StreamDirection.BIDIRECTIONAL else WebTransportReceiveStream
        mock_stream_class = mocker.patch(f"pywebtransport.session.session.{expected_class.__name__}", autospec=True)
        mock_stream_instance = mock_stream_class.return_value
        mock_stream_instance.initialize = mock.AsyncMock()
        mock_stream_instance._on_data_received = mock.AsyncMock()
        event_data: dict[str, Any] = {
            "session_id": "session-1",
            "stream_id": 2,
            "direction": direction,
        }
        if with_payload:
            event_data["initial_payload"] = {"data": b"initial", "end_stream": True}
        event = Event(type=EventType.STREAM_OPENED, data=event_data)

        await session._on_stream_opened(event=event)

        mock_stream_class.assert_called_once_with(session=session, stream_id=2)
        mock_stream_instance.initialize.assert_awaited_once()
        if with_payload:
            mock_stream_instance._on_data_received.assert_awaited_once_with(event=mock.ANY)
            received_event_arg = mock_stream_instance._on_data_received.call_args.kwargs["event"]
            assert isinstance(received_event_arg, Event)
            assert received_event_arg.data == event_data["initial_payload"]
        else:
            mock_stream_instance._on_data_received.assert_not_awaited()
        assert session.stream_manager is not None
        cast(AsyncMock, session.stream_manager.add_stream).assert_awaited_once_with(stream=mock_stream_instance)
        assert session._incoming_streams is not None
        cast(AsyncMock, session._incoming_streams.put).assert_awaited_once_with(mock_stream_instance)

    @pytest.mark.asyncio
    async def test_on_stream_opened_no_stream_manager(
        self, session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        mock_logger = mocker.patch("pywebtransport.session.session.logger")
        session.stream_manager = None
        event = Event(
            type=EventType.STREAM_OPENED,
            data={"session_id": "session-1", "stream_id": 2, "direction": StreamDirection.BIDIRECTIONAL},
        )
        initial_errors = session._stats.stream_errors

        await session._on_stream_opened(event=event)

        mock_logger.error.assert_called_once_with(
            "Error handling newly opened stream %d: %s", 2, mock.ANY, exc_info=True
        )
        assert session._stats.stream_errors == initial_errors + 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "bad_data",
        [
            {"session_id": "session-99"},
            {"session_id": "session-1", "stream_id": None},
            {"session_id": "session-1", "direction": None},
            "not a dict",
        ],
    )
    async def test_on_stream_opened_invalid_data(self, session: WebTransportSession, bad_data: Any) -> None:
        event = Event(type=EventType.STREAM_OPENED, data=bad_data)

        await session._on_stream_opened(event=event)

        assert session.stream_manager is not None
        cast(AsyncMock, session.stream_manager.add_stream).assert_not_awaited()
        assert session._incoming_streams is not None
        cast(AsyncMock, session._incoming_streams.put).assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "state, stats, connection_is_connected, expected_issue",
        [
            (SessionState.CONNECTING, {}, True, "Session stuck in connecting state"),
            (SessionState.CONNECTED, {"streams_created": 100, "stream_errors": 15}, True, "High error rate: 15/100"),
            (
                SessionState.CONNECTED,
                {"uptime": 4000, "active_streams": 0, "streams_created": 0},
                True,
                "Session appears stale",
            ),
            (SessionState.CONNECTED, {}, False, "Underlying connection not available or not connected"),
        ],
    )
    async def test_diagnose_issues(
        self,
        session: WebTransportSession,
        mocker: MockerFixture,
        state: SessionState,
        stats: dict,
        connection_is_connected: bool,
        expected_issue: str,
    ) -> None:
        session._state = state
        mocker.patch.object(session, "get_session_stats", return_value=stats)
        if session.connection:
            mocker.patch.object(
                type(session.connection),
                "is_connected",
                new_callable=PropertyMock,
                return_value=connection_is_connected,
            )

        issues = await session.diagnose_issues()

        assert any(expected_issue in issue for issue in issues)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "connection_setup",
        [
            "normal",
            "no_connection",
            "no_info_attr",
            "no_last_activity_attr",
        ],
    )
    async def test_monitor_health(
        self, session: WebTransportSession, mocker: MockerFixture, connection_setup: str
    ) -> None:
        mock_sleep = mocker.patch("pywebtransport.session.session.asyncio.sleep")
        mock_sleep.side_effect = [None, asyncio.CancelledError]
        mock_logger = mocker.patch("pywebtransport.session.session.logger")
        session._state = SessionState.CONNECTED
        if connection_setup == "no_connection":
            mocker.patch.object(WebTransportSession, "connection", new_callable=mock.PropertyMock, return_value=None)
        elif connection_setup == "no_info_attr":
            assert session.connection
            delattr(session.connection, "info")
        elif connection_setup == "no_last_activity_attr":
            assert session.connection
            session.connection.info.last_activity = None

        await session.monitor_health(check_interval=10)

        assert mock_sleep.call_count == 2
        mock_logger.debug.assert_any_call("Health monitoring cancelled for session %s", "session-1")
        mock_logger.warning.assert_not_called()
        session._state = SessionState.CLOSED

    @pytest.mark.asyncio
    async def test_initialization_on_closed_connection(self, mock_connection: Any, mocker: MockerFixture) -> None:
        mock_connection.is_closed = True
        session = WebTransportSession(connection=mock_connection, session_id="session-1")
        close_mock = mocker.patch.object(session, "close", new_callable=mocker.AsyncMock)

        await session.initialize()
        await asyncio.sleep(0)

        cast(AsyncMock, close_mock).assert_awaited_once_with(
            reason="Connection already closed upon session creation", close_connection=False
        )

    @pytest.mark.asyncio
    async def test_initialization_no_protocol_handler(self, mocker: MockerFixture, mock_connection: Any) -> None:
        mock_logger = mocker.patch("pywebtransport.session.session.logger")
        mock_connection.protocol_handler = None
        session = WebTransportSession(connection=mock_connection, session_id="session-1")

        await session.initialize()

        assert session.protocol_handler is None
        mock_logger.warning.assert_called_with("No protocol handler available for session %s", "session-1")
        await session.close()

    @pytest.mark.asyncio
    async def test_datagrams_property_when_closed(self, session: WebTransportSession) -> None:
        session._state = SessionState.CLOSED

        with pytest.raises(SessionError, match="is closed"):
            await session.datagrams

    @pytest.mark.asyncio
    async def test_ready_timeout(self, session: WebTransportSession) -> None:
        session._state = SessionState.CONNECTING

        with pytest.raises(TimeoutError, match="Session ready timeout"):
            await session.ready(timeout=0.01)

    @pytest.mark.asyncio
    async def test_create_stream_not_ready(self, session: WebTransportSession) -> None:
        session._state = SessionState.CONNECTING

        with pytest.raises(SessionError, match=r"Session session-1 not ready, current state: connecting"):
            await session.create_bidirectional_stream()

    @pytest.mark.asyncio
    async def test_create_stream_protocol_failure(self, session: WebTransportSession) -> None:
        session._state = SessionState.CONNECTED
        assert session.stream_manager is not None
        cast(AsyncMock, session.stream_manager.create_bidirectional_stream).side_effect = StreamError("Kaboom")

        with pytest.raises(StreamError, match="Kaboom"):
            await session.create_bidirectional_stream()

    @pytest.mark.asyncio
    async def test_create_stream_on_protocol_no_handler(self, session: WebTransportSession) -> None:
        session._protocol_handler = None

        with pytest.raises(SessionError, match="Protocol handler is not available"):
            await session._create_stream_on_protocol(is_unidirectional=False)

    @pytest.mark.asyncio
    async def test_create_stream_on_protocol_generic_exception(
        self, session: WebTransportSession, mock_protocol_handler: Any
    ) -> None:
        mock_protocol_handler.create_webtransport_stream.side_effect = ValueError("Generic Error")

        with pytest.raises(StreamError, match="Protocol handler failed to create stream: Generic Error"):
            await session._create_stream_on_protocol(is_unidirectional=False)

        assert session._stats.stream_errors == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("is_unidirectional", [False, True])
    async def test_create_stream_on_protocol_flow_control(
        self, session: WebTransportSession, mock_protocol_handler: Any, is_unidirectional: bool, mocker: MockerFixture
    ) -> None:
        stream_id = 101
        mock_protocol_handler.create_webtransport_stream.side_effect = [
            FlowControlError("No stream credit"),
            stream_id,
        ]

        credit_event = session._uni_stream_credit_event if is_unidirectional else session._bidi_stream_credit_event
        assert credit_event is not None
        mocker.patch.object(credit_event, "wait", new_callable=AsyncMock)
        mocker.patch.object(credit_event, "clear")

        async def set_event_later() -> None:
            await asyncio.sleep(0.01)
            credit_event.set()

        asyncio.create_task(set_event_later())
        result_stream_id = await session._create_stream_on_protocol(is_unidirectional=is_unidirectional)

        assert result_stream_id == stream_id
        cast(AsyncMock, credit_event.clear).assert_called_once()
        cast(AsyncMock, credit_event.wait).assert_awaited_once()
        assert mock_protocol_handler.create_webtransport_stream.call_count == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize("is_unidirectional", [False, True])
    async def test_create_stream_on_protocol_flow_control_no_event(
        self, session: WebTransportSession, mock_protocol_handler: Any, is_unidirectional: bool
    ) -> None:
        mock_protocol_handler.create_webtransport_stream.side_effect = FlowControlError("No stream credit")
        if is_unidirectional:
            session._uni_stream_credit_event = None
        else:
            session._bidi_stream_credit_event = None

        with pytest.raises(FlowControlError, match="No stream credit"):
            await session._create_stream_on_protocol(is_unidirectional=is_unidirectional)

    @pytest.mark.asyncio
    async def test_incoming_streams_timeout(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        session._state = SessionState.CONNECTED
        mock_stream = mocker.create_autospec(WebTransportStream, instance=True)
        mock_stream.initialize = mock.AsyncMock()
        assert session._incoming_streams is not None
        cast(AsyncMock, session._incoming_streams.get).side_effect = [asyncio.TimeoutError, mock_stream, None]

        streams = [s async for s in session.incoming_streams()]

        assert streams == [mock_stream]
        assert cast(AsyncMock, session._incoming_streams.get).call_count == 3

    @pytest.mark.asyncio
    async def test_on_session_ready_mismatched_id(self, session: WebTransportSession) -> None:
        event = Event(type=EventType.SESSION_READY, data={"session_id": "session-2"})

        await session._on_session_ready(event=event)

        assert not session.is_ready
        assert session._ready_event is not None
        assert not session._ready_event.is_set()

    @pytest.mark.asyncio
    async def test_on_session_closed_mismatched_id(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        close_mock = mocker.patch.object(session, "close", new_callable=mocker.AsyncMock)
        event = Event(type=EventType.SESSION_CLOSED, data={"session_id": "session-2"})
        session._state = SessionState.CONNECTED

        await session._on_session_closed(event=event)

        close_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_session_closed_remotely_when_already_closing(
        self, session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        close_mock = mocker.patch.object(session, "close", new_callable=mocker.AsyncMock)
        event = Event(type=EventType.SESSION_CLOSED, data={"session_id": "session-1"})
        session._state = SessionState.CLOSING

        await session._on_session_closed(event=event)

        cast(AsyncMock, close_mock).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_connection_closed_when_session_closing(
        self, session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        close_mock = mocker.patch.object(session, "close", new_callable=mocker.AsyncMock)
        event = Event(type=EventType.CONNECTION_CLOSED, data={})
        session._state = SessionState.CLOSING

        await session._on_connection_closed(event=event)

        cast(AsyncMock, close_mock).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_stream_opened_handles_exception(
        self, session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        mocker.patch("pywebtransport.session.session.WebTransportStream", autospec=True)
        event = Event(
            type=EventType.STREAM_OPENED,
            data={"session_id": "session-1", "stream_id": 2, "direction": StreamDirection.BIDIRECTIONAL},
        )
        assert session.stream_manager is not None
        cast(AsyncMock, session.stream_manager.add_stream).side_effect = ValueError("Test error")

        await session._on_stream_opened(event=event)

        assert session._stats.stream_errors == 1
        assert session._incoming_streams is not None
        cast(AsyncMock, session._incoming_streams.put).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_datagram_received_invalid_event(
        self, session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        datagram_transport = await session.datagrams
        mock_handler = mocker.patch.object(datagram_transport, "_on_datagram_received")
        event = Event(type=EventType.DATAGRAM_RECEIVED, data={"session_id": "other-session", "data": b"ping"})

        await session._on_datagram_received(event=event)

        cast(AsyncMock, mock_handler).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_datagram_received_no_handler_on_transport(
        self, session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        datagram_transport = await session.datagrams
        if hasattr(datagram_transport, "_on_datagram_received"):
            delattr(datagram_transport, "_on_datagram_received")
        event = Event(type=EventType.DATAGRAM_RECEIVED, data={"session_id": "session-1", "data": b"ping"})

        await session._on_datagram_received(event=event)

    @pytest.mark.asyncio
    async def test_on_max_data_updated(self, session: WebTransportSession) -> None:
        assert session._data_credit_event is not None
        assert not session._data_credit_event.is_set()
        event = Event(type=EventType.SESSION_MAX_DATA_UPDATED, data={"session_id": "session-1"})

        await session._on_max_data_updated(event=event)

        assert session._data_credit_event.is_set()

    @pytest.mark.asyncio
    async def test_on_max_streams_bidi_updated(self, session: WebTransportSession) -> None:
        assert session._bidi_stream_credit_event is not None
        assert not session._bidi_stream_credit_event.is_set()
        event = Event(type=EventType.SESSION_MAX_STREAMS_BIDI_UPDATED, data={"session_id": "session-1"})

        await session._on_max_streams_bidi_updated(event=event)

        assert session._bidi_stream_credit_event.is_set()

    @pytest.mark.asyncio
    async def test_on_max_streams_uni_updated(self, session: WebTransportSession) -> None:
        assert session._uni_stream_credit_event is not None
        assert not session._uni_stream_credit_event.is_set()
        event = Event(type=EventType.SESSION_MAX_STREAMS_UNI_UPDATED, data={"session_id": "session-1"})

        await session._on_max_streams_uni_updated(event=event)

        assert session._uni_stream_credit_event.is_set()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "handler_name, event_type",
        [
            ("_on_max_data_updated", EventType.SESSION_MAX_DATA_UPDATED),
            ("_on_max_streams_bidi_updated", EventType.SESSION_MAX_STREAMS_BIDI_UPDATED),
            ("_on_max_streams_uni_updated", EventType.SESSION_MAX_STREAMS_UNI_UPDATED),
        ],
    )
    async def test_on_max_credit_events_mismatched_id(
        self, session: WebTransportSession, handler_name: str, event_type: EventType
    ) -> None:
        handler = getattr(session, handler_name)
        event = Event(type=event_type, data={"session_id": "session-2"})

        await handler(event=event)

        if session._data_credit_event:
            assert not session._data_credit_event.is_set()
        if session._bidi_stream_credit_event:
            assert not session._bidi_stream_credit_event.is_set()
        if session._uni_stream_credit_event:
            assert not session._uni_stream_credit_event.is_set()

    @pytest.mark.asyncio
    async def test_diagnose_issues_no_connection_object(
        self, session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        session._state = SessionState.CONNECTED
        mocker.patch.object(session, "get_session_stats", return_value={})
        mocker.patch.object(WebTransportSession, "connection", new_callable=mock.PropertyMock, return_value=None)

        issues = await session.diagnose_issues()

        assert any("Underlying connection not available" in issue for issue in issues)

    @pytest.mark.asyncio
    async def test_diagnose_issues_no_datagram_transport(
        self, session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        session._state = SessionState.CONNECTED
        future: asyncio.Future[Any] = asyncio.Future()
        future.set_result(None)
        mocker.patch.object(WebTransportSession, "datagrams", new_callable=mocker.PropertyMock, return_value=future)

        issues = await session.diagnose_issues()

        assert not any("datagram" in issue for issue in issues)

    @pytest.mark.asyncio
    async def test_diagnose_issues_large_datagram_buffer(
        self, session: WebTransportSession, mock_datagram_transport_class: Any
    ) -> None:
        session._state = SessionState.CONNECTED

        datagram_transport = await session.datagrams
        cast(mock.MagicMock, datagram_transport.get_receive_buffer_size).return_value = 200
        issues = await session.diagnose_issues()

        assert any("Large datagram receive buffer" in issue for issue in issues)


class TestWebTransportSessionUninitialized:
    @pytest.fixture
    def mock_connection(self, mocker: MockerFixture) -> Any:
        return mocker.create_autospec(WebTransportConnection, instance=True)

    @pytest.fixture
    def uninitialized_session(self, mock_connection: Any) -> WebTransportSession:
        return WebTransportSession(connection=mock_connection, session_id="session-1")

    @pytest.mark.asyncio
    async def test_private_handlers_do_nothing_before_initialized(
        self, uninitialized_session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        mock_logger = mocker.patch("pywebtransport.session.session.logger")
        event = Event(type="", data={})

        await uninitialized_session._on_session_ready(event=event)
        await uninitialized_session._on_stream_opened(event=event)
        await uninitialized_session._on_max_data_updated(event=event)
        await uninitialized_session._on_max_streams_bidi_updated(event=event)
        await uninitialized_session._on_max_streams_uni_updated(event=event)
        uninitialized_session._sync_protocol_state()

        mock_logger.warning.assert_called_once_with(
            "Cannot sync state for session %s, session not initialized.", "session-1"
        )

    @pytest.mark.asyncio
    async def test_incoming_streams_raises_before_initialized(self, uninitialized_session: WebTransportSession) -> None:
        with pytest.raises(SessionError, match="WebTransportSession is not initialized"):
            async for _ in uninitialized_session.incoming_streams():
                pass

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name, args, match_str",
        [
            ("ready", (), "WebTransportSession is not initialized"),
            ("close", (), "WebTransportSession is not initialized"),
            ("wait_closed", (), "WebTransportSession is not initialized"),
            ("create_bidirectional_stream", (), r"Session session-1 not ready"),
            ("create_unidirectional_stream", (), r"Session session-1 not ready"),
        ],
    )
    async def test_methods_raise_before_initialized(
        self, uninitialized_session: WebTransportSession, method_name: str, args: tuple, match_str: str
    ) -> None:
        with pytest.raises(SessionError, match=match_str):
            await getattr(uninitialized_session, method_name)(*args)
