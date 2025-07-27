"""
WebTransport Client Subpackage.

This module exposes the public API for the client sub-package, including
the core WebTransportClient, high-level abstractions, and utilities.
"""

from .browser import WebTransportBrowser
from .client import ClientStats, WebTransportClient
from .monitor import ClientMonitor
from .pool import ClientPool
from .pooled import PooledClient
from .proxy import WebTransportProxy
from .reconnecting import ReconnectingClient
from .utils import (
    benchmark_client_performance,
    test_client_connectivity,
)

__all__ = [
    # Core Client
    "ClientStats",
    "WebTransportClient",
    # High-level Client Abstractions
    "ClientMonitor",
    "ClientPool",
    "PooledClient",
    "ReconnectingClient",
    "WebTransportBrowser",
    "WebTransportProxy",
    # Testing and Diagnostic Utilities
    "benchmark_client_performance",
    "test_client_connectivity",
]
