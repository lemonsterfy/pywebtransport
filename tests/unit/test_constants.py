"""Unit tests for the pywebtransport.constants module."""

import ssl
from enum import IntEnum

import pytest

from pywebtransport import ErrorCodes, __version__
from pywebtransport.constants import (
    DEFAULT_ALPN_PROTOCOLS,
    DEFAULT_BIND_HOST,
    DEFAULT_CERTFILE,
    DEFAULT_CLIENT_MAX_CONNECTIONS,
    DEFAULT_CLIENT_MAX_SESSIONS,
    DEFAULT_CLIENT_VERIFY_MODE,
    DEFAULT_CLOSE_TIMEOUT,
    DEFAULT_CONGESTION_CONTROL_ALGORITHM,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_CONNECTION_IDLE_TIMEOUT,
    DEFAULT_DEV_PORT,
    DEFAULT_FLOW_CONTROL_WINDOW_AUTO_SCALE,
    DEFAULT_FLOW_CONTROL_WINDOW_SIZE,
    DEFAULT_INITIAL_MAX_DATA,
    DEFAULT_INITIAL_MAX_STREAMS_BIDI,
    DEFAULT_INITIAL_MAX_STREAMS_UNI,
    DEFAULT_KEEP_ALIVE,
    DEFAULT_KEYFILE,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MAX_CONNECTION_RETRIES,
    DEFAULT_MAX_DATAGRAM_SIZE,
    DEFAULT_MAX_EVENT_HISTORY_SIZE,
    DEFAULT_MAX_EVENT_LISTENERS,
    DEFAULT_MAX_EVENT_QUEUE_SIZE,
    DEFAULT_MAX_MESSAGE_SIZE,
    DEFAULT_MAX_PENDING_EVENTS_PER_SESSION,
    DEFAULT_MAX_RETRY_DELAY,
    DEFAULT_MAX_STREAM_READ_BUFFER,
    DEFAULT_MAX_STREAM_WRITE_BUFFER,
    DEFAULT_MAX_TOTAL_PENDING_EVENTS,
    DEFAULT_PENDING_EVENT_TTL,
    DEFAULT_READ_TIMEOUT,
    DEFAULT_RESOURCE_CLEANUP_INTERVAL,
    DEFAULT_RETRY_BACKOFF,
    DEFAULT_RETRY_DELAY,
    DEFAULT_SERVER_MAX_CONNECTIONS,
    DEFAULT_SERVER_MAX_SESSIONS,
    DEFAULT_SERVER_VERIFY_MODE,
    DEFAULT_STREAM_CREATION_TIMEOUT,
    DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_BIDI,
    DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_UNI,
    DEFAULT_WRITE_TIMEOUT,
    H3_FRAME_TYPE_WEBTRANSPORT_STREAM,
    MAX_CLOSE_REASON_BYTES,
    MAX_PROTOCOL_STREAMS_LIMIT,
    MAX_STREAM_ID,
    SETTINGS_WT_INITIAL_MAX_DATA,
    SETTINGS_WT_INITIAL_MAX_STREAMS_BIDI,
    SETTINGS_WT_INITIAL_MAX_STREAMS_UNI,
    SUPPORTED_CONGESTION_CONTROL_ALGORITHMS,
    USER_AGENT_HEADER,
    WEBTRANSPORT_DEFAULT_PORT,
    WEBTRANSPORT_SCHEME,
    WT_DATA_BLOCKED_TYPE,
    WT_MAX_DATA_TYPE,
    WT_MAX_STREAM_DATA_TYPE,
    WT_MAX_STREAMS_BIDI_TYPE,
    WT_MAX_STREAMS_UNI_TYPE,
    WT_STREAM_DATA_BLOCKED_TYPE,
    WT_STREAMS_BLOCKED_BIDI_TYPE,
    WT_STREAMS_BLOCKED_UNI_TYPE,
    get_default_client_config,
    get_default_server_config,
)


