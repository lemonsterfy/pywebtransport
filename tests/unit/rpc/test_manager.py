"""Unit tests for the pywebtransport.rpc.manager module."""

import asyncio
import json
import struct
import uuid
from collections.abc import AsyncGenerator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from pytest_mock import MockerFixture

from pywebtransport import ConnectionError, WebTransportStream
from pywebtransport.rpc import RpcError, RpcManager, RpcTimeoutError


@pytest.fixture
def mock_stream(mocker: MockerFixture) -> MagicMock:
    stream = mocker.create_autospec(WebTransportStream, instance=True)
    stream.is_closed = False
    stream.close = AsyncMock()
    stream.write = AsyncMock()

    async def wait_forever(*args: Any, **kwargs: Any) -> None:
        await asyncio.Future()

    stream.readexactly = AsyncMock(side_effect=wait_forever)
    return stream


@pytest.fixture
def rpc_manager(mock_stream: MagicMock) -> RpcManager:
    return RpcManager(stream=mock_stream, session_id="test-session-id")


@pytest_asyncio.fixture
async def running_manager(rpc_manager: RpcManager) -> AsyncGenerator[RpcManager, None]:
    async with rpc_manager as manager:
        yield manager


@pytest.mark.asyncio
class TestRpcManagerCall:
    @pytest.fixture(autouse=True)
    def setup_mocks(self, mocker: MockerFixture) -> None:
        mocker.patch("uuid.uuid4", return_value=uuid.UUID("12345678-1234-5678-1234-567812345678"))

    async def test_call_before_activation(self, rpc_manager: RpcManager) -> None:
        with pytest.raises(RpcError, match="RpcManager has not been activated."):
            await rpc_manager.call("method")

    @pytest.mark.parametrize(
        "method, timeout, error_msg",
        [
            ("", 1.0, "must be a non-empty string"),
            (123, 1.0, "must be a non-empty string"),
            ("method", 0, "must be positive"),
            ("method", -1.0, "must be positive"),
        ],
    )
    async def test_call_invalid_arguments(
        self, running_manager: RpcManager, method: Any, timeout: float, error_msg: str
    ) -> None:
        with pytest.raises(ValueError, match=error_msg):
            await running_manager.call(method, timeout=timeout)

    async def test_call_on_closed_stream(self, running_manager: RpcManager, mock_stream: MagicMock) -> None:
        mock_stream.is_closed = True
        with pytest.raises(RpcError, match="RPC stream is not available"):
            await running_manager.call("method")

    async def test_call_send_failure_removes_pending(self, running_manager: RpcManager, mock_stream: MagicMock) -> None:
        mock_stream.write.side_effect = ConnectionError("write failed")
        with pytest.raises(RpcError, match="RPC manager shutting down."):
            await running_manager.call("my_method")
        assert not running_manager._pending_calls

    async def test_call_success(self, running_manager: RpcManager, mock_stream: MagicMock) -> None:
        call_id = "12345678-1234-5678-1234-567812345678"
        expected_payload = json.dumps({"id": call_id, "method": "my_method", "params": [1, "a"]}).encode()
        expected_header = struct.pack("!I", len(expected_payload))

        call_task = asyncio.create_task(running_manager.call("my_method", 1, "a"))
        await asyncio.sleep(0)
        future = running_manager._pending_calls[call_id]
        future.set_result("success")
        result = await call_task

        assert result == "success"
        mock_stream.write.assert_awaited_once_with(data=expected_header + expected_payload)

    async def test_call_timeout(self, running_manager: RpcManager) -> None:
        with pytest.raises(RpcTimeoutError, match="timed out"):
            await running_manager.call("my_method", timeout=0.01)


