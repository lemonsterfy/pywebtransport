"""Unit tests for the pywebtransport.rpc.exceptions module."""

import pytest

from pywebtransport.rpc import InvalidParamsError, MethodNotFoundError, RpcError, RpcErrorCode, RpcTimeoutError
from pywebtransport.types import SessionId


class TestRpcError:
    def test_init_with_custom_code_and_details(self) -> None:
        message = "Invalid request format."
        details = {"field": "missing_id"}

        error = RpcError(
            message=message,
            error_code=RpcErrorCode.INVALID_REQUEST,
            details=details,
        )

        assert error.message == message
        assert error.error_code == RpcErrorCode.INVALID_REQUEST
        assert error.details == details

    def test_init_with_session_id(self) -> None:
        message = "Something went wrong."
        session_id: SessionId = "session-abc-123"

        error = RpcError(message=message, session_id=session_id)

        expected_message = f"[Session:{session_id}] {message}"
        assert error.message == expected_message
        assert error.session_id == session_id

    def test_init_without_session_id(self) -> None:
        message = "An internal error occurred."

        error = RpcError(message=message)

        assert error.message == message
        assert error.error_code == RpcErrorCode.INTERNAL_ERROR
        assert error.session_id is None
        assert error.details == {}

    def test_to_dict_conversion(self) -> None:
        message = "A test error."
        session_id: SessionId = "session-xyz-789"
        error_code = RpcErrorCode.PARSE_ERROR
        error = RpcError(message=message, session_id=session_id, error_code=error_code)

        error_dict = error.to_dict()

        expected_message = f"[Session:{session_id}] {message}"
        expected_dict = {"code": error_code, "message": expected_message}
        assert error_dict == expected_dict


class TestRpcErrorCode:
    def test_enum_values(self) -> None:
        assert RpcErrorCode.PARSE_ERROR.value == -32700
        assert RpcErrorCode.INVALID_REQUEST.value == -32600
        assert RpcErrorCode.METHOD_NOT_FOUND.value == -32601
        assert RpcErrorCode.INVALID_PARAMS.value == -32602
        assert RpcErrorCode.INTERNAL_ERROR.value == -32603


@pytest.mark.parametrize(
    ("exception_class", "expected_code"),
    [
        (InvalidParamsError, RpcErrorCode.INVALID_PARAMS),
        (MethodNotFoundError, RpcErrorCode.METHOD_NOT_FOUND),
        (RpcTimeoutError, RpcErrorCode.INTERNAL_ERROR),
    ],
)
class TestSpecializedRpcErrors:
    def test_specialized_error_init(
        self,
        exception_class: type[RpcError],
        expected_code: RpcErrorCode,
    ) -> None:
        message = f"This is a test for {exception_class.__name__}"

        error = exception_class(message=message)

        assert isinstance(error, RpcError)
        assert error.error_code == expected_code
        assert error.message == message
        assert error.session_id is None

    def test_specialized_error_init_with_session_id(
        self,
        exception_class: type[RpcError],
        expected_code: RpcErrorCode,
    ) -> None:
        message = f"Another test for {exception_class.__name__}"
        session_id: SessionId = "session-special-456"

        error = exception_class(message=message, session_id=session_id)

        expected_message = f"[Session:{session_id}] {message}"
        assert isinstance(error, RpcError)
        assert error.error_code == expected_code
        assert error.message == expected_message
        assert error.session_id == session_id
