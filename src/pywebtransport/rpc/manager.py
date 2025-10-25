"""Manager for the Remote Procedure Call (RPC) pattern."""

from __future__ import annotations

import asyncio
import json
import struct
import uuid
from collections.abc import Callable
from types import TracebackType
from typing import Any, Self, cast

from pywebtransport.exceptions import ConnectionError
from pywebtransport.rpc.exceptions import InvalidParamsError, MethodNotFoundError, RpcError, RpcTimeoutError
from pywebtransport.stream import WebTransportStream
from pywebtransport.types import SessionId
from pywebtransport.utils import get_logger

__all__: list[str] = ["RpcManager"]

logger = get_logger(name=__name__)


class RpcManager:
    """Manages the RPC lifecycle over a single WebTransport session."""

    def __init__(
        self, *, stream: WebTransportStream, session_id: SessionId, concurrency_limit: int | None = None
    ) -> None:
        """Initialize the RpcManager."""
        self._stream = stream
        self._session_id = session_id
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._pending_calls: dict[str, asyncio.Future[Any]] = {}
        self._ingress_task: asyncio.Task[None] | None = None
        self._lock: asyncio.Lock | None = None
        self._is_closing = False
        self._concurrency_limit_value = concurrency_limit
        self._concurrency_limiter: asyncio.Semaphore | None = None

    async def __aenter__(self) -> Self:
        """Enter the async context, ensuring the RPC manager is initialized."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        if self._concurrency_limiter is None and self._concurrency_limit_value and self._concurrency_limit_value > 0:
            self._concurrency_limiter = asyncio.Semaphore(self._concurrency_limit_value)
        if self._ingress_task is None:
            self._ingress_task = asyncio.create_task(self._ingress_loop())
            self._ingress_task.add_done_callback(self._on_ingress_done)

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the async context, closing the RPC manager."""
        await self.close()

    async def close(self) -> None:
        """Close the RPC manager and its underlying stream."""
        if self._is_closing:
            return

        self._is_closing = True
        await self._cleanup()

    async def call(self, method: str, *params: Any, timeout: float = 30.0) -> Any:
        """Asynchronously call a remote method."""
        if not isinstance(method, str) or not method:
            raise ValueError("RPC method name must be a non-empty string.")
        if timeout <= 0:
            raise ValueError("Timeout must be positive.")
        if self._lock is None:
            raise RpcError(
                message=(
                    "RpcManager has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                ),
                session_id=self._session_id,
            )

        call_id = str(uuid.uuid4())
        future: asyncio.Future[Any] = asyncio.Future()
        request_data = {"id": call_id, "method": method, "params": list(params)}

        async with self._lock:
            if self._stream.is_closed:
                raise RpcError(message="RPC stream is not available or closed.", session_id=self._session_id)

            self._pending_calls[call_id] = future
            try:
                await self._send_message(message=request_data)
            except Exception:
                self._pending_calls.pop(call_id, None)
                raise

        try:
            logger.debug("RPC call #%s to method '%s' sent for session %s.", call_id, method, self._session_id)
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise RpcTimeoutError(
                message=f"RPC call to '{method}' timed out after {timeout}s.",
                session_id=self._session_id,
            ) from None
        finally:
            self._pending_calls.pop(call_id, None)

    def register(self, *, func: Callable[..., Any], name: str | None = None) -> None:
        """Register a function as a callable RPC method."""
        handler_name = name or func.__name__

        self._handlers[handler_name] = func
        logger.debug("RPC method '%s' registered for session %s.", handler_name, self._session_id)

    async def _cleanup(self) -> None:
        """Clean up all resources associated with the RPC manager."""
        if self._ingress_task and not self._ingress_task.done():
            self._ingress_task.cancel()
            try:
                await self._ingress_task
            except asyncio.CancelledError:
                pass

        if self._stream and not self._stream.is_closed:
            await self._stream.close()

        for future in self._pending_calls.values():
            if not future.done():
                future.set_exception(RpcError(message="RPC manager shutting down.", session_id=self._session_id))
        self._pending_calls.clear()

        logger.debug("RPC manager cleaned up for session %s.", self._session_id)

    async def _handle_request(self, *, message: dict[str, Any]) -> None:
        """Handle an incoming RPC request message."""
        if self._concurrency_limiter:
            async with self._concurrency_limiter:
                await self._process_request(message=message)
        else:
            await self._process_request(message=message)

    def _handle_response(self, *, message: dict[str, Any]) -> None:
        """Handle an incoming RPC response message."""
        response_id = cast(str, message.get("id"))
        future = self._pending_calls.get(response_id)

        if not future or future.done():
            logger.warning(
                "Received RPC response for unknown/completed call ID %s on session %s.", response_id, self._session_id
            )
            return

        if "error" in message:
            error_details = message["error"]
            error = RpcError(
                message=error_details.get("message", "Unknown RPC error"),
                error_code=error_details.get("code"),
                session_id=self._session_id,
            )
            future.set_exception(error)
        elif "result" in message:
            future.set_result(message["result"])

    async def _ingress_loop(self) -> None:
        """Continuously read and process incoming messages from the stream."""
        try:
            async with asyncio.TaskGroup() as tg:
                while not self._stream.is_closed:
                    try:
                        header = await self._stream.readexactly(n=4)
                        if not header:
                            break
                        length = struct.unpack("!I", header)[0]
                        payload = await self._stream.readexactly(n=length)
                        message = json.loads(payload.decode("utf-8"))

                        if "method" in message:
                            tg.create_task(self._handle_request(message=message))
                        elif "id" in message:
                            self._handle_response(message=message)
                    except (asyncio.IncompleteReadError, ConnectionError):
                        break
                    except json.JSONDecodeError:
                        logger.warning("Failed to decode RPC message for session %s.", self._session_id, exc_info=True)
                        continue
        except asyncio.CancelledError:
            pass

    def _on_ingress_done(self, task: asyncio.Task[None]) -> None:
        """Callback to trigger cleanup when the ingress task finishes."""
        if self._is_closing:
            return

        if not task.cancelled():
            if exc := task.exception():
                logger.error("RPC ingress task finished unexpectedly with an exception: %s.", exc, exc_info=exc)
        asyncio.create_task(self.close())

    async def _process_request(self, *, message: dict[str, Any]) -> None:
        """Process a single RPC request after acquiring the concurrency limit."""
        request_id = message.get("id")
        method_name = message.get("method", "")
        params = message.get("params", [])
        response_data: dict[str, Any] | None = None
        handler = self._handlers.get(method_name)

        if not handler:
            if request_id is not None:
                error = MethodNotFoundError(
                    message=f"Method '{method_name}' not found.", session_id=self._session_id
                ).to_dict()
                response_data = {"id": request_id, "error": error}
        else:
            try:
                if not isinstance(params, list):
                    raise InvalidParamsError(message="Parameters must be a list.", session_id=self._session_id)
                result = handler(*params)
                if asyncio.iscoroutine(result):
                    result = await result
                if request_id is not None:
                    response_data = {"id": request_id, "result": result}
            except InvalidParamsError as e:
                if request_id is not None:
                    response_data = {"id": request_id, "error": e.to_dict()}
            except Exception as e:
                if request_id is not None:
                    error = RpcError(
                        message=f"Error executing '{method_name}': {e}", session_id=self._session_id
                    ).to_dict()
                    response_data = {"id": request_id, "error": error}

        if response_data:
            await self._send_message(message=response_data)

    async def _send_message(self, *, message: dict[str, Any]) -> None:
        """Send a JSON-RPC message over the stream."""
        if self._stream.is_closed:
            return

        try:
            payload = json.dumps(message).encode("utf-8")
            header = struct.pack("!I", len(payload))
            await self._stream.write(data=header + payload)
        except Exception as e:
            logger.error("Failed to send RPC message for session %s: %s.", self._session_id, e, exc_info=True)
            await self._cleanup()
