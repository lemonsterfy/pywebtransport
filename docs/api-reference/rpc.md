# API Reference: rpc

This document provides a reference for the `pywebtransport.rpc` subpackage, which offers a built-in framework for Remote Procedure Calls (RPC) based on the JSON-RPC 2.0 standard.

---

## RpcManager Class

Manages the RPC lifecycle over a single `WebTransportStream`. It provides methods to register server-side functions and to call remote functions. This class implements the asynchronous context manager protocol (`async with`) to manage the background ingress loop.

### Constructor

- **`def __init__(self, *, stream: WebTransportStream, session_id: SessionId, rpc_concurrency_limit: int | None = None) -> None`**: Initializes the RPC manager.
  - `stream`: The bidirectional stream used for RPC communication.
  - `session_id`: The ID of the session this RPC manager belongs to.
  - `rpc_concurrency_limit`: The maximum number of concurrent RPC requests to process. `Default: None` (unlimited).

### Instance Methods

- **`async def call(self, *, method: str, params: list[Any], timeout: float = 30.0) -> Any`**: Calls a remote method and waits for its result.
- **`async def close(self) -> None`**: Closes the manager, stops processing new requests, and cleans up all resources.
- **`def register(self, *, func: Callable[..., Any], name: str | None = None) -> None`**: Registers a Python function or coroutine to be callable by the remote peer.

## RPC Protocol Data Classes

These dataclasses represent the core JSON-RPC 2.0 message types.

### RpcRequest Class

Represents an RPC request.

- `id` (`str | int`): A unique identifier for the request.
- `method` (`str`): The name of the method to be invoked.
- `params` (`list[Any] | dict[str, Any]`): The parameters to be passed to the method.

### RpcSuccessResponse Class

Represents a successful RPC response.

- `id` (`str | int`): The ID matching the original request.
- `result` (`Any`): The result returned by the method.

### RpcErrorResponse Class

Represents a failed RPC response.

- `id` (`str | int | None`): The ID matching the original request (or `None` if the ID could not be determined).
- `error` (`dict[str, Any]`): A dictionary containing error details (e.g., `code`, `message`).

## RPC Exceptions

These exceptions are available in the `pywebtransport.rpc` module.

- `RpcError`: The base exception for all RPC related errors.
- `InvalidParamsError`: Raised when the parameters for an RPC call are invalid.
- `MethodNotFoundError`: Raised when the requested remote method does not exist.
- `RpcTimeoutError`: Raised when a client-side `call` operation times out waiting for a response.

## RpcErrorCode Enum

An `IntEnum` that defines the standard JSON-RPC 2.0 error codes.

- `PARSE_ERROR` (`-32700`): Parse error.
- `INVALID_REQUEST` (`-32600`): Invalid Request.
- `METHOD_NOT_FOUND` (`-32601`): Method not found.
- `INVALID_PARAMS` (`-32602`): Invalid params.
- `INTERNAL_ERROR` (`-32603`): Internal error.

## See Also

- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Session API](session.md)**: Learn about the `WebTransportSession` lifecycle and management.
- **[Stream API](stream.md)**: Read from and write to WebTransport streams.
