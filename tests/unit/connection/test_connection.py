"""Unit tests for the pywebtransport.connection.connection module."""

import asyncio
from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import MagicMock

import pytest
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.connection import QuicConnection
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
from pywebtransport.config import ProxyConfig
from pywebtransport.connection import ConnectionInfo, WebTransportConnection


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
def mock_proxy_config(mock_client_config: ClientConfig) -> ClientConfig:
    mock_client_config.proxy = ProxyConfig(url="https://proxy.example.com:4433")
    return mock_client_config


@pytest.fixture
def mock_h3_engine(mocker: MockerFixture) -> Any:
    mock_cls = mocker.patch("pywebtransport.connection.connection.WebTransportH3Engine", autospec=True)
    mock_instance = mock_cls.return_value
    mock_instance.handle_event = mocker.AsyncMock(return_value=[])
    return mock_instance


@pytest.fixture
def mock_loop_factory(mocker: MockerFixture) -> Callable[[], asyncio.AbstractEventLoop]:
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
def mock_protocol_handler(mocker: MockerFixture) -> Any:
    mock_cls = mocker.patch("pywebtransport.connection.connection.WebTransportProtocolHandler", autospec=True)
    mock_instance = mock_cls.return_value
    mock_instance.stats = {"bytes_sent": 1024, "bytes_received": 2048, "errors": 1, "last_activity": 12345.0}
    mock_instance.create_webtransport_session = mocker.AsyncMock(return_value=("session_123", mocker.MagicMock()))
    mock_instance.close = mocker.AsyncMock()
    return mock_instance


@pytest.fixture
def mock_quic_connection(mocker: MockerFixture) -> MagicMock:
    mock_instance = mocker.create_autospec(QuicConnection, instance=True)
    mock_instance._rtt_smoother = mocker.MagicMock()
    mock_instance._rtt_smoother.latest_rtt = 0.1
    mock_instance.datagrams_to_send.return_value = []
    mock_instance.get_timer.return_value = None
    mock_loss = mocker.MagicMock()
    mock_loss.get_probe_timeout.return_value = 1.0
    mock_instance._loss = mock_loss

    mock_cls = mocker.patch("pywebtransport.connection.connection.QuicConnection", autospec=True)
    mock_cls.return_value = mock_instance
    return mock_cls


@pytest.fixture
def mock_server_config(mocker: MockerFixture) -> ServerConfig:
    mocker.patch("pywebtransport.config.ServerConfig.validate", return_value=None)
    config = ServerConfig(certfile="test.crt", keyfile="test.key")
    config.connection_idle_timeout = 60.0
    return config


