"""Unit tests for the pywebtransport.rpc.protocol module."""

from typing import Any

import pytest

from pywebtransport.rpc import RpcErrorResponse, RpcRequest, RpcSuccessResponse


class TestRpcErrorResponse:
    @pytest.mark.parametrize("resp_id", ["error-uuid", 500, None])
    def test_instantiation(self, resp_id: str | int | None) -> None:
        error_payload = {"code": -32601, "message": "Method not found"}

        response = RpcErrorResponse(id=resp_id, error=error_payload)

        assert response.id == resp_id
        assert response.error == error_payload

    def test_kw_only_enforced(self) -> None:
        error_payload = {"code": -32603, "message": "Internal error"}

        with pytest.raises(TypeError):
            RpcErrorResponse(1, error_payload)  # type: ignore[misc]


class TestRpcRequest:
    @pytest.mark.parametrize(
        ("req_id", "params"), [("request-string-id", [1, "arg2", True]), (12345, {"kwarg1": "value1", "kwarg2": 100})]
    )
    def test_instantiation(self, req_id: str | int, params: list[Any] | dict[str, Any]) -> None:
        method_name = "test.method"

        request = RpcRequest(id=req_id, method=method_name, params=params)

        assert request.id == req_id
        assert request.method == method_name
        assert request.params == params

    def test_kw_only_enforced(self) -> None:
        with pytest.raises(TypeError):
            RpcRequest(1, "test.method", [])  # type: ignore[misc]


class TestRpcSuccessResponse:
    @pytest.mark.parametrize("resp_id", ["response-uuid", 987])
    @pytest.mark.parametrize("result", [None, True, "a string result", 42, [1, 2], {"key": "value"}])
    def test_instantiation(self, resp_id: str | int, result: Any) -> None:
        response = RpcSuccessResponse(id=resp_id, result=result)

        assert response.id == resp_id
        assert response.result == result

    def test_kw_only_enforced(self) -> None:
        with pytest.raises(TypeError):
            RpcSuccessResponse(1, "some result")  # type: ignore[misc]