@pytest.mark.asyncio
class TestRpcManagerHandling:
    async def test_handle_response_error(self, rpc_manager: RpcManager) -> None:
        future: asyncio.Future[Any] = asyncio.Future()
        rpc_manager._pending_calls["res-1"] = future
        response_message = {
            "id": "res-1",
            "error": {"code": -32600, "message": "Invalid Request"},
        }

        rpc_manager._handle_response(message=response_message)
        with pytest.raises(RpcError, match="Invalid Request") as exc_info:
            await future
        assert exc_info.value.error_code == -32600

    async def test_handle_response_error_no_message(self, rpc_manager: RpcManager) -> None:
        future: asyncio.Future[Any] = asyncio.Future()
        rpc_manager._pending_calls["res-1"] = future
        response_message = {"id": "res-1", "error": {"code": -32000}}

        rpc_manager._handle_response(message=response_message)
        with pytest.raises(RpcError, match="Unknown RPC error"):
            await future

    async def test_handle_response_for_unknown_or_completed_call(self, rpc_manager: RpcManager) -> None:
        completed_future: asyncio.Future[Any] = asyncio.Future()
        completed_future.set_result(True)
        rpc_manager._pending_calls["completed-1"] = completed_future

        rpc_manager._handle_response(message={"id": "unknown-1", "result": "data"})
        rpc_manager._handle_response(message={"id": "completed-1", "result": "data"})
        assert not rpc_manager._pending_calls.get("unknown-1")

    async def test_handle_response_success(self, rpc_manager: RpcManager) -> None:
        future: asyncio.Future[Any] = asyncio.Future()
        rpc_manager._pending_calls["res-1"] = future
        response_message = {"id": "res-1", "result": "it worked"}

        rpc_manager._handle_response(message=response_message)
        assert await future == "it worked"

    async def test_process_request_generic_handler_error(self, rpc_manager: RpcManager, mocker: MockerFixture) -> None:
        mock_send = mocker.patch.object(rpc_manager, "_send_message", new_callable=AsyncMock)

        def faulty_handler() -> None:
            raise ValueError("Something went wrong")

        rpc_manager.register(func=faulty_handler)
        request_message = {"id": "req-1", "method": "faulty_handler", "params": []}

        await rpc_manager._process_request(message=request_message)
        assert "Error executing 'faulty_handler'" in mock_send.call_args[1]["message"]["error"]["message"]

    async def test_process_request_invalid_params_error(self, rpc_manager: RpcManager, mocker: MockerFixture) -> None:
        mock_send = mocker.patch.object(rpc_manager, "_send_message", new_callable=AsyncMock)
        rpc_manager.register(func=lambda: None, name="any")
        request_message = {"id": "req-1", "method": "any", "params": "not-a-list"}

        await rpc_manager._process_request(message=request_message)
        assert mock_send.call_args[1]["message"]["error"]["code"] == -32602

    async def test_process_request_invalid_params_notification(
        self, rpc_manager: RpcManager, mocker: MockerFixture
    ) -> None:
        mock_send = mocker.patch.object(rpc_manager, "_send_message", new_callable=AsyncMock)
        rpc_manager.register(func=lambda: None, name="any")
        request_message = {"method": "any", "params": "not-a-list"}

        await rpc_manager._process_request(message=request_message)
        mock_send.assert_not_awaited()

    @pytest.mark.parametrize("message_id", ["req-1", None])
    async def test_process_request_method_not_found(
        self, rpc_manager: RpcManager, mocker: MockerFixture, message_id: str | None
    ) -> None:
        mock_send = mocker.patch.object(rpc_manager, "_send_message", new_callable=AsyncMock)
        request_message: dict[str, Any] = {"method": "non_existent", "params": []}
        if message_id:
            request_message["id"] = message_id

        await rpc_manager._process_request(message=request_message)

        if message_id:
            mock_send.assert_awaited_once()
            assert mock_send.call_args[1]["message"]["error"]["code"] == -32601
        else:
            mock_send.assert_not_awaited()

    async def test_process_request_notification_with_error(
        self, rpc_manager: RpcManager, mocker: MockerFixture
    ) -> None:
        mock_send = mocker.patch.object(rpc_manager, "_send_message", new_callable=AsyncMock)

        def faulty_handler() -> None:
            raise ValueError("error")

        rpc_manager.register(func=faulty_handler)
        request_message = {"method": "faulty_handler", "params": []}

        await rpc_manager._process_request(message=request_message)
        mock_send.assert_not_awaited()

    async def test_process_request_success_async_handler(self, rpc_manager: RpcManager, mocker: MockerFixture) -> None:
        mock_send = mocker.patch.object(rpc_manager, "_send_message", new_callable=AsyncMock)

        async def double(x: int) -> int:
            return x * 2

        rpc_manager.register(func=double)
        request_message = {"id": "req-1", "method": "double", "params": [2]}

        await rpc_manager._process_request(message=request_message)
        mock_send.assert_awaited_once_with(message={"id": "req-1", "result": 4})

    async def test_process_request_success_sync_handler(self, rpc_manager: RpcManager, mocker: MockerFixture) -> None:
        mock_send = mocker.patch.object(rpc_manager, "_send_message", new_callable=AsyncMock)
        rpc_manager.register(func=lambda x: x * 2, name="double")
        request_message = {"id": "req-1", "method": "double", "params": [2]}

        await rpc_manager._process_request(message=request_message)
        mock_send.assert_awaited_once_with(message={"id": "req-1", "result": 4})


