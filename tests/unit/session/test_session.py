"""Unit tests for the pywebtransport.session.session module."""

import asyncio
import weakref
from collections.abc import AsyncGenerator
from typing import Any, cast
from unittest import mock
from unittest.mock import AsyncMock, Mock, PropertyMock

import pytest
from pytest_asyncio import fixture as asyncio_fixture
from pytest_mock import MockerFixture

from pywebtransport import (
    ClientConfig,
    Event,
    ServerConfig,
    SessionError,
    StreamError,
    TimeoutError,
    WebTransportReceiveStream,
    WebTransportSession,
    WebTransportStream,
)
from pywebtransport.connection import WebTransportConnection
from pywebtransport.exceptions import FlowControlError
from pywebtransport.protocol import WebTransportProtocolHandler
from pywebtransport.session import SessionDiagnostics, SessionStats
from pywebtransport.types import EventType, SessionState, StreamDirection


class TestSessionDiagnostics:
    @pytest.mark.parametrize(
        "diag_kwargs, mock_uptime, expected_issue_part",
        [
            (
                {"state": SessionState.CONNECTING},
                None,
                "Session stuck in connecting state",
            ),
            (
                {"stats": SessionStats(session_id="s1", created_at=0, streams_created=60, stream_errors=10)},
                None,
                "High error rate",
            ),
            (
                {"stats": SessionStats(session_id="s1", created_at=0, ready_at=1)},
                4000,
                "Session appears stale",
            ),
            ({"is_connection_active": False}, None, "Underlying connection not available"),
            ({"datagram_receive_buffer_size": 200}, None, "Large datagram receive buffer"),
            ({}, None, None),
        ],
    )
    def test_issues_property(
        self,
        mocker: MockerFixture,
        diag_kwargs: dict[str, Any],
        mock_uptime: float | None,
        expected_issue_part: str | None,
    ) -> None:
        if "stats" not in diag_kwargs:
            diag_kwargs["stats"] = SessionStats(session_id="s1", created_at=0)
        if "state" not in diag_kwargs:
            diag_kwargs["state"] = SessionState.CONNECTED
        if "is_connection_active" not in diag_kwargs:
            diag_kwargs["is_connection_active"] = True
        if "datagram_receive_buffer_size" not in diag_kwargs:
            diag_kwargs["datagram_receive_buffer_size"] = 0
        if "send_credit_available" not in diag_kwargs:
            diag_kwargs["send_credit_available"] = 1024
        if "receive_credit_available" not in diag_kwargs:
            diag_kwargs["receive_credit_available"] = 1024

        if mock_uptime is not None:
            mocker.patch.object(SessionStats, "uptime", new_callable=PropertyMock, return_value=mock_uptime)

        diagnostics = SessionDiagnostics(**diag_kwargs)
        issues = diagnostics.issues

        if expected_issue_part:
            assert any(expected_issue_part in issue for issue in issues)
        else:
            assert not issues


