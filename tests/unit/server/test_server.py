"""Unit tests for the pywebtransport.server.server module."""

import asyncio
import weakref
from typing import Any, NoReturn, cast

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ConnectionError, Event, ServerConfig, ServerError
from pywebtransport.connection import WebTransportConnection
from pywebtransport.manager import ConnectionManager, SessionManager
from pywebtransport.server import ServerDiagnostics, ServerStats, WebTransportServer
from pywebtransport.server.server import WebTransportServerProtocol
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
        assert "Certificate configuration appears invalid." in diagnostics.issues

    @pytest.mark.parametrize(
        "diag_kwargs, path_exists_side_effect, expected_issue_part",
        [
            ({"is_serving": False}, [True, True], "Server is not currently serving."),
            (
                {"stats": ServerStats(connections_accepted=89, connections_rejected=11)},
                [True, True],
                "High connection rejection rate",
            ),
            (
                {"connection_states": {ConnectionState.CONNECTED: 95}},
                [True, True],
                "High connection usage",
            ),
            (
                {"certfile_path": "/nonexistent/cert.pem"},
                [False, True],
                "Certificate file not found",
            ),
            (
                {"keyfile_path": "/nonexistent/key.pem"},
                [True, False],
                "Key file not found",
            ),
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
        if "stats" not in diag_kwargs:
            diag_kwargs["stats"] = ServerStats()
        if "connection_states" not in diag_kwargs:
            diag_kwargs["connection_states"] = {}
        if "session_states" not in diag_kwargs:
            diag_kwargs["session_states"] = {}
        if "is_serving" not in diag_kwargs:
            diag_kwargs["is_serving"] = True
        if "certfile_path" not in diag_kwargs:
            diag_kwargs["certfile_path"] = "cert.pem"
        if "keyfile_path" not in diag_kwargs:
            diag_kwargs["keyfile_path"] = "key.pem"
        if "max_connections" not in diag_kwargs:
            diag_kwargs["max_connections"] = 100

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
    def mock_quic_server(self, mocker: MockerFixture) -> Any:
        mock_server = mocker.MagicMock()
        mock_server.close = mocker.MagicMock()
        mock_server.wait_closed = mocker.AsyncMock()
        mock_server._transport.get_extra_info.return_value = ("127.0.0.1", 4433)
        mocker.patch(
            "pywebtransport.server.server.quic_serve",
            new_callable=mocker.AsyncMock,
            return_value=mock_server,
        )
        return mock_server

    @pytest.fixture
    def mock_server_config(self, mocker: MockerFixture) -> ServerConfig:
        mocker.patch("pywebtransport.config.ServerConfig.validate")
        config = ServerConfig(
            bind_host="127.0.0.1",
            bind_port=4433,
            certfile="cert.pem",
            keyfile="key.pem",
            max_connections=10,
        )
        config.connection_cleanup_interval = 60.0
        config.connection_idle_check_interval = 15.0
        config.connection_idle_timeout = 60.0
        config.session_cleanup_interval = 300.0
        return config

    @pytest.fixture
    def mock_session_manager(self, mocker: MockerFixture) -> Any:
        mock_manager_class = mocker.patch("pywebtransport.server.server.SessionManager", autospec=True)
        return mock_manager_class.return_value

    @pytest.fixture
    def mock_webtransport_connection(self, mocker: MockerFixture) -> Any:
        mock_conn = mocker.create_autospec(WebTransportConnection, instance=True)
        type(mock_conn).is_closed = mocker.PropertyMock(return_value=False)
        mocker.patch("pywebtransport.server.server.WebTransportConnection", return_value=mock_conn)
        return mock_conn

    @pytest.fixture
    def server(
        self,
        mock_server_config: ServerConfig,
        mock_connection_manager: Any,
        mock_session_manager: Any,
    ) -> WebTransportServer:
        return WebTransportServer(config=mock_server_config)

    @pytest.fixture(autouse=True)
    def setup_common_mocks(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.server.server.create_quic_configuration")
        mocker.patch("pywebtransport.server.server.get_timestamp", side_effect=[1000.0, 1005.0])
        mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)

    @pytest.mark.asyncio
    async def test_async_context_manager(
        self,
        server: WebTransportServer,
        mock_connection_manager: Any,
        mock_session_manager: Any,
        mocker: MockerFixture,
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
        self,
        server: WebTransportServer,
        mock_quic_server: Any,
        mock_connection_manager: Any,
        mock_session_manager: Any,
    ) -> None:
        await server.listen()

        await server.close()

        mock_connection_manager.shutdown.assert_awaited_once()
        mock_session_manager.shutdown.assert_awaited_once()
        mock_quic_server.close.assert_called_once()
        mock_quic_server.wait_closed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_idempotency(self, server: WebTransportServer, mock_quic_server: Any) -> None:
        await server.listen()

        await server.close()
        mock_quic_server.close.assert_called_once()

        await server.close()
        mock_quic_server.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_no_wait_closed(self, server: WebTransportServer, mock_quic_server: Any) -> None:
        """Test close when the server object doesn't have wait_closed."""
        await server.listen()
        delattr(mock_quic_server, "wait_closed")

        await server.close()

        mock_quic_server.close.assert_called_once()

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
        self,
        server: WebTransportServer,
        mock_connection_manager: Any,
        mock_quic_server: Any,
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
        assert diagnostics.stats.uptime == 5.0
        assert diagnostics.connection_states == {ConnectionState.CONNECTED: 1}
        assert diagnostics.session_states == {SessionState.CONNECTED: 1}
        assert diagnostics.is_serving is True

    @pytest.mark.asyncio
    async def test_diagnostics_before_listen(self, server: WebTransportServer) -> None:
        diagnostics = await server.diagnostics()

        assert diagnostics.stats.uptime == 0.0

    @pytest.mark.asyncio
    async def test_handle_new_connection_creation_failure(
        self, server: WebTransportServer, mocker: MockerFixture
    ) -> None:
        """Test connection handling when WebTransportConnection instantiation fails."""
        mocker.patch(
            "pywebtransport.server.server.WebTransportConnection",
            side_effect=ValueError("Init failed"),
        )
        mock_transport = mocker.MagicMock()
        mock_transport.close = mocker.MagicMock()

        await server._handle_new_connection(transport=mock_transport, protocol=mocker.MagicMock())

        mock_transport.close.assert_called_once()
        assert server._stats.connections_rejected == 1
        assert server._stats.connection_errors == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "event_data, server_ref_valid, conn_ref_valid, should_emit",
        [
            ({"path": "/test"}, True, True, True),
            ({"path": "/test"}, False, True, False),
            ({"path": "/test"}, True, False, False),
            ("not_a_dict", True, True, False),
        ],
    )
    async def test_handle_new_connection_event_forwarding(
        self,
        server: WebTransportServer,
        mock_webtransport_connection: Any,
        mocker: MockerFixture,
        event_data: Any,
        server_ref_valid: bool,
        conn_ref_valid: bool,
        should_emit: bool,
    ) -> None:
        server_emitter_mock = mocker.patch.object(server, "emit", new_callable=mocker.AsyncMock)
        captured_handler = mocker.MagicMock()
        mock_webtransport_connection.on.side_effect = lambda *, event_type, handler: captured_handler.set(handler)
        original_server_ref = weakref.ref(server) if server_ref_valid else lambda: None
        original_conn_ref = weakref.ref(mock_webtransport_connection) if conn_ref_valid else lambda: None
        mocker.patch("weakref.ref", side_effect=[original_server_ref, original_conn_ref])
        await server._handle_new_connection(transport=mocker.MagicMock(), protocol=mocker.MagicMock())
        event_handler = captured_handler.set.call_args[0][0]

        await event_handler(Event(type=EventType.SESSION_REQUEST, data=event_data))

        if should_emit:
            server_emitter_mock.assert_awaited_once()
            args, kwargs = server_emitter_mock.call_args
            assert kwargs["event_type"] == EventType.SESSION_REQUEST
            assert kwargs["data"]["connection"] is mock_webtransport_connection
        else:
            server_emitter_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_new_connection_failure(
        self,
        server: WebTransportServer,
        mock_connection_manager: Any,
        mock_webtransport_connection: Any,
        mocker: MockerFixture,
    ) -> None:
        mock_webtransport_connection.accept.side_effect = ConnectionError(message="Accept failed")

        await server._handle_new_connection(transport=mocker.MagicMock(), protocol=mocker.MagicMock())

        mock_webtransport_connection.close.assert_awaited_once()
        mock_connection_manager.add_connection.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_new_connection_failure_already_closed(
        self,
        server: WebTransportServer,
        mock_webtransport_connection: Any,
        mocker: MockerFixture,
    ) -> None:
        mock_webtransport_connection.accept.side_effect = ConnectionError(message="Accept failed")
        type(mock_webtransport_connection).is_closed = mocker.PropertyMock(return_value=True)

        await server._handle_new_connection(transport=mocker.MagicMock(), protocol=mocker.MagicMock())

        mock_webtransport_connection.close.assert_not_called()
        assert server._stats.connections_rejected == 1

    @pytest.mark.asyncio
    async def test_handle_new_connection_success(
        self,
        server: WebTransportServer,
        mock_connection_manager: Any,
        mock_webtransport_connection: Any,
        mocker: MockerFixture,
    ) -> None:
        mock_protocol = mocker.create_autospec(WebTransportServerProtocol, instance=True)

        await server._handle_new_connection(transport=mocker.MagicMock(), protocol=mock_protocol)

        mock_webtransport_connection.accept.assert_awaited_once()
        mock_connection_manager.add_connection.assert_awaited_once_with(connection=mock_webtransport_connection)

    @pytest.mark.asyncio
    async def test_handle_new_connection_transport_close_fails(
        self,
        server: WebTransportServer,
        mock_webtransport_connection: Any,
        mocker: MockerFixture,
    ) -> None:
        mock_transport = mocker.MagicMock()
        mock_transport.close.side_effect = OSError("Transport busy")
        mock_webtransport_connection.accept.side_effect = ConnectionError(message="Accept failed")

        await server._handle_new_connection(transport=mock_transport, protocol=mocker.MagicMock())

        assert server._stats.connection_errors == 1

    def test_init_with_custom_config(self, server: WebTransportServer, mock_server_config: ServerConfig) -> None:
        assert server.config is mock_server_config

    def test_init_with_default_config(self, mocker: MockerFixture) -> None:
        mock_config_class = mocker.patch("pywebtransport.server.server.ServerConfig", autospec=True)
        mock_config_instance = mock_config_class.return_value

        WebTransportServer(config=None)

        mock_config_class.assert_called_once_with()
        mock_config_instance.validate.assert_called_once()

    @pytest.mark.asyncio
    async def test_listen_raises_error_if_already_serving(self, server: WebTransportServer) -> None:
        server._serving = True

        with pytest.raises(ServerError, match="Server is already serving"):
            await server.listen()

    @pytest.mark.asyncio
    async def test_listen_raises_error_on_quic_serve_failure(
        self, server: WebTransportServer, mocker: MockerFixture
    ) -> None:
        mocker.patch("pywebtransport.server.server.quic_serve", side_effect=OSError("Address failed"))

        with pytest.raises(ServerError, match="Failed to start server"):
            await server.listen()

    @pytest.mark.asyncio
    async def test_listen_success(self, server: WebTransportServer, mock_quic_server: Any) -> None:
        await server.listen()

        assert server.is_serving
        assert server.local_address == ("127.0.0.1", 4433)

    @pytest.mark.asyncio
    async def test_listen_with_ca_certs(self, server: WebTransportServer, mocker: MockerFixture) -> None:
        class StopTest(BaseException):
            pass

        mock_create_quic_config = mocker.patch("pywebtransport.server.server.create_quic_configuration")
        mock_quic_config = mock_create_quic_config.return_value
        mocker.patch("pywebtransport.server.server.quic_serve", side_effect=StopTest)
        server.config.ca_certs = "/path/to/ca.pem"

        with pytest.raises(StopTest):
            await server.listen()

        mock_quic_config.load_verify_locations.assert_called_once_with(cafile="/path/to/ca.pem")

    @pytest.mark.asyncio
    async def test_serve_forever_graceful_exit(
        self, server: WebTransportServer, mock_quic_server: Any, mocker: MockerFixture
    ) -> None:
        """Test that serve_forever loop exits gracefully when _serving is set to False."""
        delattr(mock_quic_server, "wait_closed")
        await server.listen()
        mock_close = mocker.patch.object(server, "close", new_callable=mocker.AsyncMock)
        original_sleep = asyncio.sleep

        async def sleep_then_stop(delay: float) -> None:
            server._serving = False
            await original_sleep(0)

        mocker.patch("asyncio.sleep", side_effect=sleep_then_stop)
        await server.serve_forever()
        mock_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_serve_forever_keyboard_interrupt(
        self, server: WebTransportServer, mock_quic_server: Any, mocker: MockerFixture
    ) -> None:
        mock_quic_server.wait_closed.side_effect = KeyboardInterrupt
        await server.listen()
        mock_close = mocker.patch.object(server, "close", new_callable=mocker.AsyncMock)

        await server.serve_forever()

        mock_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_serve_forever_loop(
        self, server: WebTransportServer, mock_quic_server: Any, mocker: MockerFixture
    ) -> None:
        del mock_quic_server.wait_closed

        async def stop_server_and_raise(*args: Any, **kwargs: Any) -> NoReturn:
            server._serving = False
            raise asyncio.CancelledError

        mock_sleep = mocker.patch("asyncio.sleep", side_effect=stop_server_and_raise)
        await server.listen()

        await server.serve_forever()

        mock_sleep.assert_awaited_once_with(3600)

    @pytest.mark.asyncio
    async def test_serve_forever_no_wait_closed(
        self, server: WebTransportServer, mock_quic_server: Any, mocker: MockerFixture
    ) -> None:
        del mock_quic_server.wait_closed
        mocker.patch("asyncio.sleep", side_effect=asyncio.CancelledError)
        await server.listen()

        await server.serve_forever()

        mock_quic_server.close.assert_called_once()

    def test_session_manager_property(self, server: WebTransportServer, mock_session_manager: SessionManager) -> None:
        assert server.session_manager is mock_session_manager

    def test_str_representation(
        self,
        server: WebTransportServer,
        mock_quic_server: Any,
        mock_connection_manager: Any,
        mock_session_manager: Any,
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
        assert "address=unknown:0" in representation


class TestWebTransportServerProtocol:
    @pytest.fixture
    def mock_server(self, mocker: MockerFixture) -> Any:
        server = mocker.create_autospec(WebTransportServer, instance=True)
        server._active_protocols = set()
        server._handle_new_connection = mocker.AsyncMock()
        return server

    @pytest.fixture
    def protocol(self, mocker: MockerFixture, mock_server: Any) -> WebTransportServerProtocol:
        mocker.patch("aioquic.asyncio.protocol.QuicConnectionProtocol.__init__", return_value=None)
        mock_quic_conn = mocker.MagicMock()
        protocol = WebTransportServerProtocol(server=mock_server, quic=mock_quic_conn)
        protocol._transport = mocker.MagicMock()
        return protocol

    @pytest.mark.asyncio
    async def test_connection_made(self, protocol: WebTransportServerProtocol, mocker: MockerFixture) -> None:
        mock_super_made = mocker.patch("aioquic.asyncio.protocol.QuicConnectionProtocol.connection_made")
        mock_transport = mocker.MagicMock()

        protocol.connection_made(transport=mock_transport)
        await asyncio.sleep(0)

        mock_super_made.assert_called_once_with(mock_transport)
        server = protocol._server_ref()
        assert server is not None
        cast(Any, server._handle_new_connection).assert_awaited_once_with(transport=mock_transport, protocol=protocol)
        assert protocol in server._active_protocols
        if protocol._event_processor_task:
            protocol._event_processor_task.cancel()

    def test_connection_lost(self, protocol: WebTransportServerProtocol, mocker: MockerFixture) -> None:
        mock_super_lost = mocker.patch("aioquic.asyncio.protocol.QuicConnectionProtocol.connection_lost")
        mock_connection = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_connection._on_connection_lost = mocker.MagicMock()
        protocol.set_connection(connection=mock_connection)
        protocol._event_processor_task = mocker.create_autospec(asyncio.Task, instance=True)
        protocol._event_processor_task.done.return_value = False
        test_exception = RuntimeError("Connection dropped")
        server = protocol._server_ref()
        assert server
        server._active_protocols.add(protocol)

        protocol.connection_lost(exc=test_exception)

        mock_super_lost.assert_called_once_with(test_exception)
        mock_connection._on_connection_lost.assert_called_once_with(exc=test_exception)
        protocol._event_processor_task.cancel.assert_called_once()
        assert protocol not in server._active_protocols

    @pytest.mark.parametrize(
        "task_done, has_connection, server_exists",
        [(True, True, True), (False, False, True), (False, True, False)],
    )
    def test_connection_lost_edge_cases(
        self,
        protocol: WebTransportServerProtocol,
        mocker: MockerFixture,
        task_done: bool,
        has_connection: bool,
        server_exists: bool,
    ) -> None:
        mock_super_lost = mocker.patch("aioquic.asyncio.protocol.QuicConnectionProtocol.connection_lost")
        mock_connection = mocker.create_autospec(WebTransportConnection, instance=True)
        task = mocker.create_autospec(asyncio.Task, instance=True)
        task.done.return_value = task_done
        protocol._event_processor_task = task
        if has_connection:
            protocol.set_connection(connection=mock_connection)
        if not server_exists:
            mock_ref = mocker.MagicMock(spec=weakref.ReferenceType)
            mock_ref.return_value = None
            protocol._server_ref = mock_ref

        protocol.connection_lost(exc=None)

        mock_super_lost.assert_called_once()
        assert task.cancel.called is not task_done
        assert mock_connection._on_connection_lost.called is has_connection

    def test_connection_lost_no_connection(self, protocol: WebTransportServerProtocol, mocker: MockerFixture) -> None:
        """Test connection_lost when the protocol is not associated with a connection."""
        mock_super_lost = mocker.patch("aioquic.asyncio.protocol.QuicConnectionProtocol.connection_lost")
        protocol._connection_ref = None
        protocol._event_processor_task = None
        protocol.connection_lost(exc=None)
        mock_super_lost.assert_called_once_with(None)

    def test_init(self, protocol: WebTransportServerProtocol, mock_server: Any) -> None:
        assert isinstance(protocol._server_ref, weakref.ReferenceType)
        assert protocol._server_ref() is mock_server

    @pytest.mark.asyncio
    async def test_process_events_loop_fatal_error(
        self, protocol: WebTransportServerProtocol, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(protocol._event_queue, "get", side_effect=RuntimeError("queue failed"))
        protocol.connection_made(transport=mocker.MagicMock())

        await asyncio.sleep(0)

        assert protocol._event_processor_task and protocol._event_processor_task.done()

    @pytest.mark.asyncio
    async def test_process_events_loop_handler_exception(
        self, protocol: WebTransportServerProtocol, mocker: MockerFixture
    ) -> None:
        mock_connection = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_connection.protocol_handler.handle_quic_event = mocker.AsyncMock(side_effect=ValueError("handler error"))
        protocol.connection_made(transport=mocker.MagicMock())
        protocol.set_connection(connection=mock_connection)
        await asyncio.sleep(0)

        protocol.quic_event_received(event=mocker.MagicMock())
        await asyncio.sleep(0)

        mock_connection.protocol_handler.handle_quic_event.assert_awaited_once()
        if protocol._event_processor_task:
            protocol._event_processor_task.cancel()

    @pytest.mark.asyncio
    async def test_process_events_loop_no_protocol_handler(
        self, protocol: WebTransportServerProtocol, mocker: MockerFixture
    ) -> None:
        mock_connection = mocker.create_autospec(WebTransportConnection, instance=True)
        type(mock_connection).protocol_handler = mocker.PropertyMock(return_value=None)
        logger_mock = mocker.patch("pywebtransport.server.server.logger.warning")
        protocol.connection_made(transport=mocker.MagicMock())
        protocol.set_connection(connection=mock_connection)
        await asyncio.sleep(0)
        mock_event = mocker.MagicMock()

        protocol.quic_event_received(event=mock_event)
        await asyncio.sleep(0)

        logger_mock.assert_called_once_with(
            "No handler available to process event for %s: %r",
            mock_connection.connection_id,
            mock_event,
        )
        if protocol._event_processor_task:
            protocol._event_processor_task.cancel()

    @pytest.mark.asyncio
    async def test_process_events_loop_waits_for_connection(
        self, protocol: WebTransportServerProtocol, mocker: MockerFixture
    ) -> None:
        protocol.connection_made(transport=mocker.MagicMock())
        await asyncio.sleep(0)
        protocol.quic_event_received(event=mocker.MagicMock())

        assert protocol._event_queue.qsize() == 1
        await asyncio.sleep(0.02)
        assert protocol._event_queue.qsize() == 1

        if protocol._event_processor_task:
            protocol._event_processor_task.cancel()

    @pytest.mark.asyncio
    async def test_quic_event_received_forwards_directly_after_connection_set(
        self, protocol: WebTransportServerProtocol, mocker: MockerFixture
    ) -> None:
        mock_connection = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_connection.protocol_handler.handle_quic_event = mocker.AsyncMock()
        mock_event = mocker.MagicMock()
        protocol.connection_made(transport=mocker.MagicMock())
        protocol.set_connection(connection=mock_connection)
        await asyncio.sleep(0)

        protocol.quic_event_received(event=mock_event)
        await asyncio.sleep(0)

        mock_connection.protocol_handler.handle_quic_event.assert_awaited_once_with(event=mock_event)
        if protocol._event_processor_task:
            protocol._event_processor_task.cancel()

    @pytest.mark.asyncio
    async def test_set_connection_allows_processing(
        self, protocol: WebTransportServerProtocol, mocker: MockerFixture
    ) -> None:
        mock_connection = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_connection.protocol_handler.handle_quic_event = mocker.AsyncMock()
        mock_event = mocker.MagicMock()
        protocol.connection_made(transport=mocker.MagicMock())
        protocol.quic_event_received(event=mock_event)

        protocol.set_connection(connection=mock_connection)
        await asyncio.sleep(0)

        mock_connection.protocol_handler.handle_quic_event.assert_awaited_once_with(event=mock_event)
        if protocol._event_processor_task:
            protocol._event_processor_task.cancel()

    @pytest.mark.parametrize("is_closing, should_call", [(False, True), (True, False)])
    def test_transmit(
        self,
        protocol: WebTransportServerProtocol,
        mocker: MockerFixture,
        is_closing: bool,
        should_call: bool,
    ) -> None:
        mock_super_transmit = mocker.patch("aioquic.asyncio.protocol.QuicConnectionProtocol.transmit")
        mock_transport = mocker.MagicMock()
        mock_transport.is_closing.return_value = is_closing
        protocol._transport = mock_transport

        protocol.transmit()

        if should_call:
            mock_super_transmit.assert_called_once()
        else:
            mock_super_transmit.assert_not_called()
