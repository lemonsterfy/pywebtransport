# API Reference: protocol

This document provides a reference for the `pywebtransport.protocol` subpackage, containing the low-level implementation of the WebTransport over H3 protocol.

---

## WebTransportProtocolHandler Class

The core class that orchestrates WebTransport sessions and streams over a QUIC connection by processing QUIC events. It acts as the bridge between the high-level API and the underlying aioquic library.

### Constructor

- **`def __init__(self, *, quic_connection: QuicConnection, trigger_transmission: Callable[[], None], is_client: bool = True, connection: "WebTransportConnection" | None = None) -> None`**: Initializes the protocol handler. Requires the underlying `aioquic` connection, a callback to trigger data transmission, the client/server role, and optionally a weak reference back to the parent `WebTransportConnection`.

### Properties

- `quic_connection` (`QuicConnection`): The underlying `aioquic` QuicConnection object.

### Instance Methods

- **`def abort_stream(self, *, stream_id: StreamId, error_code: int) -> None`**: Aborts a stream immediately by sending appropriate QUIC frames (RESET_STREAM, STOP_SENDING).
- **`def accept_webtransport_session(self, *, stream_id: StreamId, session_id: SessionId) -> None`**: Accepts a pending WebTransport session request (server-only) by sending a 200 OK response on the control stream.
- **`async def close(self) -> None`**: Closes the protocol handler and cleans up its internal resources and event listeners.
- **`def close_webtransport_session(self, *, session_id: SessionId, code: int = 0, reason: str | None = None) -> None`**: Closes a specific WebTransport session by sending a CLOSE_WEBTRANSPORT_SESSION capsule.
- **`def connection_established(self) -> None`**: Signals that the QUIC connection handshake has successfully completed.
- **`async def create_webtransport_session(self, *, path: str, headers: Headers | None = None) -> tuple[SessionId, StreamId]`**: Initiates a new WebTransport session (client-only) by sending a CONNECT request. Returns the generated session ID and the control stream ID.
- **`def create_webtransport_stream(self, *, session_id: SessionId, is_unidirectional: bool = False) -> StreamId`**: Creates a new WebTransport data stream (uni- or bidirectional) for an established session. Returns the new stream ID.
- **`async def handle_quic_event(self, *, event: QuicEvent) -> None`**: Processes a QUIC event received from the `aioquic` protocol layer, dispatching it through the internal H3 engine and session/stream trackers.
- **`def reject_session_request(self, *, stream_id: StreamId, status_code: int) -> None`**: Rejects an incoming WebTransport session request (server-only) by sending an appropriate HTTP status code (e.g., 404, 403).
- **`def send_webtransport_datagram(self, *, session_id: SessionId, data: bytes) -> None`**: Sends a WebTransport datagram frame associated with a specific session.
- **`def send_webtransport_stream_data(self, *, stream_id: StreamId, data: bytes, end_stream: bool = False) -> None`**: Sends data on a specific WebTransport stream, handling H3 framing and flow control.

## WebTransportSessionInfo Class

Represents stateful information about a WebTransport session tracked by the protocol handler.

**Note on Usage**: This is a data class primarily used internally and for exposing session state.

### Attributes