@pytest.mark.asyncio
class TestRpcManagerIngressAndErrors:
    @pytest.mark.parametrize("error", [ConnectionError("Stream broke"), asyncio.IncompleteReadError(b"", None)])
    async def test_ingress_loop_breaks_on_io_error(
        self, rpc_manager: RpcManager, mock_stream: MagicMock, error: Exception
    ) -> None:
        cast(AsyncMock, mock_stream.readexactly).side_effect = error
        async with rpc_manager:
            if rpc_manager._ingress_task:
                await rpc_manager._ingress_task
        if rpc_manager._ingress_task:
            assert rpc_manager._ingress_task.done()

    async def test_ingress_loop_dispatches_correctly(self, rpc_manager: RpcManager, mocker: MockerFixture) -> None:
        request_msg = {"id": 1, "method": "ping", "params": []}
        response_msg = {"id": 2, "result": "pong"}
        request_bytes = json.dumps(request_msg).encode()
        response_bytes = json.dumps(response_msg).encode()
        mock_stream = rpc_manager._stream
        cast(AsyncMock, mock_stream.readexactly).side_effect = [
            struct.pack("!I", len(request_bytes)),
            request_bytes,
            struct.pack("!I", len(response_bytes)),
            response_bytes,
            asyncio.IncompleteReadError(b"", None),
        ]
        handle_req_spy = mocker.spy(rpc_manager, "_handle_request")
        handle_res_spy = mocker.spy(rpc_manager, "_handle_response")

        async with rpc_manager:
            if rpc_manager._ingress_task:
                await rpc_manager._ingress_task

        handle_req_spy.assert_awaited_once_with(message=request_msg)
        handle_res_spy.assert_called_once_with(message=response_msg)

    async def test_ingress_loop_handles_clean_eof(self, rpc_manager: RpcManager, mock_stream: MagicMock) -> None:
        cast(AsyncMock, mock_stream.readexactly).side_effect = [
            b"",
            ConnectionError("EOF"),
        ]
        async with rpc_manager:
            if rpc_manager._ingress_task:
                await rpc_manager._ingress_task
        if rpc_manager._ingress_task:
            assert rpc_manager._ingress_task.done()

    async def test_ingress_loop_skips_json_decode_error(self, rpc_manager: RpcManager, mock_stream: MagicMock) -> None:
        invalid_json = b"not-json"
        cast(AsyncMock, mock_stream.readexactly).side_effect = [
            struct.pack("!I", len(invalid_json)),
            invalid_json,
            ConnectionError("EOF"),
        ]
        async with rpc_manager:
            if rpc_manager._ingress_task:
                await rpc_manager._ingress_task
        if rpc_manager._ingress_task:
            assert rpc_manager._ingress_task.done()

    @pytest.mark.parametrize("is_closing", [True, False])
    @pytest.mark.parametrize("is_cancelled", [True, False])
    @pytest.mark.parametrize("exception", [ValueError("test error"), None])
    async def test_on_ingress_done_scenarios(
        self,
        rpc_manager: RpcManager,
        mocker: MockerFixture,
        is_closing: bool,
        is_cancelled: bool,
        exception: Exception | None,
    ) -> None:
        rpc_manager._is_closing = is_closing
        mock_close = mocker.patch.object(rpc_manager, "close", new_callable=AsyncMock)
        mock_task = mocker.create_autospec(asyncio.Task, instance=True)
        mock_task.cancelled.return_value = is_cancelled
        mock_task.exception.return_value = exception

        rpc_manager._on_ingress_done(mock_task)
        await asyncio.sleep(0)

        should_close = not is_closing
        assert mock_close.call_count == (1 if should_close else 0)

    async def test_on_ingress_done_with_exception(self, rpc_manager: RpcManager, mocker: MockerFixture) -> None:
        mock_close = mocker.patch.object(rpc_manager, "close", new_callable=AsyncMock)
        mock_task = mocker.create_autospec(asyncio.Task, instance=True)
        mock_task.cancelled.return_value = False
        mock_task.exception.return_value = ValueError("Task failed")

        rpc_manager._on_ingress_done(mock_task)
        await asyncio.sleep(0)
        mock_close.assert_awaited_once()

    async def test_send_message_error_triggers_cleanup(
        self, running_manager: RpcManager, mock_stream: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_stream.write.side_effect = ConnectionError("write error")
        cleanup_spy = mocker.spy(running_manager, "_cleanup")

        await running_manager._send_message(message={})

        cleanup_spy.assert_awaited_once()

    async def test_send_message_on_closed_stream_returns_early(
        self, running_manager: RpcManager, mock_stream: MagicMock
    ) -> None:
        mock_stream.is_closed = True
        await running_manager._send_message(message={})
        mock_stream.write.assert_not_awaited()


@pytest.mark.asyncio
class TestRpcManagerLifecycle:
    async def test_aenter_idempotency_no_concurrency(self, mock_stream: MagicMock) -> None:
        manager = RpcManager(stream=mock_stream, session_id="sid", concurrency_limit=None)
        async with manager:
            assert manager._concurrency_limiter is None
            await manager.__aenter__()
            assert manager._concurrency_limiter is None

    async def test_aenter_is_idempotent(self, rpc_manager: RpcManager) -> None:
        async with rpc_manager:
            initial_task = rpc_manager._ingress_task
            await rpc_manager.__aenter__()
            assert rpc_manager._ingress_task is initial_task

    async def test_cleanup_cancels_pending_calls_and_stream(
        self, running_manager: RpcManager, mock_stream: MagicMock
    ) -> None:
        future: asyncio.Future[Any] = asyncio.Future()
        running_manager._pending_calls["call-1"] = future

        await running_manager._cleanup()

        assert future.done()
        with pytest.raises(RpcError, match="RPC manager shutting down."):
            await future
        mock_stream.close.assert_awaited_once()

    async def test_cleanup_handles_already_closed_stream(
        self, running_manager: RpcManager, mock_stream: MagicMock
    ) -> None:
        mock_stream.is_closed = True
        await running_manager._cleanup()
        mock_stream.close.assert_not_awaited()

    async def test_cleanup_ignores_done_future(self, running_manager: RpcManager) -> None:
        future: asyncio.Future[Any] = asyncio.Future()
        future.set_result(True)
        running_manager._pending_calls["call-1"] = future

        await running_manager._cleanup()

        with pytest.raises(asyncio.InvalidStateError):
            future.set_exception(RpcError(message="should not be set"))

    async def test_close_idempotency(self, running_manager: RpcManager, mocker: MockerFixture) -> None:
        mock_cleanup = mocker.patch.object(running_manager, "_cleanup", new_callable=AsyncMock)
        await running_manager.close()
        await running_manager.close()
        mock_cleanup.assert_awaited_once()

    async def test_context_manager_flow(self, rpc_manager: RpcManager, mock_stream: MagicMock) -> None:
        async with rpc_manager:
            assert rpc_manager._ingress_task is not None
            assert not rpc_manager._ingress_task.done()

        await asyncio.sleep(0)
        mock_stream.close.assert_awaited_once()
        assert not rpc_manager._pending_calls

    async def test_init_with_concurrency_limit(self, mock_stream: MagicMock) -> None:
        manager = RpcManager(stream=mock_stream, session_id="test-session", concurrency_limit=10)
        assert manager._concurrency_limit_value == 10

    async def test_init_without_concurrency_limit(self, mock_stream: MagicMock) -> None:
        manager = RpcManager(stream=mock_stream, session_id="test-session", concurrency_limit=None)
        async with manager:
            assert manager._concurrency_limiter is None


class TestRpcManagerRegistration:
    def test_register(self, rpc_manager: RpcManager) -> None:
        def my_handler() -> None:
            pass

        rpc_manager.register(func=my_handler, name="custom_name")
        assert "custom_name" in rpc_manager._handlers
        assert rpc_manager._handlers["custom_name"] is my_handler

        rpc_manager.register(func=my_handler, name=None)
        assert "my_handler" in rpc_manager._handlers
        assert rpc_manager._handlers["my_handler"] is my_handler
