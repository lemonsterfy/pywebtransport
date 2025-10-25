"""Unit tests for the pywebtransport.connection.connection module."""

import asyncio
import ssl
from collections.abc import Callable, Generator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
import pytest_asyncio
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.connection import QuicConnection
from aioquic.quic.events import StreamDataReceived
from pytest_mock import MockerFixture

import pywebtransport.connection.connection as connection_module
from pywebtransport import ClientConfig, ClientError, ConfigurationError, ConnectionError, Event, ServerConfig
from pywebtransport.connection import ConnectionDiagnostics, ConnectionInfo, WebTransportConnection
from pywebtransport.connection.connection import _WebTransportClientProtocol
from pywebtransport.exceptions import HandshakeError
from pywebtransport.protocol import WebTransportProtocolHandler, WebTransportSessionInfo
from pywebtransport.types import ConnectionState, EventType, SessionState


@pytest.fixture(autouse=True)
def mock_asyncio_sleep(mocker: MockerFixture) -> Generator[None, None, None]:
    mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
    yield


@pytest.fixture
def mock_client_config(mocker: MockerFixture) -> ClientConfig:
    mocker.patch("pywebtransport.config.ClientConfig.validate", return_value=None)
    config = ClientConfig(certfile="test.crt", keyfile="test.key", ca_certs="ca.crt")
    config.keep_alive = True
    config.connection_keepalive_timeout = 30.0
    return config


@pytest.fixture
def mock_loop_factory(
    mocker: MockerFixture,
) -> Callable[[], asyncio.AbstractEventLoop]:
    def _factory() -> asyncio.AbstractEventLoop:
        loop = asyncio.get_running_loop()
        mocker.patch.object(loop, "time", return_value=1000.0)
        mocker.patch.object(loop, "call_at", return_value=mocker.MagicMock())

        async def mock_endpoint_creation(protocol_factory: Any, *args: Any, **kwargs: Any) -> tuple[Any, Any]:
            protocol = protocol_factory()
            transport = mocker.create_autospec(asyncio.DatagramTransport, instance=True)
            if hasattr(protocol, "connection_made"):
                protocol.connection_made(transport)
            return transport, protocol

        mocker.patch.object(loop, "create_datagram_endpoint", side_effect=mock_endpoint_creation)
        return loop

    return _factory


@pytest.fixture
def mock_protocol_handler_class(mocker: MockerFixture) -> MagicMock:
    mock_cls = mocker.patch("pywebtransport.connection.connection.WebTransportProtocolHandler", autospec=True)
    mock_instance = mock_cls.return_value
    mock_instance._stats = {
        "bytes_sent": 1024,
        "bytes_received": 2048,
        "errors": 1,
        "last_activity": 12345.0,
    }
    mock_instance.create_webtransport_session = mocker.AsyncMock(return_value=("session_123", mocker.MagicMock()))
    mock_instance.close = mocker.AsyncMock()
    mock_instance.wait_for = mocker.AsyncMock(
        return_value=Event(type=EventType.SESSION_READY, data={"session_id": "session_123"})
    )

    session_tracker_mock = mocker.MagicMock()
    session_tracker_mock.get_all_sessions.return_value = [
        WebTransportSessionInfo(
            session_id="session_123",
            state=SessionState.CONNECTED,
            control_stream_id=0,
            path="/",
            created_at=1000.0,
        )
    ]
    session_tracker_mock.get_session_info.return_value = WebTransportSessionInfo(
        session_id="session_123",
        state=SessionState.CONNECTED,
        control_stream_id=0,
        path="/",
        created_at=1000.0,
    )
    mock_instance._session_tracker = session_tracker_mock

    return mock_cls


@pytest.fixture
def mock_quic_connection(mocker: MockerFixture) -> MagicMock:
    mock_instance = mocker.create_autospec(QuicConnection, instance=True)
    setattr(mock_instance, "_rtt_smoother", mocker.MagicMock())
    getattr(mock_instance, "_rtt_smoother").latest_rtt = 0.1
    mock_instance.datagrams_to_send.return_value = []
    mock_instance.get_timer.return_value = None
    mock_loss = mocker.MagicMock()
    mock_loss.get_probe_timeout.return_value = 1.0
    mock_instance._loss = mock_loss
    mock_instance._packets_sent = 10
    mock_instance._packets_received = 20
    mock_instance._lost_packets_count = 1
    mock_instance._packets_in_flight = 5
    congestion_control_mock = mocker.MagicMock()
    congestion_control_mock.congestion_window = 14600
    mock_instance.congestion_control = congestion_control_mock
    mock_instance._quic_logger = mocker.MagicMock()

    mock_cls = mocker.patch("pywebtransport.connection.connection.QuicConnection", autospec=True)
    mock_cls.return_value = mock_instance
    return mock_cls


@pytest.fixture
def mock_server_config(mocker: MockerFixture) -> ServerConfig:
    mocker.patch("pywebtransport.config.ServerConfig.validate", return_value=None)
    config = ServerConfig(certfile="test.crt", keyfile="test.key")
    config.connection_idle_timeout = 60.0
    config.keep_alive = False
    return config


