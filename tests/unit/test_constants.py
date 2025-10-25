"""Unit tests for the pywebtransport.constants module."""

import ssl
from enum import IntEnum

import pytest

from pywebtransport import __version__ as project_version
from pywebtransport.constants import (
    DEFAULT_ACCESS_LOG,
    DEFAULT_ALPN_PROTOCOLS,
    DEFAULT_AUTO_RECONNECT,
    DEFAULT_BIND_HOST,
    DEFAULT_CLIENT_VERIFY_MODE,
    DEFAULT_CONGESTION_CONTROL_ALGORITHM,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_DEBUG,
    DEFAULT_DEV_PORT,
    DEFAULT_FLOW_CONTROL_WINDOW_AUTO_SCALE,
    DEFAULT_FLOW_CONTROL_WINDOW_SIZE,
    DEFAULT_INITIAL_MAX_DATA,
    DEFAULT_INITIAL_MAX_STREAMS_BIDI,
    DEFAULT_INITIAL_MAX_STREAMS_UNI,
    DEFAULT_KEEP_ALIVE,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MAX_PENDING_EVENTS_PER_SESSION,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_STREAMS,
    DEFAULT_MAX_TOTAL_PENDING_EVENTS,
    DEFAULT_PENDING_EVENT_TTL,
    DEFAULT_PROXY_CONNECT_TIMEOUT,
    DEFAULT_PUBSUB_SUBSCRIPTION_QUEUE_SIZE,
    DEFAULT_RPC_CONCURRENCY_LIMIT,
    DEFAULT_SERVER_MAX_CONNECTIONS,
    DEFAULT_SERVER_VERIFY_MODE,
    DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_BIDI,
    DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_UNI,
    DEFAULT_STREAM_LINE_LIMIT,
    H3_FRAME_TYPE_WEBTRANSPORT_STREAM,
    MAX_STREAM_ID,
    SETTINGS_WT_INITIAL_MAX_DATA,
    SETTINGS_WT_INITIAL_MAX_STREAMS_BIDI,
    SETTINGS_WT_INITIAL_MAX_STREAMS_UNI,
    SETTINGS_WT_MAX_SESSIONS,
    SUPPORTED_CONGESTION_CONTROL_ALGORITHMS,
    USER_AGENT_HEADER,
    WEBTRANSPORT_SCHEME,
    WT_DATA_BLOCKED_TYPE,
    WT_MAX_DATA_TYPE,
    WT_MAX_STREAMS_BIDI_TYPE,
    WT_MAX_STREAMS_UNI_TYPE,
    WT_STREAMS_BLOCKED_BIDI_TYPE,
    WT_STREAMS_BLOCKED_UNI_TYPE,
    ErrorCodes,
    get_default_client_config,
    get_default_server_config,
)


class TestConstantsValues:
    def test_top_level_constants_values(self) -> None:
        assert DEFAULT_CONGESTION_CONTROL_ALGORITHM == "cubic"
        assert DEFAULT_LOG_LEVEL == "INFO"
        assert H3_FRAME_TYPE_WEBTRANSPORT_STREAM == 0x41
        assert MAX_STREAM_ID == 2**62 - 1
        assert SETTINGS_WT_INITIAL_MAX_DATA == 0x2B61
        assert SETTINGS_WT_INITIAL_MAX_STREAMS_BIDI == 0x2B65
        assert SETTINGS_WT_INITIAL_MAX_STREAMS_UNI == 0x2B64
        assert SETTINGS_WT_MAX_SESSIONS == 0x14E9CD29
        assert SUPPORTED_CONGESTION_CONTROL_ALGORITHMS == ("reno", "cubic")
        assert USER_AGENT_HEADER == "user-agent"
        assert WEBTRANSPORT_SCHEME == "https"
        assert WT_DATA_BLOCKED_TYPE == 0x190B4D41
        assert WT_MAX_DATA_TYPE == 0x190B4D3D
        assert WT_MAX_STREAMS_BIDI_TYPE == 0x190B4D3F
        assert WT_MAX_STREAMS_UNI_TYPE == 0x190B4D40
        assert WT_STREAMS_BLOCKED_BIDI_TYPE == 0x190B4D43
        assert WT_STREAMS_BLOCKED_UNI_TYPE == 0x190B4D44
        assert DEFAULT_PROXY_CONNECT_TIMEOUT == 10.0
        assert DEFAULT_PUBSUB_SUBSCRIPTION_QUEUE_SIZE == 16
        assert DEFAULT_DEBUG is False
        assert DEFAULT_BIND_HOST == "localhost"
        assert DEFAULT_CLIENT_VERIFY_MODE == ssl.CERT_REQUIRED
        assert DEFAULT_SERVER_VERIFY_MODE == ssl.CERT_OPTIONAL
        assert DEFAULT_STREAM_LINE_LIMIT == 65536


