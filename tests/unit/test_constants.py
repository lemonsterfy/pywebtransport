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
    DEFAULT_KEEP_ALIVE,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_STREAMS,
    DEFAULT_SERVER_MAX_CONNECTIONS,
    DEFAULT_SERVER_VERIFY_MODE,
    DEFAULT_VERSION,
    DRAFT_VERSION,
    MAX_STREAM_ID,
    ORIGIN_HEADER,
    SETTINGS_ENABLE_WEBTRANSPORT,
    SUPPORTED_CONGESTION_CONTROL_ALGORITHMS,
    USER_AGENT_HEADER,
    WEBTRANSPORT_H3_BIDI_STREAM_TYPE,
    WEBTRANSPORT_HEADER,
    WEBTRANSPORT_SCHEMES,
    Defaults,
    ErrorCodes,
)


class TestConstantsValues:
    def test_top_level_constants_values(self) -> None:
        assert DEFAULT_CONGESTION_CONTROL_ALGORITHM == "cubic"
        assert DEFAULT_LOG_LEVEL == "INFO"
        assert DEFAULT_VERSION == "h3"
        assert DRAFT_VERSION == 13
        assert MAX_STREAM_ID == 2**62 - 1
        assert ORIGIN_HEADER == "origin"
        assert SETTINGS_ENABLE_WEBTRANSPORT == 0x2B603742
        assert SUPPORTED_CONGESTION_CONTROL_ALGORITHMS == ("reno", "cubic")
        assert USER_AGENT_HEADER == "user-agent"
        assert WEBTRANSPORT_H3_BIDI_STREAM_TYPE == 0x41
        assert WEBTRANSPORT_HEADER == "webtransport"
        assert WEBTRANSPORT_SCHEMES == ("https", "wss")
        assert DEFAULT_DEBUG is False
        assert DEFAULT_BIND_HOST == "localhost"
        assert DEFAULT_CLIENT_VERIFY_MODE == ssl.CERT_REQUIRED
        assert DEFAULT_SERVER_VERIFY_MODE == ssl.CERT_NONE


class TestErrorCodes:
    def test_error_codes_is_int_enum(self) -> None:
        assert issubclass(ErrorCodes, IntEnum)

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
            (ErrorCodes.APP_CONNECTION_TIMEOUT, 0x1000),
            (ErrorCodes.APP_AUTHENTICATION_FAILED, 0x1001),
            (ErrorCodes.APP_SERVICE_UNAVAILABLE, 0x1005),
        ],
    )
    def test_error_code_values(self, member: ErrorCodes, expected_value: int) -> None:
        assert member.value == expected_value


class TestDefaults:
    def test_get_client_config(self) -> None:
        config = Defaults.get_client_config()

        assert config["alpn_protocols"] == list(DEFAULT_ALPN_PROTOCOLS)
        assert config["auto_reconnect"] == DEFAULT_AUTO_RECONNECT
        assert config["congestion_control_algorithm"] == "cubic"
        assert config["connect_timeout"] == DEFAULT_CONNECT_TIMEOUT
        assert config["debug"] == DEFAULT_DEBUG
        assert config["keep_alive"] == DEFAULT_KEEP_ALIVE
        assert config["max_retries"] == DEFAULT_MAX_RETRIES
        assert config["max_streams"] == DEFAULT_MAX_STREAMS
        assert config["user_agent"] == f"pywebtransport/{project_version}"
        assert config["verify_mode"] == DEFAULT_CLIENT_VERIFY_MODE

    def test_get_client_config_returns_copy(self) -> None:
        config1 = Defaults.get_client_config()
        config2 = Defaults.get_client_config()
        assert config1 is not config2

        config1["max_streams"] = 999
        assert Defaults.get_client_config()["max_streams"] == DEFAULT_MAX_STREAMS

    def test_get_server_config(self) -> None:
        config = Defaults.get_server_config()

        assert config["access_log"] == DEFAULT_ACCESS_LOG
        assert config["bind_host"] == DEFAULT_BIND_HOST
        assert config["bind_port"] == DEFAULT_DEV_PORT
        assert config["congestion_control_algorithm"] == "cubic"
        assert config["debug"] == DEFAULT_DEBUG
        assert config["keep_alive"] == DEFAULT_KEEP_ALIVE
        assert config["max_connections"] == DEFAULT_SERVER_MAX_CONNECTIONS
        assert config["verify_mode"] == DEFAULT_SERVER_VERIFY_MODE

    def test_get_server_config_returns_copy(self) -> None:
        config1 = Defaults.get_server_config()
        config2 = Defaults.get_server_config()
        assert config1 is not config2

        config1["max_connections"] = 9999
        assert Defaults.get_server_config()["max_connections"] == DEFAULT_SERVER_MAX_CONNECTIONS
