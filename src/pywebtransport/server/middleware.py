"""WebTransport Middleware Framework."""

from __future__ import annotations

import asyncio
from typing import Any, Self

from pywebtransport.exceptions import ServerError
from pywebtransport.session import WebTransportSession
from pywebtransport.types import AuthHandlerProtocol, MiddlewareProtocol
from pywebtransport.utils import get_logger, get_timestamp

__all__ = [
    "MiddlewareManager",
    "RateLimiter",
    "create_auth_middleware",
    "create_cors_middleware",
    "create_logging_middleware",
    "create_rate_limit_middleware",
]

logger = get_logger(name="server.middleware")


class MiddlewareManager:
    """Manages a chain of server middleware."""

    def __init__(self) -> None:
        """Initialize the middleware manager."""
        self._middleware: list[MiddlewareProtocol] = []

    def add_middleware(self, *, middleware: MiddlewareProtocol) -> None:
        """Add a middleware to the chain."""
        self._middleware.append(middleware)

    def get_middleware_count(self) -> int:
        """Get the number of registered middleware."""
        return len(self._middleware)

    async def process_request(self, *, session: WebTransportSession) -> bool:
        """Process a request through the middleware chain."""
        for middleware in self._middleware:
            try:
                if not await middleware(session=session):
                    return False
            except Exception as e:
                logger.error("Middleware error: %s", e, exc_info=True)
                return False
        return True

    def remove_middleware(self, *, middleware: MiddlewareProtocol) -> None:
        """Remove a middleware from the chain."""
        if middleware in self._middleware:
            self._middleware.remove(middleware)


class RateLimiter:
    """A stateful, concurrent-safe rate-limiting middleware."""

    def __init__(
        self,
        *,
        max_requests: int = 100,
        window_seconds: int = 60,
        cleanup_interval: int = 300,
    ) -> None:
        """Initialize the rate limiter."""
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._cleanup_interval = cleanup_interval
        self._requests: dict[str, list[float]] = {}
        self._lock: asyncio.Lock | None = None
        self._cleanup_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> Self:
        """Enter async context, initializing resources and starting the background cleanup task."""
        self._lock = asyncio.Lock()
        self._start_cleanup_task()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Stop the background cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def _periodic_cleanup(self) -> None:
        """Periodically remove stale IP entries from the tracker."""
        if self._lock is None:
            logger.error("RateLimiter cleanup task cannot run without a lock.")
            return

        while True:
            await asyncio.sleep(self._cleanup_interval)
            async with self._lock:
                current_time = get_timestamp()
                cutoff_time = current_time - self._window_seconds
                stale_ips = [
                    ip for ip, timestamps in self._requests.items() if not timestamps or timestamps[-1] < cutoff_time
                ]
                for ip in stale_ips:
                    del self._requests[ip]
                if stale_ips:
                    logger.debug(
                        "Cleaned up %d stale IP entries from rate limiter.",
                        len(stale_ips),
                    )

    def _start_cleanup_task(self) -> None:
        """Create and start the periodic cleanup task if not already running."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

    async def __call__(self, *, session: WebTransportSession) -> bool:
        """Apply rate limiting to an incoming session."""
        if self._lock is None:
            raise ServerError(
                message=(
                    "RateLimiter has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )
        if not session.connection or not session.connection.remote_address:
            return True

        client_ip = session.connection.remote_address[0]
        current_time = get_timestamp()

        async with self._lock:
            cutoff_time = current_time - self._window_seconds
            client_requests = self._requests.get(client_ip, [])
            valid_requests = [t for t in client_requests if t > cutoff_time]

            if len(valid_requests) >= self._max_requests:
                logger.warning("Rate limit exceeded for %s", client_ip)
                return False

            valid_requests.append(current_time)
            self._requests[client_ip] = valid_requests
        return True


def create_auth_middleware(
    *,
    auth_handler: AuthHandlerProtocol,
) -> MiddlewareProtocol:
    """Create an authentication middleware with a custom handler."""

    async def middleware(*, session: WebTransportSession) -> bool:
        try:
            return await auth_handler(headers=session.headers)
        except Exception as e:
            logger.error("Authentication handler error: %s", e, exc_info=True)
            return False

    return middleware


def create_cors_middleware(
    *,
    allowed_origins: list[str],
) -> MiddlewareProtocol:
    """Create a CORS middleware to validate the Origin header."""
    allowed_set = set(allowed_origins)

    async def cors_middleware(*, session: WebTransportSession) -> bool:
        origin = session.headers.get("origin")
        if not origin:
            logger.warning("CORS check failed: 'Origin' header missing.")
            return False

        if "*" in allowed_set or origin in allowed_set:
            return True
        else:
            logger.warning("CORS check failed: Origin '%s' not in allowed list.", origin)
            return False

    return cors_middleware


def create_logging_middleware() -> MiddlewareProtocol:
    """Create a simple request logging middleware."""

    async def middleware(*, session: WebTransportSession) -> bool:
        remote_address_str = "unknown"
        if session.connection and session.connection.remote_address:
            remote_address_str = f"{session.connection.remote_address[0]}:{session.connection.remote_address[1]}"
        logger.info("Session request: path='%s' from=%s", session.path, remote_address_str)
        return True

    return middleware


def create_rate_limit_middleware(
    *,
    max_requests: int = 100,
    window_seconds: int = 60,
    cleanup_interval: int = 300,
) -> RateLimiter:
    """Create a stateful rate-limiting middleware instance."""
    return RateLimiter(
        max_requests=max_requests,
        window_seconds=window_seconds,
        cleanup_interval=cleanup_interval,
    )
