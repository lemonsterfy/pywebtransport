"""Unit tests for the pywebtransport.server.app module."""

import asyncio
import http
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, NoReturn, cast

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ConnectionError, Event, ServerApp, ServerConfig, WebTransportSession
from pywebtransport._protocol.events import UserAcceptSession, UserCloseSession, UserRejectSession
from pywebtransport.connection import WebTransportConnection
from pywebtransport.server.app import logger as app_logger
from pywebtransport.server.middleware import MiddlewareProtocol, MiddlewareRejected, StatefulMiddlewareProtocol
from pywebtransport.server.server import WebTransportServer
from pywebtransport.types import EventType


class TestServerApp:

    @pytest.fixture
    def app(self, mock_server: Any, mock_router: Any, mock_middleware_manager: Any) -> ServerApp:
        return ServerApp()

    @pytest.fixture
    def mock_connection(self, mocker: MockerFixture, tmp_path: Path) -> Any:
        cert = tmp_path / "conn_cert.pem"
        key = tmp_path / "conn_key.pem"
        cert.touch()
        key.touch()

        conn = mocker.create_autospec(WebTransportConnection, instance=True)
        conn.is_connected = True
        conn.config = ServerConfig(certfile=str(cert), keyfile=str(key))
        conn._send_event_to_engine = mocker.AsyncMock()
        conn.connection_id = "conn_1"
        conn._engine = mocker.Mock()
        return conn

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
    def mock_server(self, mocker: MockerFixture, tmp_path: Path) -> Any:
        cert = tmp_path / "server_cert.pem"
        key = tmp_path / "server_key.pem"
        cert.touch()
        key.touch()

        server_instance = mocker.create_autospec(WebTransportServer, instance=True)
        setattr(server_instance, "session_manager", mocker.MagicMock())
        server_instance.session_manager.add_session = mocker.AsyncMock()
        mocker.patch("pywebtransport.server.app.WebTransportServer", return_value=server_instance)
        server_instance.config = ServerConfig(bind_host="0.0.0.0", bind_port=4433, certfile=str(cert), keyfile=str(key))
        return server_instance

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture, mock_connection: Any) -> Any:
        session_instance = mocker.create_autospec(WebTransportSession, instance=True)
        session_instance.initialize = mocker.AsyncMock()
        session_instance.close = mocker.AsyncMock()
        session_instance.is_closed = False
        session_instance.session_id = "s1"
        session_instance.path = "/"
        session_instance._control_stream_id = 1

        mock_ref = mocker.Mock(return_value=mock_connection)
        session_instance._connection = mock_ref

        return session_instance

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
    async def test_async_context_manager_with_exception(
        self, app: ServerApp, mock_server: Any, mocker: MockerFixture
    ) -> None:
        mock_startup = mocker.patch.object(app, "startup", new_callable=mocker.AsyncMock)
        mock_shutdown = mocker.patch.object(app, "shutdown", new_callable=mocker.AsyncMock)

        with pytest.raises(ValueError, match="Test error"):
            async with app:
                mock_server.__aenter__.assert_awaited_once()
                mock_startup.assert_awaited_once()
                raise ValueError("Test error")

        mock_shutdown.assert_awaited_once()
        mock_server.close.assert_awaited_once()

    def test_decorators(self, app: ServerApp, mock_router: Any, mock_middleware_manager: Any) -> None:
        @app.route(path="/test")
        async def handler1(session: WebTransportSession) -> None: ...

        @app.pattern_route(pattern="/other/.*")
        async def handler2(session: WebTransportSession) -> None: ...

        mock_router.add_route.assert_called_once_with(path="/test", handler=handler1)
        mock_router.add_pattern_route.assert_called_once_with(pattern="/other/.*", handler=handler2)

        async def middleware(session: WebTransportSession) -> None:
            pass

        middleware_proto = cast(MiddlewareProtocol, middleware)

        registered_middleware = app.middleware(middleware_proto)

        assert registered_middleware is middleware_proto
        mock_middleware_manager.add_middleware.assert_called_once_with(middleware=middleware_proto)

        @app.on_startup
        def startup_handler() -> None: ...

        @app.on_shutdown
        def shutdown_handler() -> None: ...

        assert startup_handler in app._startup_handlers
        assert shutdown_handler in app._shutdown_handlers

    @pytest.mark.asyncio
    async def test_dispatch_to_handler_accept_exception(
        self, app: ServerApp, mock_session: Any, mock_router: Any, mock_connection: Any, mocker: MockerFixture
    ) -> None:
        mock_handler = mocker.AsyncMock()
        mock_router.route_request.return_value = (mock_handler, {})
        mock_connection._send_event_to_engine.side_effect = ValueError("Accept failed")
        mock_logger_error = mocker.patch.object(app_logger, "error")

        await app._dispatch_to_handler(session=mock_session)

        mock_logger_error.assert_called()
        assert len(app._active_handler_tasks) == 0

    @pytest.mark.asyncio
    async def test_dispatch_to_handler_connection_missing(
        self, app: ServerApp, mock_session: Any, mock_router: Any, mocker: MockerFixture
    ) -> None:
        mock_session._connection = mocker.Mock(return_value=None)
        mock_logger_error = mocker.patch.object(app_logger, "error")

        await app._dispatch_to_handler(session=mock_session)

        mock_logger_error.assert_called_with("Cannot dispatch handler, connection is missing.")
        mock_router.route_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_to_handler_no_route(
        self, app: ServerApp, mock_session: Any, mock_router: Any, mock_connection: Any
    ) -> None:
        mock_router.route_request.return_value = None

        await app._dispatch_to_handler(session=mock_session)
        await asyncio.sleep(0)

        mock_connection._send_event_to_engine.assert_awaited_once()
        call_args = mock_connection._send_event_to_engine.await_args[1]
        event = call_args["event"]
        assert isinstance(event, UserRejectSession)
        assert event.status_code == http.HTTPStatus.NOT_FOUND
        assert event.session_id == mock_session.session_id

    @pytest.mark.asyncio
    async def test_dispatch_to_handler_success(
        self,
        app: ServerApp,
        mock_session: Any,
        mock_router: Any,
        mock_connection: Any,
        mock_create_task: Any,
        mocker: MockerFixture,
    ) -> None:
        mock_handler = mocker.AsyncMock()
        mock_router.route_request.return_value = (mock_handler, {"id": "123"})
        mock_patch, mock_task = mock_create_task

        async def resolve_future(event: Event) -> None:
            if hasattr(event, "future") and event.future:
                event.future.set_result(None)

        mock_connection._send_event_to_engine.side_effect = resolve_future

        await app._dispatch_to_handler(session=mock_session)

        mock_connection._send_event_to_engine.assert_awaited_once()
        call_args = mock_connection._send_event_to_engine.await_args[1]
        event = call_args["event"]
        assert isinstance(event, UserAcceptSession)
        assert event.session_id == mock_session.session_id

        mock_patch.assert_called_once()
        assert mock_task in app._active_handler_tasks

    @pytest.mark.asyncio
    async def test_dispatch_to_handler_task_callbacks(
        self,
        app: ServerApp,
        mocker: MockerFixture,
        mock_create_task: Any,
        mock_session: Any,
        mock_router: Any,
        mock_connection: Any,
    ) -> None:
        mock_handler = mocker.AsyncMock()
        mock_router.route_request.return_value = (mock_handler, {})
        mock_patch, mock_task = mock_create_task
        mock_logger_error = mocker.patch.object(app_logger, "error")

        async def resolve_future(event: Event) -> None:
            if hasattr(event, "future") and event.future:
                event.future.set_result(None)

        mock_connection._send_event_to_engine.side_effect = resolve_future

        await app._dispatch_to_handler(session=mock_session)
        mock_task.add_done_callback.assert_called_once()
        callback = mock_task.add_done_callback.call_args[0][0]

        task_with_exception = mocker.MagicMock(spec=asyncio.Task)
        task_with_exception.cancelled.return_value = False
        task_with_exception.exception.return_value = ValueError("Task failed")
        app._active_handler_tasks.add(task_with_exception)

        callback(task_with_exception)
        assert task_with_exception not in app._active_handler_tasks
        mock_logger_error.assert_called()

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
    async def test_get_session_from_event_disconnected(
        self, app: ServerApp, mocker: MockerFixture, mock_connection: Any, mock_session: Any
    ) -> None:
        mock_connection.is_connected = False
        mock_logger_warning = mocker.patch.object(app_logger, "warning")

        event = Event(
            type=EventType.SESSION_REQUEST,
            data={"connection": mock_connection, "session": mock_session, "session_id": "s1"},
        )

        session = await app._get_session_from_event(event=event)

        assert session is None
        mock_logger_warning.assert_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "data_override, description",
        [
            ({"session": "not_a_session"}, "invalid_session_type"),
            ({"connection": "not_a_connection"}, "invalid_connection_type"),
            ({"session": None}, "missing_session_obj"),
            ({"connection": None}, "missing_connection"),
        ],
    )
    async def test_get_session_from_event_failures(
        self, app: ServerApp, mocker: MockerFixture, data_override: dict[str, Any], description: str
    ) -> None:
        mock_conn = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_session = mocker.create_autospec(WebTransportSession, instance=True)
        mock_ref = mocker.Mock(return_value=mock_conn)
        mock_session._connection = mock_ref

        base_data = {"connection": mock_conn, "session": mock_session, "session_id": "s1"}
        base_data.update(data_override)

        event = Event(type=EventType.SESSION_REQUEST, data=base_data)

        session = await app._get_session_from_event(event=event)

        assert session is None

    @pytest.mark.asyncio
    async def test_get_session_from_event_invalid_data_type(self, app: ServerApp, mocker: MockerFixture) -> None:
        mock_logger_warning = mocker.patch.object(app_logger, "warning")
        event = Event(type=EventType.SESSION_REQUEST, data="not_a_dict")

        session = await app._get_session_from_event(event=event)

        assert session is None
        mock_logger_warning.assert_called_with("Session request event data is not a dictionary")

    @pytest.mark.asyncio
    async def test_get_session_from_event_manager_exception(
        self, app: ServerApp, mock_connection: Any, mock_session: Any, mock_server: Any, mocker: MockerFixture
    ) -> None:
        mock_server.session_manager.add_session.side_effect = ValueError("Manager error")
        mock_logger_error = mocker.patch.object(app_logger, "error")

        event = Event(
            type=EventType.SESSION_REQUEST,
            data={"connection": mock_connection, "session": mock_session, "session_id": "s1"},
        )

        session = await app._get_session_from_event(event=event)

        assert session is mock_session
        mock_logger_error.assert_called()

    @pytest.mark.asyncio
    async def test_get_session_from_event_mismatched_connection(
        self, app: ServerApp, mocker: MockerFixture, mock_connection: Any
    ) -> None:
        other_conn = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_session = mocker.create_autospec(WebTransportSession, instance=True)

        mock_ref = mocker.Mock(return_value=other_conn)
        mock_session._connection = mock_ref

        event = Event(
            type=EventType.SESSION_REQUEST,
            data={"connection": mock_connection, "session": mock_session, "session_id": "s1"},
        )

        session = await app._get_session_from_event(event=event)

        assert session is None

    @pytest.mark.asyncio
    async def test_get_session_from_event_no_session_manager(
        self, app: ServerApp, mock_connection: Any, mock_session: Any
    ) -> None:
        setattr(app.server, "session_manager", None)

        event = Event(
            type=EventType.SESSION_REQUEST,
            data={"connection": mock_connection, "session": mock_session, "session_id": "s1"},
        )

        session = await app._get_session_from_event(event=event)

        assert session is mock_session

    @pytest.mark.asyncio
    async def test_get_session_from_event_success(
        self, app: ServerApp, mock_connection: Any, mock_session: Any, mock_server: Any
    ) -> None:
        event = Event(
            type=EventType.SESSION_REQUEST,
            data={"connection": mock_connection, "session": mock_session, "session_id": "s1"},
        )

        session = await app._get_session_from_event(event=event)

        assert session is mock_session
        mock_server.session_manager.add_session.assert_awaited_once_with(session=mock_session)

    @pytest.mark.asyncio
    async def test_handle_session_request_exception_cleanup(
        self, app: ServerApp, mocker: MockerFixture, mock_connection: Any, mock_session: Any
    ) -> None:
        mocker.patch.object(app, "_get_session_from_event", side_effect=ValueError("Unexpected"))

        event = Event(
            type=EventType.SESSION_REQUEST,
            data={"connection": mock_connection, "session_id": "s1", "session": mock_session},
        )

        await app._handle_session_request(event=event)

        mock_connection._send_event_to_engine.assert_awaited_once()
        call_args = mock_connection._send_event_to_engine.await_args[1]
        event_sent = call_args["event"]
        assert isinstance(event_sent, UserCloseSession)
        assert event_sent.session_id == "s1"

    @pytest.mark.asyncio
    async def test_handle_session_request_exception_cleanup_branches(
        self, app: ServerApp, mocker: MockerFixture, mock_connection: Any, mock_session: Any
    ) -> None:
        mocker.patch.object(app, "_get_session_from_event", side_effect=ValueError("Unexpected"))

        event_no_id = Event(type=EventType.SESSION_REQUEST, data={"connection": mock_connection})
        await app._handle_session_request(event=event_no_id)

        mock_connection._send_event_to_engine.assert_not_awaited()

        mock_connection.reset_mock()

        event_no_conn = Event(type=EventType.SESSION_REQUEST, data={"session_id": "s1"})
        await app._handle_session_request(event=event_no_conn)

        mock_connection._send_event_to_engine.assert_not_awaited()

        mock_session.is_closed = True
        event_closed = Event(
            type=EventType.SESSION_REQUEST,
            data={"connection": mock_connection, "session_id": "s1", "session": mock_session},
        )

        await app._handle_session_request(event=event_closed)
        mock_session.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_session_request_exception_cleanup_error(
        self, app: ServerApp, mocker: MockerFixture, mock_connection: Any
    ) -> None:
        mocker.patch.object(app, "_get_session_from_event", side_effect=ValueError("Unexpected"))
        mock_connection._send_event_to_engine.side_effect = ValueError("Cleanup error")
        mock_logger_error = mocker.patch.object(app_logger, "error")

        event = Event(type=EventType.SESSION_REQUEST, data={"connection": mock_connection, "session_id": "s1"})

        await app._handle_session_request(event=event)

        mock_logger_error.assert_any_call(
            "Error during session request error cleanup: %s", mocker.ANY, exc_info=mocker.ANY
        )

    @pytest.mark.asyncio
    async def test_handle_session_request_exception_cleanup_with_session(
        self, app: ServerApp, mocker: MockerFixture, mock_session: Any, mock_connection: Any
    ) -> None:
        mocker.patch.object(app, "_get_session_from_event", return_value=mock_session)
        mocker.patch.object(app, "_middleware_manager")
        mocker.patch.object(app, "_dispatch_to_handler", side_effect=ValueError("Dispatch error"))

        mock_session.close.side_effect = ValueError("Session close error")
        mock_logger_error = mocker.patch.object(app_logger, "error")

        event = Event(type=EventType.SESSION_REQUEST, data={})

        await app._handle_session_request(event=event)

        mock_session.close.assert_awaited_once()
        mock_logger_error.assert_any_call(
            "Error during session request error cleanup: %s", mocker.ANY, exc_info=mocker.ANY
        )

    @pytest.mark.asyncio
    async def test_handle_session_request_happy_path(
        self, app: ServerApp, mock_middleware_manager: Any, mocker: MockerFixture, mock_session: Any
    ) -> None:
        mock_get_session = mocker.patch.object(
            app, "_get_session_from_event", new_callable=mocker.AsyncMock, return_value=mock_session
        )
        mock_dispatch = mocker.patch.object(app, "_dispatch_to_handler", new_callable=mocker.AsyncMock)

        event = Event(type=EventType.SESSION_REQUEST, data={})

        await app._handle_session_request(event=event)

        mock_get_session.assert_awaited_once_with(event=event)
        mock_middleware_manager.process_request.assert_awaited_once_with(session=mock_session)
        mock_dispatch.assert_awaited_once_with(session=mock_session)

    @pytest.mark.asyncio
    async def test_handle_session_request_middleware_rejection(
        self,
        app: ServerApp,
        mock_middleware_manager: Any,
        mocker: MockerFixture,
        mock_session: Any,
        mock_connection: Any,
    ) -> None:
        mocker.patch.object(app, "_get_session_from_event", return_value=mock_session)
        mock_middleware_manager.process_request.side_effect = MiddlewareRejected(status_code=403)

        event = Event(type=EventType.SESSION_REQUEST, data={"connection": mock_connection})

        await app._handle_session_request(event=event)

        mock_connection._send_event_to_engine.assert_awaited_once()
        call_args = mock_connection._send_event_to_engine.await_args[1]
        event_sent = call_args["event"]
        assert isinstance(event_sent, UserRejectSession)
        assert event_sent.status_code == 403

        mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_session_request_middleware_rejection_branches(
        self,
        app: ServerApp,
        mock_middleware_manager: Any,
        mocker: MockerFixture,
        mock_session: Any,
        mock_connection: Any,
    ) -> None:
        mocker.patch.object(app, "_get_session_from_event", return_value=mock_session)
        mock_middleware_manager.process_request.side_effect = MiddlewareRejected(status_code=403)

        mock_session._control_stream_id = None
        event = Event(type=EventType.SESSION_REQUEST, data={"connection": mock_connection})
        await app._handle_session_request(event=event)

        mock_session.close.assert_awaited_once()

        mock_session.close.reset_mock()
        mock_connection._send_event_to_engine.reset_mock()

        mock_session.is_closed = True
        await app._handle_session_request(event=event)
        mock_session.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_session_request_middleware_rejection_no_connection(
        self, app: ServerApp, mock_middleware_manager: Any, mocker: MockerFixture, mock_session: Any
    ) -> None:
        mocker.patch.object(app, "_get_session_from_event", return_value=mock_session)
        mock_middleware_manager.process_request.side_effect = MiddlewareRejected(status_code=403)

        event = Event(type=EventType.SESSION_REQUEST, data={})

        await app._handle_session_request(event=event)

        mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_session_request_no_session(self, app: ServerApp, mocker: MockerFixture) -> None:
        mocker.patch.object(app, "_get_session_from_event", new_callable=mocker.AsyncMock, return_value=None)
        mock_middleware = mocker.patch.object(app, "_middleware_manager")

        event = Event(type=EventType.SESSION_REQUEST, data={})
        await app._handle_session_request(event=event)

        mock_middleware.process_request.assert_not_called()

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
        self, app: ServerApp, mocker: MockerFixture, run_kwargs: dict[str, Any], serve_kwargs: dict[str, Any]
    ) -> None:
        mocker.patch.object(app, "serve", new_callable=mocker.AsyncMock)
        mock_asyncio_run = mocker.patch("asyncio.run")

        app.run(**run_kwargs)

        mock_asyncio_run.assert_called_once()
        call_args = mock_asyncio_run.call_args
        main_coro = call_args.args[0] if call_args.args else call_args.kwargs.get("main")
        if asyncio.iscoroutine(main_coro):
            await main_coro

    @pytest.mark.asyncio
    async def test_run_handler_exception(self, app: ServerApp, mocker: MockerFixture, mock_session: Any) -> None:
        handler_mock = mocker.AsyncMock(side_effect=ValueError("Handler error"))

        await app._run_handler_safely(handler=handler_mock, session=mock_session, params={})

        handler_mock.assert_awaited_once_with(mock_session)
        mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_handler_safely_close_fails(
        self, app: ServerApp, mocker: MockerFixture, mock_session: Any
    ) -> None:
        handler_mock = mocker.AsyncMock()
        mock_session.is_closed = False
        mock_session.close.side_effect = RuntimeError("Close failed")

        await app._run_handler_safely(handler=handler_mock, session=mock_session, params={})

        handler_mock.assert_awaited_once()
        mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_handler_safely_connection_error(
        self, app: ServerApp, mocker: MockerFixture, mock_session: Any
    ) -> None:
        handler_mock = mocker.AsyncMock()
        mock_session.is_closed = False
        mock_session.close.side_effect = ConnectionError("Engine stopped")
        mock_logger_debug = mocker.patch.object(app_logger, "debug")

        await app._run_handler_safely(handler=handler_mock, session=mock_session, params={})

        mock_session.close.assert_awaited_once()
        mock_logger_debug.assert_any_call(
            "Session %s cleanup: Connection closed implicitly or Engine stopped (%s).",
            mock_session.session_id,
            mocker.ANY,
        )

    @pytest.mark.asyncio
    async def test_run_handler_session_already_closed(
        self, app: ServerApp, mocker: MockerFixture, mock_session: Any
    ) -> None:
        handler_mock = mocker.AsyncMock()
        mock_session.is_closed = True

        await app._run_handler_safely(handler=handler_mock, session=mock_session, params={})

        handler_mock.assert_awaited_once()
        mock_session.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_handler_with_params(self, app: ServerApp, mocker: MockerFixture, mock_session: Any) -> None:
        handler_mock = mocker.AsyncMock()
        params = {"id": "123", "action": "test"}

        await app._run_handler_safely(handler=handler_mock, session=mock_session, params=params)

        handler_mock.assert_awaited_once_with(mock_session, id="123", action="test")
        mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_with_exception(self, app: ServerApp, mocker: MockerFixture) -> None:
        def consume_coro_and_raise(*args: Any, **kwargs: Any) -> NoReturn:
            coro = kwargs.get("main") or (args[0] if args else None)
            if asyncio.iscoroutine(coro):
                coro.close()
            raise ValueError("Run error")

        mock_asyncio_run = mocker.patch("asyncio.run", side_effect=consume_coro_and_raise)

        with pytest.raises(ValueError, match="Run error"):
            app.run()

        mock_asyncio_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_with_keyboard_interrupt(self, app: ServerApp, mocker: MockerFixture) -> None:
        mocker.patch.object(app, "serve", new_callable=mocker.AsyncMock)
        mock_logger_info = mocker.patch.object(app_logger, "info")

        def consume_coro_and_raise(*args: Any, **kwargs: Any) -> NoReturn:
            coro = kwargs.get("main") or (args[0] if args else None)
            if asyncio.iscoroutine(coro):
                coro.close()
            raise KeyboardInterrupt

        mock_asyncio_run = mocker.patch("asyncio.run", side_effect=consume_coro_and_raise)

        app.run()

        mock_asyncio_run.assert_called_once()
        mock_logger_info.assert_called_with("Server stopped by user.")

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
        stateful_middleware = mocker.MagicMock(spec=StatefulMiddlewareProtocol)
        stateful_middleware.__aenter__ = mocker.AsyncMock()
        stateful_middleware.__aexit__ = mocker.AsyncMock()
        app.add_middleware(middleware=stateful_middleware)

        await app.startup()
        stateful_middleware.__aenter__.assert_awaited_once()

        await app.shutdown()
        stateful_middleware.__aexit__.assert_awaited_once_with(None, None, None)

    @pytest.mark.asyncio
    async def test_startup_shutdown_defensive_checks(self, app: ServerApp, mocker: MockerFixture) -> None:
        middleware = mocker.MagicMock(spec=StatefulMiddlewareProtocol)
        middleware.__aenter__ = mocker.AsyncMock()
        middleware.__aexit__ = mocker.AsyncMock()

        app._stateful_middleware.append(middleware)

        await app.startup()
        middleware.__aenter__.assert_awaited_once()

        await app.shutdown()
        middleware.__aexit__.assert_awaited_once()