- `session_id` (`SessionId`): The unique ID for the session.
- `control_stream_id` (`StreamId`): The ID of the session's control stream (the CONNECT stream).
- `state` (`SessionState`): The current state of the session (e.g., `CONNECTING`, `CONNECTED`, `CLOSED`).
- `path` (`str`): The URL path requested for the session.
- `created_at` (`float`): The timestamp when the session tracking object was created.
- `headers` (`Headers`): The headers associated with the session request/response. `Default: {}`.
- `ready_at` (`float | None`): The timestamp when the session became connected (`CONNECTED` state). `Default: None`.
- `closed_at` (`float | None`): The timestamp when the session was closed. `Default: None`.
- `close_code` (`int | None`): The application-defined code with which the session was closed (from CLOSE_SESSION capsule). `Default: None`.
- `close_reason` (`str | None`): The application-defined reason the session was closed (from CLOSE_SESSION capsule). `Default: None`.
- `local_max_data` (`int`): Flow control: The maximum amount of cumulative data this endpoint is prepared to receive for the session. `Default: 0`.
- `local_data_sent` (`int`): Flow control: The cumulative amount of data this endpoint has sent for the session. `Default: 0`.
- `peer_max_data` (`int`): Flow control: The maximum amount of cumulative data the peer has advertised it can receive. `Default: 0`.
- `peer_data_sent` (`int`): Flow control: The cumulative amount of data the peer has sent. `Default: 0`.
- `local_max_streams_bidi` (`int`): Flow control: The maximum number of concurrent bidirectional streams the peer is allowed to initiate. `Default: 0`.
- `local_streams_bidi_opened` (`int`): Flow control: The number of bidirectional streams this endpoint has initiated. `Default: 0`.
- `peer_max_streams_bidi` (`int`): Flow control: The maximum number of concurrent bidirectional streams this endpoint is allowed to initiate. `Default: 0`.
- `peer_streams_bidi_opened` (`int`): Flow control: The number of bidirectional streams the peer has initiated. `Default: 0`.
- `local_max_streams_uni` (`int`): Flow control: The maximum number of concurrent unidirectional streams the peer is allowed to initiate. `Default: 0`.
- `local_streams_uni_opened` (`int`): Flow control: The number of unidirectional streams this endpoint has initiated. `Default: 0`.
- `peer_max_streams_uni` (`int`): Flow control: The maximum number of concurrent unidirectional streams this endpoint is allowed to initiate. `Default: 0`.
- `peer_streams_uni_opened` (`int`): Flow control: The number of unidirectional streams the peer has initiated. `Default: 0`.

## StreamInfo Class

Represents stateful information about a single WebTransport stream tracked by the protocol handler.

**Note on Usage**: This is a data class primarily used internally and for exposing stream state.

### Attributes

- `stream_id` (`StreamId`): The unique QUIC ID for the stream.
- `session_id` (`SessionId`): The ID of the session this stream belongs to.
- `direction` (`StreamDirection`): The directionality of the stream (`BIDIRECTIONAL`, `SEND_ONLY`, `RECEIVE_ONLY`).
- `state` (`StreamState`): The current state of the stream (e.g., `OPEN`, `HALF_CLOSED_LOCAL`, `CLOSED`).
- `created_at` (`float`): The timestamp when the stream tracking object was created.
- `bytes_sent` (`int`): Total bytes sent on this stream by the local endpoint. `Default: 0`.
- `bytes_received` (`int`): Total bytes received on this stream by the local endpoint. `Default: 0`.
- `closed_at` (`float | None`): The timestamp when the stream was fully closed. `Default: None`.
- `close_code` (`int | None`): The error code if the stream was reset. `Default: None`.
- `close_reason` (`str | None`): A descriptive reason if the stream was reset (internal use). `Default: None`.

## Utility Functions

These helper functions are available in the `pywebtransport.protocol` module.

- **`def can_receive_data_on_stream(*, stream_id: StreamId, is_client: bool) -> bool`**: Checks if the local endpoint can receive data on a given stream based on its ID and role.
- **`def can_send_data_on_stream(*, stream_id: StreamId, is_client: bool) -> bool`**: Checks if the local endpoint can send data on a given stream based on its ID and role.
- **`def get_stream_direction_from_id(*, stream_id: StreamId, is_client: bool) -> StreamDirection`**: Determines the stream direction (`BIDIRECTIONAL`, `SEND_ONLY`, `RECEIVE_ONLY`) from its ID and the endpoint role.
- **`def validate_session_id(*, session_id: Any) -> None`**: Validates that a session ID is a non-empty string, raising `TypeError` or `ValueError` otherwise.
- **`def validate_stream_id(*, stream_id: Any) -> None`**: Validates that a stream ID is an integer within the valid QUIC range, raising `TypeError` or `ValueError` otherwise.
- **`def webtransport_code_to_http_code(app_error_code: int) -> int`**: Maps a 32-bit WebTransport application error code (used in CLOSE_SESSION) to an equivalent HTTP/3 error code range for stream resets.

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
