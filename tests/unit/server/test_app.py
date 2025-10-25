"""Unit tests for the pywebtransport.server.app module."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, NoReturn

import pytest
from pytest_mock import MockerFixture

from pywebtransport import Event, ServerConfig, WebTransportSession
from pywebtransport.connection import WebTransportConnection
from pywebtransport.manager import SessionManager
from pywebtransport.server import ServerApp, WebTransportServer
from pywebtransport.server.app import logger as app_logger
from pywebtransport.types import EventType


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
    def mock_create_task(self, mocker: MockerFixture) -> Any:
        mock_task = mocker.MagicMock(spec=asyncio.Task)

        def patch_create_task(coro: Coroutine[Any, Any, None]) -> Any:
            coro.close()
            return mock_task

        mock_patch = mocker.patch("asyncio.create_task", side_effect=patch_create_task)
        return mock_patch, mock_task

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
        server_instance = mocker.create_autospec(WebTransportServer, instance=True)
        server_instance.session_manager = mocker.create_autospec(SessionManager, instance=True)
        server_instance.session_manager.add_session = mocker.AsyncMock()
        mocker.patch("pywebtransport.server.app.WebTransportServer", return_value=server_instance)
        server_instance.config = ServerConfig(bind_host="0.0.0.0", bind_port=4433)
        return server_instance

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> Any:
        session_instance = mocker.create_autospec(WebTransportSession, instance=True)
        session_instance.initialize = mocker.AsyncMock()
        session_instance.close = mocker.AsyncMock()
        session_instance.is_closed = False
        return mocker.patch(
            "pywebtransport.server.app.WebTransportSession",
            return_value=session_instance,
        )

    @pytest.mark.asyncio
    async def test_async_context_manager(self, app: ServerApp, mock_server: Any, mocker: MockerFixture) -> None:
        mock_startup = mocker.patch.object(app, "startup", new_callable=mocker.AsyncMock)
        mock_shutdown = mocker.patch.object(app, "shutdown", new_callable=mocker.AsyncMock)

        async with app as a:
            assert a is app
            mock_server.__aenter__.assert_awaited_once()
            mock_startup.assert_awaited_once()

        mock_shutdown.assert_awaited_once()
        mock_server.close.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "setup_mock",
        [
            lambda m: setattr(m, "is_connected", False),
            lambda m: setattr(m.get_session_info, "return_value", None),
            lambda m: setattr(m, "protocol_handler", None),
        ],
        ids=["not_connected", "no_session_info", "no_protocol_handler"],
    )
    async def test_create_session_from_event_failures(
        self, app: ServerApp, mocker: MockerFixture, setup_mock: Callable[[Any], None]
    ) -> None:
        mock_conn = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_conn.protocol_handler = mocker.MagicMock()
        mock_conn.is_connected = True
        mock_conn.config = ServerConfig()
        mock_conn.get_session_info.return_value = mocker.MagicMock(path="/", headers={})
        setup_mock(mock_conn)

        event = Event(
            type=EventType.SESSION_REQUEST,
            data={"connection": mock_conn, "session_id": "s1", "control_stream_id": 1},
        )

        session = await app._create_session_from_event(event)

        assert session is None

    @pytest.mark.asyncio
    async def test_create_session_from_event_invalid_config_type(self, app: ServerApp, mocker: MockerFixture) -> None:
        mock_conn = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_conn.protocol_handler = mocker.MagicMock()
        mock_conn.is_connected = True
        mock_conn.config = {"not": "a server config"}

        event = Event(
            type=EventType.SESSION_REQUEST,
            data={"connection": mock_conn, "session_id": "s1", "control_stream_id": 1},
        )

        session = await app._create_session_from_event(event)

        assert session is None
        mock_conn.protocol_handler.close_webtransport_session.assert_called_once_with(
            session_id="s1", code=1, reason="Internal server configuration error"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "invalid_data",
        [
            "not_a_dict",
            {"session_id": "s1"},
            {"control_stream_id": 1},
            {"connection": None, "session_id": "s1", "control_stream_id": 1},
            {
                "connection": "not_a_connection",
                "session_id": "s1",
                "control_stream_id": 1,
            },
        ],
        ids=[
            "not_a_dict",
            "no_stream_id",
            "no_session_id",
            "no_connection",
            "bad_connection_type",
        ],
    )
    async def test_create_session_from_event_invalid_data(self, app: ServerApp, invalid_data: Any) -> None:
        event = Event(type=EventType.SESSION_REQUEST, data=invalid_data)

        session = await app._create_session_from_event(event)

        assert session is None

    @pytest.mark.asyncio
    async def test_create_session_from_event_missing_stream_id_only(
        self, app: ServerApp, mocker: MockerFixture
    ) -> None:
        mock_logger_warning = mocker.patch.object(app_logger, "warning")
        mock_conn = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_conn.protocol_handler = mocker.MagicMock()

        event = Event(
            type=EventType.SESSION_REQUEST,
            data={"session_id": "s1", "connection": mock_conn},
        )

        session = await app._create_session_from_event(event)

        assert session is None
        mock_logger_warning.assert_called_once_with("Missing session_id or control_stream_id in session request")

    def test_decorators(self, app: ServerApp, mock_router: Any, mock_middleware_manager: Any) -> None:
        @app.route(path="/test")
        async def handler1(session: WebTransportSession) -> None: ...

        @app.pattern_route(pattern="/other/.*")
        async def handler2(session: WebTransportSession) -> None: ...

        mock_router.add_route.assert_called_once_with(path="/test", handler=handler1)
        mock_router.add_pattern_route.assert_called_once_with(pattern="/other/.*", handler=handler2)

        @app.middleware
        async def middleware(session: WebTransportSession) -> bool:
            return True

        mock_middleware_manager.add_middleware.assert_called_once_with(middleware=middleware)

        @app.on_startup
        def startup_handler() -> None: ...

        @app.on_shutdown
        def shutdown_handler() -> None: ...

        assert startup_handler in app._startup_handlers
        assert shutdown_handler in app._shutdown_handlers

    def test_dispatch_to_handler_failures(self, app: ServerApp, mock_router: Any, mocker: MockerFixture) -> None:
        mock_session_obj = mocker.create_autospec(WebTransportSession, instance=True)

        scenarios: dict[str, Callable[[WebTransportSession], None]] = {
            "no_connection": lambda s: setattr(s, "connection", None),
            "no_protocol_handler": lambda s: setattr(s.connection, "protocol_handler", None),
            "no_control_stream_id": lambda s: setattr(s, "_control_stream_id", None),
        }

        for name, setup in scenarios.items():
            mock_session_obj.connection = mocker.create_autospec(WebTransportConnection, instance=True)
            mock_session_obj.connection.protocol_handler = mocker.MagicMock()
            mock_session_obj._control_stream_id = 4
            mock_router.reset_mock()

            setup(mock_session_obj)
            mock_router.route_request.return_value = mocker.AsyncMock()

            app._dispatch_to_handler(session=mock_session_obj)

            if mock_session_obj.connection and mock_session_obj.connection.protocol_handler:
                mock_session_obj.connection.protocol_handler.accept_webtransport_session.assert_not_called()

    def test_dispatch_to_handler_task_callbacks(
        self, app: ServerApp, mocker: MockerFixture, mock_create_task: Any
    ) -> None:
        mock_handler = mocker.AsyncMock()
        mock_session = mocker.create_autospec(WebTransportSession, instance=True)
        mock_session.connection = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_session.connection.protocol_handler = mocker.MagicMock()
        mock_session._control_stream_id = 4
        mock_router = mocker.patch.object(app, "_router")
        mock_router.route_request.return_value = mock_handler
        mock_patch, mock_task = mock_create_task
        mock_logger_error = mocker.patch.object(app_logger, "error")

        app._dispatch_to_handler(session=mock_session)
        mock_task.add_done_callback.assert_called_once()
        callback = mock_task.add_done_callback.call_args[0][0]

        task_with_exception = mocker.MagicMock(spec=asyncio.Task)
        task_with_exception.cancelled.return_value = False
        task_with_exception.exception.return_value = ValueError("Task failed")
        app._active_handler_tasks.add(task_with_exception)

        callback(task_with_exception)
        assert task_with_exception not in app._active_handler_tasks
        mock_logger_error.assert_called_once_with(
            "Handler task for session completed with error: %s",
            task_with_exception.exception.return_value,
            exc_info=task_with_exception.exception.return_value,
        )

        mock_logger_error.reset_mock()
        task_cancelled = mocker.MagicMock(spec=asyncio.Task)
        task_cancelled.cancelled.return_value = True
        app._active_handler_tasks.add(task_cancelled)

        callback(task_cancelled)
        assert task_cancelled not in app._active_handler_tasks
        mock_logger_error.assert_not_called()

        mock_logger_error.reset_mock()
        task_success = mocker.MagicMock(spec=asyncio.Task)
        task_success.cancelled.return_value = False
        task_success.exception.return_value = None
        app._active_handler_tasks.add(task_success)

        callback(task_success)
        assert task_success not in app._active_handler_tasks
        mock_logger_error.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_session_request_exception_no_connection(self, app: ServerApp, mocker: MockerFixture) -> None:
        mocker.patch.object(app, "_create_session_from_event", side_effect=ValueError("Unexpected"))
        event = Event(type=EventType.SESSION_REQUEST, data={"session_id": "s1"})
        await app._handle_session_request(event)

    @pytest.mark.asyncio
    async def test_handle_session_request_exception_with_cleanup_failure(
        self, app: ServerApp, mocker: MockerFixture
    ) -> None:
        mock_conn = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_conn.protocol_handler = mocker.MagicMock()
        mocker.patch.object(app, "_create_session_from_event", side_effect=ValueError("Initial Error"))
        mock_conn.protocol_handler.close_webtransport_session.side_effect = RuntimeError("Cleanup Failed")

        event = Event(
            type=EventType.SESSION_REQUEST,
            data={"connection": mock_conn, "session_id": "s1", "control_stream_id": 1},
        )

        await app._handle_session_request(event)

        mock_conn.protocol_handler.close_webtransport_session.assert_called_once_with(
            session_id="s1", code=1, reason="Internal server error handling request"
        )

    @pytest.mark.asyncio
    async def test_handle_session_request_exception_with_session_cleanup(
        self, app: ServerApp, mock_middleware_manager: Any, mocker: MockerFixture
    ) -> None:
        mock_session_instance = mocker.create_autospec(WebTransportSession, instance=True)
        mock_session_instance.is_closed = False
        mock_conn = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_conn.protocol_handler = mocker.MagicMock()
        mock_session_instance.connection = mock_conn
        mocker.patch.object(app, "_create_session_from_event", return_value=mock_session_instance)
        mock_middleware_manager.process_request.side_effect = ValueError("Middleware error")

        event = Event(
            type=EventType.SESSION_REQUEST,
            data={"connection": mock_conn, "session_id": "s1"},
        )

        await app._handle_session_request(event)

        mock_session_instance.close.assert_awaited_once_with(close_connection=False)

    @pytest.mark.asyncio
    async def test_handle_session_request_general_exception(self, app: ServerApp, mocker: MockerFixture) -> None:
        mocker.patch.object(app, "_create_session_from_event", side_effect=ValueError("Unexpected"))
        mock_conn = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_conn.protocol_handler = mocker.MagicMock()

        event = Event(
            type=EventType.SESSION_REQUEST,
            data={"connection": mock_conn, "session_id": "s1", "control_stream_id": 1},
        )

        await app._handle_session_request(event)

        mock_conn.protocol_handler.close_webtransport_session.assert_called_once_with(
            session_id="s1", code=1, reason="Internal server error handling request"
        )

    @pytest.mark.asyncio
    async def test_handle_session_request_happy_path(
        self,
        app: ServerApp,
        mock_middleware_manager: Any,
        mock_router: Any,
        mocker: MockerFixture,
        mock_create_task: Any,
    ) -> None:
        mock_handler = mocker.AsyncMock()
        mock_router.route_request.return_value = mock_handler
        mock_session_instance = mocker.create_autospec(WebTransportSession, instance=True)
        mock_session_instance.connection = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_session_instance.connection.protocol_handler = mocker.MagicMock()
        mock_session_instance._control_stream_id = 4
        mock_patch, mock_task = mock_create_task

        mock_create_session = mocker.patch.object(
            app,
            "_create_session_from_event",
            new_callable=mocker.AsyncMock,
            return_value=mock_session_instance,
        )

        event = Event(type=EventType.SESSION_REQUEST, data={})

        await app._handle_session_request(event)

        mock_create_session.assert_awaited_once_with(event)
        mock_middleware_manager.process_request.assert_awaited_once_with(session=mock_session_instance)
        mock_router.route_request.assert_called_once_with(session=mock_session_instance)
        mock_session_instance.connection.protocol_handler.accept_webtransport_session.assert_called_once()
        mock_patch.assert_called_once()
        assert mock_task in app._active_handler_tasks
        mock_task.add_done_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_session_request_no_session_created(self, app: ServerApp, mocker: MockerFixture) -> None:
        mocker.patch.object(app, "_create_session_from_event", return_value=None)
        event = Event(type=EventType.SESSION_REQUEST, data={})
        await app._handle_session_request(event)

    @pytest.mark.asyncio
    async def test_handle_session_request_no_session_manager(
        self,
        app: ServerApp,
        mock_server: Any,
        mock_router: Any,
        mock_session: Any,
        mocker: MockerFixture,
        mock_create_task: Any,
    ) -> None:
        mock_conn = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_conn.protocol_handler = mocker.MagicMock()
        mock_conn.is_connected = True
        mock_conn.config = ServerConfig()
        mock_router.route_request.return_value = mocker.AsyncMock()
        mock_session_info = mocker.MagicMock(path="/", headers={})
        mock_conn.get_session_info.return_value = mock_session_info
        mock_session.return_value.connection = mock_conn
        mock_session.return_value._control_stream_id = 4
        session_manager = mock_server.session_manager
        mock_server.session_manager = None
        mock_patch, mock_task = mock_create_task

        event = Event(
            type=EventType.SESSION_REQUEST,
            data={
                "connection": mock_conn,
                "session_id": "s1",
                "control_stream_id": 4,
            },
        )

        await app._handle_session_request(event)

        mock_session.return_value.initialize.assert_awaited_once()
        session_manager.add_session.assert_not_called()
        mock_conn.protocol_handler.accept_webtransport_session.assert_called_once()
        mock_patch.assert_called_once()
        assert mock_task in app._active_handler_tasks
        mock_task.add_done_callback.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "rejection_case, expected_code",
        [
            ("middleware", 403),
            ("no_route", 404),
        ],
    )
    async def test_handle_session_request_rejection_paths(
        self,
        app: ServerApp,
        mock_router: Any,
        mock_middleware_manager: Any,
        mocker: MockerFixture,
        rejection_case: str,
        expected_code: int,
    ) -> None:
        mock_session = mocker.create_autospec(WebTransportSession, instance=True)
        mock_session.path = "/"
        mock_session._control_stream_id = 4
        mock_session.is_closed = False
        mock_session.connection = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_session.connection.protocol_handler = mocker.MagicMock()
        mocker.patch.object(app, "_create_session_from_event", return_value=mock_session)

        if rejection_case == "middleware":
            mock_middleware_manager.process_request.return_value = False
        if rejection_case == "no_route":
            mock_router.route_request.return_value = None

        event = Event(
            type=EventType.SESSION_REQUEST,
            data={"connection": mock_session.connection, "session_id": "s1"},
        )

        await app._handle_session_request(event)

        mock_session.connection.protocol_handler.reject_session_request.assert_called_once_with(
            stream_id=mock_session._control_stream_id, status_code=expected_code
        )
        mock_session.connection.protocol_handler.close_webtransport_session.assert_not_called()
        if rejection_case == "middleware":
            mock_session.close.assert_awaited_once_with(close_connection=False)
        else:
            mock_session.close.assert_not_called()

    def test_init(self, app: ServerApp, mock_server: Any) -> None:
        assert app.server is mock_server
        mock_server.on.assert_called_once_with(
            event_type=EventType.SESSION_REQUEST, handler=app._handle_session_request
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "run_kwargs, serve_kwargs",
        [
            ({"host": "localhost", "port": 1234}, {"host": "localhost", "port": 1234}),
            ({}, {"host": "0.0.0.0", "port": 4433}),
        ],
        ids=["with_args", "with_defaults"],
    )
    async def test_run(
        self,
        app: ServerApp,
        mocker: MockerFixture,
        run_kwargs: dict[str, Any],
        serve_kwargs: dict[str, Any],
    ) -> None:
        mock_serve = mocker.patch.object(app, "serve", new_callable=mocker.AsyncMock)
        mock_asyncio_run = mocker.patch("asyncio.run")

        app.run(**run_kwargs)

        mock_asyncio_run.assert_called_once()
        main_coro = mock_asyncio_run.call_args[0][0]
        await main_coro
        mock_serve.assert_awaited_once_with(**serve_kwargs)

    @pytest.mark.asyncio
    async def test_run_handler_exception(self, app: ServerApp, mocker: MockerFixture, mock_session: Any) -> None:
        handler_mock = mocker.AsyncMock(side_effect=ValueError("Handler error"))

        await app._run_handler_safely(handler=handler_mock, session=mock_session.return_value)

        handler_mock.assert_awaited_once()
        mock_session.return_value.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_handler_safely_close_fails(
        self, app: ServerApp, mocker: MockerFixture, mock_session: Any
    ) -> None:
        handler_mock = mocker.AsyncMock()
        mock_session.return_value.is_closed = False
        mock_session.return_value.close.side_effect = RuntimeError("Close failed")

        await app._run_handler_safely(handler=handler_mock, session=mock_session.return_value)

        handler_mock.assert_awaited_once()
        mock_session.return_value.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_handler_session_already_closed(
        self, app: ServerApp, mocker: MockerFixture, mock_session: Any
    ) -> None:
        handler_mock = mocker.AsyncMock()
        mock_session.return_value.is_closed = True

        await app._run_handler_safely(handler=handler_mock, session=mock_session.return_value)

        handler_mock.assert_awaited_once()
        mock_session.return_value.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_with_keyboard_interrupt(self, app: ServerApp, mocker: MockerFixture) -> None:
        mocker.patch.object(app, "serve", new_callable=mocker.AsyncMock)

        def consume_coro_and_raise(coro: Coroutine[Any, Any, None]) -> NoReturn:
            coro.close()
            raise KeyboardInterrupt

        mock_asyncio_run = mocker.patch("asyncio.run", side_effect=consume_coro_and_raise)
        app.run()
        mock_asyncio_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_serve(self, app: ServerApp, mock_server: Any) -> None:
        await app.serve(host="localhost", port=8080)
        mock_server.listen.assert_awaited_once_with(host="localhost", port=8080)
        mock_server.serve_forever.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_serve_with_default_host_port(self, app: ServerApp, mock_server: Any) -> None:
        await app.serve()
        mock_server.listen.assert_awaited_once_with(host="0.0.0.0", port=4433)
        mock_server.serve_forever.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("is_async", [True, False])
    async def test_startup_and_shutdown_handlers(self, app: ServerApp, mocker: MockerFixture, is_async: bool) -> None:
        mocker.patch("asyncio.iscoroutinefunction", return_value=is_async)

        startup_handler = mocker.AsyncMock() if is_async else mocker.MagicMock()
        shutdown_handler = mocker.AsyncMock() if is_async else mocker.MagicMock()

        app.on_startup(startup_handler)
        app.on_shutdown(shutdown_handler)

        await app.startup()
        if is_async:
            startup_handler.assert_awaited_once()
        else:
            startup_handler.assert_called_once()

        await app.shutdown()
        if is_async:
            shutdown_handler.assert_awaited_once()
        else:
            shutdown_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_startup_and_shutdown_stateful_middleware(self, app: ServerApp, mocker: MockerFixture) -> None:
        stateful_middleware = mocker.MagicMock()
        stateful_middleware.__aenter__ = mocker.AsyncMock()
        stateful_middleware.__aexit__ = mocker.AsyncMock()
        app.add_middleware(middleware=stateful_middleware)

        await app.startup()
        stateful_middleware.__aenter__.assert_awaited_once()

        await app.shutdown()
        stateful_middleware.__aexit__.assert_awaited_once_with(exc_type=None, exc_val=None, exc_tb=None)

    @pytest.mark.asyncio
    async def test_shutdown_cancels_active_tasks(self, app: ServerApp, mocker: MockerFixture) -> None:
        mock_task_1 = mocker.MagicMock(spec=asyncio.Task)
        mock_task_2 = mocker.MagicMock(spec=asyncio.Task)
        app._active_handler_tasks.add(mock_task_1)
        app._active_handler_tasks.add(mock_task_2)

        mock_gather = mocker.patch("asyncio.gather", new_callable=mocker.AsyncMock)

        await app.shutdown()

        mock_task_1.cancel.assert_called_once()
        mock_task_2.cancel.assert_called_once()

        mock_gather.assert_awaited_once()
        assert mock_gather.await_args.kwargs == {"return_exceptions": True}
        assert set(mock_gather.await_args.args) == {mock_task_1, mock_task_2}
