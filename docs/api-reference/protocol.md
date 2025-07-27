# API Reference: Protocol

This document provides a comprehensive reference for the `pywebtransport.protocol` subpackage, which contains the low-level implementation for handling the WebTransport protocol logic over a QUIC connection.

---

## `WebTransportProtocolHandler` Class

This is the core class of the protocol layer. It orchestrates WebTransport sessions and streams by processing QUIC events through an internal H3 connection engine. It is an `EventEmitter` and will emit events related to session and stream state changes.

### Constructor

- **`__init__(self, quic_connection: QuicConnection, *, is_client: bool = True, connection: Optional["WebTransportConnection"] = None)`**

  Initializes the protocol handler.

### Key Public Methods

#### Session Management

- **`create_webtransport_session(self, path: str, *, headers: Optional[Headers] = None) -> Tuple[SessionId, StreamId]`**:
  (Client-only) Initiates a new WebTransport session by sending a CONNECT request. Returns the generated `SessionId` and the control `StreamId`.

- **`accept_webtransport_session(self, stream_id: StreamId, session_id: SessionId) -> None`**:
  (Server-only) Accepts a pending session request by sending a `200 OK` response.

- **`close_webtransport_session(self, session_id: SessionId, *, code: int = 0, reason: Optional[str] = None) -> None`**:
  Closes a specific WebTransport session by resetting its control stream.

- **`get_session_info(self, session_id: SessionId) -> Optional[WebTransportSessionInfo]`**:
  Retrieves the stateful information object for a given session.

- **`get_all_sessions(self) -> List[WebTransportSessionInfo]`**:
  Returns a list of all active sessions managed by this handler.

#### Stream & Datagram Management

- **`create_webtransport_stream(self, session_id: SessionId, *, is_unidirectional: bool = False) -> StreamId`**:
  Creates a new WebTransport data stream within an established session.

- **`send_webtransport_stream_data(self, stream_id: StreamId, data: bytes, *, end_stream: bool = False) -> None`**:
  Sends data on a specific WebTransport stream.

- **`send_webtransport_datagram(self, session_id: SessionId, data: bytes) -> None`**:
  Sends a datagram within a specific session.

- **`abort_stream(self, stream_id: StreamId, error_code: int) -> None`**:
  Forcefully stops a stream with a given error code.

#### Event Handling

- **`handle_quic_event(self, event: QuicEvent) -> None`**:
  The main entry point for processing events from the underlying `aioquic` connection.

### Properties

- **`connection_state` (ConnectionState)**: The current state of the underlying QUIC connection.
- **`is_connected` (bool)**: `True` if the connection state is `CONNECTED`.
- **`quic_connection` (QuicConnection)**: The underlying `aioquic` connection object.
- **`stats` (Dict[str, Any])**: A dictionary containing connection statistics.

---

## Data Classes

These dataclasses store stateful information about sessions and streams.

### `WebTransportSessionInfo`

- **`session_id` (SessionId)**: The unique ID for the session.
- **`stream_id` (StreamId)**: The ID of the session's control stream.
- **`state` (SessionState)**: The current state of the session (e.g., `CONNECTING`, `CONNECTED`).
- **`path` (str)**: The URL path for the session.
- **`created_at` (float)**: The timestamp when the session was created.
- **`headers` (Headers)**: The headers associated with the session request.
- **`ready_at` (Optional[float])**: The timestamp when the session became connected.
- **`closed_at` (Optional[float])**: The timestamp when the session was closed.
- **`close_code` (Optional[int])**: The code with which the session was closed.
- **`close_reason` (Optional[str])**: The reason the session was closed.

### `StreamInfo`

- **`stream_id` (StreamId)**: The unique ID for the stream.
- **`session_id` (SessionId)**: The ID of the session this stream belongs to.
- **`direction` (StreamDirection)**: The direction of the stream (e.g., `BIDIRECTIONAL`).
- **`state` (StreamState)**: The current state of the stream (e.g., `OPEN`, `CLOSED`).
- **`created_at` (float)**: The timestamp when the stream was created.
- **`bytes_sent` (int)**: Total bytes sent on this stream.
- **`bytes_received` (int)**: Total bytes received on this stream.
- **`closed_at` (Optional[float])**: The timestamp when the stream was closed.
- **`close_code` (Optional[int])**: The code with which the stream was closed.
- **`close_reason` (Optional[str])**: The reason the stream was closed.

---

## Protocol Utility Functions

These helper functions are available in the `pywebtransport.protocol.utils` module and assist with protocol-level logic.

- **`create_quic_configuration(\*, is_client: bool = True, **kwargs: Any) -> QuicConfiguration`**:
A factory function to create a `QuicConfiguration` object with WebTransport defaults.

- **`is_client_initiated_stream(stream_id: StreamId) -> bool`**:
  Returns `True` if the stream ID corresponds to a client-initiated stream (even number).

- **`is_server_initiated_stream(stream_id: StreamId) -> bool`**:
  Returns `True` if the stream ID corresponds to a server-initiated stream (odd number).

- **`is_bidirectional_stream(stream_id: StreamId) -> bool`**:
  Returns `True` if the stream ID corresponds to a bidirectional stream.

- **`is_unidirectional_stream(stream_id: StreamId) -> bool`**:
  Returns `True` if the stream ID corresponds to a unidirectional stream.

- **`can_send_data_on_stream(stream_id: StreamId, *, is_client: bool) -> bool`**:
  Checks if the local endpoint (client or server) is permitted to send data on the given stream.

- **`can_receive_data_on_stream(stream_id: StreamId, *, is_client: bool) -> bool`**:
  Checks if the local endpoint is permitted to receive data on the given stream.

- **`get_stream_direction_from_id(stream_id: StreamId, *, is_client: bool) -> StreamDirection`**:
  Determines if a stream is `SEND_ONLY` or `RECEIVE_ONLY` from the local endpoint's perspective.

---

## See Also

- **[Connection API](connection.md)** - Learn how the `WebTransportConnection` uses this protocol handler.
- **[Events API](events.md)** - Understand the events emitted by the protocol handler.
- **[Exceptions API](exceptions.md)** - Review exceptions that can be raised during protocol operations.
- **[Types API](types.md)** - See the definitions for types like `SessionState` and `StreamDirection`.
