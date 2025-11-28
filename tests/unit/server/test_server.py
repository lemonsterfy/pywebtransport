"""Unit tests for the pywebtransport.server.server module."""

import asyncio
from typing import Any

import pytest
from pytest_mock import MockerFixture

from pywebtransport import Event, ServerConfig, ServerError
from pywebtransport.connection import WebTransportConnection
from pywebtransport.manager import ConnectionManager, SessionManager
from pywebtransport.server import ServerDiagnostics, ServerStats, WebTransportServer
from pywebtransport.types import ConnectionState, EventType, SessionState


class TestServerDiagnostics:
    def test_issues_property_bad_path(self, mocker: MockerFixture) -> None:
        mocker.patch("pathlib.Path.exists", side_effect=OSError)
        diagnostics = ServerDiagnostics(
            stats=ServerStats(),
            connection_states={},
            session_states={},
            is_serving=True,
            certfile_path="bad",
            keyfile_path="bad",
            max_connections=100,
        )
        assert "Certificate configuration check failed" in diagnostics.issues[0]

    @pytest.mark.parametrize(
        "diag_kwargs, path_exists_side_effect, expected_issue_part",
        [
            ({"is_serving": False}, [True, True], "Server is not currently serving."),
            (
                {"stats": ServerStats(connections_accepted=89, connections_rejected=11)},
                [True, True],
                "High connection rejection rate",
            ),
            ({"connection_states": {ConnectionState.CONNECTED: 95}}, [True, True], "High connection usage"),
            ({"certfile_path": "/nonexistent/cert.pem"}, [False, True], "Certificate file not found"),
            ({"keyfile_path": "/nonexistent/key.pem"}, [True, False], "Key file not found"),
            ({}, [True, True], None),
        ],
    )
    def test_issues_property(
        self,
        mocker: MockerFixture,
        diag_kwargs: dict[str, Any],
        path_exists_side_effect: list[bool],
        expected_issue_part: str | None,
    ) -> None:
        defaults = {
            "stats": ServerStats(),
            "connection_states": {},
            "session_states": {},
            "is_serving": True,
            "certfile_path": "cert.pem",
            "keyfile_path": "key.pem",
            "max_connections": 100,
        }
        for k, v in defaults.items():
            if k not in diag_kwargs:
                diag_kwargs[k] = v

        mocker.patch("pathlib.Path.exists", side_effect=path_exists_side_effect)
        diagnostics = ServerDiagnostics(**diag_kwargs)
        issues = diagnostics.issues

        if expected_issue_part:
            assert any(expected_issue_part in issue for issue in issues)
        else:
            assert not issues


