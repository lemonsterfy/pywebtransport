"""High-level application framework for building WebTransport servers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from types import TracebackType
from typing import Any, Self, TypeVar

from pywebtransport._protocol.events import UserAcceptSession, UserCloseSession, UserRejectSession
from pywebtransport.config import ServerConfig
from pywebtransport.connection.connection import WebTransportConnection
from pywebtransport.constants import ErrorCodes
from pywebtransport.events import Event
from pywebtransport.exceptions import ConnectionError
from pywebtransport.server.middleware import MiddlewareManager
from pywebtransport.server.router import RequestRouter, SessionHandler
from pywebtransport.server.server import WebTransportServer
from pywebtransport.session.session import WebTransportSession
from pywebtransport.types import EventType, MiddlewareProtocol
from pywebtransport.utils import get_logger

__all__: list[str] = ["ServerApp"]

F = TypeVar("F", bound=Callable[..., Any])

logger = get_logger(name=__name__)


class ServerApp:
    """Implement a high-level WebTransport application with routing and middleware."""

    def __init__(self, *, config: ServerConfig | None = None) -> None:
        """Initialize the server application."""
        self._server = WebTransportServer(config=config)
        self._router = RequestRouter()
        self._middleware_manager = MiddlewareManager()
        self._stateful_middleware: list[Any] = []
        self._startup_handlers: list[Callable[[], Any]] = []
        self._shutdown_handlers: list[Callable[[], Any]] = []
        self._active_handler_tasks: set[asyncio.Task[Any]] = set()
        self._server.on(event_type=EventType.SESSION_REQUEST, handler=self._handle_session_request)

    @property
    def server(self) -> WebTransportServer:
        """Get the underlying WebTransportServer instance."""
        return self._server

    async def __aenter__(self) -> Self:
        """Enter the async context and run startup procedures."""
        await self._server.__aenter__()
        await self.startup()
        logger.info("ServerApp started.")
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        """Exit the async context and run shutdown procedures."""
        await self.shutdown()
        await self._server.close()
        logger.info("ServerApp stopped.")

    def run(self, *, host: str | None = None, port: int | None = None, **kwargs: Any) -> None:
        """Run the server application in a new asyncio event loop."""
        final_host = host if host is not None else self.server.config.bind_host
        final_port = port if port is not None else self.server.config.bind_port

        async def main() -> None:
            async with self:
                await self.serve(host=final_host, port=final_port, **kwargs)

        try:
            asyncio.run(main=main())
        except KeyboardInterrupt:
            logger.info("Server stopped by user.")

    async def serve(self, *, host: str | None = None, port: int | None = None, **kwargs: Any) -> None:
        """Start the server and serve forever."""
        final_host = host if host is not None else self.server.config.bind_host
        final_port = port if port is not None else self.server.config.bind_port
        await self._server.listen(host=final_host, port=final_port)
        await self._server.serve_forever()

    async def shutdown(self) -> None:
        """Run shutdown handlers and exit stateful middleware."""
        for handler in self._shutdown_handlers:
            if asyncio.iscoroutinefunction(handler):
                await handler()
            else:
                handler()

        for middleware in reversed(self._stateful_middleware):
            if hasattr(middleware, "__aexit__"):
                await middleware.__aexit__(None, None, None)

        if self._active_handler_tasks:
            logger.info("Cancelling %d active handler tasks...", len(self._active_handler_tasks))
            tasks_to_cancel = list(self._active_handler_tasks)
            for task in tasks_to_cancel:
                task.cancel()
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            logger.info("All active handler tasks processed.")

    async def startup(self) -> None:
        """Run startup handlers and enter stateful middleware."""
        for middleware in self._stateful_middleware:
            if hasattr(middleware, "__aenter__"):
                await middleware.__aenter__()

        for handler in self._startup_handlers:
            if asyncio.iscoroutinefunction(handler):
                await handler()
            else:
                handler()

    def add_middleware(self, *, middleware: MiddlewareProtocol) -> None:
        """Add a middleware to the processing chain."""
        self._middleware_manager.add_middleware(middleware=middleware)
        if hasattr(middleware, "__aenter__") and hasattr(middleware, "__aexit__"):
            self._stateful_middleware.append(middleware)

    def middleware(self, middleware_func: MiddlewareProtocol) -> MiddlewareProtocol:
        """Register a middleware function."""
        self.add_middleware(middleware=middleware_func)
        return middleware_func

    def on_shutdown(self, handler: F) -> F:
        """Register a handler to run on application shutdown."""
        self._shutdown_handlers.append(handler)
        return handler

    def on_startup(self, handler: F) -> F:
        """Register a handler to run on application startup."""
        self._startup_handlers.append(handler)
        return handler

    def pattern_route(self, *, pattern: str) -> Callable[[SessionHandler], SessionHandler]:
        """Register a session handler for a URL pattern."""

        def decorator(handler: SessionHandler) -> SessionHandler:
            self._router.add_pattern_route(pattern=pattern, handler=handler)
            return handler

        return decorator

    def route(self, *, path: str) -> Callable[[SessionHandler], SessionHandler]:
        """Register a session handler for a specific path."""

        def decorator(handler: SessionHandler) -> SessionHandler:
            self._router.add_route(path=path, handler=handler)
            return handler

        return decorator

    async def _dispatch_to_handler(self, *, session: WebTransportSession) -> None:
        """Find the route handler and create a background task to run it."""
        handler = self._router.route_request(session=session)

        connection = session._connection
        if not (connection and hasattr(connection, "_engine") and connection._engine):
            logger.error("Cannot dispatch handler, connection or engine is missing.")
            return

        if session._control_stream_id is None:
            logger.error("Cannot process session %s, control_stream_id is missing.", session.session_id)
            return

        loop = asyncio.get_running_loop()

        if not handler:
            logger.warning(
                "No route found for session %s (path: %s). Rejecting with 404.", session.session_id, session.path
            )
            fut = loop.create_future()
            event = UserRejectSession(session_id=session.session_id, status_code=404, future=fut)
            asyncio.create_task(coro=connection._send_event_to_engine(event=event))
            return

        logger.info("Routing session request for path '%s' to handler '%s'", session.path, handler.__name__)

        try:
            accept_fut = loop.create_future()
            accept_event = UserAcceptSession(session_id=session.session_id, future=accept_fut)
            await connection._send_event_to_engine(event=accept_event)
            await accept_fut
        except Exception as e:
            logger.error("Failed to accept session %s: %s", session.session_id, e, exc_info=True)
            return

        handler_task = asyncio.create_task(coro=self._run_handler_safely(handler=handler, session=session))
        self._active_handler_tasks.add(handler_task)

        def _task_done_callback(task: asyncio.Task[Any]) -> None:
            self._active_handler_tasks.discard(task)
            if not task.cancelled() and (exc := task.exception()):
                logger.error("Handler task for session completed with error: %s", exc, exc_info=exc)

        handler_task.add_done_callback(_task_done_callback)
        logger.info("Handler task created and tracked for session %s", session.session_id)

    async def _get_session_from_event(self, *, event: Event) -> WebTransportSession | None:
        """Validate event data and retrieve the existing WebTransportSession handle."""
        if not isinstance(event.data, dict):
            logger.warning("Session request event data is not a dictionary")
            return None

        session = event.data.get("session")
        if not isinstance(session, WebTransportSession):
            logger.warning("Invalid or missing 'session' handle in session request event data. Got: %s", type(session))
            return None

        connection = event.data.get("connection")
        if not isinstance(connection, WebTransportConnection):
            logger.warning("Invalid 'connection' object in session request")
            return None

        if session._connection is not connection:
            logger.error(
                "Session handle %s does not belong to connection %s", session.session_id, connection.connection_id
            )
            return None

        if not connection.is_connected:
            logger.warning("Connection %s is not in connected state", connection.connection_id)
            return None

        logger.info("Processing session request: session_id=%s, path='%s'", session.session_id, session.path)

        if self.server.session_manager:
            try:
                await self.server.session_manager.add_session(session=session)
            except Exception as e:
                logger.error(
                    "Failed to register session %s with SessionManager: %s", session.session_id, e, exc_info=True
                )

        return session

    async def _handle_session_request(self, event: Event) -> None:
        """Orchestrate the handling of an incoming session request."""
        session: WebTransportSession | None = None
        event_data = event.data if isinstance(event.data, dict) else {}

        connection: WebTransportConnection | None = event_data.get("connection")
        session_id_from_data: str | None = event_data.get("session_id")
        loop = asyncio.get_running_loop()

        try:
            session = await self._get_session_from_event(event=event)

            if not session:
                return

            if not await self._middleware_manager.process_request(session=session):
                logger.warning("Session request for path '%s' rejected by middleware.", session.path)
                if connection and session._control_stream_id is not None:
                    fut = loop.create_future()
                    reject_event = UserRejectSession(session_id=session.session_id, status_code=403, future=fut)
                    await connection._send_event_to_engine(event=reject_event)
                if session and not session.is_closed:
                    await session.close(close_connection=False)
                return

            await self._dispatch_to_handler(session=session)

        except Exception as e:
            sid = session.session_id if session else session_id_from_data
            logger.error("Error handling session request for session %s: %s", sid, e, exc_info=True)
            try:
                if connection and sid:
                    fut = loop.create_future()
                    close_event = UserCloseSession(
                        session_id=sid,
                        error_code=ErrorCodes.INTERNAL_ERROR,
                        reason="Internal server error handling request",
                        future=fut,
                    )
                    await connection._send_event_to_engine(event=close_event)
                if session and not session.is_closed:
                    await session.close(close_connection=False)
            except Exception as cleanup_error:
                logger.error("Error during session request error cleanup: %s", cleanup_error, exc_info=cleanup_error)

    async def _run_handler_safely(self, *, handler: SessionHandler, session: WebTransportSession) -> None:
        """Wrap the session handler execution with error handling and resource cleanup."""
        try:
            logger.debug("Handler starting for session %s", session.session_id)
            await handler(session)
            logger.debug("Handler completed for session %s", session.session_id)
        except Exception as handler_error:
            logger.error("Handler error for session %s: %s", session.session_id, handler_error, exc_info=True)
        finally:
            if not session.is_closed:
                try:
                    logger.debug("Closing session %s after handler completion/error.", session.session_id)
                    await session.close()
                except ConnectionError as e:
                    logger.debug(
                        "Session %s cleanup: Connection closed implicitly or Engine stopped (%s).",
                        session.session_id,
                        e,
                    )
                except Exception as close_error:
                    logger.error(
                        "Unexpected error closing session %s: %s", session.session_id, close_error, exc_info=True
                    )
