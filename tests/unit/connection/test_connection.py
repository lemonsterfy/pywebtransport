"""Unit tests for the pywebtransport.connection.connection module."""

import asyncio
from typing import Any, Generator

import pytest
from pytest_mock import MockerFixture

from pywebtransport import (
    ClientConfig,
    ConfigurationError,
    ConnectionError,
    ConnectionState,
    Event,
    EventType,
    HandshakeError,
    ServerConfig,
    SessionState,
)
from pywebtransport.connection import ConnectionInfo, WebTransportConnection


@pytest.fixture
def mock_client_config(mocker: MockerFixture) -> ClientConfig:
    mocker.patch("pywebtransport.config.ClientConfig.validate", return_value=None)
    return ClientConfig(certfile="test.crt", keyfile="test.key", ca_certs="ca.crt")


@pytest.fixture
def mock_server_config(mocker: MockerFixture) -> ServerConfig:
    mocker.patch("pywebtransport.config.ServerConfig.validate", return_value=None)
    return ServerConfig(certfile="test.crt", keyfile="test.key")


@pytest.fixture
def mock_quic_connection(mocker: MockerFixture) -> Any:
    mock_cls = mocker.patch("pywebtransport.connection.connection.QuicConnection", autospec=True)
    mock_instance = mock_cls.return_value
    mock_instance._rtt_smoother = mocker.MagicMock()
    mock_instance._rtt_smoother.latest_rtt = 0.1
    mock_instance.datagrams_to_send.return_value = []
    mock_instance.get_timer.return_value = None
    return mock_instance


@pytest.fixture
def mock_protocol_handler(mocker: MockerFixture) -> Any:
    mock_cls = mocker.patch(
        "pywebtransport.connection.connection.WebTransportProtocolHandler",
        autospec=True,
    )
    mock_instance = mock_cls.return_value
    mock_instance.stats = {
        "bytes_sent": 1024,
        "bytes_received": 2048,
        "errors": 1,
        "last_activity": 12345.0,
    }
    mock_instance.create_webtransport_session.return_value = (
        "session_123",
        mocker.MagicMock(),
    )
    return mock_instance


@pytest.fixture(autouse=True)
def mock_asyncio_infra(
    mocker: MockerFixture,
) -> Generator[None, None, None]:
    mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
    mocker.patch("asyncio.create_task", side_effect=lambda coro, **kwargs: asyncio.Task(coro, **kwargs))
    yield


@pytest.fixture
def mock_loop(mocker: MockerFixture) -> Any:
    loop = mocker.patch("asyncio.get_running_loop").return_value
    mock_endpoint = mocker.create_autospec(asyncio.DatagramTransport, instance=True)
    mock_protocol_instance = mocker.MagicMock()
    loop.create_datagram_endpoint = mocker.AsyncMock(return_value=(mock_endpoint, mock_protocol_instance))
    loop.time.return_value = 1000.0
    return loop


@pytest.fixture
def mock_utils(mocker: MockerFixture) -> None:
    mocker.patch("pywebtransport.connection.connection.get_timestamp", return_value=12345.0)
    mocker.patch(
        "pywebtransport.connection.connection.create_quic_configuration",
        return_value=mocker.MagicMock(),
    )


