"""Data structures for the RPC protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__: list[str] = ["RpcErrorResponse", "RpcRequest", "RpcSuccessResponse"]


@dataclass(kw_only=True)
class RpcErrorResponse:
    """A failed RPC response."""

    id: str | int | None
    error: dict[str, Any]


@dataclass(kw_only=True)
class RpcRequest:
    """An RPC request."""

    id: str | int
    method: str
    params: list[Any] | dict[str, Any]


@dataclass(kw_only=True)
class RpcSuccessResponse:
    """A successful RPC response."""

    id: str | int
    result: Any
