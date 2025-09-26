"""Core data structures for the WebTransport RPC protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "RpcErrorResponse",
    "RpcRequest",
    "RpcSuccessResponse",
]


@dataclass(kw_only=True)
class RpcErrorResponse:
    """Represents a failed RPC response."""

    id: str | int | None
    error: dict[str, Any]


@dataclass(kw_only=True)
class RpcRequest:
    """Represents an RPC request."""

    id: str | int
    method: str
    params: list[Any] | dict[str, Any]


@dataclass(kw_only=True)
class RpcSuccessResponse:
    """Represents a successful RPC response."""

    id: str | int
    result: Any
