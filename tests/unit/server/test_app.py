"""Unit tests for the pywebtransport.server.app module."""

import asyncio
from typing import Any, Coroutine, NoReturn, cast

import pytest
from pytest_mock import MockerFixture

from pywebtransport import Event, EventType, ServerConfig
from pywebtransport.connection import WebTransportConnection
from pywebtransport.server import ServerApp, WebTransportServer
from pywebtransport.session import SessionManager, WebTransportSession


class TestServerApp:
    @pytest.fixture
    def app(
        self,
        mock_server: Any,
        mock_router: Any,
        mock_middleware_manager: Any,
    ) -> ServerApp:
        return ServerApp()

    @pytest.fixture
    def mock_middleware_manager(self, mocker: MockerFixture) -> Any:
        manager_instance = mocker.MagicMock()
        manager_instance.process_request = mocker.AsyncMock(return_value=True)
        mocker.patch("pywebtransport.server.app.MiddlewareManager", return_value=manager_instance)
        return manager_instance

    @pytest.fixture
    def mock_router(self, mocker: MockerFixture) -> Any:
        router_instance = mocker.MagicMock()
        mocker.patch("pywebtransport.server.app.RequestRouter", return_value=router_instance)
        return router_instance

    @pytest.fixture
    def mock_server(self, mocker: MockerFixture) -> Any:
        server_instance = mocker.MagicMock(spec=WebTransportServer)
        server_instance.on = mocker.MagicMock()
        server_instance.listen = mocker.AsyncMock()
        server_instance.serve_forever = mocker.AsyncMock()
        server_instance.close = mocker.AsyncMock()
        server_instance.__aenter__ = mocker.AsyncMock(return_value=server_instance)
        server_instance.__aexit__ = mocker.AsyncMock()
        server_instance.config = ServerConfig(bind_host="0.0.0.0", bind_port=4433)
        server_instance.session_manager = mocker.create_autospec(SessionManager, instance=True)
        mocker.patch("pywebtransport.server.app.WebTransportServer", return_value=server_instance)
        return server_instance

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> Any:
        session_instance = mocker.create_autospec(WebTransportSession, instance=True)
        session_instance.initialize = mocker.AsyncMock()
        session_instance.close = mocker.AsyncMock()
        session_instance.is_closed = False
        return mocker.patch("pywebtransport.server.app.WebTransportSession", return_value=session_instance)

    def test_init(self, app: ServerApp, mock_server: Any) -> None:
        assert app.server is mock_server
        cast(Any, app.server).on.assert_called_once_with(EventType.SESSION_REQUEST, app._handle_session_request)

    @pytest.mark.asyncio
    async def test_run(self, app: ServerApp, mocker: MockerFixture) -> None:
        mock_serve = mocker.patch.object(app, "serve", new_callable=mocker.AsyncMock)
        mock_asyncio_run = mocker.patch("asyncio.run")

        app.run(host="localhost", port=1234)

        mock_asyncio_run.assert_called_once()
        main_coro = mock_asyncio_run.call_args[0][0]
        await main_coro
        mock_serve.assert_awaited_once_with(host="localhost", port=1234)

        mock_asyncio_run.reset_mock()
        mock_serve.reset_mock()

        def consume_coro_and_raise(coro: Coroutine[Any, Any, None]) -> NoReturn:
            coro.close()
            raise KeyboardInterrupt

        mock_asyncio_run.side_effect = consume_coro_and_raise
        app.run()
        mock_asyncio_run.assert_called_once()
        mock_serve.assert_not_awaited()

    def test_decorators(self, app: ServerApp) -> None:
        @app.route("/test")
        async def handler1(session: WebTransportSession) -> None:
            """handler1"""
            ...

        @app.pattern_route("/other/.*")
        async def handler2(session: WebTransportSession) -> None:
            """handler2"""
            ...

        cast(Any, app._router).add_route.assert_called_once_with("/test", handler1)
        cast(Any, app._router).add_pattern_route.assert_called_once_with("/other/.*", handler2)

        @app.middleware
        async def middleware(session: WebTransportSession) -> bool:
            return True

        cast(Any, app._middleware_manager).add_middleware.assert_called_once_with(middleware)

        @app.on_startup
        def startup_handler() -> None:
            """startup_handler"""
            ...

        @app.on_shutdown
        def shutdown_handler() -> None:
            """shutdown_handler"""
            ...

        assert startup_handler in app._startup_handlers
        assert shutdown_handler in app._shutdown_handlers

    @pytest.mark.asyncio
    async def test_serve(self, app: ServerApp) -> None:
        await app.serve(host="localhost", port=8080)

        cast(Any, app.server).listen.assert_awaited_once_with(host="localhost", port=8080)
        cast(Any, app.server).serve_forever.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_serve_with_default_host_port(self, app: ServerApp) -> None:
        await app.serve()

        cast(Any, app.server).listen.assert_awaited_once_with(host="0.0.0.0", port=4433)
        cast(Any, app.server).serve_forever.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_context_manager(self, app: ServerApp, mocker: MockerFixture) -> None:
        mock_startup = mocker.patch.object(app, "startup", new_callable=mocker.AsyncMock)
        mock_shutdown = mocker.patch.object(app, "shutdown", new_callable=mocker.AsyncMock)

        async with app as a:
            assert a is app
            cast(Any, app.server).__aenter__.assert_awaited_once()
            mock_startup.assert_awaited_once()

        mock_shutdown.assert_awaited_once()
        cast(Any, app.server).close.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("is_async", [True, False])
    async def test_startup_and_shutdown(self, app: ServerApp, mocker: MockerFixture, is_async: bool) -> None:
        mock_handler = mocker.AsyncMock() if is_async else mocker.MagicMock()
        mocker.patch("asyncio.iscoroutinefunction", return_value=is_async)
        stateful_middleware = mocker.MagicMock()
        stateful_middleware.__aenter__ = mocker.AsyncMock()
        stateful_middleware.__aexit__ = mocker.AsyncMock()
        app.add_middleware(stateful_middleware)
        app.on_startup(mock_handler)

        await app.startup()

        stateful_middleware.__aenter__.assert_awaited_once()
        if is_async:
            mock_handler.assert_awaited_once()
        else:
            mock_handler.assert_called_once()

        app.on_shutdown(mock_handler)
        await app.shutdown()
        if is_async:
            mock_handler.assert_awaited()
        else:
            mock_handler.assert_called()
        stateful_middleware.__aexit__.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_session_request_happy_path(
        self, app: ServerApp, mock_server: Any, mock_router: Any, mock_session: Any, mocker: MockerFixture
    ) -> None:
        mock_conn = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_conn.is_connected = True
        mock_conn.config = ServerConfig()
        mock_handler = mocker.AsyncMock()
        mock_router.route_request.return_value = mock_handler
        mock_session_info = mocker.MagicMock(path="/", headers=[])
        mock_conn.protocol_handler.get_session_info.return_value = mock_session_info
        captured_coro: Any = None

        def capture_arg(coro: Coroutine[Any, Any, None]) -> Any:
            nonlocal captured_coro
            captured_coro = coro
            return mocker.create_autospec(asyncio.Task, instance=True)

        mocker.patch("asyncio.create_task", side_effect=capture_arg)
        event = Event(
            type=EventType.SESSION_REQUEST, data={"connection": mock_conn, "session_id": "s1", "stream_id": 4}
        )

        await app._handle_session_request(event)

        mock_conn.protocol_handler.accept_webtransport_session.assert_called_once_with(stream_id=4, session_id="s1")
        mock_server.session_manager.add_session.assert_awaited_once_with(mock_session.return_value)
        assert captured_coro is not None
        await captured_coro
        mock_handler.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "rejection_case, event_data, expected_code",
        [
            ("middleware", {"session_id": "s1", "stream_id": 1}, 403),
            ("no_route", {"session_id": "s1", "stream_id": 1}, 404),
            ("bad_data", "not_a_dict", None),
            ("no_conn", {"session_id": "s1", "stream_id": 1}, None),
            ("no_session_id", {"stream_id": 1}, None),
        ],
    )
    async def test_handle_session_request_rejection_paths(
        self,
        app: ServerApp,
        mock_router: Any,
        mock_session: Any,
        mocker: MockerFixture,
        rejection_case: str,
        event_data: Any,
        expected_code: int | None,
    ) -> None:
        mock_conn = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_conn.is_connected = True
        mock_conn.config = ServerConfig()
        mock_session_info = mocker.MagicMock(path="/", headers=[])
        mock_conn.protocol_handler.get_session_info.return_value = mock_session_info
        if isinstance(event_data, dict) and "connection" not in event_data:
            event_data["connection"] = mock_conn
        if rejection_case == "middleware":
            cast(Any, app._middleware_manager).process_request.return_value = False
        if rejection_case == "no_route":
            mock_router.route_request.return_value = None
        else:
            mock_router.route_request.return_value = mocker.AsyncMock()

        event = Event(type=EventType.SESSION_REQUEST, data=event_data)

        await app._handle_session_request(event)

        if expected_code:
            mock_conn.protocol_handler.close_webtransport_session.assert_called_once()
            assert mock_conn.protocol_handler.close_webtransport_session.call_args[1]["code"] == expected_code

    @pytest.mark.asyncio
    @pytest.mark.parametrize("conn_value", [None, "not_a_connection_object"])
    async def test_handle_session_request_invalid_connection(self, app: ServerApp, conn_value: Any) -> None:
        event = Event(
            type=EventType.SESSION_REQUEST, data={"connection": conn_value, "session_id": "s1", "stream_id": 1}
        )

        await app._handle_session_request(event)

        cast(Any, app._middleware_manager).process_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_session_request_disconnected(self, app: ServerApp, mocker: MockerFixture) -> None:
        mock_conn = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_conn.is_connected = False
        mock_conn.config = ServerConfig()
        event = Event(
            type=EventType.SESSION_REQUEST, data={"connection": mock_conn, "session_id": "s1", "stream_id": 1}
        )

        await app._handle_session_request(event)

        cast(Any, app._middleware_manager).process_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_session_request_no_session_info(self, app: ServerApp, mocker: MockerFixture) -> None:
        mock_conn = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_conn.is_connected = True
        mock_conn.config = ServerConfig()
        mock_conn.protocol_handler.get_session_info.return_value = None
        event = Event(
            type=EventType.SESSION_REQUEST, data={"connection": mock_conn, "session_id": "s1", "stream_id": 1}
        )

        await app._handle_session_request(event)

        cast(Any, app._middleware_manager).process_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_session_request_general_exception(self, app: ServerApp, mocker: MockerFixture) -> None:
        mock_conn = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_conn.is_connected = True
        mock_conn.config = ServerConfig()
        mock_conn.protocol_handler.get_session_info.side_effect = ValueError("Unexpected error")
        event = Event(
            type=EventType.SESSION_REQUEST, data={"connection": mock_conn, "session_id": "s1", "stream_id": 1}
        )

        await app._handle_session_request(event)

        mock_conn.protocol_handler.close_webtransport_session.assert_called_once_with(
            "s1", code=1, reason="Internal server error"
        )

    @pytest.mark.asyncio
    async def test_run_handler_exception(
        self, app: ServerApp, mocker: MockerFixture, mock_router: Any, mock_session: Any
    ) -> None:
        mock_conn = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_conn.is_connected = True
        mock_conn.config = ServerConfig()
        handler_mock = mocker.AsyncMock(side_effect=ValueError("Handler error"))
        mock_router.route_request.return_value = handler_mock
        mock_session_info = mocker.MagicMock(path="/", headers=[])
        mock_conn.protocol_handler.get_session_info.return_value = mock_session_info
        captured_coro: Any = None

        def capture_arg(coro: Coroutine[Any, Any, None]) -> Any:
            nonlocal captured_coro
            captured_coro = coro
            return mocker.create_autospec(asyncio.Task, instance=True)

        mocker.patch("asyncio.create_task", side_effect=capture_arg)
        event = Event(
            type=EventType.SESSION_REQUEST, data={"connection": mock_conn, "session_id": "s1", "stream_id": 1}
        )

        await app._handle_session_request(event)

        assert captured_coro is not None
        await captured_coro
        handler_mock.assert_awaited_once()
        mock_session.return_value.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_handler_session_already_closed(
        self, app: ServerApp, mocker: MockerFixture, mock_router: Any, mock_session: Any
    ) -> None:
        mock_conn = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_conn.is_connected = True
        mock_conn.config = ServerConfig()
        handler_mock = mocker.AsyncMock()
        mock_router.route_request.return_value = handler_mock
        mock_session.return_value.is_closed = True
        mock_session_info = mocker.MagicMock(path="/", headers=[])
        mock_conn.protocol_handler.get_session_info.return_value = mock_session_info
        captured_coro: Any = None

        def capture_arg(coro: Coroutine[Any, Any, None]) -> Any:
            nonlocal captured_coro
            captured_coro = coro
            return mocker.create_autospec(asyncio.Task, instance=True)

        mocker.patch("asyncio.create_task", side_effect=capture_arg)
        event = Event(
            type=EventType.SESSION_REQUEST, data={"connection": mock_conn, "session_id": "s1", "stream_id": 1}
        )

        await app._handle_session_request(event)

        assert captured_coro is not None
        await captured_coro
        handler_mock.assert_awaited_once()
        mock_session.return_value.close.assert_not_called()