class TestWebTransportServer:
    @pytest.fixture
    def mock_connection_manager(self, mocker: MockerFixture) -> Any:
        mock_manager_class = mocker.patch("pywebtransport.server.server.ConnectionManager", autospec=True)
        return mock_manager_class.return_value

    @pytest.fixture
    def mock_create_server(self, mocker: MockerFixture) -> Any:
        mock_server = mocker.MagicMock()
        mock_server.close = mocker.MagicMock()
        mock_server._transport.get_extra_info.return_value = ("127.0.0.1", 4433)
        return mocker.patch(
            "pywebtransport.server.server.create_server", new_callable=mocker.AsyncMock, return_value=mock_server
        )

    @pytest.fixture
    def mock_quic_server(self, mock_create_server: Any) -> Any:
        return mock_create_server.return_value

    @pytest.fixture
    def mock_server_config(self, mocker: MockerFixture) -> ServerConfig:
        mocker.patch("pywebtransport.config.ServerConfig.validate")
        config = ServerConfig(
            bind_host="127.0.0.1", bind_port=4433, certfile="cert.pem", keyfile="key.pem", max_connections=10
        )
        config.connection_idle_timeout = 60.0
        return config

    @pytest.fixture
    def mock_session_manager(self, mocker: MockerFixture) -> Any:
        mock_manager_class = mocker.patch("pywebtransport.server.server.SessionManager", autospec=True)
        return mock_manager_class.return_value

    @pytest.fixture
    def mock_webtransport_connection(self, mocker: MockerFixture) -> Any:
        mock_conn = mocker.create_autospec(WebTransportConnection, instance=True)
        type(mock_conn).is_closed = mocker.PropertyMock(return_value=False)
        mock_conn.events = mocker.MagicMock()
        mock_conn.initialize = mocker.AsyncMock()
        mock_conn.connection_id = "test_conn_id"
        mocker.patch("pywebtransport.server.server.WebTransportConnection", return_value=mock_conn)
        return mock_conn

    @pytest.fixture
    def server(
        self, mock_server_config: ServerConfig, mock_connection_manager: Any, mock_session_manager: Any
    ) -> WebTransportServer:
        return WebTransportServer(config=mock_server_config)

    @pytest.fixture(autouse=True)
    def setup_common_mocks(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.server.server.get_timestamp", side_effect=[1000.0, 1005.0])
        mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        mocker.patch("pathlib.Path.exists", return_value=True)

    @pytest.mark.asyncio
    async def test_async_context_manager(
        self, server: WebTransportServer, mock_connection_manager: Any, mock_session_manager: Any, mocker: MockerFixture
    ) -> None:
        mock_close = mocker.patch.object(server, "close", new_callable=mocker.AsyncMock)

        async with server as s:
            assert s is server
            mock_connection_manager.__aenter__.assert_awaited_once()
            mock_session_manager.__aenter__.assert_awaited_once()

        mock_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_context_manager_with_exception(
        self, server: WebTransportServer, mocker: MockerFixture
    ) -> None:
        mock_close = mocker.patch.object(server, "close", new_callable=mocker.AsyncMock)

        with pytest.raises(ValueError, match="Test exception"):
            async with server:
                raise ValueError("Test exception")

        mock_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close(
        self, server: WebTransportServer, mock_quic_server: Any, mock_connection_manager: Any, mock_session_manager: Any
    ) -> None:
        await server.listen()

        await server.close()

        mock_connection_manager.shutdown.assert_awaited_once()
        mock_session_manager.shutdown.assert_awaited_once()
        mock_quic_server.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_idempotency(self, server: WebTransportServer, mock_quic_server: Any) -> None:
        await server.listen()

        await server.close()
        mock_quic_server.close.assert_called_once()

        await server.close()
        mock_quic_server.close.assert_called_once()
        assert not server.is_serving

    @pytest.mark.asyncio
    async def test_close_with_done_task(
        self, server: WebTransportServer, mock_quic_server: Any, mocker: MockerFixture
    ) -> None:
        await server.listen()
        done_task = mocker.create_autospec(asyncio.Task, instance=True)
        done_task.done.return_value = True
        not_done_task = mocker.create_autospec(asyncio.Task, instance=True)
        not_done_task.done.return_value = False
        server._background_tasks = [done_task, not_done_task]
        mock_gather = mocker.patch("asyncio.gather", new_callable=mocker.AsyncMock)

        await server.close()

        done_task.cancel.assert_not_called()
        not_done_task.cancel.assert_called_once()
        mock_gather.assert_awaited_once_with(done_task, not_done_task, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_close_with_manager_shutdown_error(
        self, server: WebTransportServer, mock_connection_manager: Any, mock_quic_server: Any
    ) -> None:
        await server.listen()
        mock_connection_manager.shutdown.side_effect = RuntimeError("Shutdown error")

        await server.close()

        mock_connection_manager.shutdown.assert_awaited_once()
        mock_quic_server.close.assert_called_once()

    def test_connection_manager_property(
        self, server: WebTransportServer, mock_connection_manager: ConnectionManager
    ) -> None:
        assert server.connection_manager is mock_connection_manager

    @pytest.mark.asyncio
    async def test_diagnostics(
        self,
        server: WebTransportServer,
        mock_connection_manager: Any,
        mock_session_manager: Any,
        mock_quic_server: Any,
        mocker: MockerFixture,
    ) -> None:
        await server.listen()
        mock_conn = mocker.MagicMock()
        mock_conn.state = ConnectionState.CONNECTED
        mock_session = mocker.MagicMock()
        mock_session.state = SessionState.CONNECTED
        mock_connection_manager.get_all_resources = mocker.AsyncMock(return_value=[mock_conn])
        mock_session_manager.get_all_resources = mocker.AsyncMock(return_value=[mock_session])

        diagnostics = await server.diagnostics()

        assert isinstance(diagnostics, ServerDiagnostics)
        assert diagnostics.stats.to_dict()["uptime"] == 5.0
        assert diagnostics.connection_states == {ConnectionState.CONNECTED: 1}
        assert diagnostics.session_states == {SessionState.CONNECTED: 1}
        assert diagnostics.is_serving is True

    @pytest.mark.asyncio
    async def test_diagnostics_before_listen(self, server: WebTransportServer) -> None:
        diagnostics = await server.diagnostics()

        assert diagnostics.stats.to_dict()["uptime"] == 0.0

    @pytest.mark.asyncio
    async def test_create_connection_callback_invalid_transport(
        self, server: WebTransportServer, mocker: MockerFixture
    ) -> None:
        mock_transport = mocker.MagicMock()
        del mock_transport.sendto
        mock_transport.is_closing.return_value = False
        mock_protocol = mocker.MagicMock()

        conn = server._create_connection_callback(protocol=mock_protocol, transport=mock_transport)

        assert conn is None
        mock_transport.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_connection_callback_exception(
        self, server: WebTransportServer, mocker: MockerFixture
    ) -> None:
        mock_transport = mocker.Mock(spec=asyncio.DatagramTransport)
        mock_transport.sendto = mocker.Mock()
        mock_transport.is_closing.return_value = False
        mock_protocol = mocker.MagicMock()
        mocker.patch("pywebtransport.server.server.WebTransportConnection", side_effect=ValueError("Init failed"))

        conn = server._create_connection_callback(protocol=mock_protocol, transport=mock_transport)

        assert conn is None
        mock_transport.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_connection_callback_exception_closing(
        self, server: WebTransportServer, mocker: MockerFixture
    ) -> None:
        mock_transport = mocker.Mock(spec=asyncio.DatagramTransport)
        mock_transport.sendto = mocker.Mock()
        mock_transport.is_closing.return_value = True
        mock_protocol = mocker.MagicMock()
        mocker.patch("pywebtransport.server.server.WebTransportConnection", side_effect=ValueError("Init failed"))

        conn = server._create_connection_callback(protocol=mock_protocol, transport=mock_transport)

        assert conn is None
        mock_transport.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_connection_callback_success(
        self, server: WebTransportServer, mocker: MockerFixture, mock_webtransport_connection: Any
    ) -> None:
        mock_transport = mocker.Mock(spec=asyncio.DatagramTransport)
        mock_transport.sendto = mocker.Mock()
        mock_protocol = mocker.MagicMock()
        mock_init_task = mocker.patch.object(server, "_initialize_and_register_connection")
        mock_create_task = mocker.patch("asyncio.create_task")

        conn = server._create_connection_callback(protocol=mock_protocol, transport=mock_transport)

        assert conn is mock_webtransport_connection
        mock_init_task.assert_called_once()
        mock_create_task.assert_called_once()

        call_args = mock_create_task.call_args
        if call_args:
            coro = call_args.kwargs.get("coro") or call_args.args[0]
            if asyncio.iscoroutine(coro):
                coro.close()

    @pytest.mark.asyncio
    async def test_initialize_and_register_connection_success(
        self,
        server: WebTransportServer,
        mock_connection_manager: Any,
        mock_webtransport_connection: Any,
        mocker: MockerFixture,
    ) -> None:
        await server._initialize_and_register_connection(connection=mock_webtransport_connection)

        mock_webtransport_connection.events.on.assert_called_once()
        mock_webtransport_connection.initialize.assert_awaited_once()
        mock_connection_manager.add_connection.assert_awaited_once_with(connection=mock_webtransport_connection)
        assert server._stats.connections_accepted == 1

    @pytest.mark.asyncio
    async def test_initialize_and_register_connection_failure(
        self,
        server: WebTransportServer,
        mock_connection_manager: Any,
        mock_webtransport_connection: Any,
        mocker: MockerFixture,
    ) -> None:
        mock_webtransport_connection.initialize.side_effect = ValueError("Init failed")

        await server._initialize_and_register_connection(connection=mock_webtransport_connection)

        assert server._stats.connections_rejected == 1
        assert server._stats.connection_errors == 1
        mock_webtransport_connection.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_initialize_and_register_connection_failure_closed(
        self,
        server: WebTransportServer,
        mock_connection_manager: Any,
        mock_webtransport_connection: Any,
        mocker: MockerFixture,
    ) -> None:
        mock_webtransport_connection.initialize.side_effect = ValueError("Init failed")
        type(mock_webtransport_connection).is_closed = mocker.PropertyMock(return_value=True)

        await server._initialize_and_register_connection(connection=mock_webtransport_connection)

        assert server._stats.connections_rejected == 1
        mock_webtransport_connection.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_initialize_and_register_connection_event_forwarding(
        self, server: WebTransportServer, mock_webtransport_connection: Any, mocker: MockerFixture
    ) -> None:
        server_emit = mocker.patch.object(server, "emit", new_callable=mocker.AsyncMock)

        await server._initialize_and_register_connection(connection=mock_webtransport_connection)

        call_args = mock_webtransport_connection.events.on.call_args
        assert call_args is not None
        handler = call_args.kwargs["handler"]

        event_data = {"session_id": "s1"}
        test_event = Event(type=EventType.SESSION_REQUEST, data=event_data)

        await handler(test_event)

        server_emit.assert_awaited_once()
        assert server_emit.await_args is not None
        emit_kwargs = server_emit.await_args.kwargs
        assert emit_kwargs["event_type"] == EventType.SESSION_REQUEST
        assert emit_kwargs["data"]["session_id"] == "s1"
        assert emit_kwargs["data"]["connection"] is mock_webtransport_connection

    @pytest.mark.asyncio
    async def test_initialize_and_register_connection_event_forwarding_nodata(
        self, server: WebTransportServer, mock_webtransport_connection: Any, mocker: MockerFixture
    ) -> None:
        server_emit = mocker.patch.object(server, "emit", new_callable=mocker.AsyncMock)
        await server._initialize_and_register_connection(connection=mock_webtransport_connection)

        call_args = mock_webtransport_connection.events.on.call_args
        assert call_args is not None
        handler = call_args.kwargs["handler"]

        test_event = Event(type=EventType.SESSION_REQUEST, data=None)
        await handler(test_event)

        server_emit.assert_awaited_once()
        assert server_emit.await_args is not None
        emit_kwargs = server_emit.await_args.kwargs
        assert emit_kwargs["data"]["connection"] is mock_webtransport_connection

    def test_init_with_custom_config(self, server: WebTransportServer, mock_server_config: ServerConfig) -> None:
        assert server.config is mock_server_config

    def test_init_with_default_config(self, mocker: MockerFixture) -> None:
        mock_config_class = mocker.patch("pywebtransport.server.server.ServerConfig", autospec=True)
        mock_config_instance = mock_config_class.return_value
        mock_config_instance.max_connections = 100
        mock_config_instance.connection_idle_timeout = 60.0
        mock_config_instance.max_sessions = 100

        WebTransportServer(config=None)

        mock_config_class.assert_called_once_with()
        mock_config_instance.validate.assert_called_once()

    @pytest.mark.asyncio
    async def test_listen_raises_error_if_already_serving(self, server: WebTransportServer) -> None:
        server._serving = True

        with pytest.raises(ServerError, match="Server is already serving"):
            await server.listen()

    @pytest.mark.asyncio
    async def test_listen_raises_error_on_create_server_failure(
        self, server: WebTransportServer, mock_create_server: Any, mocker: MockerFixture
    ) -> None:
        mock_create_server.side_effect = OSError("Address failed")

        with pytest.raises(ServerError, match="Failed to start server"):
            await server.listen()

    @pytest.mark.asyncio
    async def test_listen_success(self, server: WebTransportServer, mock_quic_server: Any) -> None:
        await server.listen()

        assert server.is_serving
        assert server.local_address == ("127.0.0.1", 4433)

    @pytest.mark.asyncio
    async def test_listen_with_explicit_host_port(self, server: WebTransportServer, mock_create_server: Any) -> None:
        await server.listen(host="1.2.3.4", port=9999)
        mock_create_server.assert_called_once()
        call_kwargs = mock_create_server.call_args.kwargs
        assert call_kwargs["host"] == "1.2.3.4"
        assert call_kwargs["port"] == 9999
        assert server.is_serving

    def test_local_address_oserror(self, server: WebTransportServer, mock_quic_server: Any) -> None:
        server._server = mock_quic_server
        mock_quic_server._transport.get_extra_info.side_effect = OSError("Transport error")
        assert server.local_address is None

    @pytest.mark.asyncio
    async def test_listen_cert_file_not_found(
        self, server: WebTransportServer, mock_create_server: Any, mocker: MockerFixture
    ) -> None:
        mock_create_server.side_effect = FileNotFoundError("Cert missing")
        with pytest.raises(ServerError, match="Certificate/Key file error"):
            await server.listen()

    @pytest.mark.asyncio
    async def test_listen_generic_exception(
        self, server: WebTransportServer, mock_create_server: Any, mocker: MockerFixture
    ) -> None:
        mock_create_server.side_effect = Exception("Generic error")
        with pytest.raises(ServerError, match="Failed to start server"):
            await server.listen()

    @pytest.mark.asyncio
    async def test_serve_forever_not_listening(self, server: WebTransportServer) -> None:
        with pytest.raises(ServerError, match="Server is not listening"):
            await server.serve_forever()

    @pytest.mark.asyncio
    async def test_serve_forever_graceful_exit(
        self, server: WebTransportServer, mock_quic_server: Any, mocker: MockerFixture
    ) -> None:
        await server.listen()

        async def trigger_shutdown() -> None:
            await asyncio.sleep(0.01)
            await server.close()

        asyncio.create_task(trigger_shutdown())
        await server.serve_forever()
        assert not server.is_serving

    @pytest.mark.asyncio
    async def test_serve_forever_keyboard_interrupt(
        self, server: WebTransportServer, mock_quic_server: Any, mocker: MockerFixture
    ) -> None:
        await server.listen()
        assert server._shutdown_event is not None

        mocker.patch.object(server._shutdown_event, "wait", side_effect=KeyboardInterrupt)

        with pytest.raises(KeyboardInterrupt):
            await server.serve_forever()

    @pytest.mark.asyncio
    async def test_serve_forever_wait_exception(
        self, server: WebTransportServer, mock_quic_server: Any, mocker: MockerFixture
    ) -> None:
        """Test serve_forever handling of non-cancellation errors during wait."""
        await server.listen()
        assert server._shutdown_event is not None
        mock_logger_error = mocker.patch("pywebtransport.server.server.logger.error")

        mocker.patch.object(server._shutdown_event, "wait", side_effect=ValueError("Wait error"))

        await server.serve_forever()

        mock_logger_error.assert_called_with("Error during serve_forever wait: %s", mocker.ANY)

    def test_session_manager_property(self, server: WebTransportServer, mock_session_manager: SessionManager) -> None:
        assert server.session_manager is mock_session_manager

    def test_str_representation(
        self, server: WebTransportServer, mock_quic_server: Any, mock_connection_manager: Any, mock_session_manager: Any
    ) -> None:
        server._serving = True
        server._server = mock_quic_server
        mock_connection_manager.__len__.return_value = 5
        mock_session_manager.__len__.return_value = 2

        representation = str(server)

        assert "status=serving" in representation
        assert "address=127.0.0.1:4433" in representation
        assert "connections=5" in representation
        assert "sessions=2" in representation

    def test_str_representation_not_serving(self, server: WebTransportServer) -> None:
        representation = str(server)

        assert "status=stopped" in representation
        assert "address=unknown" in representation
