"""Unit tests for the pywebtransport.types module."""

import ssl
from typing import Any

import pytest

from pywebtransport import ConnectionState, EventType, Headers, Serializer, SessionState, StreamDirection, StreamState
from pywebtransport.types import (
    AuthHandlerProtocol,
    BidirectionalStreamProtocol,
    ClientConfigProtocol,
    Data,
    MiddlewareProtocol,
    ReadableStreamProtocol,
    ServerConfigProtocol,
    WritableStreamProtocol,
)


class TestEnumerations:
    @pytest.mark.parametrize(
        "member, expected_value",
        [
            (ConnectionState.IDLE, "idle"),
            (ConnectionState.CONNECTING, "connecting"),
            (ConnectionState.CONNECTED, "connected"),
            (ConnectionState.CLOSING, "closing"),
            (ConnectionState.CLOSED, "closed"),
            (ConnectionState.FAILED, "failed"),
            (ConnectionState.DRAINING, "draining"),
        ],
    )
    def test_connection_state(self, member: ConnectionState, expected_value: str) -> None:
        assert member.value == expected_value

    @pytest.mark.parametrize(
        "member, expected_value",
        [
            (EventType.CAPSULE_RECEIVED, "capsule_received"),
            (EventType.CONNECTION_CLOSED, "connection_closed"),
            (EventType.CONNECTION_ESTABLISHED, "connection_established"),
            (EventType.CONNECTION_FAILED, "connection_failed"),
            (EventType.CONNECTION_LOST, "connection_lost"),
            (EventType.DATAGRAM_ERROR, "datagram_error"),
            (EventType.DATAGRAM_RECEIVED, "datagram_received"),
            (EventType.DATAGRAM_SENT, "datagram_sent"),
            (EventType.PROTOCOL_ERROR, "protocol_error"),
            (EventType.SETTINGS_RECEIVED, "settings_received"),
            (EventType.SESSION_CLOSED, "session_closed"),
            (EventType.SESSION_DRAINING, "session_draining"),
            (EventType.SESSION_MAX_DATA_UPDATED, "session_max_data_updated"),
            (EventType.SESSION_MAX_STREAMS_BIDI_UPDATED, "session_max_streams_bidi_updated"),
            (EventType.SESSION_MAX_STREAMS_UNI_UPDATED, "session_max_streams_uni_updated"),
            (EventType.SESSION_READY, "session_ready"),
            (EventType.SESSION_REQUEST, "session_request"),
            (EventType.STREAM_CLOSED, "stream_closed"),
            (EventType.STREAM_DATA_RECEIVED, "stream_data_received"),
            (EventType.STREAM_ERROR, "stream_error"),
            (EventType.STREAM_OPENED, "stream_opened"),
            (EventType.TIMEOUT_ERROR, "timeout_error"),
        ],
    )
    def test_event_type(self, member: EventType, expected_value: str) -> None:
        assert member.value == expected_value

    @pytest.mark.parametrize(
        "member, expected_value",
        [
            (SessionState.CONNECTING, "connecting"),
            (SessionState.CONNECTED, "connected"),
            (SessionState.CLOSING, "closing"),
            (SessionState.DRAINING, "draining"),
            (SessionState.CLOSED, "closed"),
        ],
    )
    def test_session_state(self, member: SessionState, expected_value: str) -> None:
        assert member.value == expected_value

    @pytest.mark.parametrize(
        "member, expected_value",
        [
            (StreamDirection.BIDIRECTIONAL, "bidirectional"),
            (StreamDirection.SEND_ONLY, "send_only"),
            (StreamDirection.RECEIVE_ONLY, "receive_only"),
        ],
    )
    def test_stream_direction(self, member: StreamDirection, expected_value: str) -> None:
        assert member.value == expected_value

    @pytest.mark.parametrize(
        "member, expected_value",
        [
            (StreamState.IDLE, "idle"),
            (StreamState.OPEN, "open"),
            (StreamState.HALF_CLOSED_LOCAL, "half_closed_local"),
            (StreamState.HALF_CLOSED_REMOTE, "half_closed_remote"),
            (StreamState.CLOSED, "closed"),
            (StreamState.RESET_SENT, "reset_sent"),
            (StreamState.RESET_RECEIVED, "reset_received"),
        ],
    )
    def test_stream_state(self, member: StreamState, expected_value: str) -> None:
        assert member.value == expected_value