class TestConstantsValues:

    def test_top_level_constants_values(self) -> None:
        assert DEFAULT_CONGESTION_CONTROL_ALGORITHM == "cubic"
        assert DEFAULT_LOG_LEVEL == "INFO"
        assert H3_FRAME_TYPE_WEBTRANSPORT_STREAM == 0x41
        assert MAX_CLOSE_REASON_BYTES == 1024
        assert MAX_PROTOCOL_STREAMS_LIMIT == 2**60
        assert MAX_STREAM_ID == 2**62 - 1
        assert SETTINGS_WT_INITIAL_MAX_DATA == 0x2B61
        assert SETTINGS_WT_INITIAL_MAX_STREAMS_BIDI == 0x2B65
        assert SETTINGS_WT_INITIAL_MAX_STREAMS_UNI == 0x2B64
        assert SUPPORTED_CONGESTION_CONTROL_ALGORITHMS == ("reno", "cubic")
        assert USER_AGENT_HEADER == "user-agent"
        assert WEBTRANSPORT_SCHEME == "https"
        assert WT_DATA_BLOCKED_TYPE == 0x190B4D41
        assert WT_MAX_DATA_TYPE == 0x190B4D3D
        assert WT_MAX_STREAM_DATA_TYPE == 0x190B4D3E
        assert WT_MAX_STREAMS_BIDI_TYPE == 0x190B4D3F
        assert WT_MAX_STREAMS_UNI_TYPE == 0x190B4D40
        assert WT_STREAM_DATA_BLOCKED_TYPE == 0x190B4D42
        assert WT_STREAMS_BLOCKED_BIDI_TYPE == 0x190B4D43
        assert WT_STREAMS_BLOCKED_UNI_TYPE == 0x190B4D44
        assert DEFAULT_BIND_HOST == "localhost"
        assert WEBTRANSPORT_DEFAULT_PORT == 443
        assert DEFAULT_CLIENT_VERIFY_MODE == ssl.CERT_REQUIRED
        assert DEFAULT_SERVER_VERIFY_MODE == ssl.CERT_NONE
        assert DEFAULT_CLIENT_MAX_SESSIONS == 100
        assert DEFAULT_SERVER_MAX_SESSIONS == 10000
        assert DEFAULT_MAX_STREAM_READ_BUFFER == 65536
        assert DEFAULT_MAX_STREAM_WRITE_BUFFER == 1024 * 1024
        assert DEFAULT_RESOURCE_CLEANUP_INTERVAL == 15.0
        assert DEFAULT_CLOSE_TIMEOUT == 5.0
        assert DEFAULT_CERTFILE is None
        assert DEFAULT_KEYFILE is None