class TestConnectionInfo:
    def test_initialization(self) -> None:
        info = ConnectionInfo(connection_id="test", state=ConnectionState.IDLE)
        assert info.connection_id == "test"
        assert info.state == ConnectionState.IDLE
        assert info.uptime == 0.0

    def test_uptime(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.connection.connection.get_timestamp", return_value=110.0)
        info = ConnectionInfo(connection_id="test", state=ConnectionState.CONNECTED)
        assert info.uptime == 0.0
        info.established_at = 100.0
        assert info.uptime == 10.0
        info.closed_at = 105.0
        assert info.uptime == 5.0

    def test_to_dict(self) -> None:
        info = ConnectionInfo(connection_id="test", state=ConnectionState.IDLE)
        info_dict = info.to_dict()
        assert info_dict["connection_id"] == "test"
        assert info_dict["state"] == ConnectionState.IDLE


class TestWebTransportConnection:
    @pytest.fixture
    def connection(self, mock_client_config: ClientConfig) -> WebTransportConnection:
        return WebTransportConnection(config=mock_client_config)

    def test_initialization(self, connection: WebTransportConnection) -> None:
        assert connection.state == ConnectionState.IDLE
        assert not connection.is_connected
        assert connection.config is not None
        assert connection.connection_id.startswith("conn_")

    @pytest.mark.parametrize(
        "state, expected",
        [
            (ConnectionState.CONNECTED, True),
            (ConnectionState.IDLE, False),
            (ConnectionState.CLOSING, False),
        ],
    )
    def test_is_connected_property(
        self, connection: WebTransportConnection, state: ConnectionState, expected: bool
    ) -> None:
        connection._state = state
        assert connection.is_connected is expected

    def test_info_property_full(self, connection: WebTransportConnection, mock_quic_connection: Any) -> None:
        mock_quic_connection._packets_sent = 500
        mock_quic_connection._packets_received = 400
        connection._quic_connection = mock_quic_connection
        info = connection.info
        assert info.packets_sent == 500
        assert info.packets_received == 400

    def test_address_properties_no_transport(self, connection: WebTransportConnection) -> None:
        assert connection.local_address is None
        assert connection.remote_address is None

    def test_string_representation(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        assert "remote=unknown" in str(connection)
        mock_transport = mocker.MagicMock()
        mock_transport.get_extra_info.return_value = ("127.0.0.1", 1234)
        connection._transport = mock_transport
        assert "remote=127.0.0.1:1234" in str(connection)

    def test_set_state_idempotency(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        mock_logger_debug = mocker.patch("pywebtransport.connection.connection.logger.debug")
        connection._state = ConnectionState.CONNECTED
        connection._set_state(ConnectionState.CONNECTED)
        mock_logger_debug.assert_not_called()

    @pytest.mark.asyncio
    async def test_aenter_aexit(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        mock_close = mocker.patch.object(connection, "close", new_callable=mocker.AsyncMock)
        async with connection as conn:
            assert conn is connection
        mock_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_success(
        self,
        connection: WebTransportConnection,
        mocker: MockerFixture,
        mock_quic_connection: Any,
        mock_protocol_handler: Any,
        mock_loop: Any,
        mock_utils: None,
    ) -> None:
        emit_spy = mocker.AsyncMock()
        connection.on(EventType.CONNECTION_ESTABLISHED, emit_spy)
        await connection.connect(host="localhost", port=4433)
        assert connection.state == ConnectionState.CONNECTED
        assert connection.is_connected
        mock_loop.create_datagram_endpoint.assert_awaited_once()
        mock_quic_connection.connect.assert_called_once()
        assert mock_protocol_handler.create_webtransport_session.called
        emit_spy.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_already_connected(self, connection: WebTransportConnection) -> None:
        connection._state = ConnectionState.CONNECTING
        with pytest.raises(ConnectionError, match="already in state"):
            await connection.connect(host="localhost", port=4433)

    @pytest.mark.asyncio
    async def test_connect_with_server_config(self, mock_server_config: ServerConfig) -> None:
        connection = WebTransportConnection(config=mock_server_config)
        with pytest.raises(ConfigurationError):
            await connection.connect(host="localhost", port=4433)

    @pytest.mark.asyncio
    async def test_connect_handshake_fails(
        self,
        connection: WebTransportConnection,
        mock_protocol_handler: Any,
        mock_loop: Any,
        mock_utils: None,
    ) -> None:
        mock_protocol_handler.create_webtransport_session.side_effect = HandshakeError("Test Handshake Error")
        with pytest.raises(ConnectionError, match="Failed to connect"):
            await connection.connect(host="localhost", port=4433)
        assert connection.is_closed

    @pytest.mark.asyncio
    async def test_accept_success(
        self,
        mock_server_config: ServerConfig,
        mocker: MockerFixture,
        mock_loop: Any,
        mock_utils: None,
    ) -> None:
        connection = WebTransportConnection(config=mock_server_config)
        mock_transport = mocker.create_autospec(asyncio.DatagramTransport)
        mock_protocol = mocker.MagicMock()
        mock_protocol._quic = mocker.MagicMock()
        mock_protocol._quic.get_timer.return_value = None
        await connection.accept(transport=mock_transport, protocol=mock_protocol)
        assert connection.state == ConnectionState.CONNECTED
        assert connection.is_connected
        assert connection._transport is mock_transport

    @pytest.mark.asyncio
    async def test_accept_failure_during_init(
        self, mock_server_config: ServerConfig, mocker: MockerFixture, mock_loop: Any
    ) -> None:
        connection = WebTransportConnection(config=mock_server_config)
        mocker.patch.object(connection, "_initialize_protocol_handler", side_effect=RuntimeError("Init failed"))
        with pytest.raises(ConnectionError, match="Failed to accept connection: Init failed"):
            await connection.accept(transport=mocker.MagicMock(), protocol=mocker.MagicMock())
        assert connection.is_closed

    @pytest.mark.asyncio
    async def test_close(
        self,
        connection: WebTransportConnection,
        mock_quic_connection: Any,
        mocker: MockerFixture,
        mock_utils: None,
    ) -> None:
        connection._state = ConnectionState.CONNECTED

        async def dummy_coro() -> None:
            pass

        mock_task = asyncio.create_task(dummy_coro())
        mocker.patch.object(mock_task, "done", return_value=False)
        connection._heartbeat_task = mock_task
        timer_handle = mocker.patch.object(connection, "_timer_handle", new=mocker.MagicMock())
        connection._quic_connection = mock_quic_connection
        await connection.close(code=1, reason="test")
        assert connection.state == ConnectionState.CLOSED
        assert mock_task.cancelled()
        timer_handle.cancel.assert_called_once()
        mock_quic_connection.close.assert_called_once_with(error_code=1, reason_phrase="test")
        assert connection._closed_future.done()

    @pytest.mark.asyncio
    async def test_close_idempotency(self, connection: WebTransportConnection) -> None:
        connection._state = ConnectionState.CLOSING
        await connection.close()
        connection._state = ConnectionState.CLOSED
        await connection.close()

    @pytest.mark.asyncio
    async def test_wait_ready_fast_path(self, connection: WebTransportConnection) -> None:
        connection._state = ConnectionState.CONNECTED
        await connection.wait_ready(timeout=0)

    @pytest.mark.asyncio
    async def test_wait_ready_timeout(self, connection: WebTransportConnection) -> None:
        with pytest.raises(asyncio.TimeoutError):
            await connection.wait_ready(timeout=0.01)

    @pytest.mark.asyncio
    async def test_wait_closed_fast_path(self, connection: WebTransportConnection) -> None:
        connection._state = ConnectionState.CLOSED
        await connection.wait_closed()

    @pytest.mark.asyncio
    async def test_wait_for_ready_session_fast_path(
        self, connection: WebTransportConnection, mocker: MockerFixture, mock_protocol_handler: Any
    ) -> None:
        mock_session_info = mocker.MagicMock()
        mock_session_info.state = SessionState.CONNECTED
        mock_session_info.session_id = "session_ready"
        mock_protocol_handler.get_all_sessions.return_value = [mock_session_info]
        connection._protocol_handler = mock_protocol_handler
        session_id = await connection.wait_for_ready_session(timeout=1)
        assert session_id == "session_ready"

    @pytest.mark.asyncio
    async def test_wait_for_ready_session_slow_path(
        self,
        connection: WebTransportConnection,
        mock_protocol_handler: Any,
        mocker: MockerFixture,
    ) -> None:
        mock_protocol_handler.get_all_sessions.return_value = []
        mock_event = mocker.MagicMock(data={"session_id": "session_waited"})
        mock_protocol_handler.wait_for = mocker.AsyncMock(return_value=mock_event)
        connection._protocol_handler = mock_protocol_handler
        session_id = await connection.wait_for_ready_session(timeout=1)
        assert session_id == "session_waited"
        mock_protocol_handler.wait_for.assert_awaited_once_with(
            EventType.SESSION_READY, timeout=1, condition=mocker.ANY
        )

    @pytest.mark.asyncio
    async def test_wait_for_ready_session_timeout(
        self, connection: WebTransportConnection, mock_protocol_handler: Any
    ) -> None:
        mock_protocol_handler.get_all_sessions.return_value = []
        mock_protocol_handler.wait_for.side_effect = asyncio.TimeoutError
        connection._protocol_handler = mock_protocol_handler
        with pytest.raises(ConnectionError, match="Session ready timeout"):
            await connection.wait_for_ready_session(timeout=0.1)

    @pytest.mark.asyncio
    async def test_heartbeat_loop(
        self,
        connection: WebTransportConnection,
        mock_quic_connection: Any,
        mocker: MockerFixture,
    ) -> None:
        mocker.patch.object(
            WebTransportConnection,
            "is_connected",
            new_callable=mocker.PropertyMock,
            side_effect=[True, False],
        )
        mock_transmit = mocker.patch.object(connection, "_transmit")
        connection._quic_connection = mock_quic_connection
        await connection._heartbeat_loop()
        mock_quic_connection.send_ping.assert_called_once_with(uid=1)
        mock_transmit.assert_called_once()

    @pytest.mark.asyncio
    async def test_heartbeat_loop_exception(
        self, connection: WebTransportConnection, mock_quic_connection: Any, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(
            WebTransportConnection, "is_connected", new_callable=mocker.PropertyMock, side_effect=[True, False]
        )
        mock_quic_connection.send_ping.side_effect = ValueError("Ping failed")
        connection._quic_connection = mock_quic_connection
        await connection._heartbeat_loop()
        mock_quic_connection.send_ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_transmit_fails(
        self, connection: WebTransportConnection, mock_loop: Any, mocker: MockerFixture
    ) -> None:
        mock_quic = mocker.MagicMock()
        mock_quic.datagrams_to_send.return_value = [(b"data", ("addr", 1))]
        mock_quic.get_timer.return_value = None
        mock_transport, _ = await mock_loop.create_datagram_endpoint()
        mock_transport.sendto.side_effect = OSError("Socket closed")
        connection._quic_connection = mock_quic
        connection._transport = mock_transport
        connection._transmit()
        mock_transport.sendto.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_connection_lost_idempotency(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        mock_close = mocker.patch.object(connection, "close", new_callable=mocker.AsyncMock)
        connection._state = ConnectionState.CLOSING
        connection._on_connection_lost(None)
        mock_close.assert_not_awaited()
        connection._state = ConnectionState.CLOSED
        connection._on_connection_lost(None)
        mock_close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_forward_session_request_from_handler(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        mock_emit = mocker.patch.object(connection, "emit", new_callable=mocker.AsyncMock)
        event_data = {"path": "/test"}
        event = Event(type=EventType.SESSION_REQUEST, data=event_data)
        await connection._forward_session_request_from_handler(event)
        mock_emit.assert_awaited_once_with(EventType.SESSION_REQUEST, data=event_data)

    @pytest.mark.asyncio
    async def test_diagnose_issues_healthy(self, connection: WebTransportConnection, mock_quic_connection: Any) -> None:
        connection._state = ConnectionState.CONNECTED
        connection._quic_connection = mock_quic_connection
        diagnosis = await connection.diagnose_issues()
        assert diagnosis["is_connected"] is True
        assert not diagnosis["issues"]
        assert not diagnosis["recommendations"]
        assert "ping_rtt" in diagnosis

    @pytest.mark.asyncio
    async def test_diagnose_issues_not_connected_async(
        self, connection: WebTransportConnection, mock_utils: None
    ) -> None:
        diagnosis = await connection.diagnose_issues()
        assert diagnosis["is_connected"] is False
        assert "Connection not established" in diagnosis["issues"]

    @pytest.mark.asyncio
    async def test_diagnose_issues_high_error_count(
        self,
        connection: WebTransportConnection,
        mock_protocol_handler: Any,
        mock_quic_connection: Any,
    ) -> None:
        connection._state = ConnectionState.CONNECTED
        connection._quic_connection = mock_quic_connection
        connection._protocol_handler = mock_protocol_handler
        mock_protocol_handler.stats["errors"] = 100
        diagnosis = await connection.diagnose_issues()
        assert "High error count: 100" in diagnosis["issues"]

    @pytest.mark.asyncio
    async def test_diagnose_issues_packet_loss_and_rtt_timeout(
        self, connection: WebTransportConnection, mock_quic_connection: Any, mocker: MockerFixture
    ) -> None:
        connection._state = ConnectionState.CONNECTED
        connection._quic_connection = mock_quic_connection
        mock_quic_connection._packets_sent = 2000
        mock_quic_connection._packets_received = 0
        mocker.patch.object(connection, "_get_rtt", new_callable=mocker.AsyncMock, side_effect=asyncio.TimeoutError)
        diagnosis = await connection.diagnose_issues()
        assert "Data is being sent, but no packets are being received" in diagnosis["issues"]
        assert "RTT check timed out" in diagnosis["issues"]

    @pytest.mark.asyncio
    async def test_monitor_health_success_and_timeout(
        self, connection: WebTransportConnection, mocker: MockerFixture, mock_quic_connection: Any
    ) -> None:
        connection._state = ConnectionState.CONNECTED
        connection._quic_connection = mock_quic_connection
        mock_get_rtt = mocker.patch.object(
            connection, "_get_rtt", new_callable=mocker.AsyncMock, side_effect=[0.1, asyncio.TimeoutError]
        )
        await connection.monitor_health(check_interval=0.01, rtt_timeout=1.0)
        assert mock_get_rtt.call_count == 2

    @pytest.mark.asyncio
    async def test_get_rtt_unavailable(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        mock_quic = mocker.MagicMock(spec=object())
        connection._quic_connection = mock_quic
        with pytest.raises(ConnectionError, match="RTT is not available"):
            await connection._get_rtt()

    @pytest.mark.asyncio
    async def test_aexit_with_exception(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        mock_close = mocker.patch.object(connection, "close", new_callable=mocker.AsyncMock)
        with pytest.raises(ValueError, match="test error"):
            async with connection:
                raise ValueError("test error")
        mock_close.assert_awaited_once()
