"""Unit tests for the pywebtransport.server.server module."""

import asyncio
import weakref
from typing import Any, NoReturn, cast

import pytest
from _pytest.logging import LogCaptureFixture
from pytest_mock import MockerFixture

from pywebtransport import ConnectionError, Event, EventType, ServerConfig, ServerError
from pywebtransport.connection import ConnectionManager, WebTransportConnection
from pywebtransport.server import WebTransportServer
from pywebtransport.server.server import WebTransportServerProtocol
from pywebtransport.session import SessionManager


class TestWebTransportServer:
    @pytest.fixture
    def mock_connection_manager(self, mocker: MockerFixture) -> Any:
        mock_manager = mocker.create_autospec(ConnectionManager, instance=True)
        mocker.patch("pywebtransport.server.server.ConnectionManager.create", return_value=mock_manager)
        return mock_manager

    @pytest.fixture
    def mock_quic_server(self, mocker: MockerFixture) -> Any:
        mock_server = mocker.MagicMock()
        mock_server.close = mocker.MagicMock()
        mock_server.wait_closed = mocker.AsyncMock()
        mock_server._transport.get_extra_info.return_value = ("127.0.0.1", 4433)
        mocker.patch("pywebtransport.server.server.quic_serve", new_callable=mocker.AsyncMock, return_value=mock_server)
        return mock_server

    @pytest.fixture
    def mock_server_config(self, mocker: MockerFixture) -> ServerConfig:
        mocker.patch("pywebtransport.config.ServerConfig.validate")
        return ServerConfig(
            bind_host="127.0.0.1", bind_port=4433, certfile="cert.pem", keyfile="key.pem", max_connections=10
        )

    @pytest.fixture
    def mock_session_manager(self, mocker: MockerFixture) -> Any:
        mock_manager = mocker.create_autospec(SessionManager, instance=True)
        mocker.patch("pywebtransport.server.server.SessionManager.create", return_value=mock_manager)
        return mock_manager

    @pytest.fixture
    def mock_webtransport_connection(self, mocker: MockerFixture) -> Any:
        mock_conn = mocker.create_autospec(WebTransportConnection, instance=True)
        type(mock_conn).is_closed = mocker.PropertyMock(return_value=False)
        mocker.patch("pywebtransport.server.server.WebTransportConnection", return_value=mock_conn)
        return mock_conn

    @pytest.fixture
    def server(
        self, mock_server_config: ServerConfig, mock_connection_manager: Any, mock_session_manager: Any
    ) -> WebTransportServer:
        return WebTransportServer(config=mock_server_config)

    @pytest.fixture(autouse=True)
    def setup_common_mocks(self, mocker: MockerFixture) -> None:
        mocker.patch("aioquic.quic.configuration.QuicConfiguration.load_cert_chain")
        mocker.patch("pywebtransport.server.server.get_timestamp", return_value=1000.0)
        mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)

    def test_init_with_custom_config(self, server: WebTransportServer, mock_server_config: ServerConfig) -> None:
        assert server.config is mock_server_config

    def test_init_with_default_config(self, mocker: MockerFixture) -> None:
        mock_create = mocker.patch("pywebtransport.config.ServerConfig.create", autospec=True)

        WebTransportServer(config=None)

        mock_create.assert_called_once()
        mock_create.return_value.validate.assert_called_once()

    def test_str_representation(self, server: WebTransportServer, mock_quic_server: Any) -> None:
        server._serving = True
        server._server = mock_quic_server

        representation = str(server)

        assert "status=serving" in representation
        assert "address=127.0.0.1:4433" in representation

    @pytest.mark.asyncio
    async def test_listen_success(
        self, server: WebTransportServer, mock_quic_server: Any, mocker: MockerFixture
    ) -> None:
        mock_start_tasks = mocker.patch.object(server, "_start_background_tasks")

        await server.listen()

        assert server.is_serving
        assert server.local_address == ("127.0.0.1", 4433)
        mock_start_tasks.assert_called_once()

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

    @pytest.mark.asyncio
    async def test_handle_new_connection_success(
        self,
        server: WebTransportServer,
        mock_connection_manager: Any,
        mock_webtransport_connection: Any,
        mocker: MockerFixture,
    ) -> None:
        mock_protocol = mocker.create_autospec(WebTransportServerProtocol, instance=True)

        await server._handle_new_connection(mocker.MagicMock(), mock_protocol)

        mock_webtransport_connection.accept.assert_awaited_once()
        mock_connection_manager.add_connection.assert_awaited_once_with(mock_webtransport_connection)

    @pytest.mark.asyncio
    async def test_handle_new_connection_event_forwarding(
        self, server: WebTransportServer, mock_webtransport_connection: Any, mocker: MockerFixture
    ) -> None:
        server_emitter_mock = mocker.patch.object(server, "emit", new_callable=mocker.AsyncMock)
        captured_handler = mocker.MagicMock()
        mock_webtransport_connection.on.side_effect = lambda event, handler: captured_handler.set(handler)
        await server._handle_new_connection(mocker.MagicMock(), mocker.MagicMock())
        event_handler = captured_handler.set.call_args[0][0]
        event_data = {"path": "/test"}

        await event_handler(Event(type=EventType.SESSION_REQUEST, data=event_data))

        server_emitter_mock.assert_awaited_once()
        args, kwargs = server_emitter_mock.call_args
        assert args[0] == EventType.SESSION_REQUEST
        assert kwargs["data"]["connection"] is mock_webtransport_connection

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
    async def test_handle_new_connection_failure(
        self,
        server: WebTransportServer,
        mock_connection_manager: Any,
        mock_webtransport_connection: Any,
        mocker: MockerFixture,
    ) -> None:
        mock_webtransport_connection.accept.side_effect = ConnectionError("Accept failed")

        await server._handle_new_connection(mocker.MagicMock(), mocker.MagicMock())

        mock_webtransport_connection.close.assert_awaited_once()
        mock_connection_manager.add_connection.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_new_connection_transport_close_fails(
        self, server: WebTransportServer, mock_webtransport_connection: Any, mocker: MockerFixture
    ) -> None:
        mock_transport = mocker.MagicMock()
        mock_transport.close.side_effect = OSError("Transport busy")
        mock_webtransport_connection.accept.side_effect = ConnectionError("Accept failed")

        await server._handle_new_connection(mock_transport, mocker.MagicMock())

        assert server._stats.connection_errors == 1

    @pytest.mark.asyncio
    async def test_get_server_stats(
        self, server: WebTransportServer, mock_connection_manager: Any, mock_session_manager: Any, mocker: MockerFixture
    ) -> None:
        mock_connection_manager.get_stats = mocker.AsyncMock(return_value={"active": 1})
        mock_session_manager.get_stats = mocker.AsyncMock(return_value={"active": 2})

        stats = await server.get_server_stats()

        assert stats["connections"] == {"active": 1}
        assert stats["sessions"] == {"active": 2}

    @pytest.mark.asyncio
    async def test_get_server_stats_before_listen(self, server: WebTransportServer) -> None:
        stats = await server.get_server_stats()

        assert stats["uptime"] == 0.0

    @pytest.mark.asyncio
    async def test_debug_state(
        self, server: WebTransportServer, mock_connection_manager: Any, mocker: MockerFixture
    ) -> None:
        mock_connection_manager.get_all_connections = mocker.AsyncMock(return_value=[])

        state = await server.debug_state()

        assert "aggregated_stats" in state
        assert "connections" in state

    @pytest.mark.asyncio
    async def test_diagnose_issues_high_usage(
        self, server: WebTransportServer, mock_connection_manager: Any, mocker: MockerFixture
    ) -> None:
        server._serving = True
        mocker.patch("pathlib.Path.exists", return_value=True)
        mock_connection_manager.get_stats = mocker.AsyncMock(return_value={"active": 10})

        issues = await server.diagnose_issues()

        assert issues == ["High connection usage: 100.0%"]

    @pytest.mark.asyncio
    async def test_diagnose_issues_rejection_rate(
        self, server: WebTransportServer, mock_connection_manager: Any, mocker: MockerFixture
    ) -> None:
        server._serving = True
        mocker.patch("pathlib.Path.exists", return_value=True)
        mock_connection_manager.get_stats = mocker.AsyncMock(return_value={"active": 0})
        server._stats.connections_accepted = 89
        server._stats.connections_rejected = 11

        issues = await server.diagnose_issues()

        assert "High connection rejection rate: 11/100" in issues

    @pytest.mark.asyncio
    async def test_diagnose_issues_bad_cert_path(
        self, server: WebTransportServer, mock_connection_manager: Any, mocker: MockerFixture
    ) -> None:
        server._serving = True
        mock_connection_manager.get_stats = mocker.AsyncMock(return_value={"active": 0})
        mocker.patch("pathlib.Path.exists", side_effect=OSError("Permission denied"))

        issues = await server.diagnose_issues()

        assert "Certificate configuration appears invalid." in issues

    @pytest.mark.asyncio
    async def test_cleanup_loop(
        self,
        server: WebTransportServer,
        mock_connection_manager: Any,
        mock_session_manager: Any,
        mocker: MockerFixture,
    ) -> None:
        server._serving = True
        mocker.patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError])

        await server._cleanup_loop(interval=60.0)

        mock_connection_manager.cleanup_closed_connections.assert_awaited_once()
        mock_session_manager.cleanup_closed_sessions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cleanup_loop_logs_errors(
        self,
        server: WebTransportServer,
        mock_connection_manager: Any,
        caplog: LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        server._serving = True
        mock_connection_manager.cleanup_closed_connections.side_effect = ValueError("Cleanup failed")
        mocker.patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError])

        await server._cleanup_loop(interval=60.0)

        assert "Cleanup loop error: Cleanup failed" in caplog.text

    @pytest.mark.asyncio
    async def test_cleanup_loop_no_cleanup_methods(self, server: WebTransportServer, mocker: MockerFixture) -> None:
        server._serving = True
        plain_manager = mocker.MagicMock()
        del plain_manager.cleanup_closed_connections
        server._connection_manager = plain_manager
        mocker.patch("asyncio.sleep", side_effect=asyncio.CancelledError)

        await server._cleanup_loop(interval=60.0)

    @pytest.mark.asyncio
    async def test_listen_with_ca_certs(self, server: WebTransportServer, mocker: MockerFixture) -> None:
        class StopTest(BaseException):
            pass

        mock_load_verify = mocker.patch("aioquic.quic.configuration.QuicConfiguration.load_verify_locations")
        mocker.patch("pywebtransport.server.server.quic_serve", side_effect=StopTest)
        server.config.ca_certs = "/path/to/ca.pem"

        with pytest.raises(StopTest):
            await server.listen()

        mock_load_verify.assert_called_once_with(cafile="/path/to/ca.pem")