class TestDefaultConfigs:

    def test_get_client_config(self) -> None:
        config = get_default_client_config()

        assert config["alpn_protocols"] == list(DEFAULT_ALPN_PROTOCOLS)
        assert config["ca_certs"] is None
        assert config["certfile"] is None
        assert config["close_timeout"] == DEFAULT_CLOSE_TIMEOUT
        assert config["congestion_control_algorithm"] == "cubic"
        assert config["connect_timeout"] == DEFAULT_CONNECT_TIMEOUT
        assert config["connection_idle_timeout"] == DEFAULT_CONNECTION_IDLE_TIMEOUT
        assert config["flow_control_window_auto_scale"] == DEFAULT_FLOW_CONTROL_WINDOW_AUTO_SCALE
        assert config["flow_control_window_size"] == DEFAULT_FLOW_CONTROL_WINDOW_SIZE
        assert config["headers"] == {}
        assert config["initial_max_data"] == DEFAULT_INITIAL_MAX_DATA
        assert config["initial_max_streams_bidi"] == DEFAULT_INITIAL_MAX_STREAMS_BIDI
        assert config["initial_max_streams_uni"] == DEFAULT_INITIAL_MAX_STREAMS_UNI
        assert config["keep_alive"] == DEFAULT_KEEP_ALIVE
        assert config["keyfile"] is None
        assert config["log_level"] == DEFAULT_LOG_LEVEL
        assert config["max_connection_retries"] == DEFAULT_MAX_CONNECTION_RETRIES
        assert config["max_connections"] == DEFAULT_CLIENT_MAX_CONNECTIONS
        assert config["max_datagram_size"] == DEFAULT_MAX_DATAGRAM_SIZE
        assert config["max_event_history_size"] == DEFAULT_MAX_EVENT_HISTORY_SIZE
        assert config["max_event_listeners"] == DEFAULT_MAX_EVENT_LISTENERS
        assert config["max_event_queue_size"] == DEFAULT_MAX_EVENT_QUEUE_SIZE
        assert config["max_message_size"] == DEFAULT_MAX_MESSAGE_SIZE
        assert config["max_pending_events_per_session"] == DEFAULT_MAX_PENDING_EVENTS_PER_SESSION
        assert config["max_retry_delay"] == DEFAULT_MAX_RETRY_DELAY
        assert config["max_sessions"] == DEFAULT_CLIENT_MAX_SESSIONS
        assert config["max_stream_read_buffer"] == DEFAULT_MAX_STREAM_READ_BUFFER
        assert config["max_stream_write_buffer"] == DEFAULT_MAX_STREAM_WRITE_BUFFER
        assert config["max_total_pending_events"] == DEFAULT_MAX_TOTAL_PENDING_EVENTS
        assert config["pending_event_ttl"] == DEFAULT_PENDING_EVENT_TTL
        assert config["read_timeout"] == DEFAULT_READ_TIMEOUT
        assert config["resource_cleanup_interval"] == DEFAULT_RESOURCE_CLEANUP_INTERVAL
        assert config["retry_backoff"] == DEFAULT_RETRY_BACKOFF
        assert config["retry_delay"] == DEFAULT_RETRY_DELAY
        assert config["stream_creation_timeout"] == DEFAULT_STREAM_CREATION_TIMEOUT
        assert config["stream_flow_control_increment_bidi"] == DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_BIDI
        assert config["stream_flow_control_increment_uni"] == DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_UNI
        assert config["user_agent"] == f"PyWebTransport/{__version__}"
        assert config["verify_mode"] == DEFAULT_CLIENT_VERIFY_MODE
        assert config["write_timeout"] == DEFAULT_WRITE_TIMEOUT

    def test_get_client_config_returns_copy(self) -> None:
        config1 = get_default_client_config()
        config2 = get_default_client_config()

        assert config1 is not config2

        config1["max_connections"] = 999

        assert get_default_client_config()["max_connections"] == DEFAULT_CLIENT_MAX_CONNECTIONS

    def test_get_server_config(self) -> None:
        config = get_default_server_config()

        assert config["alpn_protocols"] == list(DEFAULT_ALPN_PROTOCOLS)
        assert config["bind_host"] == DEFAULT_BIND_HOST
        assert config["bind_port"] == DEFAULT_DEV_PORT
        assert config["ca_certs"] is None
        assert config["certfile"] == DEFAULT_CERTFILE
        assert config["close_timeout"] == DEFAULT_CLOSE_TIMEOUT
        assert config["congestion_control_algorithm"] == "cubic"
        assert config["connection_idle_timeout"] == DEFAULT_CONNECTION_IDLE_TIMEOUT
        assert config["flow_control_window_auto_scale"] == DEFAULT_FLOW_CONTROL_WINDOW_AUTO_SCALE
        assert config["flow_control_window_size"] == DEFAULT_FLOW_CONTROL_WINDOW_SIZE
        assert config["initial_max_data"] == DEFAULT_INITIAL_MAX_DATA
        assert config["initial_max_streams_bidi"] == DEFAULT_INITIAL_MAX_STREAMS_BIDI
        assert config["initial_max_streams_uni"] == DEFAULT_INITIAL_MAX_STREAMS_UNI
        assert config["keep_alive"] == DEFAULT_KEEP_ALIVE
        assert config["keyfile"] == DEFAULT_KEYFILE
        assert config["log_level"] == DEFAULT_LOG_LEVEL
        assert config["max_connections"] == DEFAULT_SERVER_MAX_CONNECTIONS
        assert config["max_datagram_size"] == DEFAULT_MAX_DATAGRAM_SIZE
        assert config["max_event_history_size"] == DEFAULT_MAX_EVENT_HISTORY_SIZE
        assert config["max_event_listeners"] == DEFAULT_MAX_EVENT_LISTENERS
        assert config["max_event_queue_size"] == DEFAULT_MAX_EVENT_QUEUE_SIZE
        assert config["max_message_size"] == DEFAULT_MAX_MESSAGE_SIZE
        assert config["max_pending_events_per_session"] == DEFAULT_MAX_PENDING_EVENTS_PER_SESSION
        assert config["max_sessions"] == DEFAULT_SERVER_MAX_SESSIONS
        assert config["max_stream_read_buffer"] == DEFAULT_MAX_STREAM_READ_BUFFER
        assert config["max_stream_write_buffer"] == DEFAULT_MAX_STREAM_WRITE_BUFFER
        assert config["max_total_pending_events"] == DEFAULT_MAX_TOTAL_PENDING_EVENTS
        assert config["pending_event_ttl"] == DEFAULT_PENDING_EVENT_TTL
        assert config["read_timeout"] == DEFAULT_READ_TIMEOUT
        assert config["resource_cleanup_interval"] == DEFAULT_RESOURCE_CLEANUP_INTERVAL
        assert config["stream_creation_timeout"] == DEFAULT_STREAM_CREATION_TIMEOUT
        assert config["stream_flow_control_increment_bidi"] == DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_BIDI
        assert config["stream_flow_control_increment_uni"] == DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_UNI
        assert config["verify_mode"] == DEFAULT_SERVER_VERIFY_MODE
        assert config["write_timeout"] == DEFAULT_WRITE_TIMEOUT

    def test_get_server_config_returns_copy(self) -> None:
        config1 = get_default_server_config()
        config2 = get_default_server_config()

        assert config1 is not config2

        config1["max_connections"] = 9999

        assert get_default_server_config()["max_connections"] == DEFAULT_SERVER_MAX_CONNECTIONS