@pytest.fixture(autouse=True)
def mock_utils_create_quic_config(mocker: MockerFixture) -> MagicMock:
    mock_quic_config = mocker.MagicMock()
    mock_quic_config.load_cert_chain = mocker.MagicMock()
    mock_quic_config.load_verify_locations = mocker.MagicMock()
    mock_quic_config.max_datagram_size = 65527
    mock_quic_config.congestion_control_algorithm = "reno"
    mock_quic_config.idle_timeout = 30.0
    return mocker.patch(
        "pywebtransport.connection.connection.create_quic_configuration",
        return_value=mock_quic_config,
    )


class TestConnectionDiagnostics:
    @pytest.mark.parametrize(
        "diag_kwargs, expected_issue_part",
        [
            (
                {"stats": ConnectionInfo(connection_id="", state=ConnectionState.CONNECTING)},
                "Connection not established",
            ),
            (
                {"stats": ConnectionInfo(connection_id="", state=ConnectionState.CONNECTED, error_count=11)},
                "High error count",
            ),
            ({"rtt": 1.1}, "High latency"),
            (
                {
                    "stats": ConnectionInfo(
                        connection_id="",
                        state=ConnectionState.CONNECTED,
                        packets_sent=1001,
                    )
                },
                "no packets are being received",
            ),
            ({}, None),
        ],
    )
    def test_issues_property(self, diag_kwargs: dict[str, Any], expected_issue_part: str | None) -> None:
        if "stats" not in diag_kwargs:
            diag_kwargs["stats"] = ConnectionInfo(connection_id="", state=ConnectionState.CONNECTED)
        if "rtt" not in diag_kwargs:
            diag_kwargs["rtt"] = 0.1
        if "cwnd" not in diag_kwargs:
            diag_kwargs["cwnd"] = 14600
        if "packets_in_flight" not in diag_kwargs:
            diag_kwargs["packets_in_flight"] = 0
        if "packet_loss_rate" not in diag_kwargs:
            diag_kwargs["packet_loss_rate"] = 0.0

        diagnostics = ConnectionDiagnostics(**diag_kwargs)
        issues = diagnostics.issues

        if expected_issue_part:
            assert any(expected_issue_part in issue for issue in issues)
        else:
            assert not issues

    def test_issues_property_stale_connection(self, mocker: MockerFixture) -> None:
        mocker.patch("asyncio.get_running_loop").return_value.time.return_value = 1400.0
        stats = ConnectionInfo(
            connection_id="",
            state=ConnectionState.CONNECTED,
            last_activity=1000.0,
        )

        diagnostics = ConnectionDiagnostics(
            stats=stats,
            rtt=0.1,
            cwnd=14600,
            packets_in_flight=0,
            packet_loss_rate=0.0,
        )

        assert any("Connection appears stale" in issue for issue in diagnostics.issues)


class TestConnectionInfo:
    def test_to_dict(self) -> None:
        info = ConnectionInfo(connection_id="test", state=ConnectionState.CONNECTED)

        info_dict = info.to_dict()

        assert info_dict["connection_id"] == "test"
        assert info_dict["state"] == ConnectionState.CONNECTED

    def test_uptime(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.connection.connection.get_timestamp", return_value=110.0)
        info = ConnectionInfo(connection_id="test", state=ConnectionState.CONNECTED, established_at=100.0)

        assert info.uptime == 10.0

        info.closed_at = 105.0
        assert info.uptime == 5.0

        info.established_at = None
        assert info.uptime == 0.0


@pytest.mark.filterwarnings("ignore::DeprecationWarning:aioquic.*")
class TestWebTransportClientProtocol:
    @pytest.fixture
    def mock_owner(self, mocker: MockerFixture) -> MagicMock:
        owner = mocker.create_autospec(WebTransportConnection, instance=True)
        owner.protocol_handler = mocker.create_autospec(WebTransportProtocolHandler, instance=True)
        owner.protocol_handler.handle_quic_event = mocker.AsyncMock()
        return owner

    @pytest_asyncio.fixture
    async def protocol(
        self,
        mock_owner: MagicMock,
        mock_quic_connection: MagicMock,
    ) -> _WebTransportClientProtocol:
        return _WebTransportClientProtocol(owner=mock_owner, quic=mock_quic_connection.return_value)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "task_is_done, task_exists",
        [(False, True), (True, True), (False, False)],
    )
    async def test_connection_lost(
        self,
        protocol: _WebTransportClientProtocol,
        mock_owner: MagicMock,
        mocker: MockerFixture,
        task_is_done: bool,
        task_exists: bool,
    ) -> None:
        if task_exists:
            task = mocker.create_autospec(asyncio.Task, instance=True)
            task.done.return_value = task_is_done
            protocol._event_processor_task = task
        else:
            protocol._event_processor_task = None

        protocol.connection_lost(exc=None)

        if task_exists and not task_is_done:
            task.cancel.assert_called_once()
        elif task_exists:
            task.cancel.assert_not_called()

        mock_owner._on_connection_lost.assert_called_once_with(exc=None)

    @pytest.mark.asyncio
    async def test_connection_lost_full_path(
        self,
        mock_quic_connection: MagicMock,
        mock_client_config: ClientConfig,
        mocker: MockerFixture,
        protocol: _WebTransportClientProtocol,
    ) -> None:
        owner = WebTransportConnection(config=mock_client_config)
        mock_emit = mocker.patch.object(owner, "emit", new_callable=mocker.AsyncMock)
        owner._state = ConnectionState.CONNECTED
        owner._protocol = protocol
        create_task_spy = mocker.spy(asyncio, "create_task")
        protocol._owner = owner

        protocol.connection_lost(exc=None)
        await asyncio.sleep(0)

        create_task_spy.assert_called_once()
        task = create_task_spy.call_args.args[0]
        await task
        mock_emit.assert_awaited_once_with(
            event_type=EventType.CONNECTION_LOST,
            data={"connection_id": owner.connection_id, "exception": None},
        )

    @pytest.mark.asyncio
    async def test_process_events_loop(self, protocol: _WebTransportClientProtocol, mock_owner: MagicMock) -> None:
        protocol.connection_made(transport=MagicMock())
        assert protocol._event_queue is not None
        called_event = asyncio.Event()

        async def side_effect(*args: Any, **kwargs: Any) -> None:
            called_event.set()
            raise Exception("test error from side_effect")

        protocol._owner = mock_owner
        mock_owner.protocol_handler.handle_quic_event.side_effect = side_effect
        event = StreamDataReceived(stream_id=0, data=b"test", end_stream=False)
        protocol._event_queue.put_nowait(event)

        await asyncio.wait_for(called_event.wait(), timeout=1)
        await asyncio.sleep(0)

        mock_owner.protocol_handler.handle_quic_event.assert_called_once()
        assert protocol._event_processor_task is not None

    @pytest.mark.asyncio
    async def test_process_events_loop_cancelled(
        self, protocol: _WebTransportClientProtocol, mocker: MockerFixture
    ) -> None:
        protocol.connection_made(transport=MagicMock())
        assert protocol._event_queue is not None
        mocker.patch.object(protocol._event_queue, "get", side_effect=asyncio.CancelledError)

        await protocol._process_events_loop()

    @pytest.mark.asyncio
    async def test_process_events_loop_fatal_error(
        self, protocol: _WebTransportClientProtocol, mocker: MockerFixture
    ) -> None:
        protocol.connection_made(transport=MagicMock())
        assert protocol._event_queue is not None
        mocker.patch.object(protocol._event_queue, "get", side_effect=RuntimeError("Fatal Error"))

        await protocol._process_events_loop()

    @pytest.mark.asyncio
    async def test_process_events_loop_no_queue(self, protocol: _WebTransportClientProtocol) -> None:
        protocol._event_queue = None

        await protocol._process_events_loop()

    @pytest.mark.asyncio
    async def test_quic_event_received_no_queue(self, protocol: _WebTransportClientProtocol) -> None:
        protocol._event_queue = None

        protocol.quic_event_received(StreamDataReceived(stream_id=0, data=b"test", end_stream=False))


