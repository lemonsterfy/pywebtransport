"""Unit tests for the pywebtransport.session.session module."""

import asyncio
from typing import Any

import pytest
from pytest_mock import MockerFixture

from pywebtransport import (
    ClientConfig,
    Event,
    EventType,
    SessionError,
    SessionState,
    StreamDirection,
    StreamError,
    TimeoutError,
    WebTransportSession,
    WebTransportStream,
)
from pywebtransport.connection import WebTransportConnection
from pywebtransport.protocol import WebTransportProtocolHandler
from pywebtransport.session import SessionStats
from pywebtransport.stream import StreamManager


@pytest.fixture
def mock_protocol_handler(mocker: MockerFixture) -> Any:
    handler = mocker.create_autospec(WebTransportProtocolHandler, instance=True)
    handler.on = mocker.MagicMock()
    handler.off = mocker.MagicMock()
    handler.get_session_info.return_value = None
    handler.create_webtransport_stream.return_value = 101
    return handler


@pytest.fixture
def mock_connection(mocker: MockerFixture, mock_protocol_handler: Any) -> Any:
    connection = mocker.create_autospec(WebTransportConnection, instance=True)
    connection.protocol_handler = mock_protocol_handler
    connection.config = object()
    connection.connection_id = "conn-123"
    connection.state.value = "connected"
    connection.is_connected = True
    connection.info = mocker.MagicMock()
    connection.info.last_activity = 1000.0
    return connection


@pytest.fixture
def mock_stream_manager(mocker: MockerFixture) -> Any:
    manager = mocker.create_autospec(StreamManager, instance=True)
    manager.create_bidirectional_stream = mocker.AsyncMock(
        return_value=mocker.create_autospec(WebTransportStream, instance=True)
    )
    manager.create_unidirectional_stream = mocker.AsyncMock(
        return_value=mocker.create_autospec(WebTransportStream, instance=True)
    )
    manager.shutdown = mocker.AsyncMock()
    manager.add_stream = mocker.AsyncMock()
    manager.get_stats = mocker.AsyncMock(return_value={"total_created": 0, "total_closed": 0})
    manager.get_all_streams = mocker.AsyncMock(return_value=[])
    mocker.patch("pywebtransport.session.session.StreamManager.create", return_value=manager)
    return manager


@pytest.fixture
def mock_datagram_stream(mocker: MockerFixture) -> Any:
    mock_class = mocker.patch("pywebtransport.session.session.WebTransportDatagramDuplexStream", autospec=True)
    mock_instance = mock_class.return_value
    mock_instance.close = mocker.AsyncMock()
    mock_instance.stats = {"datagrams_sent": 0, "datagrams_received": 0}
    mock_instance.get_receive_buffer_size.return_value = 0
    return mock_class


@pytest.fixture
def session(
    mock_connection: Any,
    mock_stream_manager: Any,
    mock_datagram_stream: Any,
    mocker: MockerFixture,
) -> WebTransportSession:
    mocker.patch("pywebtransport.session.session.get_timestamp", return_value=1000.0)
    session_instance = WebTransportSession(connection=mock_connection, session_id="session-1")
    session_instance._ready_event = mocker.create_autospec(asyncio.Event, instance=True)
    session_instance._closed_event = mocker.create_autospec(asyncio.Event, instance=True)
    session_instance._incoming_streams = mocker.create_autospec(asyncio.Queue, instance=True)
    return session_instance


class TestSessionStats:
    def test_properties(self) -> None:
        stats = SessionStats(session_id="session-1", created_at=1000.0)
        assert stats.uptime == 0.0
        assert stats.active_streams == 0

        stats.ready_at = 1100.0
        stats.streams_created = 10
        stats.streams_closed = 4

        stats.closed_at = 1300.0
        assert stats.uptime == 200.0
        assert stats.active_streams == 6

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