class TestDefaultConfigs:
    def test_get_client_config(self) -> None:
        config = get_default_client_config()

        assert config["alpn_protocols"] == list(DEFAULT_ALPN_PROTOCOLS)
        assert config["auto_reconnect"] == DEFAULT_AUTO_RECONNECT
        assert config["congestion_control_algorithm"] == "cubic"
        assert config["connect_timeout"] == DEFAULT_CONNECT_TIMEOUT
        assert config["debug"] == DEFAULT_DEBUG
        assert config["flow_control_window_auto_scale"] == DEFAULT_FLOW_CONTROL_WINDOW_AUTO_SCALE
        assert config["flow_control_window_size"] == DEFAULT_FLOW_CONTROL_WINDOW_SIZE
        assert config["initial_max_data"] == DEFAULT_INITIAL_MAX_DATA
        assert config["initial_max_streams_bidi"] == DEFAULT_INITIAL_MAX_STREAMS_BIDI
        assert config["initial_max_streams_uni"] == DEFAULT_INITIAL_MAX_STREAMS_UNI
        assert config["keep_alive"] == DEFAULT_KEEP_ALIVE
        assert config["max_pending_events_per_session"] == DEFAULT_MAX_PENDING_EVENTS_PER_SESSION
        assert config["max_retries"] == DEFAULT_MAX_RETRIES
        assert config["max_streams"] == DEFAULT_MAX_STREAMS
        assert config["max_total_pending_events"] == DEFAULT_MAX_TOTAL_PENDING_EVENTS
        assert config["pending_event_ttl"] == DEFAULT_PENDING_EVENT_TTL
        assert config["proxy"] is None
        assert config["rpc_concurrency_limit"] == DEFAULT_RPC_CONCURRENCY_LIMIT
        assert config["stream_flow_control_increment_bidi"] == DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_BIDI
        assert config["stream_flow_control_increment_uni"] == DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_UNI
        assert config["user_agent"] == f"pywebtransport/{project_version}"
        assert config["verify_mode"] == DEFAULT_CLIENT_VERIFY_MODE

    def test_get_client_config_returns_copy(self) -> None:
        config1 = get_default_client_config()
        config2 = get_default_client_config()

        assert config1 is not config2

        config1["max_streams"] = 999

        assert get_default_client_config()["max_streams"] == DEFAULT_MAX_STREAMS

    def test_get_server_config(self) -> None:
        config = get_default_server_config()

        assert config["access_log"] == DEFAULT_ACCESS_LOG
        assert config["bind_host"] == DEFAULT_BIND_HOST
        assert config["bind_port"] == DEFAULT_DEV_PORT
        assert config["congestion_control_algorithm"] == "cubic"
        assert config["debug"] == DEFAULT_DEBUG
        assert config["flow_control_window_auto_scale"] == DEFAULT_FLOW_CONTROL_WINDOW_AUTO_SCALE
        assert config["flow_control_window_size"] == DEFAULT_FLOW_CONTROL_WINDOW_SIZE
        assert config["initial_max_data"] == DEFAULT_INITIAL_MAX_DATA
        assert config["initial_max_streams_bidi"] == DEFAULT_INITIAL_MAX_STREAMS_BIDI
        assert config["initial_max_streams_uni"] == DEFAULT_INITIAL_MAX_STREAMS_UNI
        assert config["keep_alive"] == DEFAULT_KEEP_ALIVE
        assert config["max_connections"] == DEFAULT_SERVER_MAX_CONNECTIONS
        assert config["max_pending_events_per_session"] == DEFAULT_MAX_PENDING_EVENTS_PER_SESSION
        assert config["max_total_pending_events"] == DEFAULT_MAX_TOTAL_PENDING_EVENTS
        assert config["pending_event_ttl"] == DEFAULT_PENDING_EVENT_TTL
        assert config["rpc_concurrency_limit"] == DEFAULT_RPC_CONCURRENCY_LIMIT
        assert config["stream_flow_control_increment_bidi"] == DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_BIDI
        assert config["stream_flow_control_increment_uni"] == DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_UNI
        assert config["verify_mode"] == DEFAULT_SERVER_VERIFY_MODE

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
            (ErrorCodes.STREAM_LIMIT_ERROR, 0x4),
            (ErrorCodes.PROTOCOL_VIOLATION, 0xA),
            (ErrorCodes.H3_DATAGRAM_ERROR, 0x33),
            (ErrorCodes.H3_NO_ERROR, 0x100),
            (ErrorCodes.H3_GENERAL_PROTOCOL_ERROR, 0x101),
            (ErrorCodes.H3_INTERNAL_ERROR, 0x102),
            (ErrorCodes.H3_SETTINGS_ERROR, 0x109),
            (ErrorCodes.QPACK_DECOMPRESSION_FAILED, 0x200),
            (ErrorCodes.QPACK_ENCODER_STREAM_ERROR, 0x201),
            (ErrorCodes.QPACK_DECODER_STREAM_ERROR, 0x202),
            (ErrorCodes.WT_SESSION_GONE, 0x170D7B68),
            (ErrorCodes.WT_BUFFERED_STREAM_REJECTED, 0x3994BD84),
            (ErrorCodes.WT_APPLICATION_ERROR_FIRST, 0x52E4A40FA8DB),
            (ErrorCodes.APP_CONNECTION_TIMEOUT, 0x1000),
            (ErrorCodes.APP_AUTHENTICATION_FAILED, 0x1001),
            (ErrorCodes.APP_SERVICE_UNAVAILABLE, 0x1005),
        ],
    )
    def test_error_code_values(self, member: ErrorCodes, expected_value: int) -> None:
        assert member.value == expected_value

    def test_error_codes_is_int_enum(self) -> None:
        assert issubclass(ErrorCodes, IntEnum)
