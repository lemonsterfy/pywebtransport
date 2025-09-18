# API Reference: protocol

This document provides a reference for the `pywebtransport.protocol` subpackage, which contains the low-level implementation for handling WebTransport protocol logic.

---

## WebTransportProtocolHandler Class

The core class that orchestrates WebTransport sessions and streams over a QUIC connection by processing QUIC events.

### Constructor

- **`def __init__(self, *, quic_connection: QuicConnection, is_client: bool = True, connection: "WebTransportConnection" | None = None)`**: Initializes the protocol handler.

### Properties

- `is_connected` (`bool`): `True` if the underlying connection is established.
- `connection` (`WebTransportConnection | None`): A weak reference to the parent `WebTransportConnection`.
- `connection_state` (`ConnectionState`): The current state of the underlying connection.
- `quic_connection` (`QuicConnection`): The underlying `aioquic` QuicConnection object.
- `stats` (`dict[str, Any]`: A copy of the protocol handler's statistics.

### Instance Methods

- **`async def close(self) -> None`**: Closes the protocol handler and cleans up its resources.
- **`def connection_established(self) -> None`**: Signals that the QUIC connection is established.
- **`def abort_stream(self, *, stream_id: StreamId, error_code: int) -> None`**: Aborts a stream immediately.
- **`def accept_webtransport_session(self, *, stream_id: StreamId, session_id: SessionId) -> None`**: Accepts a pending WebTransport session (server-only).
- **`def close_webtransport_session(self, *, session_id: SessionId, code: int = 0, reason: str | None = None) -> None`**: Closes a specific WebTransport session.
- **`async def create_webtransport_session(self, *, path: str, headers: Headers | None = None) -> tuple[SessionId, StreamId]`**: Initiates a new WebTransport session (client-only).
- **`def create_webtransport_stream(self, *, session_id: SessionId, is_unidirectional: bool = False) -> StreamId`**: Creates a new WebTransport data stream for a session.
- **`async def establish_session(self, *, path: str, headers: Headers | None = None, timeout: float = 30.0) -> tuple[SessionId, StreamId]`**: Establishes a WebTransport session with a specified timeout.
- **`async def handle_quic_event(self, *, event: QuicEvent) -> None`**: Processes a QUIC event through the H3 engine and handles the results.
- **`def send_webtransport_datagram(self, *, session_id: SessionId, data: bytes) -> None`**: Sends a WebTransport datagram for a session.
- **`def send_webtransport_stream_data(self, *, stream_id: StreamId, data: bytes, end_stream: bool = False) -> None`**: Sends data on a specific WebTransport stream.
- **`def get_all_sessions(self) -> list[WebTransportSessionInfo]`**: Gets a list of all current sessions.
- **`def get_health_status(self) -> dict[str, Any]`**: Gets the overall health status of the protocol handler.
- **`def get_session_info(self, *, session_id: SessionId) -> WebTransportSessionInfo | None`**: Gets information about a specific session.
- **`async def read_stream_complete(self, *, stream_id: StreamId, timeout: float = 30.0) -> bytes`**: Receives all data from a stream until it is ended.
- **`async def recover_session(self, *, session_id: SessionId, max_retries: int = 3) -> bool`**: Attempts to recover a failed session by creating a new one.
- **`def write_stream_chunked(self, *, stream_id: StreamId, data: Data, chunk_size: int = 8192) -> int`**: Sends data on a stream in managed chunks.

## WebTransportSessionInfo Class

Represents stateful information about a WebTransport session.

**Note on Usage**: The constructor for this dataclass requires all parameters to be passed as keyword arguments.

### Attributes

- `session_id` (`SessionId`): The unique ID for the session.
- `stream_id` (`StreamId`): The ID of the session's control stream.
- `state` (`SessionState`): The current state of the session.
- `path` (`str`): The URL path for the session.
- `created_at` (`float`): The timestamp when the session was created.
- `headers` (`Headers`): The headers associated with the session request. `Default: {}`.
- `ready_at` (`float | None`): The timestamp when the session became connected. `Default: None`.
- `closed_at` (`float | None`): The timestamp when the session was closed. `Default: None`.
- `close_code` (`int | None`): The code with which the session was closed. `Default: None`.
- `close_reason` (`str | None`): The reason the session was closed. `Default: None`.
- `local_max_data` (`int`): The maximum amount of data this endpoint is prepared to receive. `Default: 0`.
- `local_data_sent` (`int`): The amount of data this endpoint has sent. `Default: 0`.
- `peer_max_data` (`int`): The maximum amount of data the peer is prepared to receive. `Default: 0`.
- `peer_data_sent` (`int`): The amount of data the peer has sent. `Default: 0`.
- `local_max_streams_bidi` (`int`): The maximum number of bidirectional streams the peer can create. `Default: 0`.
- `local_streams_bidi_opened` (`int`): The number of bidirectional streams this endpoint has opened. `Default: 0`.
- `peer_max_streams_bidi` (`int`): The maximum number of bidirectional streams this endpoint can create. `Default: 0`.
- `peer_streams_bidi_opened` (`int`): The number of bidirectional streams the peer has opened. `Default: 0`.
- `local_max_streams_uni` (`int`): The maximum number of unidirectional streams the peer can create. `Default: 0`.
- `local_streams_uni_opened` (`int`): The number of unidirectional streams this endpoint has opened. `Default: 0`.
- `peer_max_streams_uni` (`int`): The maximum number of unidirectional streams this endpoint can create. `Default: 0`.
- `peer_streams_uni_opened` (`int`): The number of unidirectional streams the peer has opened. `Default: 0`.

## StreamInfo Class

Represents stateful information about a single WebTransport stream.

**Note on Usage**: The constructor for this dataclass requires all parameters to be passed as keyword arguments.

### Attributes

- `stream_id` (`StreamId`): The unique ID for the stream.
- `session_id` (`SessionId`): The ID of the session this stream belongs to.
- `direction` (`StreamDirection`): The direction of the stream.
- `state` (`StreamState`): The current state of the stream.
- `created_at` (`float`): The timestamp when the stream was created.
- `bytes_sent` (`int`): Total bytes sent on this stream. `Default: 0`.
- `bytes_received` (`int`): Total bytes received on this stream. `Default: 0`.
- `closed_at` (`float | None`): The timestamp when the stream was closed. `Default: None`.
- `close_code` (`int | None`): The code with which the stream was closed. `Default: None`.
- `close_reason` (`str | None`): The reason the stream was closed. `Default: None`.

## Utility Functions

These helper functions are available in the `pywebtransport.protocol.utils` module.

- **`def can_receive_data(*, connection_state: ConnectionState, session_state: SessionState) -> bool`**: Checks if data can be received based on connection and session states.
- **`def can_receive_data_on_stream(*, stream_id: StreamId, is_client: bool) -> bool`**: Checks if the local endpoint can receive data on a given stream.
- **`def can_send_data(*, connection_state: ConnectionState, session_state: SessionState) -> bool`**: Checks if data can be sent based on connection and session states.
- **`def can_send_data_on_stream(*, stream_id: StreamId, is_client: bool) -> bool`**: Checks if the local endpoint can send data on a given stream.
- **`def create_quic_configuration(\*, is_client: bool = True, **kwargs: Any) -> QuicConfiguration`\*\*: Creates a QUIC configuration from keyword arguments.
- **`def get_stream_direction_from_id(*, stream_id: StreamId, is_client: bool) -> StreamDirection`**: Determines the stream direction from its ID and the endpoint role.
- **`def is_bidirectional_stream(*, stream_id: StreamId) -> bool`**: Checks if a stream is bidirectional.
- **`def is_client_initiated_stream(*, stream_id: StreamId) -> bool`**: Checks if a stream was initiated by the client.
- **`def is_server_initiated_stream(*, stream_id: StreamId) -> bool`**: Checks if a stream was initiated by the server.
- **`def is_unidirectional_stream(*, stream_id: StreamId) -> bool`**: Checks if a stream is unidirectional.
- **`def webtransport_code_to_http_code(app_error_code: int) -> int`**: Maps a 32-bit WebTransport application error code to an HTTP/3 error code.

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