@pytest.mark.asyncio
class TestWebTransportSession:
    async def test_initialization(
        self,
        session: Any,
        mock_connection: Any,
        mock_protocol_handler: Any,
        mocker: MockerFixture,
    ) -> None:
        assert session.session_id == "session-1"
        assert session.state == SessionState.CONNECTING
        assert session.connection is mock_connection
        assert session.protocol_handler is mock_protocol_handler
        expected_calls = [
            mocker.call(EventType.SESSION_READY, session._on_session_ready),
            mocker.call(EventType.SESSION_CLOSED, session._on_session_closed),
            mocker.call(EventType.STREAM_OPENED, session._on_stream_opened),
            mocker.call(EventType.DATAGRAM_RECEIVED, session._on_datagram_received),
        ]
        mock_protocol_handler.on.assert_has_calls(expected_calls, any_order=True)
        mock_protocol_handler.get_session_info.assert_called_once_with("session-1")

    async def test_initialization_no_protocol_handler(self, mocker: MockerFixture, mock_connection: Any) -> None:
        mock_logger = mocker.patch("pywebtransport.session.session.logger")
        mock_connection.protocol_handler = None
        session = WebTransportSession(connection=mock_connection, session_id="session-1")
        assert session.protocol_handler is None
        mock_logger.warning.assert_called_with("No protocol handler available for session session-1")
        await session.close()

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
        mock_event_class = mocker.patch("pywebtransport.session.session.asyncio.Event", autospec=True)

        session = WebTransportSession(connection=mock_connection, session_id="session-1")

        assert session.state == SessionState.CONNECTED
        assert session.is_ready
        assert session.path == "/synced"
        assert session.headers == {"x-synced": "true"}
        mock_event_class.return_value.set.assert_called_once()

    async def test_properties(self, session: Any) -> None:
        session._state = SessionState.CONNECTED
        assert session.is_ready
        assert not session.is_closed

        session._state = SessionState.CLOSED
        assert not session.is_ready
        assert session.is_closed

    async def test_str_representation(self, mock_connection: Any, mocker: MockerFixture) -> None:
        long_session_id = "long-session-id-that-will-be-truncated"
        session = WebTransportSession(connection=mock_connection, session_id=long_session_id)
        mocker.patch("pywebtransport.session.session.format_duration", return_value="1m 30s")
        session._stats.streams_created = 8
        session._stats.streams_closed = 2
        session._stats.datagrams_sent = 100
        session._stats.datagrams_received = 200
        session._path = "/test"

        assert str(session) == (
            "Session(long-session..., state=connecting, path=/test, " "uptime=1m 30s, streams=6/8, datagrams=100/200)"
        )

    async def test_datagrams_property_lazy_creation(self, session: Any, mock_datagram_stream: Any) -> None:
        assert session._datagrams is None
        _ = session.datagrams
        mock_datagram_stream.assert_called_once_with(session=session)

    async def test_datagrams_property_when_closed(self, session: Any) -> None:
        session._state = SessionState.CLOSED
        with pytest.raises(SessionError, match="is closed, cannot access datagrams"):
            _ = session.datagrams

    async def test_ready_already_connected(self, session: Any) -> None:
        session._state = SessionState.CONNECTED
        await session.ready(timeout=0.1)
        session._ready_event.wait.assert_not_awaited()

    async def test_ready_waits_for_event(self, session: Any) -> None:
        session._state = SessionState.CONNECTING
        await session.ready()
        session._ready_event.wait.assert_awaited_once()

    async def test_ready_timeout(self, session: Any) -> None:
        session._state = SessionState.CONNECTING
        session._ready_event.wait.side_effect = asyncio.TimeoutError()
        with pytest.raises(TimeoutError, match="Session ready timeout"):
            await session.ready(timeout=0.01)

    async def test_wait_closed(self, session: Any) -> None:
        await session.wait_closed()
        session._closed_event.wait.assert_awaited_once()

    async def test_close_session(
        self,
        session: Any,
        mock_stream_manager: Any,
        mock_protocol_handler: Any,
        mocker: MockerFixture,
    ) -> None:
        _ = session.datagrams
        mock_datagram_instance = session._datagrams
        mocker.patch("pywebtransport.session.session.get_timestamp", return_value=2000.0)
        await session.close(code=123, reason="test")

        assert session.state == SessionState.CLOSED
        assert session._closed_at == 2000.0
        assert session.is_closed
        mock_stream_manager.shutdown.assert_awaited_once()
        assert session._datagrams is not None
        mock_datagram_instance.close.assert_awaited_once()
        session._incoming_streams.put.assert_awaited_once_with(None)
        mock_protocol_handler.close_webtransport_session.assert_called_once_with("session-1", code=123, reason="test")
        session._closed_event.set.assert_called_once()
        mock_protocol_handler.off.assert_called()

    async def test_close_without_datagram_stream(self, session: Any, mock_datagram_stream: Any) -> None:
        assert session._datagrams is None
        await session.close()
        mock_datagram_stream.return_value.close.assert_not_awaited()

    async def test_close_idempotent(self, session: Any, mock_protocol_handler: Any) -> None:
        session._state = SessionState.CONNECTING
        await session.close()
        assert mock_protocol_handler.close_webtransport_session.call_count == 1
        await session.close()
        assert mock_protocol_handler.close_webtransport_session.call_count == 1
        assert session.state == SessionState.CLOSED

    async def test_create_stream_not_ready(self, session: Any) -> None:
        session._state = SessionState.CONNECTING
        with pytest.raises(SessionError, match=r"Session session-1 not ready, current state: connecting"):
            await session.create_bidirectional_stream()

    @pytest.mark.parametrize("method_name", ["create_bidirectional_stream", "create_unidirectional_stream"])
    async def test_create_stream_no_connection(self, session: Any, method_name: str, mocker: MockerFixture) -> None:
        session._state = SessionState.CONNECTED
        session._connection = mocker.MagicMock(return_value=None)
        with pytest.raises(SessionError, match="has no active connection"):
            await getattr(session, method_name)()

    async def test_create_stream_protocol_failure(self, session: Any, mock_stream_manager: Any) -> None:
        session._state = SessionState.CONNECTED
        mock_stream_manager.create_bidirectional_stream.side_effect = StreamError(
            "Protocol handler failed to create stream: Kaboom"
        )
        with pytest.raises(StreamError, match="Protocol handler failed to create stream: Kaboom"):
            await session.create_bidirectional_stream()

    @pytest.mark.parametrize("method_name", ["create_bidirectional_stream", "create_unidirectional_stream"])
    async def test_create_stream_default_timeout(
        self, session: Any, mock_stream_manager: Any, method_name: str
    ) -> None:
        session._state = SessionState.CONNECTED
        manager_method = getattr(mock_stream_manager, method_name)
        manager_method.side_effect = asyncio.TimeoutError()

        with pytest.raises(StreamError, match="Timed out creating .* stream after 10.0s"):
            await getattr(session, method_name)()

    @pytest.mark.parametrize("method_name", ["create_bidirectional_stream", "create_unidirectional_stream"])
    async def test_create_stream_with_client_config(
        self, session: Any, mock_connection: Any, mock_stream_manager: Any, method_name: str
    ) -> None:
        session._state = SessionState.CONNECTED
        mock_connection.config = ClientConfig(stream_creation_timeout=0.01)
        manager_method = getattr(mock_stream_manager, method_name)
        manager_method.side_effect = asyncio.TimeoutError()

        with pytest.raises(StreamError, match="Timed out creating .* stream after 0.01s"):
            await getattr(session, method_name)()

    async def test_incoming_streams(self, session: Any, mocker: MockerFixture) -> None:
        session._state = SessionState.CONNECTED
        mock_stream1 = mocker.MagicMock()
        mock_stream2 = mocker.MagicMock()
        session._incoming_streams.get.side_effect = [mock_stream1, mock_stream2, None]

        streams = [s async for s in session.incoming_streams()]

        assert streams == [mock_stream1, mock_stream2]
        session._state = SessionState.CLOSED

    async def test_incoming_streams_timeout(self, session: Any, mocker: MockerFixture) -> None:
        session._state = SessionState.CONNECTED
        mock_stream = mocker.MagicMock()
        session._incoming_streams.get.side_effect = [asyncio.TimeoutError, mock_stream, None]

        streams = [s async for s in session.incoming_streams()]
        assert streams == [mock_stream]
        assert session._incoming_streams.get.call_count == 3

    async def test_on_session_ready(self, session: Any) -> None:
        event_data = {
            "session_id": "session-1",
            "path": "/ready",
            "headers": {"content-type": "application/json"},
            "stream_id": 101,
        }
        event = Event(type=EventType.SESSION_READY, data=event_data)
        await session._on_session_ready(event)
        assert session.is_ready
        assert session.path == "/ready"
        assert session.headers == {"content-type": "application/json"}
        session._ready_event.set.assert_called_once()

    async def test_on_session_closed_remotely(self, session: Any, mocker: MockerFixture) -> None:
        close_mock = mocker.patch.object(session, "close", new_callable=mocker.AsyncMock)
        event_data = {"session_id": "session-1", "code": 404, "reason": "Not Found"}
        event = Event(type=EventType.SESSION_CLOSED, data=event_data)
        session._state = SessionState.CONNECTED
        await session._on_session_closed(event)
        close_mock.assert_awaited_once_with(code=404, reason="Not Found")

    async def test_on_session_closed_remotely_when_already_closing(self, session: Any, mocker: MockerFixture) -> None:
        close_mock = mocker.patch.object(session, "close", new_callable=mocker.AsyncMock)
        event = Event(type=EventType.SESSION_CLOSED, data={"session_id": "session-1"})
        session._state = SessionState.CLOSING
        await session._on_session_closed(event)
        close_mock.assert_not_awaited()

    async def test_on_stream_opened(self, session: Any, mock_stream_manager: Any, mocker: MockerFixture) -> None:
        mock_cls = mocker.patch("pywebtransport.session.session.WebTransportStream", autospec=True)
        event = Event(
            type=EventType.STREAM_OPENED,
            data={"session_id": "session-1", "stream_id": 2, "direction": StreamDirection.BIDIRECTIONAL},
        )
        await session._on_stream_opened(event)
        mock_cls.assert_called_once_with(session=session, stream_id=2)
        mock_stream_manager.add_stream.assert_awaited_once_with(mock_cls.return_value)
        session._incoming_streams.put.assert_awaited_once_with(mock_cls.return_value)

    async def test_on_stream_opened_handles_exception(
        self, session: Any, mock_stream_manager: Any, mocker: MockerFixture
    ) -> None:
        mocker.patch("pywebtransport.session.session.WebTransportStream", autospec=True)
        event = Event(
            type=EventType.STREAM_OPENED,
            data={"session_id": "session-1", "stream_id": 2, "direction": StreamDirection.BIDIRECTIONAL},
        )
        mock_stream_manager.add_stream.side_effect = ValueError("Test error")

        await session._on_stream_opened(event)

        assert session._stats.stream_errors == 1
        session._incoming_streams.put.assert_not_awaited()

    @pytest.mark.parametrize(
        "bad_data",
        [
            {"session_id": "session-99"},
            {"session_id": "session-1", "stream_id": None},
            {"session_id": "session-1", "direction": None},
            "not a dict",
        ],
    )
    async def test_on_stream_opened_invalid_data(self, session: Any, mock_stream_manager: Any, bad_data: Any) -> None:
        event = Event(type=EventType.STREAM_OPENED, data=bad_data)
        await session._on_stream_opened(event)
        mock_stream_manager.add_stream.assert_not_awaited()
        session._incoming_streams.put.assert_not_awaited()

    async def test_on_datagram_received(self, session: Any, mocker: MockerFixture) -> None:
        _ = session.datagrams
        mock_handler = mocker.patch.object(session.datagrams, "_on_datagram_received")
        event = Event(type=EventType.DATAGRAM_RECEIVED, data={"session_id": "session-1", "data": b"ping"})

        await session._on_datagram_received(event)
        mock_handler.assert_awaited_once_with(event)

    async def test_on_datagram_received_invalid_event(self, session: Any, mocker: MockerFixture) -> None:
        _ = session.datagrams
        mock_handler = mocker.patch.object(session.datagrams, "_on_datagram_received")
        event = Event(type=EventType.DATAGRAM_RECEIVED, data={"session_id": "other-session", "data": b"ping"})
        await session._on_datagram_received(event)
        mock_handler.assert_not_awaited()

    async def test_on_datagram_received_no_handler_on_stream(self, session: Any, mocker: MockerFixture) -> None:
        _ = session.datagrams
        if hasattr(session.datagrams, "_on_datagram_received"):
            delattr(session.datagrams, "_on_datagram_received")
        event = Event(type=EventType.DATAGRAM_RECEIVED, data={"session_id": "session-1", "data": b"ping"})
        await session._on_datagram_received(event)

    async def test_get_summary(self, session: Any, mocker: MockerFixture) -> None:
        stats_data = {"bytes_sent": 1024, "datagrams_sent": 100, "stream_errors": 5}
        mocker.patch.object(session, "get_session_stats", return_value=stats_data)
        session._path = "/summary"
        summary = await session.get_summary()

        assert summary["session_id"] == "session-1"
        assert summary["path"] == "/summary"
        assert summary["data"]["bytes_sent"] == 1024
        assert summary["errors"]["stream_errors"] == 5

    async def test_get_summary_no_stats(self, session: Any, mocker: MockerFixture) -> None:
        mocker.patch.object(session, "get_session_stats", return_value={})
        summary = await session.get_summary()
        assert summary["streams"]["total_created"] == 0
        assert summary["data"]["datagrams_sent"] == 0
        assert summary["errors"]["stream_errors"] == 0

    async def test_debug_state(
        self, session: Any, mock_stream_manager: Any, mock_connection: Any, mocker: MockerFixture
    ) -> None:
        mock_bidi_stream = mocker.create_autospec(WebTransportStream, instance=True)
        mock_bidi_stream.stream_id = 2
        mock_bidi_stream.state.value = "open"
        mock_bidi_stream.direction = "bidirectional"
        mock_bidi_stream.bytes_sent = 100
        mock_bidi_stream.bytes_received = 200
        mock_stream_manager.get_all_streams.return_value = [mock_bidi_stream]
        _ = session.datagrams
        session.datagrams.get_receive_buffer_size.return_value = 10

        debug_info = await session.debug_state()

        assert debug_info["session"]["id"] == "session-1"
        assert debug_info["streams"][0]["stream_id"] == 2
        assert debug_info["datagrams"]["receive_buffer"] == 10
        assert debug_info["connection"]["id"] == "conn-123"

    async def test_debug_state_no_connection(self, session: Any, mock_stream_manager: Any) -> None:
        session._connection = lambda: None
        debug_info = await session.debug_state()
        assert debug_info["connection"]["id"] is None
        assert debug_info["connection"]["state"] == "N/A"

    async def test_diagnose_issues(self, session: Any, mocker: MockerFixture) -> None:
        session._state = SessionState.CONNECTING
        issues = await session.diagnose_issues()
        assert "Session stuck in connecting state" in issues

        session._state = SessionState.CONNECTED
        stats = {"streams_created": 100, "stream_errors": 15}
        mocker.patch.object(session, "get_session_stats", return_value=stats)
        issues = await session.diagnose_issues()
        assert "High error rate: 15/100" in issues

        stats = {"uptime": 4000, "active_streams": 0}
        mocker.patch.object(session, "get_session_stats", return_value=stats)
        issues = await session.diagnose_issues()
        assert "Session appears stale (long uptime with no active streams)" in issues

    async def test_monitor_health(self, session: Any, mocker: MockerFixture) -> None:
        mock_sleep = mocker.patch("pywebtransport.session.session.asyncio.sleep")
        mock_sleep.side_effect = [None, asyncio.CancelledError]
        mock_logger = mocker.patch("pywebtransport.session.session.logger")

        await session.monitor_health(check_interval=10)

        assert mock_sleep.call_count == 2
        mock_logger.debug.assert_any_call("Health monitoring cancelled for session session-1")

    async def test_monitor_health_handles_exception(self, session: Any, mocker: MockerFixture) -> None:
        mock_sleep = mocker.patch("pywebtransport.session.session.asyncio.sleep", side_effect=ValueError("Test Error"))
        mock_logger = mocker.patch("pywebtransport.session.session.logger")

        await session.monitor_health()

        mock_sleep.assert_awaited_once()
        mock_logger.error.assert_called_once_with("Session health monitoring error: Test Error")

    async def test_monitor_health_inactive_warning(self, session: Any, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.session.session.get_timestamp", return_value=1400.0)
        assert session.connection is not None
        session.connection.info.last_activity = 1000.0
        mock_sleep = mocker.patch("pywebtransport.session.session.asyncio.sleep", side_effect=asyncio.CancelledError)
        mock_logger = mocker.patch("pywebtransport.session.session.logger")

        await session.monitor_health()

        mock_sleep.assert_awaited_once()
        mock_logger.warning.assert_called_once_with("Session session-1 appears inactive (no connection activity)")