class TestRuntimeCheckableProtocols:
    class GoodAuthHandler:
        async def __call__(self, *, headers: Headers) -> bool:
            return True

    class BadAuthHandler:
        async def handle(self, *, headers: Headers) -> bool:
            return True

    class GoodMiddleware:
        async def __call__(self, *, session: Any) -> bool:
            return True

    class BadMiddleware:
        async def process_session(self, *, session: Any) -> Any:
            return session

    class GoodReadableStream:
        async def read(self, *, size: int = -1) -> bytes:
            return b""

        async def readline(self, *, separator: bytes = b"\n") -> bytes:
            return b""

        async def readexactly(self, *, n: int) -> bytes:
            return b""

        async def readuntil(self, *, separator: bytes = b"\n") -> bytes:
            return b""

        def at_eof(self) -> bool:
            return False

    class BadReadableStream:
        async def read(self, *, size: int = -1) -> bytes:
            return b""

        async def readline(self, *, separator: bytes = b"\n") -> bytes:
            return b""

        async def readexactly(self, *, n: int) -> bytes:
            return b""

        async def readuntil(self, *, separator: bytes = b"\n") -> bytes:
            return b""

    class GoodWritableStream:
        async def write(self, *, data: Data) -> None:
            pass

        async def writelines(self, *, lines: list[Data]) -> None:
            pass

        async def flush(self) -> None:
            pass

        async def close(self, *, code: int | None = None, reason: str | None = None) -> None:
            pass

        def is_closing(self) -> bool:
            return False

    class GoodBidirectionalStream(GoodWritableStream, GoodReadableStream):
        pass

    class GoodClientConfig:
        alpn_protocols: list[str] = ["h3"]
        auto_reconnect: bool = False
        ca_certs: str | None = None
        certfile: str | None = None
        close_timeout: float = 2.0
        congestion_control_algorithm: str = "cubic"
        connect_timeout: float = 5.0
        connection_cleanup_interval: float = 30.0
        connection_idle_check_interval: float = 5.0
        connection_idle_timeout: float = 60.0
        connection_keepalive_timeout: float = 30.0
        debug: bool = False
        flow_control_window_auto_scale: bool = True
        flow_control_window_size: int = 1024
        headers: Headers = {}
        initial_max_data: int = 0
        initial_max_streams_bidi: int = 0
        initial_max_streams_uni: int = 0
        keep_alive: bool = True
        keyfile: str | None = None
        log_level: str = "INFO"
        max_connections: int = 100
        max_datagram_size: int = 65535
        max_incoming_streams: int = 100
        max_pending_events_per_session: int = 16
        max_retries: int = 3
        max_retry_delay: float = 30.0
        max_stream_buffer_size: int = 1024 * 1024
        max_streams: int = 100
        max_total_pending_events: int = 1000
        pending_event_ttl: float = 5.0
        read_timeout: float | None = 5.0
        retry_backoff: float = 2.0
        retry_delay: float = 1.0
        stream_buffer_size: int = 65536
        stream_cleanup_interval: float = 15.0
        stream_creation_timeout: float = 10.0
        stream_flow_control_increment_bidi: int = 10
        stream_flow_control_increment_uni: int = 10
        user_agent: str = "pywebtransport"
        verify_mode: ssl.VerifyMode | None = ssl.CERT_REQUIRED
        write_timeout: float | None = 5.0

    class BadClientConfig:
        alpn_protocols: list[str] = ["h3"]
        ca_certs: str | None = None
        certfile: str | None = None
        close_timeout: float = 2.0
        congestion_control_algorithm: str = "cubic"
        connect_timeout: float = 5.0
        connection_cleanup_interval: float = 30.0
        connection_idle_check_interval: float = 5.0
        connection_idle_timeout: float = 60.0
        connection_keepalive_timeout: float = 30.0
        headers: Headers = {}
        keyfile: str | None = None
        max_connections: int = 100
        max_datagram_size: int = 65535
        max_incoming_streams: int = 100
        max_streams: int = 100
        read_timeout: float | None = 5.0
        stream_buffer_size: int = 65536
        stream_cleanup_interval: float = 15.0
        stream_creation_timeout: float = 10.0
        user_agent: str = "pywebtransport"
        verify_mode: ssl.VerifyMode | None = ssl.CERT_REQUIRED
        write_timeout: float | None = 5.0

    class GoodServerConfig:
        access_log: bool = True
        alpn_protocols: list[str] = ["h3"]
        bind_host: str = "localhost"
        bind_port: int = 4433
        ca_certs: str | None = None
        certfile: str = "cert.pem"
        congestion_control_algorithm: str = "cubic"
        connection_cleanup_interval: float = 30.0
        connection_idle_check_interval: float = 5.0
        connection_idle_timeout: float = 60.0
        connection_keepalive_timeout: float = 30.0
        debug: bool = False
        flow_control_window_auto_scale: bool = True
        flow_control_window_size: int = 1024
        initial_max_data: int = 0
        initial_max_streams_bidi: int = 0
        initial_max_streams_uni: int = 0
        keep_alive: bool = True
        keyfile: str = "key.pem"
        log_level: str = "INFO"
        max_connections: int = 1000
        max_datagram_size: int = 65535
        max_incoming_streams: int = 100
        max_pending_events_per_session: int = 16
        max_sessions: int = 10000
        max_stream_buffer_size: int = 1024 * 1024
        max_streams_per_connection: int = 100
        max_total_pending_events: int = 1000
        middleware: list = []
        pending_event_ttl: float = 5.0
        read_timeout: float | None = 30.0
        session_cleanup_interval: float = 60.0
        stream_buffer_size: int = 65536
        stream_cleanup_interval: float = 15.0
        stream_flow_control_increment_bidi: int = 10
        stream_flow_control_increment_uni: int = 10
        verify_mode: ssl.VerifyMode = ssl.CERT_NONE
        write_timeout: float | None = 30.0

    class BadServerConfig:
        alpn_protocols: list[str] = ["h3"]
        bind_host: str = "localhost"
        bind_port: int = 4433
        ca_certs: str | None = None
        congestion_control_algorithm: str = "cubic"
        connection_cleanup_interval: float = 30.0
        connection_idle_check_interval: float = 5.0
        connection_idle_timeout: float = 60.0
        connection_keepalive_timeout: float = 30.0
        keep_alive: bool = True
        max_connections: int = 1000
        max_datagram_size: int = 65535
        max_incoming_streams: int = 100
        max_sessions: int = 10000
        max_streams_per_connection: int = 100
        read_timeout: float | None = 30.0
        session_cleanup_interval: float = 60.0
        stream_cleanup_interval: float = 15.0
        verify_mode: ssl.VerifyMode = ssl.CERT_NONE
        write_timeout: float | None = 30.0

    class GoodSerializer:
        def serialize(self, *, obj: Any) -> bytes:
            return b"serialized"

        def deserialize(self, *, data: bytes, obj_type: type[Any] | None = None) -> Any:
            return "deserialized"

    class BadSerializer:
        def serialize(self, *, obj: Any) -> bytes:
            return b"serialized"

    def test_auth_handler_protocol_conformance(self) -> None:
        assert isinstance(self.GoodAuthHandler(), AuthHandlerProtocol)

    def test_auth_handler_protocol_non_conformance(self) -> None:
        assert not isinstance(self.BadAuthHandler(), AuthHandlerProtocol)

    def test_middleware_protocol_conformance(self) -> None:
        assert isinstance(self.GoodMiddleware(), MiddlewareProtocol)

    def test_middleware_protocol_non_conformance(self) -> None:
        assert not isinstance(self.BadMiddleware(), MiddlewareProtocol)

    def test_readable_stream_protocol_conformance(self) -> None:
        assert isinstance(self.GoodReadableStream(), ReadableStreamProtocol)

    def test_readable_stream_protocol_non_conformance(self) -> None:
        assert not isinstance(self.BadReadableStream(), ReadableStreamProtocol)

    def test_writable_stream_protocol_conformance(self) -> None:
        assert isinstance(self.GoodWritableStream(), WritableStreamProtocol)

    def test_bidirectional_stream_protocol_conformance(self) -> None:
        instance = self.GoodBidirectionalStream()

        assert isinstance(instance, BidirectionalStreamProtocol)
        assert isinstance(instance, WritableStreamProtocol)
        assert isinstance(instance, ReadableStreamProtocol)

    def test_client_config_protocol_conformance(self) -> None:
        assert isinstance(self.GoodClientConfig(), ClientConfigProtocol)

    def test_client_config_protocol_non_conformance(self) -> None:
        assert not isinstance(self.BadClientConfig(), ClientConfigProtocol)

    def test_server_config_protocol_conformance(self) -> None:
        assert isinstance(self.GoodServerConfig(), ServerConfigProtocol)

    def test_server_config_protocol_non_conformance(self) -> None:
        assert not isinstance(self.BadServerConfig(), ServerConfigProtocol)

    def test_serializer_protocol_conformance(self) -> None:
        assert isinstance(self.GoodSerializer(), Serializer)

    def test_serializer_protocol_non_conformance(self) -> None:
        assert not isinstance(self.BadSerializer(), Serializer)
