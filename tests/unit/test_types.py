"""Unit tests for the pywebtransport.types module."""

import ssl

import pytest

from pywebtransport import ConnectionState, EventType, SessionState, StreamDirection, StreamState
from pywebtransport.types import (
    BidirectionalStreamProtocol,
    ClientConfigProtocol,
    Data,
    Headers,
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
            (EventType.CONNECTION_ESTABLISHED, "connection_established"),
            (EventType.CONNECTION_FAILED, "connection_failed"),
            (EventType.CONNECTION_LOST, "connection_lost"),
            (EventType.CONNECTION_CLOSED, "connection_closed"),
            (EventType.SESSION_REQUEST, "session_request"),
            (EventType.SESSION_READY, "session_ready"),
            (EventType.STREAM_OPENED, "stream_opened"),
            (EventType.DATAGRAM_RECEIVED, "datagram_received"),
            (EventType.PROTOCOL_ERROR, "protocol_error"),
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
    class GoodReadableStream:
        async def read(self, size: int = -1) -> bytes:
            return b""

        async def readline(self, separator: bytes = b"\n") -> bytes:
            return b""

        async def readexactly(self, n: int) -> bytes:
            return b""

        async def readuntil(self, separator: bytes = b"\n") -> bytes:
            return b""

        def at_eof(self) -> bool:
            return False

    class BadReadableStream:
        async def read(self, size: int = -1) -> bytes:
            return b""

        async def readline(self, separator: bytes = b"\n") -> bytes:
            return b""

        async def readexactly(self, n: int) -> bytes:
            return b""

        async def readuntil(self, separator: bytes = b"\n") -> bytes:
            return b""

    class GoodWritableStream:
        async def write(self, data: Data) -> None:
            pass

        async def writelines(self, lines: list[Data]) -> None:
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
        connect_timeout: float = 5.0
        read_timeout: float | None = 5.0
        write_timeout: float | None = 5.0
        close_timeout: float = 2.0
        max_streams: int = 100
        stream_buffer_size: int = 65536
        verify_mode: ssl.VerifyMode | None = ssl.CERT_REQUIRED
        ca_certs: str | None = None
        certfile: str | None = None
        keyfile: str | None = None
        check_hostname: bool = True
        alpn_protocols: list[str] = ["h3"]
        http_version: str = "HTTP/3"
        user_agent: str = "pywebtransport"
        headers: Headers = {}

    class BadClientConfig:
        connect_timeout: float = 5.0
        read_timeout: float | None = 5.0
        write_timeout: float | None = 5.0
        close_timeout: float = 2.0
        max_streams: int = 100
        stream_buffer_size: int = 65536
        verify_mode: ssl.VerifyMode | None = ssl.CERT_REQUIRED
        ca_certs: str | None = None
        certfile: str | None = None
        keyfile: str | None = None
        check_hostname: bool = True
        alpn_protocols: list[str] = ["h3"]
        http_version: str = "HTTP/3"
        headers: Headers = {}

    class GoodServerConfig:
        bind_host: str = "localhost"
        bind_port: int = 4433
        certfile: str = "cert.pem"
        keyfile: str = "key.pem"
        ca_certs: str | None = None
        verify_mode: ssl.VerifyMode = ssl.CERT_NONE
        max_connections: int = 1000
        max_streams_per_connection: int = 100
        connection_timeout: float = 60.0
        read_timeout: float | None = 30.0
        write_timeout: float | None = 30.0
        alpn_protocols: list[str] = ["h3"]
        http_version: str = "HTTP/3"
        backlog: int = 100
        reuse_port: bool = False
        keep_alive: bool = True

    class BadServerConfig:
        bind_host: str = "localhost"
        bind_port: int = 4433
        ca_certs: str | None = None
        verify_mode: ssl.VerifyMode = ssl.CERT_NONE
        max_connections: int = 1000
        max_streams_per_connection: int = 100
        connection_timeout: float = 60.0
        read_timeout: float | None = 30.0
        write_timeout: float | None = 30.0
        alpn_protocols: list[str] = ["h3"]
        http_version: str = "HTTP/3"
        backlog: int = 100
        reuse_port: bool = False
        keep_alive: bool = True

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