@pytest.fixture
def mock_utils_create_quic_config(mocker: MockerFixture) -> MagicMock:
    mock_quic_config = mocker.MagicMock()
    mock_quic_config.load_cert_chain = mocker.MagicMock()
    mock_quic_config.load_verify_locations = mocker.MagicMock()
    mock_quic_config.max_datagram_size = 65536
    mock_quic_config.congestion_control_algorithm = "reno"
    mock_quic_config.idle_timeout = 30.0
    return mocker.patch(
        "pywebtransport.connection.connection.create_quic_configuration",
        return_value=mock_quic_config,
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
        assert connection.last_activity_time == 0.0
        assert connection.idle_timeout is None
        assert connection._proxy_addr is None

    def test_initialization_server(self, mock_server_config: ServerConfig) -> None:
        connection = WebTransportConnection(config=mock_server_config)

        assert connection.idle_timeout == 60.0

    @pytest.mark.asyncio
    async def test_create_client_direct_path(self, mocker: MockerFixture, mock_client_config: ClientConfig) -> None:
        mock_direct = mocker.patch(
            "pywebtransport.connection.connection.WebTransportConnection._create_direct_client",
            new_callable=mocker.AsyncMock,
        )
        mock_proxied = mocker.patch(
            "pywebtransport.connection.connection.WebTransportConnection._create_proxied_client",
            new_callable=mocker.AsyncMock,
        )

        await WebTransportConnection.create_client(config=mock_client_config, host="localhost", port=4433)

        mock_direct.assert_awaited_once()
        mock_proxied.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_client_proxied_path(self, mocker: MockerFixture, mock_proxy_config: ClientConfig) -> None:
        mock_direct = mocker.patch(
            "pywebtransport.connection.connection.WebTransportConnection._create_direct_client",
            new_callable=mocker.AsyncMock,
        )
        mock_proxied = mocker.patch(
            "pywebtransport.connection.connection.WebTransportConnection._create_proxied_client",
            new_callable=mocker.AsyncMock,
        )

        await WebTransportConnection.create_client(config=mock_proxy_config, host="localhost", port=4433)

        mock_direct.assert_not_called()
        mock_proxied.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_server_factory(self, mocker: MockerFixture, mock_server_config: ServerConfig) -> None:
        mock_accept = mocker.patch(
            "pywebtransport.connection.connection.WebTransportConnection.accept", new_callable=mocker.AsyncMock
        )
        mock_transport = mocker.MagicMock()
        mock_protocol = mocker.MagicMock()

        conn = None
        try:
            conn = await WebTransportConnection.create_server(
                config=mock_server_config, transport=mock_transport, protocol=mock_protocol
            )
            mock_accept.assert_awaited_once_with(transport=mock_transport, protocol=mock_protocol)
            assert isinstance(conn, WebTransportConnection)
        finally:
            if conn:
                await conn.close()

    @pytest.mark.parametrize(
        "state, expected",
        [
            (ConnectionState.CONNECTED, True),
            (ConnectionState.IDLE, False),
            (ConnectionState.CLOSING, False),
            (ConnectionState.CLOSED, False),
        ],
    )
    def test_is_connected_property(
        self, connection: WebTransportConnection, state: ConnectionState, expected: bool
    ) -> None:
        connection._state = state

        assert connection.is_connected is expected

    @pytest.mark.parametrize(
        "state, expected",
        [
            (ConnectionState.CLOSING, True),
            (ConnectionState.CONNECTED, False),
            (ConnectionState.IDLE, False),
            (ConnectionState.CLOSED, False),
        ],
    )
    def test_is_closing_property(
        self, connection: WebTransportConnection, state: ConnectionState, expected: bool
    ) -> None:
        connection._state = state

        assert connection.is_closing is expected

    def test_info_property_scenarios(
        self,
        connection: WebTransportConnection,
        mock_quic_connection: Any,
        mock_protocol_handler: Any,
    ) -> None:
        info = connection.info
        assert info.bytes_sent == 0
        assert info.packets_sent == 0

        connection._quic_connection = mock_quic_connection.return_value
        mock_quic_connection.return_value._packets_sent = 500
        mock_quic_connection.return_value._packets_received = 400
        info = connection.info
        assert info.packets_sent == 500
        assert info.packets_received == 400
        assert info.bytes_sent == 0

        connection._protocol_handler = mock_protocol_handler
        info = connection.info
        assert info.packets_sent == 500
        assert info.bytes_sent == 1024

    def test_address_properties(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        assert connection.local_address is None
        assert connection.remote_address is None

        mock_transport = mocker.MagicMock()
        mock_transport.get_extra_info.side_effect = lambda name, default=None: {
            "sockname": ("127.0.0.1", 12345),
            "peername": ("1.1.1.1", 443),
        }.get(name, default)
        connection._transport = mock_transport
        assert connection.local_address == ("127.0.0.1", 12345)
        assert connection.remote_address == ("1.1.1.1", 443)

    def test_string_representation(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        assert "remote=unknown" in str(connection)

        mock_transport = mocker.MagicMock()

        def get_extra_info_side_effect(name: str, default: Any = None) -> Any:
            if name == "sockname":
                return ("192.168.1.1", 54321)
            if name == "peername":
                return ("8.8.8.8", 443)
            return default

        mock_transport.get_extra_info.side_effect = get_extra_info_side_effect
        connection._transport = mock_transport
        mocker.patch("pywebtransport.connection.connection.get_timestamp", return_value=1005.0)
        connection._info.established_at = 1000.0

        assert "remote=8.8.8.8:443" in str(connection)
        assert "uptime=5.0s" in str(connection)

    @pytest.mark.asyncio
    async def test_aenter_aexit(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        mock_close = mocker.patch.object(connection, "close", new_callable=mocker.AsyncMock)

        async with connection as conn:
            assert conn is connection

        mock_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_aexit_with_exception(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        mock_close = mocker.patch.object(connection, "close", new_callable=mocker.AsyncMock)

        with pytest.raises(ValueError, match="test error"):
            async with connection:
                raise ValueError("test error")

        mock_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close(
        self,
        connection: WebTransportConnection,
        mock_quic_connection: Any,
        mock_protocol_handler: Any,
        mocker: MockerFixture,
    ) -> None:
        connection._state = ConnectionState.CONNECTED
        connection._protocol_handler = mock_protocol_handler
        mock_super_close = mocker.patch("pywebtransport.events.EventEmitter.close", new_callable=mocker.AsyncMock)
        mock_emit = mocker.patch.object(connection, "emit", new_callable=mocker.AsyncMock)
        mock_task = asyncio.create_task(asyncio.sleep(0))
        mocker.patch.object(mock_task, "done", return_value=False)
        connection._heartbeat_task = mock_task
        timer_handle = mocker.patch.object(connection, "_timer_handle", new=mocker.MagicMock())
        connection._quic_connection = mock_quic_connection.return_value
        connection._closed_future = asyncio.Future()

        await connection.close(code=1, reason="test")

        assert connection.state == ConnectionState.CLOSED
        assert mock_task.cancelled()
        timer_handle.cancel.assert_called_once()
        mock_protocol_handler.close.assert_awaited_once()
        mock_quic_connection.return_value.close.assert_called_once_with(error_code=1, reason_phrase="test")
        mock_super_close.assert_awaited_once()
        mock_emit.assert_awaited_with(
            event_type=EventType.CONNECTION_CLOSED, data={"connection_id": connection.connection_id}
        )
        assert connection._closed_future.done()

    @pytest.mark.asyncio
    async def test_close_with_exception(self, connection: WebTransportConnection, mock_quic_connection: Any) -> None:
        connection._state = ConnectionState.CONNECTED
        connection._quic_connection = mock_quic_connection.return_value
        mock_quic_connection.return_value.close.side_effect = RuntimeError("QUIC error")

        await connection.close()

        assert connection.state == ConnectionState.CLOSED

    @pytest.mark.asyncio
    async def test_close_idempotency(self, connection: WebTransportConnection) -> None:
        connection._state = ConnectionState.CLOSING
        await connection.close()
        connection._state = ConnectionState.CLOSED
        await connection.close()

    @pytest.mark.asyncio
    async def test_create_direct_client_success(
        self,
        mocker: MockerFixture,
        mock_client_config: ClientConfig,
        mock_quic_connection: Any,
        mock_protocol_handler: Any,
        mock_loop_factory: Any,
        mock_utils_create_quic_config: MagicMock,
    ) -> None:
        mock_loop = mock_loop_factory()
        emit_spy = mocker.AsyncMock()
        mocker.patch.object(
            WebTransportConnection, "on", side_effect=lambda event_type, handler: emit_spy.on(event_type, handler)
        )
        mocker.patch.object(WebTransportConnection, "emit", new=emit_spy)
        mocker.patch("pywebtransport.connection.connection.WebTransportConnection._start_background_tasks")

        conn = None
        try:
            conn = await WebTransportConnection.create_client(config=mock_client_config, host="localhost", port=4433)
            assert conn.state == ConnectionState.CONNECTED
            assert conn.is_connected
            mock_utils_create_quic_config.assert_called_once_with(is_client=True, **mock_client_config.to_dict())
            mock_loop.create_datagram_endpoint.assert_called_once()
            mock_quic_connection.return_value.connect.assert_called_once()
            mock_protocol_handler.create_webtransport_session.assert_awaited_once()
            emit_spy.assert_awaited_once()
        finally:
            if conn:
                await conn.close()

    @pytest.mark.asyncio
    async def test_create_direct_client_handshake_fails(
        self,
        mock_client_config: ClientConfig,
        mock_protocol_handler: Any,
        mock_loop_factory: Any,
        mock_quic_connection: Any,
        mock_utils_create_quic_config: MagicMock,
    ) -> None:
        mock_loop_factory()
        mock_protocol_handler.create_webtransport_session.side_effect = HandshakeError(message="Test Handshake Error")

        with pytest.raises(ConnectionError, match="Failed to connect"):
            await WebTransportConnection.create_client(config=mock_client_config, host="localhost", port=4433)

    @pytest.mark.asyncio
    async def test_create_direct_client_endpoint_fails(
        self, mock_client_config: ClientConfig, mock_loop_factory: Any, mock_utils_create_quic_config: MagicMock
    ) -> None:
        mock_loop = mock_loop_factory()
        mock_loop.create_datagram_endpoint.side_effect = OSError("Cannot assign requested address")

        with pytest.raises(ConnectionError, match="QUIC create_datagram_endpoint failed"):
            await WebTransportConnection.create_client(config=mock_client_config, host="localhost", port=4433)

    @pytest.mark.asyncio
    async def test_create_proxied_client_success(
        self,
        mocker: MockerFixture,
        mock_proxy_config: ClientConfig,
        mock_protocol_handler: Any,
        mock_loop_factory: Any,
        mock_quic_connection: Any,
        mock_utils_create_quic_config: MagicMock,
    ) -> None:
        mock_loop = mock_loop_factory()
        mock_handshake = mocker.patch(
            "pywebtransport.connection.connection.WebTransportConnection._perform_proxy_connect_handshake",
            new_callable=mocker.AsyncMock,
        )

        conn = None
        try:
            conn = await WebTransportConnection.create_client(config=mock_proxy_config, host="localhost", port=4433)
            assert conn.is_connected
            assert conn._proxy_addr == ("proxy.example.com", 4433)
            mock_handshake.assert_awaited_once_with(
                config=mock_proxy_config,
                target_host="localhost",
                target_port=4433,
                proxy_addr=("proxy.example.com", 4433),
            )
            mock_loop.create_datagram_endpoint.assert_called_once()
            _, kwargs = mock_loop.create_datagram_endpoint.call_args
            assert kwargs["remote_addr"] == ("proxy.example.com", 4433)
        finally:
            if conn:
                await conn.close()

    @pytest.mark.asyncio
    async def test_create_proxied_client_handshake_fails(
        self, mocker: MockerFixture, mock_proxy_config: ClientConfig
    ) -> None:
        mocker.patch(
            "pywebtransport.connection.connection.WebTransportConnection._perform_proxy_connect_handshake",
            new_callable=mocker.AsyncMock,
            side_effect=HandshakeError(message="Proxy auth failed"),
        )
        with pytest.raises(HandshakeError, match="Proxy auth failed"):
            await WebTransportConnection.create_client(config=mock_proxy_config, host="localhost", port=4433)

    @pytest.mark.asyncio
    async def test_perform_proxy_connect_handshake_success(
        self, mocker: MockerFixture, mock_proxy_config: ClientConfig, mock_h3_engine: Any, mock_loop_factory: Any
    ) -> None:
        mock_loop = mock_loop_factory()

        async def mock_wait_for_side_effect(fut: asyncio.Future, *args: Any, **kwargs: Any) -> None:
            if not fut.done():
                fut.set_result(None)

        mock_wait_for = mocker.patch(
            "pywebtransport.connection.connection.asyncio.wait_for", side_effect=mock_wait_for_side_effect
        )

        await WebTransportConnection._perform_proxy_connect_handshake(
            config=mock_proxy_config,
            target_host="localhost",
            target_port=4433,
            proxy_addr=("proxy.example.com", 4433),
        )

        mock_loop.create_datagram_endpoint.assert_called_once()
        mock_h3_engine.send_headers.assert_called_once()
        mock_wait_for.assert_called_once()

    @pytest.mark.asyncio
    async def test_perform_proxy_connect_handshake_failure_status(
        self, mocker: MockerFixture, mock_proxy_config: ClientConfig, mock_h3_engine: Any, mock_loop_factory: Any
    ) -> None:
        mock_loop_factory()

        async def mock_wait_for_side_effect(fut: asyncio.Future, *args: Any, **kwargs: Any) -> None:
            if not fut.done():
                fut.set_exception(HandshakeError(message="Proxy returned status 502"))
            await fut

        mocker.patch("pywebtransport.connection.connection.asyncio.wait_for", side_effect=mock_wait_for_side_effect)

        with pytest.raises(HandshakeError, match="Proxy returned status 502"):
            await WebTransportConnection._perform_proxy_connect_handshake(
                config=mock_proxy_config,
                target_host="localhost",
                target_port=4433,
                proxy_addr=("proxy.example.com", 4433),
            )

    @pytest.mark.asyncio
    async def test_perform_proxy_connect_handshake_timeout(
        self, mocker: MockerFixture, mock_proxy_config: ClientConfig, mock_h3_engine: Any, mock_loop_factory: Any
    ) -> None:
        mock_loop_factory()
        mocker.patch("pywebtransport.connection.connection.asyncio.wait_for", side_effect=asyncio.TimeoutError)
        with pytest.raises(asyncio.TimeoutError):
            await WebTransportConnection._perform_proxy_connect_handshake(
                config=mock_proxy_config,
                target_host="localhost",
                target_port=4433,
                proxy_addr=("proxy.example.com", 4433),
            )

    @pytest.mark.asyncio
    async def test_accept_success(
        self, mock_server_config: ServerConfig, mocker: MockerFixture, mock_loop_factory: Any
    ) -> None:
        mock_loop = mock_loop_factory()
        conn = WebTransportConnection(config=mock_server_config)
        mock_transport, mock_protocol = await mock_loop.create_datagram_endpoint(protocol_factory=mocker.MagicMock)
        mock_protocol._quic = mocker.MagicMock()
        mock_protocol._quic.get_timer.return_value = None
        mock_protocol.set_connection = mocker.MagicMock()
        mocker.patch.object(conn, "_start_background_tasks")

        try:
            await conn.accept(transport=mock_transport, protocol=mock_protocol)

            assert conn.state == ConnectionState.CONNECTED
            assert conn.is_connected
            assert conn._transport is mock_transport
            mock_protocol.set_connection.assert_called_once_with(connection=conn)
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_accept_protocol_without_set_connection(
        self, mock_server_config: ServerConfig, mocker: MockerFixture
    ) -> None:
        conn = WebTransportConnection(config=mock_server_config)
        mock_transport = mocker.create_autospec(asyncio.DatagramTransport)
        mock_protocol = mocker.create_autospec(QuicConnectionProtocol, instance=True)
        mock_protocol._quic = mocker.MagicMock()
        mock_protocol._quic.get_timer.return_value = None
        mocker.patch.object(conn, "_start_background_tasks")
        try:
            await conn.accept(transport=mock_transport, protocol=mock_protocol)
            assert conn.is_connected
            assert not hasattr(mock_protocol, "set_connection") or not mock_protocol.set_connection.called
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_accept_already_started(self, mock_server_config: ServerConfig, mocker: MockerFixture) -> None:
        conn = WebTransportConnection(config=mock_server_config)
        conn._state = ConnectionState.CONNECTED

        with pytest.raises(ConnectionError, match="already in state"):
            await conn.accept(transport=mocker.MagicMock(), protocol=mocker.MagicMock())

    @pytest.mark.asyncio
    async def test_accept_with_client_config(self, mock_client_config: ClientConfig, mocker: MockerFixture) -> None:
        conn = WebTransportConnection(config=mock_client_config)
        with pytest.raises(ConfigurationError):
            await conn.accept(transport=mocker.MagicMock(), protocol=mocker.MagicMock())

    @pytest.mark.asyncio
    async def test_accept_failure_during_init(
        self, mock_server_config: ServerConfig, mocker: MockerFixture, mock_loop_factory: Any
    ) -> None:
        mock_loop_factory()
        conn = WebTransportConnection(config=mock_server_config)
        mocker.patch.object(conn, "_initialize_protocol_handler", side_effect=RuntimeError("Init failed"))

        with pytest.raises(ConnectionError, match="Failed to accept connection: Init failed"):
            await conn.accept(transport=mocker.MagicMock(), protocol=mocker.MagicMock())

        assert conn.is_closed

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
    async def test_wait_closed_no_future(self, connection: WebTransportConnection) -> None:
        connection._closed_future = None
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
        self, connection: WebTransportConnection, mock_protocol_handler: Any, mocker: MockerFixture
    ) -> None:
        mock_protocol_handler.get_all_sessions.return_value = []
        mock_event = mocker.MagicMock(data={"session_id": "session_waited"})
        mock_protocol_handler.wait_for.return_value = mock_event
        connection._protocol_handler = mock_protocol_handler
        session_id = await connection.wait_for_ready_session(timeout=1)
        assert session_id == "session_waited"
        mock_protocol_handler.wait_for.assert_awaited_once_with(
            event_type=EventType.SESSION_READY, timeout=1, condition=mocker.ANY
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
    async def test_wait_for_ready_session_no_handler(self, connection: WebTransportConnection) -> None:
        with pytest.raises(ConnectionError, match="Protocol handler is not initialized"):
            await connection.wait_for_ready_session()

    @pytest.mark.asyncio
    async def test_wait_for_ready_session_generic_error(
        self, connection: WebTransportConnection, mock_protocol_handler: Any
    ) -> None:
        mock_protocol_handler.get_all_sessions.return_value = []
        mock_protocol_handler.wait_for.side_effect = ValueError("test error")
        connection._protocol_handler = mock_protocol_handler
        with pytest.raises(ConnectionError, match="Failed to get a ready session: test error"):
            await connection.wait_for_ready_session()

    def test_set_state_idempotency(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        mock_logger_debug = mocker.patch("pywebtransport.connection.connection.logger.debug")
        connection._state = ConnectionState.CONNECTED
        connection._set_state(new_state=ConnectionState.CONNECTED)
        mock_logger_debug.assert_not_called()

    @pytest.mark.asyncio
    async def test_heartbeat_loop(
        self, connection: WebTransportConnection, mock_quic_connection: Any, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(
            WebTransportConnection, "is_connected", new_callable=mocker.PropertyMock, side_effect=[True, False]
        )
        mock_transmit = mocker.patch.object(connection, "_transmit")
        connection._quic_connection = mock_quic_connection.return_value

        await connection._heartbeat_loop()

        mock_quic_connection.return_value.send_ping.assert_called_once_with(uid=1)
        mock_transmit.assert_called_once()

    @pytest.mark.asyncio
    async def test_heartbeat_loop_no_quic(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        def run_loop_and_set_quic_to_none() -> Generator[bool, None, None]:
            yield True
            connection._quic_connection = None
            yield True
            yield False

        side_effect_gen = run_loop_and_set_quic_to_none()
        mocker.patch.object(
            WebTransportConnection, "is_connected", new_callable=mocker.PropertyMock, side_effect=side_effect_gen
        )
        mock_transmit = mocker.patch.object(connection, "_transmit")
        mock_quic = mocker.create_autospec(QuicConnection, instance=True)
        connection._quic_connection = mock_quic

        await connection._heartbeat_loop()

        mock_quic.send_ping.assert_called_once_with(uid=1)
        mock_transmit.assert_called()

    @pytest.mark.asyncio
    async def test_heartbeat_loop_exception(
        self, connection: WebTransportConnection, mock_quic_connection: Any, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(
            WebTransportConnection, "is_connected", new_callable=mocker.PropertyMock, side_effect=[True, False]
        )
        mock_quic_connection.return_value.send_ping.side_effect = ValueError("Ping failed")
        connection._quic_connection = mock_quic_connection.return_value

        await connection._heartbeat_loop()

        mock_quic_connection.return_value.send_ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_schedule_transmit_logic(
        self, connection: WebTransportConnection, mock_quic_connection: Any, mock_loop_factory: Any
    ) -> None:
        mock_loop = mock_loop_factory()
        connection._quic_connection = mock_quic_connection.return_value

        mock_quic_connection.return_value.get_timer.return_value = 1001.0
        connection._schedule_transmit()
        mock_loop.call_at.assert_called_once_with(when=1001.0, callback=connection._transmit)

        connection._schedule_transmit()
        assert connection._timer_handle is not None
        mock_timer_handle: Any = mock_loop.call_at.return_value
        mock_timer_handle.cancel.assert_called_once()

        mock_loop.call_at.reset_mock()
        connection._state = ConnectionState.CLOSED
        connection._schedule_transmit()
        mock_loop.call_at.assert_not_called()

    @pytest.mark.asyncio
    async def test_transmit_with_proxy(
        self, connection: WebTransportConnection, mock_loop_factory: Any, mocker: MockerFixture
    ) -> None:
        mock_loop = mock_loop_factory()
        mock_quic = mocker.MagicMock()
        proxy_addr = ("10.0.0.1", 8888)
        target_addr = ("8.8.8.8", 443)
        mock_quic.datagrams_to_send.return_value = [(b"data", target_addr)]
        transport, _ = await mock_loop.create_datagram_endpoint(protocol_factory=mocker.MagicMock)
        transport.is_closing.return_value = False
        connection._quic_connection = mock_quic
        connection._transport = transport
        connection._proxy_addr = proxy_addr

        connection._transmit()

        transport.sendto.assert_called_once_with(data=b"data", addr=proxy_addr)

    @pytest.mark.asyncio
    async def test_transmit_fails(
        self, connection: WebTransportConnection, mock_loop_factory: Any, mocker: MockerFixture
    ) -> None:
        mock_loop = mock_loop_factory()
        mock_quic = mocker.MagicMock()
        mock_quic.datagrams_to_send.return_value = [(b"data", ("addr", 1))]
        mock_quic.get_timer.return_value = None
        transport, _ = await mock_loop.create_datagram_endpoint(protocol_factory=mocker.MagicMock)
        transport.is_closing.return_value = False
        transport.sendto.side_effect = OSError("Socket closed")
        connection._quic_connection = mock_quic
        connection._transport = transport

        connection._transmit()

        transport.sendto.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_connection_lost(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        mock_close = mocker.patch.object(connection, "close", new_callable=mocker.AsyncMock)
        connection._state = ConnectionState.CONNECTED

        connection._on_connection_lost(exc=RuntimeError("disconnected"))
        await asyncio.sleep(0)

        mock_close.assert_called_once_with(reason="Connection lost: disconnected")

    @pytest.mark.asyncio
    async def test_on_connection_lost_idempotency(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        mock_close = mocker.patch.object(connection, "close", new_callable=mocker.AsyncMock)
        connection._state = ConnectionState.CLOSING

        connection._on_connection_lost(exc=None)

        mock_close.assert_not_called()
        connection._state = ConnectionState.CLOSED
        connection._on_connection_lost(exc=None)
        mock_close.assert_not_called()

    @pytest.mark.asyncio
    async def test_forward_session_request_from_handler(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        mock_emit = mocker.patch.object(connection, "emit", new_callable=mocker.AsyncMock)
        event_data = {"path": "/test"}
        event = Event(type=EventType.SESSION_REQUEST, data=event_data)

        await connection._forward_session_request_from_handler(event=event)

        mock_emit.assert_awaited_once_with(event_type=EventType.SESSION_REQUEST, data=event_data)

    @pytest.mark.asyncio
    async def test_initiate_handshake_no_handler(self, connection: WebTransportConnection) -> None:
        with pytest.raises(HandshakeError, match="Protocol handler or config not ready"):
            await connection._initiate_webtransport_handshake(path="/")

    @pytest.mark.asyncio
    async def test_initiate_handshake_exception(
        self, connection: WebTransportConnection, mock_protocol_handler: Any
    ) -> None:
        connection._protocol_handler = mock_protocol_handler
        mock_protocol_handler.create_webtransport_session.side_effect = RuntimeError("Session creation failed")

        with pytest.raises(HandshakeError, match="WebTransport handshake failed"):
            await connection._initiate_webtransport_handshake(path="/")

    @pytest.mark.asyncio
    async def test_client_protocol_connection_lost(
        self,
        mock_client_config: ClientConfig,
        mocker: MockerFixture,
        mock_loop_factory: Any,
        mock_quic_connection: Any,
        mock_utils_create_quic_config: MagicMock,
    ) -> None:
        mock_loop = mock_loop_factory()
        real_protocol_instance = None

        async def endpoint_factory_executor(*args: Any, **kwargs: Any) -> tuple[Any, Any]:
            protocol_factory = args[0]
            nonlocal real_protocol_instance
            real_protocol_instance = protocol_factory()
            transport = mocker.MagicMock()
            real_protocol_instance.connection_made(transport)
            return transport, real_protocol_instance

        mock_loop.create_datagram_endpoint.side_effect = endpoint_factory_executor
        mock_on_lost = mocker.patch("pywebtransport.connection.connection.WebTransportConnection._on_connection_lost")
        mocker.patch("pywebtransport.connection.connection.WebTransportConnection._start_background_tasks")

        with pytest.raises(ConnectionError):
            await WebTransportConnection.create_client(config=mock_client_config, host="localhost", port=4433)

        assert real_protocol_instance is not None
        exc = RuntimeError("disconnected")
        real_protocol_instance.connection_lost(exc)
        mock_on_lost.assert_called_once_with(exc)

    def test_get_summary(self, connection: WebTransportConnection, mock_protocol_handler: Any) -> None:
        connection._protocol_handler = mock_protocol_handler

        summary = connection.get_summary()

        assert summary["id"] == connection.connection_id
        assert summary["bytes_sent"] == 1024

    def test_get_ready_session_id_no_handler(self, connection: WebTransportConnection) -> None:
        session_id = connection.get_ready_session_id()

        assert session_id is None

    @pytest.mark.asyncio
    async def test_monitor_health_success_and_timeout(
        self, connection: WebTransportConnection, mocker: MockerFixture, mock_quic_connection: Any
    ) -> None:
        connection._state = ConnectionState.CONNECTED
        connection._quic_connection = mock_quic_connection.return_value
        mock_get_rtt = mocker.patch.object(
            connection, "_get_rtt", new_callable=mocker.AsyncMock, side_effect=[0.1, asyncio.TimeoutError]
        )

        await connection.monitor_health(check_interval=0.01, rtt_timeout=1.0)

        assert mock_get_rtt.call_count == 2

    @pytest.mark.asyncio
    async def test_monitor_health_exception(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        connection._state = ConnectionState.CONNECTED
        mock_get_rtt = mocker.patch.object(
            connection, "_get_rtt", new_callable=mocker.AsyncMock, side_effect=ValueError("RTT fail")
        )

        await connection.monitor_health(check_interval=0.01)

        mock_get_rtt.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_rtt_unavailable(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        mock_quic = mocker.MagicMock(spec=object())
        connection._quic_connection = mock_quic

        with pytest.raises(ConnectionError, match="RTT is not available"):
            await connection._get_rtt()

    @pytest.mark.asyncio
    async def test_diagnose_issues_healthy(self, connection: WebTransportConnection, mock_quic_connection: Any) -> None:
        connection._state = ConnectionState.CONNECTED
        connection._quic_connection = mock_quic_connection.return_value

        diagnosis = await connection.diagnose_issues()

        assert diagnosis["is_connected"] is True
        assert not diagnosis["issues"]
        assert not diagnosis["recommendations"]
        assert "ping_rtt" in diagnosis

    @pytest.mark.asyncio
    async def test_diagnose_issues_not_connected(self, connection: WebTransportConnection) -> None:
        diagnosis = await connection.diagnose_issues()

        assert diagnosis["is_connected"] is False
        assert "Connection not established" in diagnosis["issues"]

    @pytest.mark.asyncio
    async def test_diagnose_issues_high_error_count(
        self, connection: WebTransportConnection, mock_protocol_handler: Any, mock_quic_connection: Any
    ) -> None:
        connection._state = ConnectionState.CONNECTED
        connection._quic_connection = mock_quic_connection.return_value
        connection._protocol_handler = mock_protocol_handler
        mock_protocol_handler.stats["errors"] = 100

        diagnosis = await connection.diagnose_issues()

        assert "High error count: 100" in diagnosis["issues"]

    @pytest.mark.asyncio
    async def test_diagnose_issues_stale_connection(
        self,
        connection: WebTransportConnection,
        mock_protocol_handler: Any,
        mock_quic_connection: Any,
        mock_loop_factory: Any,
    ) -> None:
        mock_loop = mock_loop_factory()
        connection._state = ConnectionState.CONNECTED
        connection._quic_connection = mock_quic_connection.return_value
        connection._protocol_handler = mock_protocol_handler
        mock_loop.time.return_value = 10000.0
        mock_protocol_handler.stats["last_activity"] = 9000.0

        diagnosis = await connection.diagnose_issues()

        assert "Connection appears stale (no activity in 5+ minutes)" in diagnosis["issues"]

    @pytest.mark.asyncio
    async def test_diagnose_issues_packet_loss_and_rtt_timeout(
        self, connection: WebTransportConnection, mock_quic_connection: Any, mocker: MockerFixture
    ) -> None:
        connection._state = ConnectionState.CONNECTED
        connection._quic_connection = mock_quic_connection.return_value
        mock_quic_connection.return_value._packets_sent = 2000
        mock_quic_connection.return_value._packets_received = 0
        mocker.patch.object(connection, "_get_rtt", new_callable=mocker.AsyncMock, side_effect=asyncio.TimeoutError)

        diagnosis = await connection.diagnose_issues()

        assert "Data is being sent, but no packets are being received" in diagnosis["issues"]
        assert "RTT check timed out" in diagnosis["issues"]

    @pytest.mark.asyncio
    async def test_diagnose_issues_high_rtt(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        connection._state = ConnectionState.CONNECTED
        mocker.patch.object(connection, "_get_rtt", new_callable=mocker.AsyncMock, return_value=2.0)

        diagnosis = await connection.diagnose_issues()

        assert "High latency (RTT): 2000.0ms" in diagnosis["issues"]

    @pytest.mark.asyncio
    async def test_diagnose_issues_rtt_check_fails(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        connection._state = ConnectionState.CONNECTED
        mocker.patch.object(connection, "_get_rtt", new_callable=mocker.AsyncMock, side_effect=ValueError("RTT error"))

        diagnosis = await connection.diagnose_issues()

        assert "RTT check failed: RTT error" in diagnosis["issues"]
