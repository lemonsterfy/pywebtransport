"""
WebTransport Server Subpackage.

Provides the high-level ServerApp framework, core components,
and utilities for building WebTransport applications.
"""

from .app import ServerApp
from .cluster import ServerCluster
from .middleware import (
    MiddlewareManager,
    create_auth_middleware,
    create_cors_middleware,
    create_logging_middleware,
    create_rate_limit_middleware,
)
from .monitor import ServerMonitor
from .router import RequestRouter
from .server import ServerStats, WebTransportServer
from .utils import (
    create_development_server,
    create_echo_server_app,
    create_simple_app,
    echo_handler,
    health_check_handler,
)

__all__ = [
    # High-level Application Framework
    "ServerApp",
    "create_development_server",
    "create_echo_server_app",
    "create_simple_app",
    # Core Server & Management Components
    "MiddlewareManager",
    "RequestRouter",
    "ServerCluster",
    "ServerMonitor",
    "ServerStats",
    "WebTransportServer",
    # Built-in Handlers
    "echo_handler",
    "health_check_handler",
    # Built-in Middleware Factories
    "create_auth_middleware",
    "create_cors_middleware",
    "create_logging_middleware",
    "create_rate_limit_middleware",
]