class TestSessionStats:
    def test_properties(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.session.session.get_timestamp", return_value=1200.0)
        stats = SessionStats(session_id="session-1", created_at=1000.0)
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

    def test_uptime_not_ready(self) -> None:
        stats = SessionStats(session_id="session-1", created_at=1000.0)

        assert stats.ready_at is None
        assert stats.uptime == 0.0


@pytest.mark.asyncio
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

        mock_conn_stats = mocker.MagicMock()
        mock_conn_stats.last_activity = 1000.0
        mock_conn_diags = mocker.MagicMock()
        mock_conn_diags.stats = mock_conn_stats
        type(connection).diagnostics = PropertyMock(return_value=mock_conn_diags)

        connection.on = mocker.MagicMock()
        connection.off = mocker.MagicMock()
        connection.once = mocker.MagicMock()
        connection.close = mocker.AsyncMock()
        connection.get_session_info = mocker.Mock(return_value=None)
        return connection

    @pytest.fixture
    def mock_datagram_transport_class(self, mocker: MockerFixture) -> Any:
        mock_class = mocker.patch("pywebtransport.session.session.WebTransportDatagramTransport", autospec=True)
        mock_instance = mock_class.return_value

        mock_instance.initialize = AsyncMock()
        mock_instance.close = AsyncMock()
        mock_datagram_stats = mocker.MagicMock()
        mock_datagram_stats.datagrams_sent = 0
        mock_datagram_stats.datagrams_received = 0
        mock_datagram_diags = mocker.MagicMock()
        mock_datagram_diags.stats = mock_datagram_stats
        type(mock_instance).diagnostics = PropertyMock(return_value=mock_datagram_diags)
        mock_instance.get_receive_buffer_size = Mock(return_value=0)
        mock_instance.receive_from_protocol = AsyncMock()
        return mock_class

    @pytest.fixture
    def mock_protocol_handler(self, mocker: MockerFixture) -> Any:
        handler = mocker.create_autospec(WebTransportProtocolHandler, instance=True)
        handler.on = mocker.MagicMock()
        handler.off = mocker.MagicMock()
        handler.create_webtransport_stream.return_value = 101
        handler.close_webtransport_session = mocker.Mock()
        handler.send_webtransport_datagram = mocker.Mock()
        handler.quic_connection = mocker.MagicMock()
        type(handler.quic_connection)._max_datagram_size = PropertyMock(return_value=1200)
        return handler

    @pytest.fixture
    def mock_stream_manager_class(self, mocker: MockerFixture) -> Any:
        manager_instance = mocker.create_autospec(WebTransportSession, instance=True)
        manager_instance.__aenter__ = mocker.AsyncMock(return_value=manager_instance)
        manager_instance.__aexit__ = mocker.AsyncMock()
        manager_instance.create_bidirectional_stream = mocker.AsyncMock(
            return_value=mocker.create_autospec(WebTransportStream, instance=True)
        )
        manager_instance.create_unidirectional_stream = mocker.AsyncMock(
            return_value=mocker.create_autospec(WebTransportStream, instance=True)
        )
        manager_instance.shutdown = mocker.AsyncMock()
        manager_instance.add_stream = mocker.AsyncMock()
        manager_instance.get_stats = mocker.AsyncMock(return_value={"total_created": 0, "total_closed": 0})
        return mocker.patch(
            "pywebtransport.session.session.StreamManager",
            return_value=manager_instance,
        )

    @asyncio_fixture
    async def session(
        self,
        mock_connection: Any,
        mock_stream_manager_class: Any,
        mock_datagram_transport_class: Any,
    ) -> AsyncGenerator[WebTransportSession, None]:
        session_instance = WebTransportSession(
            connection=mock_connection,
            session_id="session-1",
            path="/test",
            headers={"x-test": "true"},
        )
        await session_instance.initialize()
        session_instance._incoming_streams = mock.create_autospec(asyncio.Queue, instance=True)

        yield session_instance

        if not session_instance.is_closed and session_instance.stream_manager:
            try:
                await session_instance.close(close_connection=False)
            except (ValueError, ExceptionGroup, RuntimeError, IOError):
                pass

    async def test_async_context_manager(self, mock_connection: Any, mocker: MockerFixture) -> None:
        session = WebTransportSession(connection=mock_connection, session_id="session-1")
        mocker.patch(
            "pywebtransport.session.session.StreamManager",
            return_value=mocker.AsyncMock(),
        )
        ready_mock = mocker.patch.object(session, "ready", new_callable=mocker.AsyncMock)
        close_mock = mocker.patch.object(session, "close", new_callable=mocker.AsyncMock)

        async def initialize_side_effect(*args: Any, **kwargs: Any) -> None:
            session._is_initialized = True

        initialize_mock = mocker.patch.object(
            session,
            "initialize",
            new_callable=mocker.AsyncMock,
            side_effect=initialize_side_effect,
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

    async def test_close_aggregates_single_parallel_with_serial_group(
        self, session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        await session.create_datagram_transport()
        err_parallel = IOError("Parallel Error")
        err_serial_group = ExceptionGroup("Serial Group", [ValueError("V"), TypeError("T")])

        mocker.patch.object(session._datagram_transport, "close", side_effect=err_parallel)
        assert session.protocol_handler is not None
        mocker.patch.object(
            session.protocol_handler,
            "close_webtransport_session",
            side_effect=err_serial_group,
        )

        with pytest.raises(ExceptionGroup) as exc_info:
            await session.close(close_connection=False)

        assert len(exc_info.value.exceptions) == 3
        expected_exceptions = (err_parallel,) + err_serial_group.exceptions
        assert set(exc_info.value.exceptions) == set(expected_exceptions)
        assert session.is_closed

    async def test_close_handles_datagram_transport_error(
        self, session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        datagram_transport = await session.create_datagram_transport()
        err = IOError("Datagram transport failed")
        mocker.patch.object(datagram_transport, "close", side_effect=err)

        with pytest.raises(ExceptionGroup) as exc_info:
            await session.close(close_connection=False)

        assert exc_info.value.exceptions == (err,)
        assert session.is_closed

    async def test_close_handles_parallel_and_serial_errors(
        self, session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        datagram_transport = await session.create_datagram_transport()
        err_parallel = IOError("Datagram transport failed")
        err_serial = RuntimeError("Protocol handler failed")
        mocker.patch.object(datagram_transport, "close", side_effect=err_parallel)
        assert session.protocol_handler is not None
        mocker.patch.object(
            session.protocol_handler,
            "close_webtransport_session",
            side_effect=err_serial,
        )

        with pytest.raises(ExceptionGroup) as exc_info:
            await session.close(close_connection=False)

        assert set(exc_info.value.exceptions) == {err_parallel, err_serial}
        assert session.is_closed

    async def test_close_handles_protocol_handler_error(self, session: WebTransportSession) -> None:
        err = RuntimeError("Protocol handler failed")
        assert session.protocol_handler is not None
        cast(Mock, session.protocol_handler.close_webtransport_session).side_effect = err

        with pytest.raises(RuntimeError, match="Protocol handler failed"):
            await session.close(close_connection=False)

        assert session.is_closed

    async def test_close_handles_single_parallel_error_only(
        self, session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        datagram_transport = await session.create_datagram_transport()
        err_parallel = IOError("Datagram transport failed")
        mocker.patch.object(datagram_transport, "close", side_effect=err_parallel)
        assert session.protocol_handler is not None
        mocker.patch.object(session.protocol_handler, "close_webtransport_session")

        with pytest.raises(ExceptionGroup) as exc_info:
            await session.close(close_connection=False)

        assert len(exc_info.value.exceptions) == 1
        assert exc_info.value.exceptions[0] is err_parallel
        assert session.is_closed

    @pytest.mark.parametrize("initial_state", [SessionState.CONNECTING, SessionState.CLOSING, SessionState.CLOSED])
    async def test_close_idempotent(
        self,
        session: WebTransportSession,
        mock_protocol_handler: Any,
        initial_state: SessionState,
    ) -> None:
        session._state = initial_state
        is_closing_or_closed = initial_state in (
            SessionState.CLOSING,
            SessionState.CLOSED,
        )

        await session.close(close_connection=False)

        if is_closing_or_closed:
            mock_protocol_handler.close_webtransport_session.assert_not_called()
        else:
            mock_protocol_handler.close_webtransport_session.assert_called_once()

        expected_final_state = SessionState.CLOSED if initial_state == SessionState.CONNECTING else initial_state
        assert session.state == expected_final_state

    async def test_close_with_connection_already_closed(
        self, session: WebTransportSession, mock_connection: Any
    ) -> None:
        mock_connection.is_closed = True
        await session.close(close_connection=True)
        cast(AsyncMock, mock_connection.close).assert_not_awaited()

    async def test_close_without_datagram_transport(
        self, session: WebTransportSession, mock_datagram_transport_class: Any
    ) -> None:
        assert not hasattr(session, "_datagram_transport")
        await session.close(close_connection=False)
        cast(AsyncMock, mock_datagram_transport_class.return_value.close).assert_not_awaited()

    async def test_connection_property_is_none(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        mock_ref = mocker.MagicMock(spec=weakref.ref)
        mock_ref.return_value = None
        session._connection = mock_ref

        assert session.connection is None

    async def test_create_bidirectional_stream_on_protocol_flow_control_no_event(
        self, session: WebTransportSession, mock_protocol_handler: Any
    ) -> None:
        mock_protocol_handler.create_webtransport_stream.side_effect = FlowControlError(message="No stream credit")
        session._bidi_stream_credit_event = None
        with pytest.raises(FlowControlError, match="No stream credit"):
            await session._create_stream_on_protocol(is_unidirectional=False)

    async def test_create_datagram_transport(
        self,
        session: WebTransportSession,
        mock_protocol_handler: Any,
        mock_datagram_transport_class: Any,
    ) -> None:
        transport = await session.create_datagram_transport()

        mock_datagram_transport_class.assert_called_once()
        call_args = mock_datagram_transport_class.call_args.kwargs
        assert call_args["session_id"] == "session-1"
        assert call_args["max_datagram_size"] == 1200
        assert callable(call_args["datagram_sender"])

        call_args["datagram_sender"](b"test")
        mock_protocol_handler.send_webtransport_datagram.assert_called_once_with(session_id="session-1", data=b"test")

        assert transport is mock_datagram_transport_class.return_value
        cast(AsyncMock, transport.initialize).assert_awaited_once()

    async def test_create_datagram_transport_idempotent(self, session: WebTransportSession) -> None:
        transport1 = await session.create_datagram_transport()
        transport2 = await session.create_datagram_transport()
        assert transport1 is transport2

    async def test_create_datagram_transport_no_protocol_handler(self, session: WebTransportSession) -> None:
        session._protocol_handler = None
        with pytest.raises(SessionError, match="Protocol handler is not available"):
            await session.create_datagram_transport()

    async def test_create_datagram_transport_when_closed(self, session: WebTransportSession) -> None:
        session._state = SessionState.CLOSED
        with pytest.raises(SessionError, match="is closed"):
            await session.create_datagram_transport()

    async def test_create_stream_not_ready(self, session: WebTransportSession) -> None:
        session._state = SessionState.CONNECTING
        with pytest.raises(SessionError, match=r"Session session-1 not ready, current state: connecting"):
            await session.create_bidirectional_stream()

    async def test_create_stream_on_protocol_generic_exception(
        self, session: WebTransportSession, mock_protocol_handler: Any
    ) -> None:
        mock_protocol_handler.create_webtransport_stream.side_effect = ValueError("Generic Error")
        with pytest.raises(StreamError, match="Protocol handler failed to create stream: Generic Error"):
            await session._create_stream_on_protocol(is_unidirectional=False)
        assert session._stats.stream_errors == 1

    @pytest.mark.parametrize("is_unidirectional", [False, True])
    async def test_create_stream_on_protocol_flow_control(
        self,
        session: WebTransportSession,
        mock_protocol_handler: Any,
        is_unidirectional: bool,
        mocker: MockerFixture,
    ) -> None:
        stream_id = 101
        mock_protocol_handler.create_webtransport_stream.side_effect = [
            FlowControlError(message="No stream credit"),
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

    async def test_create_stream_on_protocol_no_handler(self, session: WebTransportSession) -> None:
        session._protocol_handler = None
        with pytest.raises(SessionError, match="Protocol handler is not available"):
            await session._create_stream_on_protocol(is_unidirectional=False)

    async def test_create_stream_protocol_failure(self, session: WebTransportSession) -> None:
        session._state = SessionState.CONNECTED
        assert session.stream_manager is not None
        cast(AsyncMock, session.stream_manager.create_bidirectional_stream).side_effect = StreamError(message="Kaboom")
        with pytest.raises(StreamError, match="Kaboom"):
            await session.create_bidirectional_stream()

    @pytest.mark.parametrize("method_name", ["create_bidirectional_stream", "create_unidirectional_stream"])
    async def test_create_stream_raises_timeout_error(self, session: WebTransportSession, method_name: str) -> None:
        await session.initialize()
        session._state = SessionState.CONNECTED
        assert session.stream_manager is not None
        manager_method = getattr(session.stream_manager, method_name)
        cast(AsyncMock, manager_method).side_effect = asyncio.TimeoutError
        with pytest.raises(StreamError, match="Timed out creating .* stream"):
            await getattr(session, method_name)()
        assert session._stats.stream_errors == 1

    @pytest.mark.parametrize("method_name", ["create_bidirectional_stream", "create_unidirectional_stream"])
    async def test_create_stream_timeout_logic_branches(
        self, session: WebTransportSession, method_name: str, mocker: MockerFixture
    ) -> None:
        await session.initialize()
        session._state = SessionState.CONNECTED
        assert session.stream_manager is not None
        manager_method = getattr(session.stream_manager, method_name)
        mock_stream = mocker.create_autospec(WebTransportStream, instance=True)
        mock_stream.initialize = mocker.AsyncMock()
        cast(AsyncMock, manager_method).return_value = mock_stream
        await getattr(session, method_name)(timeout=0.01)
        await getattr(session, method_name)()
        session._config = ServerConfig()
        await getattr(session, method_name)()

    @pytest.mark.parametrize("method_name", ["create_bidirectional_stream", "create_unidirectional_stream"])
    async def test_create_stream_with_client_config(self, session: WebTransportSession, method_name: str) -> None:
        session._state = SessionState.CONNECTED
        session._config = ClientConfig(stream_creation_timeout=0.01)
        assert session.stream_manager is not None
        manager_method = getattr(session.stream_manager, method_name)
        cast(AsyncMock, manager_method).side_effect = asyncio.TimeoutError
        with pytest.raises(StreamError, match="Timed out creating .* stream after 0.01s"):
            await getattr(session, method_name)()

    @pytest.mark.parametrize("method_name", ["create_bidirectional_stream", "create_unidirectional_stream"])
    async def test_create_stream_with_explicit_timeout(self, session: WebTransportSession, method_name: str) -> None:
        session._state = SessionState.CONNECTED
        assert session.stream_manager is not None
        manager_method = getattr(session.stream_manager, method_name)
        cast(AsyncMock, manager_method).side_effect = asyncio.TimeoutError
        with pytest.raises(StreamError, match="Timed out creating .* stream after 0.1s"):
            await getattr(session, method_name)(timeout=0.1)

    @pytest.mark.parametrize("method_name", ["create_bidirectional_stream", "create_unidirectional_stream"])
    async def test_create_stream_default_timeout(self, session: WebTransportSession, method_name: str) -> None:
        session._state = SessionState.CONNECTED
        session._config = ServerConfig()
        assert session.stream_manager is not None
        manager_method = getattr(session.stream_manager, method_name)
        cast(AsyncMock, manager_method).side_effect = asyncio.TimeoutError
        with pytest.raises(StreamError, match="Timed out creating .* stream after 10.0s"):
            await getattr(session, method_name)()

    @pytest.mark.parametrize("method_name", ["create_bidirectional_stream", "create_unidirectional_stream"])
    async def test_create_stream_no_connection(
        self, session: WebTransportSession, method_name: str, mocker: MockerFixture
    ) -> None:
        session._state = SessionState.CONNECTED
        mocker.patch.object(WebTransportSession, "connection", new_callable=mock.PropertyMock, return_value=None)
        with pytest.raises(SessionError, match="has no active connection"):
            await getattr(session, method_name)()

    @pytest.mark.parametrize("method_name", ["create_bidirectional_stream", "create_unidirectional_stream"])
    async def test_create_stream_no_stream_manager(self, session: WebTransportSession, method_name: str) -> None:
        session._state = SessionState.CONNECTED
        session.stream_manager = None
        with pytest.raises(SessionError, match="StreamManager is not available"):
            await getattr(session, method_name)()

    async def test_create_unidirectional_stream_on_protocol_flow_control_no_event(
        self, session: WebTransportSession, mock_protocol_handler: Any
    ) -> None:
        mock_protocol_handler.create_webtransport_stream.side_effect = FlowControlError(message="No stream credit")
        session._uni_stream_credit_event = None
        with pytest.raises(FlowControlError, match="No stream credit"):
            await session._create_stream_on_protocol(is_unidirectional=True)

    async def test_diagnostics(self, session: WebTransportSession, mock_connection: Any, mocker: MockerFixture) -> None:
        await session.create_datagram_transport()
        assert session.stream_manager is not None
        cast(AsyncMock, session.stream_manager.get_stats).return_value = {
            "total_created": 10,
            "total_closed": 4,
        }
        mock_datagram_transport = session._datagram_transport

        mock_datagram_diags = mocker.MagicMock()
        mock_datagram_diags.stats.datagrams_sent = 50
        mock_datagram_diags.stats.datagrams_received = 60
        mocker.patch.object(
            type(mock_datagram_transport),
            "diagnostics",
            new_callable=PropertyMock,
            return_value=mock_datagram_diags,
        )

        cast(Mock, mock_datagram_transport.get_receive_buffer_size).return_value = 123

        mock_session_info = mocker.MagicMock(
            peer_max_data=1000,
            local_data_sent=200,
            local_max_data=800,
            peer_data_sent=300,
        )
        mock_connection.get_session_info.return_value = mock_session_info

        diags = await session.diagnostics()

        assert isinstance(diags, SessionDiagnostics)
        assert diags.stats.streams_created == 10
        assert diags.stats.datagrams_sent == 50
        assert diags.state == session.state
        assert diags.is_connection_active is True
        assert diags.datagram_receive_buffer_size == 123
        assert diags.send_credit_available == 800
        assert diags.receive_credit_available == 500

    async def test_incoming_streams(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        session._state = SessionState.CONNECTED
        mock_stream1 = mocker.create_autospec(WebTransportStream, instance=True)
        mock_stream1.initialize = mock.AsyncMock()
        mock_stream2 = mocker.create_autospec(WebTransportStream, instance=True)
        mock_stream2.initialize = mock.AsyncMock()
        assert session._incoming_streams is not None
        cast(AsyncMock, session._incoming_streams.get).side_effect = [
            mock_stream1,
            mock_stream2,
            None,
        ]

        streams = [s async for s in session.incoming_streams()]

        assert streams == [mock_stream1, mock_stream2]
        session._state = SessionState.CLOSED

    @pytest.mark.parametrize("start_state", [SessionState.CLOSING, SessionState.CLOSED])
    async def test_incoming_streams_on_closed_session(
        self, session: WebTransportSession, start_state: SessionState
    ) -> None:
        session._state = start_state
        streams = [s async for s in session.incoming_streams()]
        assert streams == []

    async def test_incoming_streams_stops_on_none(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        session._state = SessionState.CONNECTED
        assert session._incoming_streams is not None
        cast(AsyncMock, session._incoming_streams.get).side_effect = [None]
        streams = [s async for s in session.incoming_streams()]
        assert streams == []

    async def test_incoming_streams_timeout(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        session._state = SessionState.CONNECTED
        mock_stream = mocker.create_autospec(WebTransportStream, instance=True)
        mock_stream.initialize = mock.AsyncMock()
        assert session._incoming_streams is not None
        cast(AsyncMock, session._incoming_streams.get).side_effect = [
            asyncio.TimeoutError,
            mock_stream,
            None,
        ]
        streams = [s async for s in session.incoming_streams()]
        assert streams == [mock_stream]
        assert cast(AsyncMock, session._incoming_streams.get).call_count == 3

    async def test_initialization(
        self,
        session: WebTransportSession,
        mock_connection: Any,
        mock_protocol_handler: Any,
        mock_stream_manager_class: Any,
        mocker: MockerFixture,
    ) -> None:
        assert session.session_id == "session-1"
        assert session.state == SessionState.CONNECTING
        assert session.connection is mock_connection
        assert session.protocol_handler is mock_protocol_handler

        mock_stream_manager_class.assert_called_once()
        call_args = mock_stream_manager_class.call_args.kwargs
        assert "stream_factory" in call_args and callable(call_args["stream_factory"])
        assert "session_factory" in call_args and callable(call_args["session_factory"])
        assert call_args["session_factory"]() is session

        expected_calls = [
            mocker.call(event_type=EventType.SESSION_READY, handler=session._on_session_ready),
            mocker.call(event_type=EventType.SESSION_CLOSED, handler=session._on_session_closed),
            mocker.call(event_type=EventType.STREAM_OPENED, handler=session._on_stream_opened),
            mocker.call(
                event_type=EventType.DATAGRAM_RECEIVED,
                handler=session._on_datagram_received,
            ),
            mocker.call(
                event_type=EventType.SESSION_MAX_DATA_UPDATED,
                handler=session._on_max_data_updated,
            ),
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
            event_type=EventType.CONNECTION_CLOSED,
            handler=session._on_connection_closed,
        )
        mock_connection.get_session_info.assert_called_once_with(session_id="session-1")

    async def test_initialize_idempotent(self, session: WebTransportSession) -> None:
        assert session._is_initialized
        await session.initialize()
        assert session.stream_manager is not None
        cast(AsyncMock, session.stream_manager.__aenter__).assert_awaited_once()

    async def test_initialization_no_protocol_handler(self, mocker: MockerFixture, mock_connection: Any) -> None:
        mock_logger = mocker.patch("pywebtransport.session.session.logger")
        mock_connection.protocol_handler = None
        session = WebTransportSession(connection=mock_connection, session_id="session-1")

        await session.initialize()

        assert session.protocol_handler is None
        mock_logger.warning.assert_called_with("No protocol handler available for session %s", "session-1")
        await session.close()

    async def test_initialization_on_closed_connection(self, mock_connection: Any, mocker: MockerFixture) -> None:
        mock_connection.is_closed = True
        session = WebTransportSession(connection=mock_connection, session_id="session-1")
        close_mock = mocker.patch.object(session, "close", new_callable=mocker.AsyncMock)

        await session.initialize()
        await asyncio.sleep(0)

        close_mock.assert_awaited_once_with(
            reason="Connection already closed upon session creation",
            close_connection=False,
        )

    @pytest.mark.parametrize(
        "last_activity_timestamp, get_timestamp_return, should_warn",
        [
            (1000.0, 1400.0, True),
            (1000.0, 1100.0, False),
        ],
    )
    async def test_monitor_health_activity_check(
        self,
        session: WebTransportSession,
        mocker: MockerFixture,
        last_activity_timestamp: float,
        get_timestamp_return: float,
        should_warn: bool,
    ) -> None:
        mocker.patch(
            "pywebtransport.session.session.get_timestamp",
            return_value=get_timestamp_return,
        )
        assert session.connection is not None
        type(session.connection.diagnostics.stats).last_activity = PropertyMock(return_value=last_activity_timestamp)
        mocker.patch(
            "pywebtransport.session.session.asyncio.sleep",
            side_effect=asyncio.CancelledError,
        )
        mock_logger = mocker.patch("pywebtransport.session.session.logger")
        session._state = SessionState.CONNECTED

        await session.monitor_health()

        session._state = SessionState.CLOSED
        if should_warn:
            mock_logger.warning.assert_called_once_with(
                "Session %s appears inactive (no connection activity)", "session-1"
            )
        else:
            mock_logger.warning.assert_not_called()

    async def test_monitor_health_handles_exception(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        error = ValueError("Test Error")
        mock_sleep = mocker.patch("pywebtransport.session.session.asyncio.sleep", side_effect=error)
        mock_logger = mocker.patch("pywebtransport.session.session.logger")
        await session.monitor_health()
        mock_sleep.assert_awaited_once()
        mock_logger.error.assert_called_once_with("Session health monitoring error: %s", error, exc_info=True)

    @pytest.mark.parametrize(
        "connection_setup",
        [
            "normal",
            "no_connection",
            "no_diagnostics_attr",
            "no_stats_attr",
            "no_last_activity_attr",
        ],
    )
    async def test_monitor_health(
        self, session: WebTransportSession, mocker: MockerFixture, connection_setup: str
    ) -> None:
        mock_sleep = mocker.patch("pywebtransport.session.session.asyncio.sleep")
        mock_sleep.side_effect = asyncio.CancelledError
        mock_logger = mocker.patch("pywebtransport.session.session.logger")
        mocker.patch("pywebtransport.session.session.get_timestamp", return_value=1100.0)
        session._state = SessionState.CONNECTED

        if connection_setup == "no_connection":
            mocker.patch.object(
                WebTransportSession,
                "connection",
                new_callable=mock.PropertyMock,
                return_value=None,
            )
        elif connection_setup == "no_diagnostics_attr":
            assert session.connection
            delattr(session.connection, "diagnostics")
        elif connection_setup == "no_stats_attr":
            assert session.connection
            mock_diags = mocker.MagicMock(spec=[])
            mocker.patch.object(
                WebTransportConnection,
                "diagnostics",
                new_callable=PropertyMock,
                return_value=mock_diags,
            )
        elif connection_setup == "no_last_activity_attr":
            assert session.connection
            mock_stats = mocker.MagicMock(spec=[])
            mock_diags = mocker.MagicMock()
            mock_diags.stats = mock_stats
            mocker.patch.object(
                WebTransportConnection,
                "diagnostics",
                new_callable=PropertyMock,
                return_value=mock_diags,
            )

        await session.monitor_health(check_interval=10)

        mock_sleep.assert_awaited_once()
        mock_logger.debug.assert_any_call("Health monitoring cancelled for session %s", "session-1")
        mock_logger.warning.assert_not_called()
        session._state = SessionState.CLOSED

    async def test_on_connection_closed(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        close_mock = mocker.patch.object(session, "close", new_callable=mocker.AsyncMock)
        event = Event(type=EventType.CONNECTION_CLOSED, data={})
        session._state = SessionState.CONNECTED
        await session._on_connection_closed(event=event)
        await asyncio.sleep(0)
        cast(AsyncMock, close_mock).assert_awaited_once_with(
            reason="Underlying connection closed", close_connection=False
        )

    async def test_on_connection_closed_when_session_closing(
        self, session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        close_mock = mocker.patch.object(session, "close", new_callable=mocker.AsyncMock)
        event = Event(type=EventType.CONNECTION_CLOSED, data={})
        session._state = SessionState.CLOSING
        await session._on_connection_closed(event=event)
        cast(AsyncMock, close_mock).assert_not_awaited()

    @pytest.mark.parametrize("bad_data", ["not a dict", {"session_id": "other-session"}])
    async def test_on_datagram_received_invalid_event(self, session: WebTransportSession, bad_data: Any) -> None:
        datagram_transport = await session.create_datagram_transport()
        event = Event(type=EventType.DATAGRAM_RECEIVED, data=bad_data)
        await session._on_datagram_received(event=event)
        cast(AsyncMock, datagram_transport.receive_from_protocol).assert_not_awaited()

    async def test_on_datagram_received_mismatched_id(self, session: WebTransportSession) -> None:
        datagram_transport = await session.create_datagram_transport()
        event = Event(
            type=EventType.DATAGRAM_RECEIVED,
            data={"session_id": "session-2", "data": b"ping"},
        )
        await session._on_datagram_received(event=event)
        cast(AsyncMock, datagram_transport.receive_from_protocol).assert_not_awaited()

    async def test_on_datagram_received_no_transport(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        mock_logger = mocker.patch("pywebtransport.session.session.logger")
        assert not hasattr(session, "_datagram_transport")
        event = Event(
            type=EventType.DATAGRAM_RECEIVED,
            data={"session_id": "session-1", "data": b"ping"},
        )

        await session._on_datagram_received(event=event)

        mock_logger.debug.assert_not_called()

    async def test_on_datagram_received(self, session: WebTransportSession) -> None:
        datagram_transport = await session.create_datagram_transport()
        event = Event(
            type=EventType.DATAGRAM_RECEIVED,
            data={"session_id": "session-1", "data": b"ping"},
        )
        await session._on_datagram_received(event=event)
        cast(AsyncMock, datagram_transport.receive_from_protocol).assert_awaited_once_with(data=b"ping")

    @pytest.mark.parametrize(
        "handler_name, event_type",
        [
            ("_on_max_data_updated", EventType.SESSION_MAX_DATA_UPDATED),
            (
                "_on_max_streams_bidi_updated",
                EventType.SESSION_MAX_STREAMS_BIDI_UPDATED,
            ),
            (
                "_on_max_streams_uni_updated",
                EventType.SESSION_MAX_STREAMS_UNI_UPDATED,
            ),
        ],
    )
    @pytest.mark.parametrize("bad_data", ["not a dict", {"session_id": "session-2"}])
    async def test_on_max_credit_events_invalid_data(
        self,
        session: WebTransportSession,
        handler_name: str,
        event_type: EventType,
        bad_data: Any,
    ) -> None:
        handler = getattr(session, handler_name)
        event = Event(type=event_type, data=bad_data)
        await handler(event=event)
        if session._data_credit_event:
            assert not session._data_credit_event.is_set()
        if session._bidi_stream_credit_event:
            assert not session._bidi_stream_credit_event.is_set()
        if session._uni_stream_credit_event:
            assert not session._uni_stream_credit_event.is_set()

    async def test_on_max_data_updated(self, session: WebTransportSession) -> None:
        assert session._data_credit_event is not None
        assert not session._data_credit_event.is_set()
        event = Event(type=EventType.SESSION_MAX_DATA_UPDATED, data={"session_id": "session-1"})
        await session._on_max_data_updated(event=event)
        assert session._data_credit_event.is_set()

    async def test_on_max_streams_bidi_updated(self, session: WebTransportSession) -> None:
        assert session._bidi_stream_credit_event is not None
        assert not session._bidi_stream_credit_event.is_set()
        event = Event(
            type=EventType.SESSION_MAX_STREAMS_BIDI_UPDATED,
            data={"session_id": "session-1"},
        )
        await session._on_max_streams_bidi_updated(event=event)
        assert session._bidi_stream_credit_event.is_set()

    async def test_on_max_streams_uni_updated(self, session: WebTransportSession) -> None:
        assert session._uni_stream_credit_event is not None
        assert not session._uni_stream_credit_event.is_set()
        event = Event(
            type=EventType.SESSION_MAX_STREAMS_UNI_UPDATED,
            data={"session_id": "session-1"},
        )
        await session._on_max_streams_uni_updated(event=event)
        assert session._uni_stream_credit_event.is_set()

    async def test_on_session_closed_mismatched_id(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        close_mock = mocker.patch.object(session, "close", new_callable=mocker.AsyncMock)
        event = Event(type=EventType.SESSION_CLOSED, data={"session_id": "session-2"})
        session._state = SessionState.CONNECTED
        await session._on_session_closed(event=event)
        close_mock.assert_not_awaited()

    @pytest.mark.parametrize("initial_state", [SessionState.CLOSING, SessionState.CLOSED])
    async def test_on_session_closed_remotely_when_already_closing_or_closed(
        self,
        session: WebTransportSession,
        mocker: MockerFixture,
        initial_state: SessionState,
    ) -> None:
        close_mock = mocker.patch.object(session, "close", new_callable=mocker.AsyncMock)
        event = Event(type=EventType.SESSION_CLOSED, data={"session_id": "session-1"})
        session._state = initial_state
        await session._on_session_closed(event=event)
        cast(AsyncMock, close_mock).assert_not_awaited()

    async def test_on_session_closed_remotely(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        close_mock = mocker.patch.object(session, "close", new_callable=mocker.AsyncMock)
        event = Event(
            type=EventType.SESSION_CLOSED,
            data={"session_id": "session-1", "code": 404, "reason": "Not Found"},
        )
        session._state = SessionState.CONNECTED
        await session._on_session_closed(event=event)
        cast(AsyncMock, close_mock).assert_awaited_once_with(code=404, reason="Not Found")

    async def test_on_session_ready_mismatched_id(self, session: WebTransportSession) -> None:
        event = Event(type=EventType.SESSION_READY, data={"session_id": "session-2"})
        await session._on_session_ready(event=event)
        assert not session.is_ready
        assert session._ready_event is not None
        assert not session._ready_event.is_set()

    @pytest.mark.parametrize(
        "event_data_override, expected_path, expected_headers",
        [
            (
                {
                    "path": "/ready",
                    "headers": {"content-type": "application/json"},
                    "control_stream_id": 101,
                },
                "/ready",
                {"content-type": "application/json"},
            ),
            ({}, "/test", {"x-test": "true"}),
            ({"path": "/new_path"}, "/new_path", {"x-test": "true"}),
        ],
    )
    async def test_on_session_ready(
        self,
        session: WebTransportSession,
        event_data_override: dict[str, Any],
        expected_path: str,
        expected_headers: dict[str, Any],
    ) -> None:
        event_data = {"session_id": "session-1", **event_data_override}
        event = Event(type=EventType.SESSION_READY, data=event_data)

        await session._on_session_ready(event=event)

        assert session.is_ready
        assert session.path == expected_path
        assert session.headers == expected_headers
        if "control_stream_id" in event_data:
            assert session._control_stream_id == event_data["control_stream_id"]

        assert session._ready_event is not None
        assert session._ready_event.is_set()

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

    async def test_on_stream_opened_handles_exception(
        self, session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        mocker.patch("pywebtransport.session.session.WebTransportStream", autospec=True)
        event = Event(
            type=EventType.STREAM_OPENED,
            data={
                "session_id": "session-1",
                "stream_id": 2,
                "direction": StreamDirection.BIDIRECTIONAL,
            },
        )
        assert session.stream_manager is not None
        cast(AsyncMock, session.stream_manager.add_stream).side_effect = ValueError("Test error")
        await session._on_stream_opened(event=event)
        assert session._stats.stream_errors == 1
        assert session._incoming_streams is not None
        cast(AsyncMock, session._incoming_streams.put).assert_not_awaited()

    async def test_on_stream_opened_initialization_failure(
        self, session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        mock_stream_class = mocker.patch("pywebtransport.session.session.WebTransportStream", autospec=True)
        mock_stream_instance = mock_stream_class.return_value
        mock_stream_instance.initialize = mocker.AsyncMock(side_effect=ValueError("Init failed"))

        event = Event(
            type=EventType.STREAM_OPENED,
            data={
                "session_id": "session-1",
                "stream_id": 2,
                "direction": StreamDirection.BIDIRECTIONAL,
            },
        )

        await session._on_stream_opened(event=event)

        assert session._stats.stream_errors == 1
        assert session.stream_manager is not None
        cast(AsyncMock, session.stream_manager.add_stream).assert_not_awaited()
        assert session._incoming_streams is not None
        cast(AsyncMock, session._incoming_streams.put).assert_not_awaited()

    async def test_on_stream_opened_no_stream_manager(
        self, session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        mock_logger = mocker.patch("pywebtransport.session.session.logger")
        session.stream_manager = None
        event = Event(
            type=EventType.STREAM_OPENED,
            data={
                "session_id": "session-1",
                "stream_id": 2,
                "direction": StreamDirection.BIDIRECTIONAL,
            },
        )
        initial_errors = session._stats.stream_errors

        await session._on_stream_opened(event=event)

        mock_logger.error.assert_called_once_with(
            "Error handling newly opened stream %d: %s", 2, mock.ANY, exc_info=True
        )
        assert session._stats.stream_errors == initial_errors + 1

    @pytest.mark.parametrize(
        "direction",
        [StreamDirection.BIDIRECTIONAL, StreamDirection.RECEIVE_ONLY, StreamDirection.SEND_ONLY],
    )
    @pytest.mark.parametrize("with_payload", [True, False])
    async def test_on_stream_opened(
        self,
        session: WebTransportSession,
        mocker: MockerFixture,
        direction: StreamDirection,
        with_payload: bool,
    ) -> None:
        expected_class = WebTransportStream if direction == StreamDirection.BIDIRECTIONAL else WebTransportReceiveStream
        mock_stream_class = mocker.patch(f"pywebtransport.session.session.{expected_class.__name__}", autospec=True)
        mock_stream_instance = mock_stream_class.return_value
        mock_stream_instance.initialize = mocker.AsyncMock()
        mock_stream_instance._on_data_received = mocker.AsyncMock()
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
            mock_stream_instance._on_data_received.assert_awaited_once()
            received_event_arg = mock_stream_instance._on_data_received.call_args.kwargs["event"]
            assert isinstance(received_event_arg, Event)
            assert received_event_arg.type == EventType.STREAM_DATA_RECEIVED
            assert isinstance(received_event_arg.data, dict)
            assert received_event_arg.data["stream_id"] == 2
            assert received_event_arg.data["data"] == b"initial"
        else:
            mock_stream_instance._on_data_received.assert_not_awaited()
        assert session.stream_manager is not None
        cast(AsyncMock, session.stream_manager.add_stream).assert_awaited_once_with(stream=mock_stream_instance)
        assert session._incoming_streams is not None
        cast(AsyncMock, session._incoming_streams.put).assert_awaited_once_with(mock_stream_instance)

    async def test_properties(self, session: WebTransportSession) -> None:
        session._state = SessionState.CONNECTED
        assert (session.is_ready, session.is_closed) == (True, False)

        session._state = SessionState.CLOSED
        assert (session.is_ready, session.is_closed) == (False, True)

    async def test_ready_already_connected(self, session: WebTransportSession) -> None:
        session._state = SessionState.CONNECTED
        await session.ready(timeout=0.1)

    async def test_ready_timeout(self, session: WebTransportSession) -> None:
        session._state = SessionState.CONNECTING
        with pytest.raises(TimeoutError, match="Session ready timeout"):
            await session.ready(timeout=0.01)

    async def test_ready_waits_for_event(self, session: WebTransportSession) -> None:
        session._state = SessionState.CONNECTING
        assert session._ready_event is not None
        session._ready_event.set()
        await session.ready()

    async def test_str_representation(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        session._session_id = "long-session-id-that-will-be-truncated"
        mocker.patch("pywebtransport.session.session.format_duration", return_value="1m 30s")
        session._stats.streams_created = 8
        session._stats.streams_closed = 2
        session._stats.datagrams_sent = 100
        session._stats.datagrams_received = 200
        session._path = "/test"
        session._state = SessionState.CONNECTING

        representation = str(session)

        assert representation == (
            "Session(long-session..., "
            "state=connecting, "
            "path=/test, "
            "uptime=1m 30s, "
            "streams=6/8, "
            "datagrams=100/200)"
        )

    async def test_sync_protocol_state_no_connection(self, mock_connection: Any, mocker: MockerFixture) -> None:
        session = WebTransportSession(connection=mock_connection, session_id="session-1")
        await session.initialize()
        mocker.patch.object(type(session), "connection", new_callable=PropertyMock, return_value=None)
        session._sync_protocol_state()

    async def test_sync_protocol_state_no_headers(self, mock_connection: Any, mocker: MockerFixture) -> None:
        mock_session_info = mocker.MagicMock()
        mock_session_info.state = SessionState.CONNECTED
        mock_session_info.ready_at = 999.0
        mock_session_info.path = "/synced"
        mock_session_info.headers = None
        mock_session_info.control_stream_id = 42
        mock_connection.get_session_info.return_value = mock_session_info

        session = WebTransportSession(connection=mock_connection, session_id="session-1")
        await session.initialize()

        assert session.state == SessionState.CONNECTED
        assert session.is_ready
        assert session.headers == {}

    async def test_sync_protocol_state_not_connected(self, mock_connection: Any, mocker: MockerFixture) -> None:
        mock_session_info = mocker.MagicMock()
        mock_session_info.state = SessionState.CONNECTING
        mock_connection.get_session_info.return_value = mock_session_info

        session = WebTransportSession(connection=mock_connection, session_id="session-1")
        await session.initialize()

        assert session.state == SessionState.CONNECTING
        assert not session.is_ready
        assert session._ready_event is not None
        assert not session._ready_event.is_set()

    async def test_sync_protocol_state_on_init(self, mock_connection: Any, mocker: MockerFixture) -> None:
        mock_session_info = mocker.MagicMock()
        mock_session_info.state = SessionState.CONNECTED
        mock_session_info.ready_at = 999.0
        mock_session_info.path = "/synced"
        mock_session_info.headers = {"x-synced": "true"}
        mock_session_info.control_stream_id = 42
        mock_connection.get_session_info.return_value = mock_session_info

        session = WebTransportSession(connection=mock_connection, session_id="session-1")
        await session.initialize()

        assert session.state == SessionState.CONNECTED
        assert session.is_ready
        assert session.path == "/synced"
        assert session.headers == {"x-synced": "true"}
        assert session._control_stream_id == 42
        assert session._ready_event is not None
        assert session._ready_event.is_set()

    async def test_sync_protocol_state_with_existing_path(self, mock_connection: Any, mocker: MockerFixture) -> None:
        mock_session_info = mocker.MagicMock(state=SessionState.CONNECTED, path="/protocol-path")
        mock_connection.get_session_info.return_value = mock_session_info

        session = WebTransportSession(connection=mock_connection, session_id="session-1", path="/initial-path")
        await session.initialize()

        assert session.path == "/initial-path"

    async def test_teardown_no_connection(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        mocker.patch.object(
            WebTransportSession,
            "connection",
            new_callable=mock.PropertyMock,
            return_value=None,
        )
        session._teardown_event_handlers()

    async def test_teardown_no_protocol_handler(self, session: WebTransportSession) -> None:
        session._protocol_handler = None
        session._teardown_event_handlers()

    async def test_wait_closed(self, session: WebTransportSession) -> None:
        assert session._closed_event is not None
        session._closed_event.set()
        await session.wait_closed()


@pytest.mark.asyncio
class TestWebTransportSessionUninitialized:
    @pytest.fixture
    def mock_connection(self, mocker: MockerFixture) -> Any:
        connection = mocker.create_autospec(WebTransportConnection, instance=True)
        connection.get_session_info.return_value = None
        return connection

    @pytest.fixture
    def uninitialized_session(self, mock_connection: Any) -> WebTransportSession:
        return WebTransportSession(connection=mock_connection, session_id="session-1")

    async def test_diagnostics_uninitialized(self, uninitialized_session: WebTransportSession) -> None:
        diags = await uninitialized_session.diagnostics()
        assert diags.stats.streams_created == 0
        assert diags.state == SessionState.CONNECTING

    async def test_incoming_streams_raises_before_initialized(self, uninitialized_session: WebTransportSession) -> None:
        with pytest.raises(SessionError, match="WebTransportSession is not initialized"):
            async for _ in uninitialized_session.incoming_streams():
                pass

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
        self,
        uninitialized_session: WebTransportSession,
        method_name: str,
        args: tuple[Any, ...],
        match_str: str,
    ) -> None:
        with pytest.raises(SessionError, match=match_str):
            await getattr(uninitialized_session, method_name)(*args)

    async def test_private_handlers_do_nothing_before_initialized(
        self, uninitialized_session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        mock_logger = mocker.patch("pywebtransport.session.session.logger")
        event = Event(type="", data={})
        uninitialized_session._ready_event = None
        uninitialized_session._incoming_streams = None
        uninitialized_session._data_credit_event = None
        uninitialized_session._bidi_stream_credit_event = None
        uninitialized_session._uni_stream_credit_event = None

        await uninitialized_session._on_session_ready(event=event)
        await uninitialized_session._on_stream_opened(event=event)
        await uninitialized_session._on_max_data_updated(event=event)
        await uninitialized_session._on_max_streams_bidi_updated(event=event)
        await uninitialized_session._on_max_streams_uni_updated(event=event)
        uninitialized_session._sync_protocol_state()

        mock_logger.warning.assert_called_once_with(
            "Cannot sync state for session %s, session not initialized.", "session-1"
        )
        assert uninitialized_session._ready_event is None

    async def test_ready_uninitialized(self, uninitialized_session: WebTransportSession) -> None:
        with pytest.raises(SessionError, match="WebTransportSession is not initialized"):
            await uninitialized_session.ready()
