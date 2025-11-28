"""Custom exception hierarchy for the RPC system."""

from __future__ import annotations

from enum import IntEnum
from typing import Any

from pywebtransport.exceptions import WebTransportError
from pywebtransport.types import SessionId

__all__: list[str] = ["InvalidParamsError", "MethodNotFoundError", "RpcError", "RpcErrorCode", "RpcTimeoutError"]


class RpcErrorCode(IntEnum):
    """Standard JSON-RPC 2.0 error codes."""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603


class RpcError(WebTransportError):
    """Base exception for RPC errors."""

    def __init__(
        self,
        message: str,
        *,
        error_code: int = RpcErrorCode.INTERNAL_ERROR,
        session_id: SessionId | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the RPC error."""
        full_message = f"[Session:{session_id}] {message}" if session_id else message
        super().__init__(message=full_message, error_code=error_code, details=details)
        self.session_id = session_id

    def to_dict(self) -> dict[str, Any]:
        """Convert the exception to a JSON-RPC compliant error object."""
        return {"code": self.error_code, "message": self.message}


class InvalidParamsError(RpcError):
    """Raised when the parameters for an RPC call are invalid."""

    def __init__(self, message: str, *, session_id: SessionId | None = None) -> None:
        """Initialize the invalid params error."""
        super().__init__(message=message, error_code=RpcErrorCode.INVALID_PARAMS, session_id=session_id)


class MethodNotFoundError(RpcError):
    """Raised when the remote method does not exist."""

    def __init__(self, message: str, *, session_id: SessionId | None = None) -> None:
        """Initialize the method not found error."""
        super().__init__(message=message, error_code=RpcErrorCode.METHOD_NOT_FOUND, session_id=session_id)


class RpcTimeoutError(RpcError):
    """Raised when an RPC call times out."""

    def __init__(self, message: str, *, session_id: SessionId | None = None) -> None:
        """Initialize the RPC timeout error."""
        super().__init__(message=message, error_code=RpcErrorCode.INTERNAL_ERROR, session_id=session_id)
