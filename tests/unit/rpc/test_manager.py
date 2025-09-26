"""Unit tests for the pywebtransport.rpc.manager module."""

import asyncio
import json
import struct
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ConnectionError, WebTransportSession, WebTransportStream
from pywebtransport.rpc import InvalidParamsError, RpcError, RpcManager, RpcTimeoutError


@pytest.fixture
def mock_session(mocker: MockerFixture) -> MagicMock:
    session = mocker.create_autospec(WebTransportSession, instance=True)
    session.session_id = "test-session-id"
    return session


@pytest.fixture
def mock_stream(mocker: MockerFixture) -> MagicMock:
    stream = mocker.create_autospec(WebTransportStream, instance=True)
    stream.is_closed = False
    stream.close = AsyncMock()
    stream.write = AsyncMock()

    async def wait_forever(*args: Any, **kwargs: Any) -> None:
        await asyncio.Future()

    stream.readexactly.side_effect = wait_forever
    return stream


@pytest.fixture
def rpc_manager(mock_session: MagicMock) -> RpcManager:
    return RpcManager(session=mock_session)


@pytest.mark.asyncio
class TestRpcManagerLifecycle:
    async def test_init(self, rpc_manager: RpcManager, mock_session: MagicMock) -> None:
        assert rpc_manager._session is mock_session
        assert not rpc_manager._handlers
        assert not rpc_manager._pending_calls

    async def test_context_manager_flow(
        self,
        rpc_manager: RpcManager,
        mock_session: MagicMock,
        mock_stream: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        mock_session.create_bidirectional_stream.return_value = mock_stream
        mock_create_task = mocker.patch("asyncio.create_task", side_effect=asyncio.create_task)

        async with rpc_manager:
            mock_session.create_bidirectional_stream.assert_awaited_once()
            assert mock_create_task.call_count == 1
            assert rpc_manager._stream is mock_stream
            assert rpc_manager._ingress_task is not None
            assert not rpc_manager._ingress_task.done()

        await asyncio.sleep(0)

        mock_stream.close.assert_awaited_once()
        assert not rpc_manager._pending_calls

    async def test_context_manager_reentry(self, rpc_manager: RpcManager) -> None:
        async with rpc_manager:
            assert rpc_manager._lock is not None
            lock_id = id(rpc_manager._lock)
            async with rpc_manager:
                assert id(rpc_manager._lock) == lock_id

    async def test_context_manager_with_exception(
        self,
        rpc_manager: RpcManager,
        mock_session: MagicMock,
        mock_stream: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        mock_session.create_bidirectional_stream.return_value = mock_stream
        mocker.patch("asyncio.create_task", side_effect=asyncio.create_task)

        with pytest.raises(ValueError, match="test exception"):
            async with rpc_manager:
                raise ValueError("test exception")

        await asyncio.sleep(0)
        mock_stream.close.assert_awaited_once()

    async def test_close_idempotency(self, rpc_manager: RpcManager, mocker: MockerFixture) -> None:
        mock_cleanup = mocker.patch.object(rpc_manager, "_cleanup", new_callable=AsyncMock)

        await rpc_manager.close()
        await rpc_manager.close()

        mock_cleanup.assert_awaited_once()

    async def test_cleanup(self, rpc_manager: RpcManager, mock_stream: MagicMock) -> None:
        future: asyncio.Future[Any] = asyncio.Future()
        ingress_task = asyncio.create_task(asyncio.sleep(0.1))
        rpc_manager._stream = mock_stream
        rpc_manager._pending_calls["call-1"] = future
        rpc_manager._ingress_task = ingress_task

        await rpc_manager._cleanup()

        mock_stream.close.assert_awaited_once()
        assert future.done()
        with pytest.raises(RpcError, match="RPC manager shutting down."):
            await future
        assert not rpc_manager._pending_calls
        assert ingress_task.cancelled()

    async def test_cleanup_with_done_future(self, rpc_manager: RpcManager) -> None:
        future: asyncio.Future[Any] = asyncio.Future()
        future.set_result("already done")
        rpc_manager._pending_calls["call-1"] = future

        await rpc_manager._cleanup()

        assert await future == "already done"
        assert "call-1" not in rpc_manager._pending_calls


@pytest.mark.asyncio
class TestRpcManagerCall:
    @pytest.fixture(autouse=True)
    def setup_mocks(
        self,
        mock_session: MagicMock,
        mock_stream: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        mock_session.create_bidirectional_stream.return_value = mock_stream
        mocker.patch("asyncio.create_task", side_effect=asyncio.create_task)
        mocker.patch(
            "uuid.uuid4",
            return_value=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        )

    async def test_call_success(self, rpc_manager: RpcManager, mock_stream: MagicMock) -> None:
        async with rpc_manager:
            call_id = "12345678-1234-5678-1234-567812345678"
            expected_payload = json.dumps({"id": call_id, "method": "my_method", "params": [1, "a"]}).encode()
            expected_header = struct.pack("!I", len(expected_payload))

            call_task = asyncio.create_task(rpc_manager.call("my_method", 1, "a"))
            await asyncio.sleep(0)
            future = rpc_manager._pending_calls[call_id]
            future.set_result("success")
            result = await call_task

            assert result == "success"
            assert call_id not in rpc_manager._pending_calls
            mock_stream.write.assert_awaited_once_with(data=expected_header + expected_payload)

    async def test_call_cleans_up_on_send_error(self, rpc_manager: RpcManager, mock_stream: MagicMock) -> None:
        mock_stream.write.side_effect = ConnectionError(message="send failed")

        async with rpc_manager:
            with pytest.raises(RpcError, match="RPC manager shutting down."):
                await rpc_manager.call("failing_method")

            assert not rpc_manager._pending_calls

    async def test_call_timeout(self, rpc_manager: RpcManager, mocker: MockerFixture) -> None:
        async with rpc_manager:
            mocker.patch("asyncio.wait_for", side_effect=asyncio.TimeoutError)
            with pytest.raises(RpcTimeoutError, match="RPC call to 'my_method' timed out"):
                await rpc_manager.call("my_method", timeout=10)

        assert not rpc_manager._pending_calls

    async def test_call_before_activation(self, rpc_manager: RpcManager) -> None:
        with pytest.raises(RpcError, match="RpcManager has not been activated."):
            await rpc_manager.call("method")

    async def test_call_validation(self, rpc_manager: RpcManager) -> None:
        async with rpc_manager:
            with pytest.raises(ValueError, match="RPC method name must be a non-empty string."):
                await rpc_manager.call("")
            with pytest.raises(ValueError, match="Timeout must be positive."):
                await rpc_manager.call("method", timeout=0)

    async def test_call_on_closed_stream(self, rpc_manager: RpcManager, mock_stream: MagicMock) -> None:
        async with rpc_manager:
            mock_stream.is_closed = True

            with pytest.raises(RpcError, match="RPC stream is not available or closed."):
                await rpc_manager.call("method")


class TestRpcManagerHandling:
    def test_register(self, rpc_manager: RpcManager) -> None:
        def my_handler() -> None:
            pass

        rpc_manager.register(func=my_handler, name="custom_name")

        assert "custom_name" in rpc_manager._handlers
        assert rpc_manager._handlers["custom_name"] is my_handler

        rpc_manager.register(func=my_handler, name=None)

        assert "my_handler" in rpc_manager._handlers
        assert rpc_manager._handlers["my_handler"] is my_handler

    @pytest.mark.asyncio
    async def test_handle_response_success(self, rpc_manager: RpcManager) -> None:
        future: asyncio.Future[Any] = asyncio.Future()
        rpc_manager._pending_calls["res-1"] = future
        response_message = {"id": "res-1", "result": "it worked"}

        rpc_manager._handle_response(message=response_message)

        assert await future == "it worked"

    @pytest.mark.asyncio
    async def test_handle_response_error(self, rpc_manager: RpcManager) -> None:
        future: asyncio.Future[Any] = asyncio.Future()
        rpc_manager._pending_calls["res-1"] = future
        response_message = {"id": "res-1", "error": {"code": -32600, "message": "Invalid Request"}}

        rpc_manager._handle_response(message=response_message)

        with pytest.raises(RpcError, match="Invalid Request") as exc_info:
            await future
        assert exc_info.value.error_code == -32600

    @pytest.mark.asyncio
    async def test_handle_response_error_missing_details(self, rpc_manager: RpcManager) -> None:
        future: asyncio.Future[Any] = asyncio.Future()
        rpc_manager._pending_calls["res-1"] = future
        response_message = {"id": "res-1", "error": {}}

        rpc_manager._handle_response(message=response_message)

        with pytest.raises(RpcError, match="Unknown RPC error") as exc_info:
            await future
        assert exc_info.value.error_code == 1

    @pytest.mark.asyncio
    async def test_handle_request_success(self, rpc_manager: RpcManager, mocker: MockerFixture) -> None:
        mock_send = mocker.patch.object(rpc_manager, "_send_message", new_callable=AsyncMock)
        handler = mocker.MagicMock(return_value="pong")
        rpc_manager.register(func=handler, name="ping")
        request_message = {"id": "req-1", "method": "ping", "params": [1]}

        await rpc_manager._handle_request(message=request_message)

        handler.assert_called_once_with(1)
        mock_send.assert_awaited_once_with(message={"id": "req-1", "result": "pong"})

    @pytest.mark.asyncio
    async def test_handle_request_with_async_handler(self, rpc_manager: RpcManager, mocker: MockerFixture) -> None:
        mock_send = mocker.patch.object(rpc_manager, "_send_message", new_callable=AsyncMock)

        async def async_handler(arg: int) -> str:
            await asyncio.sleep(0)
            return f"async pong {arg}"

        rpc_manager.register(func=async_handler, name="async_ping")
        request_message = {"id": "req-2", "method": "async_ping", "params": [42]}

        await rpc_manager._handle_request(message=request_message)

        mock_send.assert_awaited_once_with(message={"id": "req-2", "result": "async pong 42"})

    @pytest.mark.asyncio
    async def test_handle_request_method_not_found(self, rpc_manager: RpcManager, mocker: MockerFixture) -> None:
        mock_send = mocker.patch.object(rpc_manager, "_send_message", new_callable=AsyncMock)
        request_message = {"id": "req-1", "method": "non_existent", "params": []}

        await rpc_manager._handle_request(message=request_message)

        assert mock_send.call_args[1]["message"]["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_handle_request_as_notification(self, rpc_manager: RpcManager, mocker: MockerFixture) -> None:
        mock_send = mocker.patch.object(rpc_manager, "_send_message", new_callable=AsyncMock)
        handler = mocker.MagicMock()
        rpc_manager.register(func=handler, name="notify")
        request_message = {"method": "notify", "params": []}

        await rpc_manager._handle_request(message=request_message)

        handler.assert_called_once_with()
        mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_request_with_invalid_params_type(
        self, rpc_manager: RpcManager, mocker: MockerFixture
    ) -> None:
        mock_send = mocker.patch.object(rpc_manager, "_send_message", new_callable=AsyncMock)
        rpc_manager.register(func=lambda: None, name="any")
        request_message = {"id": "req-1", "method": "any", "params": "not-a-list"}

        await rpc_manager._handle_request(message=request_message)

        assert mock_send.call_args[1]["message"]["error"]["code"] == -32602

    @pytest.mark.asyncio
    async def test_handle_request_handler_raises_exception(
        self, rpc_manager: RpcManager, mocker: MockerFixture
    ) -> None:
        mock_send = mocker.patch.object(rpc_manager, "_send_message", new_callable=AsyncMock)
        handler = mocker.MagicMock(side_effect=ValueError("test error"))
        rpc_manager.register(func=handler, name="failing")
        request_message = {"id": "req-1", "method": "failing", "params": []}

        await rpc_manager._handle_request(message=request_message)

        assert mock_send.call_args[1]["message"]["error"]["code"] == -32603

    def test_handle_response_for_unknown_or_completed_id(self, rpc_manager: RpcManager, mocker: MockerFixture) -> None:
        mock_log = mocker.patch("pywebtransport.rpc.manager.logger.warning")
        future: asyncio.Future[Any] = asyncio.Future()
        rpc_manager._pending_calls["res-1"] = future
        response_message = {"id": "unknown-id", "result": "late response"}
        rpc_manager._handle_response(message=response_message)
        mock_log.assert_called_once()
        mock_log.reset_mock()
        future.set_result("done")
        response_message = {"id": "res-1", "result": "another late response"}
        rpc_manager._handle_response(message=response_message)
        mock_log.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_request_notification_method_not_found(
        self, rpc_manager: RpcManager, mocker: MockerFixture
    ) -> None:
        mock_send = mocker.patch.object(rpc_manager, "_send_message", new_callable=AsyncMock)
        request_message = {"method": "non_existent", "params": []}

        await rpc_manager._handle_request(message=request_message)

        mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("error_type, error_code", [(InvalidParamsError, -32602), (ValueError, -32603)])
    async def test_handle_request_notification_with_error(
        self, rpc_manager: RpcManager, mocker: MockerFixture, error_type: type[Exception], error_code: int
    ) -> None:
        mock_send = mocker.patch.object(rpc_manager, "_send_message", new_callable=AsyncMock)
        handler = mocker.MagicMock(side_effect=error_type)
        rpc_manager.register(func=handler, name="failing_notification")
        request_message: dict[str, Any] = {"id": None, "method": "failing_notification", "params": []}

        await rpc_manager._handle_request(message=request_message)

        mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_request_notification_with_invalid_params_type(
        self, rpc_manager: RpcManager, mocker: MockerFixture
    ) -> None:
        mock_send = mocker.patch.object(rpc_manager, "_send_message", new_callable=AsyncMock)
        rpc_manager.register(func=lambda: None, name="any")
        request_message = {"method": "any", "params": "not-a-list"}

        await rpc_manager._handle_request(message=request_message)

        mock_send.assert_not_awaited()


@pytest.mark.asyncio
class TestRpcManagerIngressAndErrors:
    async def test_ingress_loop_without_stream(self, rpc_manager: RpcManager) -> None:
        rpc_manager._stream = None

        await rpc_manager._ingress_loop()

        assert rpc_manager._ingress_task is None

    async def test_manager_handles_immediately_closed_stream(
        self, rpc_manager: RpcManager, mock_session: MagicMock, mock_stream: MagicMock
    ) -> None:
        mock_stream.is_closed = True
        mock_session.create_bidirectional_stream.return_value = mock_stream

        async with rpc_manager:
            await asyncio.sleep(0)

        assert rpc_manager._ingress_task is not None
        assert rpc_manager._ingress_task.done()
        mock_stream.close.assert_not_awaited()

    async def test_ingress_loop_handles_clean_eof(
        self, rpc_manager: RpcManager, mock_stream: MagicMock, mock_session: MagicMock
    ) -> None:
        mock_stream.readexactly.side_effect = [b""]
        mock_session.create_bidirectional_stream.return_value = mock_stream
        await rpc_manager._ensure_initialized()

        assert rpc_manager._ingress_task is not None
        await rpc_manager._ingress_task
        await asyncio.sleep(0)

        assert rpc_manager._ingress_task.done()
        assert not rpc_manager._ingress_task.cancelled()
        mock_stream.close.assert_awaited()

    async def test_ingress_loop_handles_bad_json_and_continues(
        self, rpc_manager: RpcManager, mock_stream: MagicMock, mock_session: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_log = mocker.patch("pywebtransport.rpc.manager.logger.warning")
        header1 = struct.pack("!I", 5)
        payload1 = b"{'bad"
        mock_stream.readexactly.side_effect = [header1, payload1, ConnectionError(message="Stream broke")]
        mock_session.create_bidirectional_stream.return_value = mock_stream

        async with rpc_manager:
            await asyncio.sleep(0)

        mock_log.assert_called_once()
        mock_stream.close.assert_awaited()

    @pytest.mark.parametrize(
        "exc", [ConnectionError(message="Stream broke"), asyncio.IncompleteReadError(partial=b"", expected=1)]
    )
    async def test_ingress_loop_breaks_on_io_error(
        self, rpc_manager: RpcManager, mock_stream: MagicMock, mock_session: MagicMock, exc: Exception
    ) -> None:
        mock_stream.readexactly.side_effect = exc
        mock_session.create_bidirectional_stream.return_value = mock_stream

        async with rpc_manager:
            await asyncio.sleep(0.01)

        assert rpc_manager._ingress_task is not None
        assert rpc_manager._ingress_task.done()
        assert rpc_manager._ingress_task.exception() is None
        mock_stream.close.assert_awaited()

    @pytest.mark.parametrize(
        "is_closing, task_cancelled, task_exception",
        [(True, False, None), (False, True, None), (False, False, None), (False, False, ValueError("Task failed"))],
    )
    async def test_on_ingress_done_scenarios(
        self,
        rpc_manager: RpcManager,
        mocker: MockerFixture,
        is_closing: bool,
        task_cancelled: bool,
        task_exception: Exception | None,
    ) -> None:
        mock_close = mocker.patch.object(rpc_manager, "close", new_callable=AsyncMock)
        mock_log = mocker.patch("pywebtransport.rpc.manager.logger.error")
        mock_task = mocker.create_autospec(asyncio.Task, instance=True)
        mock_task.cancelled.return_value = task_cancelled
        mock_task.exception.return_value = task_exception
        rpc_manager._is_closing = is_closing

        rpc_manager._on_ingress_done(mock_task)
        await asyncio.sleep(0)

        if is_closing:
            mock_close.assert_not_awaited()
        else:
            mock_close.assert_awaited_once()

        if task_exception and not is_closing:
            mock_log.assert_called_once()
        else:
            mock_log.assert_not_called()

    async def test_send_message_on_closed_stream(self, rpc_manager: RpcManager, mock_stream: MagicMock) -> None:
        rpc_manager._stream = mock_stream
        mock_stream.is_closed = True

        await rpc_manager._send_message(message={})

        mock_stream.write.assert_not_awaited()

    async def test_send_message_handles_write_error(
        self, rpc_manager: RpcManager, mock_stream: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_cleanup = mocker.patch.object(rpc_manager, "_cleanup", new_callable=AsyncMock)
        rpc_manager._stream = mock_stream
        mock_stream.write.side_effect = ConnectionError(message="Broken pipe")

        await rpc_manager._send_message(message={"id": 1})

        mock_cleanup.assert_awaited_once()