class TestWebTransportConnection:
    @pytest.fixture
    def connection(self, mock_client_config: ClientConfig) -> WebTransportConnection:
        return WebTransportConnection(config=mock_client_config)

    @pytest.fixture
    def ready_connection(
        self,
        connection: WebTransportConnection,
        mock_quic_connection: MagicMock,
        mocker: MockerFixture,
    ) -> WebTransportConnection:
        connection._state = ConnectionState.CONNECTED
        connection._info.state = ConnectionState.CONNECTED
        connection._quic_connection = mock_quic_connection.return_value
        connection._transport = mocker.create_autospec(asyncio.DatagramTransport, instance=True)
        connection._transport.is_closing.return_value = False
        connection._transport.get_extra_info.return_value = ("127.0.0.1", 1234)
        connection._info.established_at = 1000.0

        mock_protocol = mocker.create_autospec(QuicConnectionProtocol, instance=True)
        mock_protocol.transmit = mocker.MagicMock()
        connection._protocol = mock_protocol

        protocol_handler_mock = mocker.create_autospec(WebTransportProtocolHandler, instance=True)
        protocol_handler_mock._stats = {
            "bytes_sent": 1024,
            "bytes_received": 2048,
            "errors": 1,
            "last_activity": 12345.0,
        }
        session_tracker_mock = mocker.MagicMock()
        session_tracker_mock.get_all_sessions.return_value = [
            WebTransportSessionInfo(
                session_id="session_123",
                state=SessionState.CONNECTED,
                control_stream_id=0,
                path="/",
                created_at=1000.0,
            )
        ]
        session_tracker_mock.get_session_info.return_value = WebTransportSessionInfo(
            session_id="session_123",
            state=SessionState.CONNECTED,
            control_stream_id=0,
            path="/",
            created_at=1000.0,
        )
        protocol_handler_mock._session_tracker = session_tracker_mock
        connection._protocol_handler = protocol_handler_mock

        return connection

    @pytest.fixture
    def server_connection(self, mock_server_config: ServerConfig) -> WebTransportConnection:
        return WebTransportConnection(config=mock_server_config)

    @pytest.mark.asyncio
    async def test_accept_errors(self, server_connection: WebTransportConnection) -> None:
        server_connection._state = ConnectionState.CONNECTED
        with pytest.raises(ConnectionError, match="already in state"):
            await server_connection.accept(transport=MagicMock(), protocol=MagicMock())

        server_connection._state = ConnectionState.IDLE
        server_connection._config = ClientConfig()
        with pytest.raises(ConfigurationError):
            await server_connection.accept(transport=MagicMock(), protocol=MagicMock())

    @pytest.mark.asyncio
    async def test_accept_initialization_error(
        self, server_connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(
            server_connection,
            "_initialize_protocol_handler",
            side_effect=ConnectionError("init failed"),
        )

        with pytest.raises(ConnectionError, match="init failed"):
            await server_connection.accept(transport=MagicMock(), protocol=MagicMock())

    @pytest.mark.asyncio
    async def test_accept_protocol_no_set_connection(
        self, server_connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(
            server_connection,
            "_initialize_protocol_handler",
            new_callable=mocker.AsyncMock,
        )
        mocker.patch.object(server_connection, "_start_background_tasks")
        mock_protocol = mocker.MagicMock()
        mock_protocol.transmit = mocker.MagicMock()
        mock_protocol._quic = mocker.MagicMock()
        delattr(mock_protocol, "set_connection")

        await server_connection.accept(transport=mocker.MagicMock(), protocol=mock_protocol)

        assert server_connection.is_connected
        mock_protocol.transmit.assert_called_once()

    @pytest.mark.asyncio
    async def test_accept_success(
        self,
        mock_server_config: ServerConfig,
        mocker: MockerFixture,
        mock_loop_factory: Callable[[], asyncio.AbstractEventLoop],
    ) -> None:
        mock_loop = mock_loop_factory()
        conn = WebTransportConnection(config=mock_server_config)
        mock_transport, mock_protocol = await mock_loop.create_datagram_endpoint(protocol_factory=mocker.MagicMock)
        mock_protocol.transmit = mocker.MagicMock()
        mock_protocol._quic = mocker.MagicMock()
        mock_protocol._quic.get_timer.return_value = None
        mock_protocol.set_connection = mocker.MagicMock()
        mocker.patch.object(conn, "_start_background_tasks")

        await conn.accept(transport=mock_transport, protocol=mock_protocol)

        assert conn.state == ConnectionState.CONNECTED
        mock_protocol.transmit.assert_called_once()
        await conn.close()

    def test_address_properties_none(self, connection: WebTransportConnection) -> None:
        assert connection.local_address is None
        assert connection.remote_address is None

    @pytest.mark.asyncio
    async def test_async_context_manager(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        mock_close = mocker.patch.object(connection, "close", new_callable=mocker.AsyncMock)

        async with connection:
            assert connection._closed_future is not None

        mock_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_context_manager_reentry(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        mock_close = mocker.patch.object(connection, "close", new_callable=mocker.AsyncMock)

        async with connection:
            async with connection:
                pass

        assert mock_close.call_count == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "initial_state, close_called",
        [
            (ConnectionState.CONNECTED, True),
            (ConnectionState.CLOSING, False),
            (ConnectionState.CLOSED, False),
        ],
    )
    async def test_close(
        self,
        connection: WebTransportConnection,
        mock_quic_connection: MagicMock,
        mocker: MockerFixture,
        initial_state: ConnectionState,
        close_called: bool,
    ) -> None:
        mock_protocol_handler = mocker.patch.object(connection, "_protocol_handler", autospec=True)
        mock_protocol_handler.close = mocker.AsyncMock()
        connection._state = initial_state
        if initial_state == ConnectionState.CLOSING:
            assert connection.is_closing is True
        connection._quic_connection = mock_quic_connection.return_value
        connection._closed_future = asyncio.Future()

        await connection.close(code=1, reason="test")

        if close_called:
            assert connection.state == ConnectionState.CLOSED
            mock_protocol_handler.close.assert_awaited_once()
            mock_quic_connection.return_value.close.assert_called_once_with(error_code=1, reason_phrase="test")
            assert connection._closed_future.done()
        else:
            assert connection.state == initial_state
            mock_protocol_handler.close.assert_not_awaited()
            mock_quic_connection.return_value.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_no_future(self, ready_connection: WebTransportConnection) -> None:
        ready_connection._closed_future = None

        await ready_connection.close()

        assert ready_connection._closed_future is not None

    @pytest.mark.asyncio
    async def test_close_no_handler_or_timer(self, ready_connection: WebTransportConnection) -> None:
        ready_connection._protocol_handler = None
        ready_connection._timer_handle = None

        await ready_connection.close()

        assert ready_connection.is_closed

    @pytest.mark.asyncio
    async def test_close_quic_error(
        self,
        ready_connection: WebTransportConnection,
        mock_quic_connection: MagicMock,
    ) -> None:
        mock_quic_connection.return_value.close.side_effect = RuntimeError("QUIC Error")

        await ready_connection.close()

        assert ready_connection.state == ConnectionState.CLOSED

    @pytest.mark.asyncio
    async def test_close_with_done_future(self, ready_connection: WebTransportConnection) -> None:
        future: asyncio.Future[None] = asyncio.Future()
        future.set_result(None)
        ready_connection._closed_future = future

        await ready_connection.close()

        assert ready_connection.is_closed
        assert ready_connection._closed_future.done()

    @pytest.mark.asyncio
    async def test_close_with_done_task(self, ready_connection: WebTransportConnection, mocker: MockerFixture) -> None:
        ready_connection._heartbeat_task = mocker.create_autospec(asyncio.Task, instance=True)
        cast(MagicMock, ready_connection._heartbeat_task.done).return_value = True
        mock_gather = mocker.patch("asyncio.gather", new_callable=mocker.AsyncMock)

        await ready_connection.close()

        ready_connection._heartbeat_task.cancel.assert_not_called()
        mock_gather.assert_awaited_once_with(ready_connection._heartbeat_task, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_close_with_tasks_and_timer(
        self, ready_connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        ready_connection._heartbeat_task = mocker.create_autospec(asyncio.Task, instance=True)
        cast(MagicMock, ready_connection._heartbeat_task.done).return_value = False
        ready_connection._timer_handle = mocker.create_autospec(asyncio.TimerHandle, instance=True)
        mock_gather = mocker.patch("asyncio.gather", new_callable=mocker.AsyncMock)

        await ready_connection.close()

        ready_connection._heartbeat_task.cancel.assert_called_once()
        ready_connection._timer_handle.cancel.assert_called_once()
        mock_gather.assert_awaited_once_with(ready_connection._heartbeat_task, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_create_client_connection_fails(
        self,
        mock_client_config: ClientConfig,
        mock_loop_factory: Callable[[], asyncio.AbstractEventLoop],
        mocker: MockerFixture,
    ) -> None:
        loop = mock_loop_factory()
        mocker.patch.object(
            loop,
            "create_datagram_endpoint",
            side_effect=OSError("Test network error"),
        )

        with pytest.raises(ConnectionError):
            await WebTransportConnection.create_client(config=mock_client_config, host="localhost", port=4433)

    @pytest.mark.asyncio
    async def test_create_client_handshake_fails(
        self,
        mock_client_config: ClientConfig,
        mock_protocol_handler_class: MagicMock,
        mock_loop_factory: Callable[[], asyncio.AbstractEventLoop],
        mock_quic_connection: MagicMock,
    ) -> None:
        mock_loop_factory()
        mock_protocol_handler_class.return_value.create_webtransport_session.side_effect = HandshakeError("Test Error")

        with pytest.raises(ConnectionError, match="Failed to connect"):
            await WebTransportConnection.create_client(config=mock_client_config, host="localhost", port=4433)

    @pytest.mark.asyncio
    async def test_create_client_no_protocol(
        self,
        mock_client_config: ClientConfig,
        mock_loop_factory: Callable[[], asyncio.AbstractEventLoop],
        mocker: MockerFixture,
    ) -> None:
        mock_loop_factory()
        mocker.patch.object(
            WebTransportConnection,
            "_establish_quic_connection",
            new_callable=mocker.AsyncMock,
        )

        with pytest.raises(ConnectionError, match=r"Failed to connect.*QUIC protocol was not initialized"):
            await WebTransportConnection.create_client(config=mock_client_config, host="localhost", port=4433)

    @pytest.mark.asyncio
    async def test_create_client_success(
        self,
        mocker: MockerFixture,
        mock_client_config: ClientConfig,
        mock_quic_connection: MagicMock,
        mock_protocol_handler_class: MagicMock,
        mock_loop_factory: Callable[[], asyncio.AbstractEventLoop],
    ) -> None:
        mock_loop_factory()
        emit_spy = mocker.AsyncMock()
        mocker.patch.object(WebTransportConnection, "emit", new=emit_spy)
        mocker.patch("pywebtransport.connection.connection.WebTransportConnection._start_background_tasks")
        mocker.patch.object(
            WebTransportConnection,
            "_initiate_webtransport_handshake",
            new_callable=mocker.AsyncMock,
        )

        conn = await WebTransportConnection.create_client(config=mock_client_config, host="localhost", port=4433)

        assert conn.state == ConnectionState.CONNECTED
        assert conn.is_connected is True
        assert conn.is_closing is False
        assert conn.is_closed is False
        assert conn._protocol is not None
        mock_protocol_handler_class.assert_called_with(
            quic_connection=mock_quic_connection.return_value,
            is_client=True,
            connection=conn,
            trigger_transmission=conn._protocol.transmit,
        )
        cast(AsyncMock, conn._initiate_webtransport_handshake).assert_awaited_once()
        emit_spy.assert_awaited_once()
        await conn.close()
        assert conn.is_closed is True

    @pytest.mark.asyncio
    async def test_create_server(
        self,
        mock_server_config: ServerConfig,
        mocker: MockerFixture,
        mock_loop_factory: Callable[[], asyncio.AbstractEventLoop],
    ) -> None:
        mock_loop = mock_loop_factory()
        mock_transport, mock_protocol = await mock_loop.create_datagram_endpoint(protocol_factory=mocker.MagicMock)
        mock_protocol._quic = mocker.MagicMock()

        conn = await WebTransportConnection.create_server(
            config=mock_server_config,
            transport=mock_transport,
            protocol=mock_protocol,
        )

        assert conn.state == ConnectionState.CONNECTED
        await conn.close()

    @pytest.mark.asyncio
    async def test_create_server_accept_error(
        self,
        mock_server_config: ServerConfig,
        mocker: MockerFixture,
        mock_loop_factory: Callable[[], asyncio.AbstractEventLoop],
    ) -> None:
        mock_loop = mock_loop_factory()
        mock_transport, mock_protocol = await mock_loop.create_datagram_endpoint(protocol_factory=mocker.MagicMock)
        mocker.patch(
            "pywebtransport.connection.connection.WebTransportConnection.accept",
            side_effect=ConnectionError("Accept failed"),
        )

        with pytest.raises(ConnectionError, match="Accept failed"):
            await WebTransportConnection.create_server(
                config=mock_server_config,
                transport=mock_transport,
                protocol=mock_protocol,
            )

    def test_diagnostics_no_quic_attributes(self, ready_connection: WebTransportConnection) -> None:
        assert ready_connection._quic_connection is not None
        delattr(ready_connection._quic_connection, "_rtt_smoother")
        delattr(ready_connection._quic_connection, "congestion_control")

        diagnostics = ready_connection.diagnostics

        assert diagnostics.rtt == 0.0
        assert diagnostics.cwnd == 0

    def test_diagnostics_not_connected(self, connection: WebTransportConnection) -> None:
        connection._quic_connection = None
        connection._protocol_handler = None

        diagnostics = connection.diagnostics

        assert diagnostics.stats.bytes_sent == 0
        assert diagnostics.stats.packets_sent == 0
        assert diagnostics.packet_loss_rate == 0.0

    @pytest.mark.asyncio
    async def test_establish_quic_connection_configs(
        self,
        mocker: MockerFixture,
        mock_loop_factory: Callable[[], asyncio.AbstractEventLoop],
        mock_utils_create_quic_config: MagicMock,
    ) -> None:
        mock_loop_factory()
        mock_quic_connection_cls = mocker.patch("pywebtransport.connection.connection.QuicConnection")
        config = ClientConfig(verify_mode=ssl.VerifyMode.CERT_OPTIONAL)
        config.certfile = None
        config.ca_certs = None
        conn = WebTransportConnection(config=config)

        await conn._establish_quic_connection(host="localhost", port=4433)

        assert conn._quic_connection is not None
        called_config = mock_quic_connection_cls.call_args.kwargs["configuration"]
        assert called_config.verify_mode == ssl.VerifyMode.CERT_OPTIONAL
        mock_config = mock_utils_create_quic_config.return_value
        mock_config.load_cert_chain.assert_not_called()
        mock_config.load_verify_locations.assert_not_called()

    @pytest.mark.asyncio
    async def test_establish_quic_connection_type_error(self, server_connection: WebTransportConnection) -> None:
        with pytest.raises(TypeError):
            await server_connection._establish_quic_connection(host="localhost", port=4433)

    @pytest.mark.asyncio
    async def test_forward_session_request(
        self, server_connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        mock_emit = mocker.patch.object(server_connection, "emit", new_callable=mocker.AsyncMock)
        mock_event = MagicMock(data={"test": "data"})

        await server_connection._forward_session_request_from_handler(mock_event)

        mock_emit.assert_awaited_once_with(event_type=EventType.SESSION_REQUEST, data={"test": "data"})

    @pytest.mark.asyncio
    async def test_get_rtt_errors_detailed(self, ready_connection: WebTransportConnection) -> None:
        assert ready_connection._quic_connection is not None
        mock_smoother = getattr(ready_connection._quic_connection, "_rtt_smoother")
        delattr(ready_connection._quic_connection, "_rtt_smoother")

        with pytest.raises(ConnectionError, match="RTT is not available"):
            await ready_connection._get_rtt()

        setattr(ready_connection._quic_connection, "_rtt_smoother", mock_smoother)
        delattr(getattr(ready_connection._quic_connection, "_rtt_smoother"), "latest_rtt")
        with pytest.raises(ConnectionError, match="RTT is not available"):
            await ready_connection._get_rtt()

    @pytest.mark.asyncio
    async def test_get_rtt_no_connection(self, ready_connection: WebTransportConnection) -> None:
        ready_connection._quic_connection = None

        with pytest.raises(ConnectionError, match="Connection not active or RTT is not available"):
            await ready_connection._get_rtt()

    def test_get_ready_session_id_not_connected(self, ready_connection: WebTransportConnection) -> None:
        assert ready_connection.protocol_handler is not None
        cast(
            MagicMock,
            ready_connection.protocol_handler._session_tracker.get_all_sessions,
        ).return_value[0].state = SessionState.CLOSED

        assert ready_connection.get_ready_session_id() is None

    @pytest.mark.asyncio
    async def test_heartbeat_loop(
        self,
        ready_connection: WebTransportConnection,
        mock_quic_connection: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        mocker.patch.object(
            WebTransportConnection,
            "is_connected",
            new_callable=mocker.PropertyMock,
            side_effect=[True, False],
        )
        mock_transmit = mocker.patch.object(ready_connection._protocol, "transmit")

        await ready_connection._heartbeat_loop()

        mock_quic_connection.return_value.send_ping.assert_called_once_with(uid=1)
        mock_transmit.assert_called_once()

    @pytest.mark.asyncio
    async def test_heartbeat_loop_error(self, ready_connection: WebTransportConnection, mocker: MockerFixture) -> None:
        mocker.patch.object(
            WebTransportConnection,
            "is_connected",
            new_callable=mocker.PropertyMock,
            side_effect=[True, False],
        )
        mocker.patch.object(ready_connection._protocol, "transmit", side_effect=RuntimeError("Transmit Error"))

        await ready_connection._heartbeat_loop()

    @pytest.mark.asyncio
    async def test_heartbeat_loop_no_quic(
        self, ready_connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(
            WebTransportConnection,
            "is_connected",
            new_callable=mocker.PropertyMock,
            side_effect=[True, False],
        )
        ready_connection._quic_connection = None

        await ready_connection._heartbeat_loop()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "conn_fixture, should_raise",
        [("connection", False), ("server_connection", True)],
    )
    async def test_initiate_handshake_error(
        self, request: pytest.FixtureRequest, conn_fixture: str, should_raise: bool
    ) -> None:
        connection: WebTransportConnection = request.getfixturevalue(conn_fixture)
        connection._protocol_handler = None

        with pytest.raises(HandshakeError, match="Protocol handler or config not ready"):
            await connection._initiate_webtransport_handshake(path="/")

        if should_raise:
            connection._protocol_handler = MagicMock()
            with pytest.raises(HandshakeError, match="Protocol handler or config not ready"):
                await connection._initiate_webtransport_handshake(path="/")

    @pytest.mark.asyncio
    async def test_initiate_handshake_exception(
        self, ready_connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        assert ready_connection.protocol_handler is not None
        mocker.patch.object(
            ready_connection.protocol_handler,
            "create_webtransport_session",
            side_effect=RuntimeError("test"),
        )

        with pytest.raises(HandshakeError):
            await ready_connection._initiate_webtransport_handshake(path="/")

    @pytest.mark.asyncio
    async def test_initialize_protocol_handler_no_protocol(self, ready_connection: WebTransportConnection) -> None:
        ready_connection._protocol = None

        with pytest.raises(ConnectionError, match="QUIC protocol not initialized"):
            await ready_connection._initialize_protocol_handler(is_client=True)

    @pytest.mark.asyncio
    async def test_initialize_protocol_handler_server(
        self,
        ready_connection: WebTransportConnection,
        mock_protocol_handler_class: MagicMock,
    ) -> None:
        ready_connection._protocol_handler = None

        await ready_connection._initialize_protocol_handler(is_client=False)

        assert ready_connection.protocol_handler is not None
        mock_protocol_handler_class.return_value.on.assert_called_once_with(
            event_type=EventType.SESSION_REQUEST,
            handler=ready_connection._forward_session_request_from_handler,
        )

    @pytest.mark.parametrize(
        "config_fixture_name, expected_idle_timeout",
        [("mock_client_config", None), ("mock_server_config", 60.0)],
    )
    def test_initialization(
        self,
        request: pytest.FixtureRequest,
        config_fixture_name: str,
        expected_idle_timeout: float | None,
    ) -> None:
        config = request.getfixturevalue(config_fixture_name)

        connection = WebTransportConnection(config=config)

        assert connection.state == ConnectionState.IDLE
        assert connection.connection_id.startswith("conn_")
        assert connection.idle_timeout == expected_idle_timeout

    @pytest.mark.asyncio
    async def test_monitor_health(self, ready_connection: WebTransportConnection, mocker: MockerFixture) -> None:
        mocker.patch.object(
            WebTransportConnection,
            "is_connected",
            new_callable=mocker.PropertyMock,
            side_effect=[True, False],
        )
        mock_get_rtt = mocker.patch.object(
            ready_connection,
            "_get_rtt",
            new_callable=mocker.AsyncMock,
            return_value=0.1,
        )

        await ready_connection.monitor_health(check_interval=0.01)

        mock_get_rtt.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_monitor_health_cancelled(
        self, ready_connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "asyncio.sleep",
            new_callable=mocker.AsyncMock,
            side_effect=asyncio.CancelledError,
        )
        mock_get_rtt = mocker.patch.object(
            ready_connection,
            "_get_rtt",
            new_callable=mocker.AsyncMock,
            return_value=0.1,
        )

        await ready_connection.monitor_health(check_interval=0.01)

        mock_get_rtt.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_monitor_health_error_loop(
        self, ready_connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(
            WebTransportConnection,
            "is_connected",
            new_callable=mocker.PropertyMock,
            side_effect=RuntimeError("test"),
        )

        await ready_connection.monitor_health(check_interval=0.01)

    @pytest.mark.asyncio
    async def test_monitor_health_errors(self, ready_connection: WebTransportConnection, mocker: MockerFixture) -> None:
        mocker.patch.object(
            WebTransportConnection,
            "is_connected",
            new_callable=PropertyMock,
            side_effect=[True, True, False],
        )
        mocker.patch.object(
            ready_connection,
            "_get_rtt",
            new_callable=mocker.AsyncMock,
            side_effect=[asyncio.TimeoutError, Exception("RTT Error")],
        )

        await ready_connection.monitor_health(check_interval=0.01)

    @pytest.mark.asyncio
    async def test_on_connection_lost_emits_event(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        create_task_spy = mocker.spy(asyncio, "create_task")
        connection._state = ConnectionState.CONNECTED
        exc = RuntimeError("disconnected")

        connection._on_connection_lost(exc=exc)

        create_task_spy.assert_called_once()
        task = create_task_spy.call_args.args[0]
        assert task.cr_code.co_name == "emit"

    @pytest.mark.asyncio
    async def test_on_connection_lost_idempotency(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        mock_emit = mocker.patch.object(connection, "emit", new_callable=mocker.AsyncMock)
        connection._state = ConnectionState.CLOSING

        connection._on_connection_lost(exc=None)
        await asyncio.sleep(0)

        mock_emit.assert_not_awaited()

    def test_private_schedule_transmit(
        self,
        ready_connection: WebTransportConnection,
        mock_quic_connection: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        ready_connection._timer_handle = MagicMock()
        mock_quic_connection.return_value.get_timer.return_value = None

        ready_connection._schedule_transmit()

        ready_connection._timer_handle.cancel.assert_called_once()
        ready_connection._timer_handle = None
        mock_loop = mocker.patch("asyncio.get_running_loop")
        mock_quic_connection.return_value.get_timer.return_value = 12345.0

        ready_connection._schedule_transmit()

        assert ready_connection._protocol is not None
        mock_loop.return_value.call_at.assert_called_once_with(
            when=12345.0, callback=ready_connection._protocol.transmit
        )
        mock_loop.return_value.call_at.reset_mock()
        ready_connection._state = ConnectionState.CLOSED

        ready_connection._schedule_transmit()

        mock_loop.return_value.call_at.assert_not_called()

    def test_session_methods(self, ready_connection: WebTransportConnection) -> None:
        assert len(ready_connection.get_all_sessions()) == 1
        assert ready_connection.get_ready_session_id() == "session_123"
        assert ready_connection.get_session_info(session_id="session_123") is not None

    def test_session_methods_not_ready(self, connection: WebTransportConnection) -> None:
        assert connection.get_all_sessions() == []
        assert connection.get_session_info(session_id="foo") is None

    def test_set_state_idempotency(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        logger_spy = mocker.spy(connection_module.logger, "debug")
        connection._state = ConnectionState.CONNECTED

        connection._set_state(new_state=ConnectionState.CONNECTED)

        logger_spy.assert_not_called()

    def test_start_background_tasks_no_keepalive(self, connection: WebTransportConnection) -> None:
        connection.config.keep_alive = False

        connection._start_background_tasks()

        assert connection._heartbeat_task is None

    def test_str_representation(self, ready_connection: WebTransportConnection) -> None:
        string_rep = str(ready_connection)

        assert ready_connection.connection_id[:8] in string_rep
        assert "state=connected" in string_rep
        assert "127.0.0.1:1234" in string_rep

        assert ready_connection._transport is not None
        cast(MagicMock, ready_connection._transport.get_extra_info).return_value = None
        assert "remote=unknown" in str(ready_connection)

        ready_connection._info.established_at = None
        assert "uptime=0s" in str(ready_connection)

    @pytest.mark.asyncio
    async def test_wait_closed_already_closed(self, connection: WebTransportConnection) -> None:
        connection._state = ConnectionState.CLOSED

        await connection.wait_closed()

    @pytest.mark.asyncio
    async def test_wait_closed_no_future(self, connection: WebTransportConnection) -> None:
        connection._closed_future = None

        await connection.wait_closed()

    @pytest.mark.asyncio
    async def test_wait_for_ready_session_fast_path(self, ready_connection: WebTransportConnection) -> None:
        session_id = await ready_connection.wait_for_ready_session()

        assert session_id == "session_123"
        assert ready_connection.protocol_handler
        cast(MagicMock, ready_connection.protocol_handler.on).assert_not_called()

    @pytest.mark.asyncio
    async def test_wait_for_ready_session_no_handler(self, connection: WebTransportConnection) -> None:
        with pytest.raises(ConnectionError, match="Protocol handler is not initialized"):
            await connection.wait_for_ready_session()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "event, expected_exception, expected_message",
        [
            (
                Event(type=EventType.SESSION_READY, data={"session_id": "slow_session"}),
                None,
                "slow_session",
            ),
            (
                Event(
                    type=EventType.SESSION_CLOSED,
                    data={"session_id": "s1", "reason": "closed early"},
                ),
                ClientError,
                "Session closed before ready: closed early",
            ),
            (
                Event(type=EventType.SESSION_CLOSED, data={"session_id": "s1"}),
                ClientError,
                "Session closed before ready: unknown reason",
            ),
            (
                Event(type=EventType.SESSION_READY, data={}),
                ConnectionError,
                r"Failed to get a ready session: .* missing session_id",
            ),
            (asyncio.TimeoutError, ConnectionError, "Session ready/closed timeout"),
            (
                RuntimeError("generic error"),
                ConnectionError,
                "Failed to get a ready session: generic error",
            ),
        ],
    )
    async def test_wait_for_ready_session_slow_path(
        self,
        ready_connection: WebTransportConnection,
        mocker: MockerFixture,
        event: Event | type[Exception] | Exception,
        expected_exception: type[Exception] | None,
        expected_message: str,
    ) -> None:
        assert ready_connection.protocol_handler
        mocker.patch.object(ready_connection, "get_ready_session_id", return_value=None)
        mocker.patch("asyncio.get_running_loop").create_future.return_value = asyncio.Future()
        mock_wait_for = mocker.patch("asyncio.wait_for", new_callable=mocker.AsyncMock)
        if event is asyncio.TimeoutError:
            mock_wait_for.side_effect = asyncio.TimeoutError
        elif isinstance(event, Exception):
            mock_wait_for.side_effect = event
        else:
            mock_wait_for.return_value = event

        if expected_exception:
            with pytest.raises(expected_exception, match=expected_message):
                await ready_connection.wait_for_ready_session()
        else:
            session_id = await ready_connection.wait_for_ready_session()
            assert session_id == expected_message

    @pytest.mark.asyncio
    async def test_wait_methods(self, ready_connection: WebTransportConnection, mocker: MockerFixture) -> None:
        await ready_connection.wait_ready(timeout=0.1)

        new_conn = WebTransportConnection(config=ready_connection.config)
        mock_wait_for = mocker.patch.object(new_conn, "wait_for", new_callable=mocker.AsyncMock)

        await new_conn.wait_ready(timeout=0.1)

        mock_wait_for.assert_awaited_once_with(event_type=EventType.CONNECTION_ESTABLISHED, timeout=0.1)
        unclosed_conn = WebTransportConnection(config=ready_connection.config)
        unclosed_conn._closed_future = asyncio.Future()

        wait_task = asyncio.create_task(unclosed_conn.wait_closed())
        await asyncio.sleep(0)

        assert not wait_task.done()
        unclosed_conn._closed_future.set_result(None)
        await wait_task
