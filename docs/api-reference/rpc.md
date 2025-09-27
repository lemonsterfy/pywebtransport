# API Reference: rpc

This document provides a reference for the `pywebtransport.rpc` subpackage, which offers a built-in framework for Remote Procedure Calls (RPC) based on the JSON-RPC 2.0 standard.

---

## RpcManager Class

Manages the RPC lifecycle over a single `WebTransportSession`. It provides methods to register server-side functions and to call remote functions.

**Note on Usage**: `RpcManager` must be used as an asynchronous context manager (`async with ...`).

### Constructor

- **`def __init__(self, *, session: WebTransportSession, concurrency_limit: int | None = None) -> None`**: Initializes the RPC manager for a given session. The `concurrency_limit` parameter controls the maximum number of concurrent RPC requests that can be processed.

### Instance Methods

- **`def register(self, *, func: Callable[..., Any], name: str | None = None) -> None`**: Registers a Python function or coroutine to be callable by the remote peer.
- **`async def call(self, method: str, *params: Any, timeout: float = 30.0) -> Any`**: Calls a remote method and waits for its result. Parameters should be passed as positional arguments after `method`.
- **`async def close(self) -> None`**: Closes the manager and stops processing new requests.

## RPC Exceptions

These exceptions are available in the `pywebtransport.rpc.exceptions` module.

- `RpcError`: The base exception for all RPC related errors. It contains structured error data and can be serialized to a JSON-RPC 2.0 error object.
- `InvalidParamsError`: Raised when the parameters for an RPC call are invalid. Corresponds to error code -32602.
- `MethodNotFoundError`: Raised when the requested remote method does not exist. Corresponds to error code -32601.
- `RpcTimeoutError`: Raised when a client-side `call` operation times out waiting for a response.

## RpcErrorCode Enum

An `IntEnum` that defines the standard JSON-RPC 2.0 error codes, available in `pywebtransport.rpc.exceptions`.

### Attributes

- `PARSE_ERROR` (`int`): Represents a JSON parsing error on the server. `Default: -32700`.
- `INVALID_REQUEST` (`int`): The JSON sent is not a valid Request object. `Default: -32600`.
- `METHOD_NOT_FOUND` (`int`): The method does not exist / is not available. `Default: -32601`.
- `INVALID_PARAMS` (`int`): Invalid method parameter(s). `Default: -32602`.
- `INTERNAL_ERROR` (`int`): Internal JSON-RPC error. `Default: -32603`.

## See Also

- **[Session API](session.md)**: Understand the `WebTransportSession` which this manager is built upon.
- **[Serializer API](serializer.md)**: Learn about the serializers used for RPC data.
- **[Exceptions API](exceptions.md)**: Understand the library's complete error and exception hierarchy.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
