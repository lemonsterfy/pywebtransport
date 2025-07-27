"""
WebTransport Connection Subpackage.

Provides high-level abstractions for creating and managing
WebTransport connections, including managers, pools, and load balancers.
"""

from .connection import ConnectionInfo, WebTransportConnection
from .load_balancer import ConnectionLoadBalancer
from .manager import ConnectionManager
from .pool import ConnectionPool

__all__ = [
    "ConnectionInfo",
    "ConnectionLoadBalancer",
    "ConnectionManager",
    "ConnectionPool",
    "WebTransportConnection",
]