class TestWebTransportServerProtocol:
    @pytest.fixture
    def mock_server(self, mocker: MockerFixture) -> Any:
        server = mocker.create_autospec(WebTransportServer, instance=True)
        server._handle_new_connection = mocker.AsyncMock()
        return server

    @pytest.fixture
    def protocol(self, mocker: MockerFixture, mock_server: Any) -> WebTransportServerProtocol:
        mocker.patch("aioquic.asyncio.protocol.QuicConnectionProtocol.__init__", return_value=None)
        mock_quic_conn = mocker.MagicMock()
        return WebTransportServerProtocol(mock_server, quic=mock_quic_conn)

    def test_init(self, protocol: WebTransportServerProtocol, mock_server: Any) -> None:
        assert isinstance(protocol._server_ref, weakref.ReferenceType)
        assert protocol._server_ref() is mock_server

    @pytest.mark.asyncio
    async def test_connection_made(self, protocol: WebTransportServerProtocol, mocker: MockerFixture) -> None:
        mock_super_made = mocker.patch("aioquic.asyncio.protocol.QuicConnectionProtocol.connection_made")
        mock_transport = mocker.MagicMock()

        protocol.connection_made(mock_transport)
        await asyncio.sleep(0)

        mock_super_made.assert_called_once_with(mock_transport)
        server = protocol._server_ref()
        assert server is not None
        cast(Any, server._handle_new_connection).assert_awaited_once_with(mock_transport, protocol)

    @pytest.mark.asyncio
    async def test_quic_event_received_forwards_event_when_connection_is_set(
        self, protocol: WebTransportServerProtocol, mocker: MockerFixture
    ) -> None:
        mock_connection = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_connection.protocol_handler.handle_quic_event = mocker.AsyncMock()
        mock_event = mocker.MagicMock()
        protocol.set_connection(mock_connection)

        protocol.quic_event_received(mock_event)
        await asyncio.sleep(0)

        mock_connection.protocol_handler.handle_quic_event.assert_awaited_once_with(mock_event)

    def test_quic_event_received_buffers_event_when_no_connection(
        self, protocol: WebTransportServerProtocol, mocker: MockerFixture
    ) -> None:
        protocol.quic_event_received(mocker.MagicMock())

        assert len(protocol._pending_events) == 1

    @pytest.mark.asyncio
    async def test_set_connection_processes_pending_events(
        self, protocol: WebTransportServerProtocol, mocker: MockerFixture
    ) -> None:
        mock_connection = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_connection.protocol_handler.handle_quic_event = mocker.AsyncMock()
        mock_events = [mocker.MagicMock(), mocker.MagicMock()]
        protocol._pending_events = mock_events

        protocol.set_connection(mock_connection)
        await asyncio.sleep(0)

        mock_connection.protocol_handler.handle_quic_event.assert_has_awaits(
            [mocker.call(e) for e in mock_events], any_order=True
        )

    def test_set_connection_no_pending_events(
        self, protocol: WebTransportServerProtocol, mocker: MockerFixture
    ) -> None:
        mock_connection = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_connection.protocol_handler.handle_quic_event = mocker.AsyncMock()

        protocol.set_connection(mock_connection)

        mock_connection.protocol_handler.handle_quic_event.assert_not_called()
