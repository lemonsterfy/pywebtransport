"""Server-side framework for WebTransport applications."""

from .app import ServerApp
from .cluster import ServerCluster
from .middleware import (
    AuthHandlerProtocol,
    MiddlewareManager,
    MiddlewareProtocol,
    MiddlewareRejected,
    StatefulMiddlewareProtocol,
    create_auth_middleware,
    create_cors_middleware,
    create_logging_middleware,
    create_rate_limit_middleware,
)
from .router import RequestRouter, SessionHandler
from .server import ServerDiagnostics, ServerStats, WebTransportServer

__all__: list[str] = [
    "AuthHandlerProtocol",
    "MiddlewareManager",
    "MiddlewareProtocol",
    "MiddlewareRejected",
    "RequestRouter",
    "ServerApp",
    "ServerCluster",
    "ServerDiagnostics",
    "ServerStats",
    "SessionHandler",
    "StatefulMiddlewareProtocol",
    "WebTransportServer",
    "create_auth_middleware",
    "create_cors_middleware",
    "create_logging_middleware",
    "create_rate_limit_middleware",
]
