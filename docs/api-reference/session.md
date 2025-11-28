# API Reference: session

This document provides a reference for the `pywebtransport.session` subpackage, which contains the high-level abstractions for managing WebTransport sessions.

---

## WebTransportSession Class

A high-level handle for a WebTransport session. It manages the lifecycle of a specific WebTransport session over a shared QUIC connection, including stream creation and datagram transmission. This class implements the asynchronous context manager protocol (`async with`) to ensure sessions are properly closed.

### Constructor

- **`def __init__(self, *, connection: WebTransportConnection, session_id: SessionId, path: str, headers: Headers, control_stream_id: StreamId | None) -> None`**: Initializes the WebTransport session handle.

### Properties

- `events` (`EventEmitter`): The event emitter for session-level events (e.g., `STREAM_OPENED`, `DATAGRAM_RECEIVED`).
- `headers` (`Headers`): A copy of the initial HTTP headers used to establish the session.
- `is_closed` (`bool`): `True` if the session state is `CLOSED`.
- `path` (`str`): The URL path associated with this session.
- `session_id` (`SessionId`): The unique identifier for this session.
- `state` (`SessionState`): The current state of the session (e.g., `CONNECTING`, `CONNECTED`, `CLOSED`).

### Instance Methods

- **`async def close(self, *, error_code: int = 0, reason: str | None = None, close_connection: bool = False) -> None`**: Closes the WebTransport session. Optionally closes the underlying connection.
- **`async def create_bidirectional_stream(self) -> WebTransportStream`**: Creates and returns a new bidirectional stream. Raises `TimeoutError` if stream creation exceeds the configured timeout.
- **`async def create_unidirectional_stream(self) -> WebTransportSendStream`**: Creates and returns a new unidirectional (send-only) stream. Raises `TimeoutError` if stream creation exceeds the configured timeout.
- **`async def diagnostics(self) -> SessionDiagnostics`**: Asynchronously retrieves a snapshot of the session's diagnostic information from the engine.
- **`async def grant_data_credit(self, *, max_data: int) -> None`**: Manually grants data flow control credit (MAX_DATA) to the peer.
- **`async def grant_streams_credit(self, *, max_streams: int, is_unidirectional: bool) -> None`**: Manually grants stream flow control credit (MAX_STREAMS) to the peer.
- **`async def send_datagram(self, *, data: Data) -> None`**: Sends an unreliable datagram to the peer.

## SessionDiagnostics Class

A dataclass representing a snapshot of session diagnostics.

### Attributes

- `session_id` (`SessionId`): The unique identifier for the session.
- `control_stream_id` (`StreamId`): The ID of the H3 control stream associated with this session.
- `state` (`SessionState`): The state of the session at the time of the snapshot.
- `path` (`str`): The URL path.
- `headers` (`Headers`): The initial headers.
- `created_at` (`float`): Timestamp when the session was created.
- `local_max_data` (`int`): The current local MAX_DATA limit.
- `local_data_sent` (`int`): Total bytes sent by the local endpoint.
- `peer_max_data` (`int`): The current peer MAX_DATA limit.
- `peer_data_sent` (`int`): Total bytes sent by the peer.
- `local_max_streams_bidi` (`int`): Local limit for bidirectional streams.
- `local_streams_bidi_opened` (`int`): Number of bidirectional streams opened locally.
- `peer_max_streams_bidi` (`int`): Peer limit for bidirectional streams.
- `peer_streams_bidi_opened` (`int`): Number of bidirectional streams opened by peer.
- `local_max_streams_uni` (`int`): Local limit for unidirectional streams.
- `local_streams_uni_opened` (`int`): Number of unidirectional streams opened locally.
- `peer_max_streams_uni` (`int`): Peer limit for unidirectional streams.
- `peer_streams_uni_opened` (`int`): Number of unidirectional streams opened by peer.
- `pending_bidi_stream_futures` (`list[Any]`): List of pending futures for bidirectional stream creation.
- `pending_uni_stream_futures` (`list[Any]`): List of pending futures for unidirectional stream creation.
- `datagrams_sent` (`int`): Total datagrams sent.
- `datagram_bytes_sent` (`int`): Total datagram bytes sent.
- `datagrams_received` (`int`): Total datagrams received.
- `datagram_bytes_received` (`int`): Total datagram bytes received.
- `close_code` (`int | None`): The error code if the session is closed.
- `close_reason` (`str | None`): The reason string if the session is closed.
- `closed_at` (`float | None`): Timestamp when the session was closed.
- `ready_at` (`float | None`): Timestamp when the session became ready.

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