class TestErrorCodes:

    @pytest.mark.parametrize(
        "member, expected_value",
        [
            (ErrorCodes.NO_ERROR, 0x0),
            (ErrorCodes.INTERNAL_ERROR, 0x1),
            (ErrorCodes.CONNECTION_REFUSED, 0x2),
            (ErrorCodes.FLOW_CONTROL_ERROR, 0x3),
            (ErrorCodes.STREAM_LIMIT_ERROR, 0x4),
            (ErrorCodes.STREAM_STATE_ERROR, 0x5),
            (ErrorCodes.FINAL_SIZE_ERROR, 0x6),
            (ErrorCodes.FRAME_ENCODING_ERROR, 0x7),
            (ErrorCodes.TRANSPORT_PARAMETER_ERROR, 0x8),
            (ErrorCodes.CONNECTION_ID_LIMIT_ERROR, 0x9),
            (ErrorCodes.PROTOCOL_VIOLATION, 0xA),
            (ErrorCodes.INVALID_TOKEN, 0xB),
            (ErrorCodes.APPLICATION_ERROR, 0xC),
            (ErrorCodes.CRYPTO_BUFFER_EXCEEDED, 0xD),
            (ErrorCodes.KEY_UPDATE_ERROR, 0xE),
            (ErrorCodes.AEAD_LIMIT_REACHED, 0xF),
            (ErrorCodes.NO_VIABLE_PATH, 0x10),
            (ErrorCodes.H3_DATAGRAM_ERROR, 0x33),
            (ErrorCodes.H3_NO_ERROR, 0x100),
            (ErrorCodes.H3_GENERAL_PROTOCOL_ERROR, 0x101),
            (ErrorCodes.H3_INTERNAL_ERROR, 0x102),
            (ErrorCodes.H3_STREAM_CREATION_ERROR, 0x103),
            (ErrorCodes.H3_CLOSED_CRITICAL_STREAM, 0x104),
            (ErrorCodes.H3_FRAME_UNEXPECTED, 0x105),
            (ErrorCodes.H3_FRAME_ERROR, 0x106),
            (ErrorCodes.H3_EXCESSIVE_LOAD, 0x107),
            (ErrorCodes.H3_ID_ERROR, 0x108),
            (ErrorCodes.H3_SETTINGS_ERROR, 0x109),
            (ErrorCodes.H3_MISSING_SETTINGS, 0x10A),
            (ErrorCodes.H3_REQUEST_REJECTED, 0x10B),
            (ErrorCodes.H3_REQUEST_CANCELLED, 0x10C),
            (ErrorCodes.H3_REQUEST_INCOMPLETE, 0x10D),
            (ErrorCodes.H3_MESSAGE_ERROR, 0x10E),
            (ErrorCodes.H3_CONNECT_ERROR, 0x10F),
            (ErrorCodes.H3_VERSION_FALLBACK, 0x110),
            (ErrorCodes.QPACK_DECOMPRESSION_FAILED, 0x200),
            (ErrorCodes.QPACK_ENCODER_STREAM_ERROR, 0x201),
            (ErrorCodes.QPACK_DECODER_STREAM_ERROR, 0x202),
            (ErrorCodes.WT_SESSION_GONE, 0x170D7B68),
            (ErrorCodes.WT_BUFFERED_STREAM_REJECTED, 0x3994BD84),
            (ErrorCodes.WT_FLOW_CONTROL_ERROR, 0x045D4487),
            (ErrorCodes.WT_APPLICATION_ERROR_FIRST, 0x52E4A40FA8DB),
            (ErrorCodes.WT_APPLICATION_ERROR_LAST, 0x52E5AC983162),
            (ErrorCodes.APP_CONNECTION_TIMEOUT, 0x1000),
            (ErrorCodes.APP_AUTHENTICATION_FAILED, 0x1001),
            (ErrorCodes.APP_PERMISSION_DENIED, 0x1002),
            (ErrorCodes.APP_RESOURCE_EXHAUSTED, 0x1003),
            (ErrorCodes.APP_INVALID_REQUEST, 0x1004),
            (ErrorCodes.APP_SERVICE_UNAVAILABLE, 0x1005),
        ],
    )
    def test_error_code_values(self, member: ErrorCodes, expected_value: int) -> None:
        assert member.value == expected_value

    def test_error_codes_is_int_enum(self) -> None:
        assert issubclass(ErrorCodes, IntEnum)
