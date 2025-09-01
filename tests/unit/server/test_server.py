"""Unit tests for the pywebtransport.server.server module."""

import asyncio
import weakref
from typing import Any, NoReturn, cast

import pytest
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
        mocker.patch("pywebtransport.server.server.create_quic_configuration")
        mocker.patch("pywebtransport.server.server.get_timestamp", side_effect=[1000.0, 1005.0])
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

    def test_str_representation_not_serving(self, server: WebTransportServer) -> None:
        representation = str(server)

        assert "status=stopped" in representation
        assert "address=unknown:0" in representation

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
    async def test_close_with_manager_shutdown_error(
        self, server: WebTransportServer, mock_connection_manager: Any, mock_quic_server: Any
    ) -> None:
        await server.listen()
        mock_connection_manager.shutdown.side_effect = RuntimeError("Shutdown error")

        await server.close()

        mock_connection_manager.shutdown.assert_awaited_once()
        mock_quic_server.close.assert_called_once()

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
    async def test_async_context_manager_with_exception(
        self, server: WebTransportServer, mocker: MockerFixture
    ) -> None:
        mock_close = mocker.patch.object(server, "close", new_callable=mocker.AsyncMock)

        with pytest.raises(ValueError, match="Test exception"):
            async with server:
                raise ValueError("Test exception")

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
    async def test_serve_forever_keyboard_interrupt(
        self, server: WebTransportServer, mock_quic_server: Any, mocker: MockerFixture
    ) -> None:
        mock_quic_server.wait_closed.side_effect = KeyboardInterrupt
        await server.listen()
        mock_close = mocker.patch.object(server, "close", new_callable=mocker.AsyncMock)

        await server.serve_forever()

        mock_close.assert_awaited_once()

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
        mock_webtransport_connection.on.side_effect = lambda event, handler: captured_handler.set(handler)
        original_server_ref = weakref.ref(server) if server_ref_valid else lambda: None
        original_conn_ref = weakref.ref(mock_webtransport_connection) if conn_ref_valid else lambda: None
        mocker.patch("weakref.ref", side_effect=[original_server_ref, original_conn_ref])
        await server._handle_new_connection(mocker.MagicMock(), mocker.MagicMock())
        event_handler = captured_handler.set.call_args[0][0]

        await event_handler(Event(type=EventType.SESSION_REQUEST, data=event_data))

        if should_emit:
            server_emitter_mock.assert_awaited_once()
            args, kwargs = server_emitter_mock.call_args
            assert args[0] == EventType.SESSION_REQUEST
            assert kwargs["data"]["connection"] is mock_webtransport_connection
        else:
            server_emitter_mock.assert_not_called()

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
    async def test_handle_new_connection_failure_already_closed(
        self, server: WebTransportServer, mock_webtransport_connection: Any, mocker: MockerFixture
    ) -> None:
        mock_webtransport_connection.accept.side_effect = ConnectionError("Accept failed")
        type(mock_webtransport_connection).is_closed = mocker.PropertyMock(return_value=True)

        await server._handle_new_connection(mocker.MagicMock(), mocker.MagicMock())

        mock_webtransport_connection.close.assert_not_called()
        assert server._stats.connections_rejected == 1

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
    async def test_get_server_stats_after_listen(
        self,
        server: WebTransportServer,
        mock_connection_manager: Any,
        mock_session_manager: Any,
        mock_quic_server: Any,
        mocker: MockerFixture,
    ) -> None:
        await server.listen()
        mock_connection_manager.get_stats = mocker.AsyncMock(return_value={"active": 1})
        mock_session_manager.get_stats = mocker.AsyncMock(return_value={"active": 2})

        stats = await server.get_server_stats()

        assert stats["uptime"] == 5.0
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
    async def test_diagnose_issues_no_connection_stats(
        self, server: WebTransportServer, mock_connection_manager: Any, mocker: MockerFixture
    ) -> None:
        server._serving = True
        mocker.patch("pathlib.Path.exists", return_value=True)
        mock_connection_manager.get_stats = mocker.AsyncMock(return_value=None)

        issues = await server.diagnose_issues()

        assert issues == []

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
        protocol = WebTransportServerProtocol(mock_server, quic=mock_quic_conn)
        protocol._transport = mocker.MagicMock()
        return protocol

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
        assert protocol in server._active_protocols
        if protocol._event_processor_task:
            protocol._event_processor_task.cancel()

    def test_connection_lost(self, protocol: WebTransportServerProtocol, mocker: MockerFixture) -> None:
        mock_super_lost = mocker.patch("aioquic.asyncio.protocol.QuicConnectionProtocol.connection_lost")
        mock_connection = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_connection._on_connection_lost = mocker.MagicMock()
        protocol.set_connection(mock_connection)
        protocol._event_processor_task = mocker.create_autospec(asyncio.Task, instance=True)
        protocol._event_processor_task.done.return_value = False
        test_exception = RuntimeError("Connection dropped")
        server = protocol._server_ref()
        assert server
        server._active_protocols.add(protocol)

        protocol.connection_lost(test_exception)

        mock_super_lost.assert_called_once_with(test_exception)
        mock_connection._on_connection_lost.assert_called_once_with(test_exception)
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
            protocol.set_connection(mock_connection)
        if not server_exists:
            mock_ref = mocker.MagicMock(spec=weakref.ReferenceType)
            mock_ref.return_value = None
            protocol._server_ref = mock_ref

        protocol.connection_lost(None)

        mock_super_lost.assert_called_once()
        assert task.cancel.called is not task_done
        assert mock_connection._on_connection_lost.called is has_connection

    @pytest.mark.asyncio
    async def test_quic_event_received_forwards_directly_after_connection_set(
        self, protocol: WebTransportServerProtocol, mocker: MockerFixture
    ) -> None:
        mock_connection = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_connection.protocol_handler.handle_quic_event = mocker.AsyncMock()
        mock_event = mocker.MagicMock()
        protocol.connection_made(mocker.MagicMock())
        protocol.set_connection(mock_connection)
        await asyncio.sleep(0)

        protocol.quic_event_received(mock_event)
        await asyncio.sleep(0)

        mock_connection.protocol_handler.handle_quic_event.assert_awaited_once_with(mock_event)
        if protocol._event_processor_task:
            protocol._event_processor_task.cancel()

    @pytest.mark.asyncio
    async def test_process_events_loop_waits_for_connection(
        self, protocol: WebTransportServerProtocol, mocker: MockerFixture
    ) -> None:
        protocol.connection_made(mocker.MagicMock())
        await asyncio.sleep(0)
        protocol.quic_event_received(mocker.MagicMock())

        assert protocol._event_queue.qsize() == 1
        await asyncio.sleep(0.02)
        assert protocol._event_queue.qsize() == 1

        if protocol._event_processor_task:
            protocol._event_processor_task.cancel()

    @pytest.mark.asyncio
    async def test_process_events_loop_handler_exception(
        self, protocol: WebTransportServerProtocol, mocker: MockerFixture
    ) -> None:
        mock_connection = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_connection.protocol_handler.handle_quic_event = mocker.AsyncMock(side_effect=ValueError("handler error"))
        protocol.connection_made(mocker.MagicMock())
        protocol.set_connection(mock_connection)
        await asyncio.sleep(0)

        protocol.quic_event_received(mocker.MagicMock())
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
        protocol.connection_made(mocker.MagicMock())
        protocol.set_connection(mock_connection)
        await asyncio.sleep(0)

        protocol.quic_event_received(mocker.MagicMock())
        await asyncio.sleep(0)

        if protocol._event_processor_task:
            protocol._event_processor_task.cancel()

    @pytest.mark.asyncio
    async def test_process_events_loop_fatal_error(
        self, protocol: WebTransportServerProtocol, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(protocol._event_queue, "get", side_effect=RuntimeError("queue failed"))
        protocol.connection_made(mocker.MagicMock())

        await asyncio.sleep(0)

        assert protocol._event_processor_task and protocol._event_processor_task.done()

    @pytest.mark.asyncio
    async def test_set_connection_allows_processing(
        self, protocol: WebTransportServerProtocol, mocker: MockerFixture
    ) -> None:
        mock_connection = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_connection.protocol_handler.handle_quic_event = mocker.AsyncMock()
        mock_event = mocker.MagicMock()
        protocol.connection_made(mocker.MagicMock())
        protocol.quic_event_received(mock_event)

        protocol.set_connection(mock_connection)
        await asyncio.sleep(0)

        mock_connection.protocol_handler.handle_quic_event.assert_awaited_once_with(mock_event)
        if protocol._event_processor_task:
            protocol._event_processor_task.cancel()

    @pytest.mark.parametrize("is_closing, should_call", [(False, True), (True, False)])
    def test_transmit(
        self, protocol: WebTransportServerProtocol, mocker: MockerFixture, is_closing: bool, should_call: bool
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
