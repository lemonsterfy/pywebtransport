# API Reference: rpc

This document provides a reference for the `pywebtransport.rpc` subpackage, which offers a built-in framework for Remote Procedure Calls (RPC) based on the JSON-RPC 2.0 standard.

---

## RpcManager Class

Manages the RPC lifecycle over a single `WebTransportStream`. It provides methods to register server-side functions and to call remote functions.

**Note on Usage**: `RpcManager` must be used as an asynchronous context manager (`async with ...`).

### Constructor

- **`def __init__(self, *, stream: WebTransportStream, session_id: SessionId, concurrency_limit: int | None = None) -> None`**: Initializes the RPC manager over a specific stream. The `concurrency_limit` parameter controls the maximum number of concurrent RPC requests that can be processed.

### Instance Methods

- **`async def __aenter__(self) -> Self`**: Enters the async context and starts the background task for processing incoming messages.
- **`async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None`**: Exits the async context, closing the manager and its underlying stream.
- **`async def call(self, method: str, *params: Any, timeout: float = 30.0) -> Any`**: Calls a remote method and waits for its result. Parameters should be passed as positional arguments after `method`.
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

- `RpcError`: The base exception for all RPC related errors. It contains structured error data and can be serialized to a JSON-RPC 2.0 error object.
- `InvalidParamsError`: Raised when the parameters for an RPC call are invalid. Corresponds to error code -32602.
- `MethodNotFoundError`: Raised when the requested remote method does not exist. Corresponds to error code -32601.
- `RpcTimeoutError`: Raised when a client-side `call` operation times out waiting for a response.

## RpcErrorCode Enum

An `IntEnum` that defines the standard JSON-RPC 2.0 error codes.

### Attributes

- `PARSE_ERROR` (`int`): Represents a JSON parsing error on the server. `Default: -32700`.
- `INVALID_REQUEST` (`int`): The JSON sent is not a valid Request object. `Default: -32600`.
- `METHOD_NOT_FOUND` (`int`): The method does not exist / is not available. `Default: -32601`.
- `INVALID_PARAMS` (`int`): Invalid method parameter(s). `Default: -32602`.
- `INTERNAL_ERROR` (`int`): Internal JSON-RPC error. `Default: -32603`.

## See Also

- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Session API](session.md)**: Learn about the `WebTransportSession` lifecycle and management.
- **[Stream API](stream.md)**: Read from and write to WebTransport streams.