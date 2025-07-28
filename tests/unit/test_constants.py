"""Unit tests for the pywebtransport.constants module."""

from enum import IntEnum

import pytest
from pytest_mock import MockerFixture

from pywebtransport import __version__ as project_version
from pywebtransport.constants import (
    DEFAULT_LOG_LEVEL,
    ORIGIN_HEADER,
    WEBTRANSPORT_SCHEMES,
    Defaults,
    ErrorCodes,
    WebTransportConstants,
)


class TestConstantsValues:
    def test_module_level_constants(self) -> None:
        assert DEFAULT_LOG_LEVEL == "INFO"
        assert ORIGIN_HEADER == "origin"
        assert WEBTRANSPORT_SCHEMES == ("https", "wss")

    def test_webtransport_constants_class(self) -> None:
        assert WebTransportConstants.DEFAULT_SECURE_PORT == 443
        assert WebTransportConstants.DRAFT_VERSION == 13
        assert WebTransportConstants.DEFAULT_VERSION == "h3"
        assert WebTransportConstants.WEBTRANSPORT_H3_BIDI_STREAM_TYPE == 0x41
        assert WebTransportConstants.SETTINGS_ENABLE_WEBTRANSPORT == 0x2B603742
        assert WebTransportConstants.DEFAULT_CONNECT_TIMEOUT == 30.0


class TestErrorCodes:
    def test_error_codes_is_int_enum(self) -> None:
        assert issubclass(ErrorCodes, IntEnum)

    @pytest.mark.parametrize(
        "member, expected_value",
        [
            (ErrorCodes.NO_ERROR, 0x0),
            (ErrorCodes.INTERNAL_ERROR, 0x1),
            (ErrorCodes.PROTOCOL_VIOLATION, 0xA),
            (ErrorCodes.H3_NO_ERROR, 0x100),
            (ErrorCodes.H3_GENERAL_PROTOCOL_ERROR, 0x101),
            (ErrorCodes.H3_SETTINGS_ERROR, 0x109),
            (ErrorCodes.APP_CONNECTION_TIMEOUT, 0x1000),
            (ErrorCodes.APP_AUTHENTICATION_FAILED, 0x1001),
            (ErrorCodes.APP_SERVICE_UNAVAILABLE, 0x1005),
        ],
    )
    def test_error_code_values(self, member: ErrorCodes, expected_value: int) -> None:
        assert member.value == expected_value


class TestDefaults:
    def test_get_client_config(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "pywebtransport.constants._DEFAULT_CLIENT_CONFIG",
            {
                "connect_timeout": WebTransportConstants.DEFAULT_CONNECT_TIMEOUT,
                "read_timeout": WebTransportConstants.DEFAULT_READ_TIMEOUT,
                "write_timeout": WebTransportConstants.DEFAULT_WRITE_TIMEOUT,
                "close_timeout": WebTransportConstants.DEFAULT_CLOSE_TIMEOUT,
                "max_streams": WebTransportConstants.DEFAULT_MAX_STREAMS,
                "stream_buffer_size": WebTransportConstants.DEFAULT_BUFFER_SIZE,
                "alpn_protocols": list(WebTransportConstants.DEFAULT_ALPN_PROTOCOLS),
                "http_version": "3",
                "verify_mode": None,
                "check_hostname": True,
                "user_agent": f"pywebtransport/{project_version}",
            },
        )
        config = Defaults.get_client_config()
        assert config["connect_timeout"] == 30.0
        assert config["max_streams"] == 100
        assert config["user_agent"] == f"pywebtransport/{project_version}"

    def test_get_client_config_returns_copy(self) -> None:
        config1 = Defaults.get_client_config()
        config2 = Defaults.get_client_config()
        assert config1 is not config2

        config1["max_streams"] = 999
        assert Defaults.get_client_config()["max_streams"] == 100

    def test_get_server_config(self) -> None:
        config = Defaults.get_server_config()
        assert config["bind_host"] == "localhost"
        assert config["bind_port"] == WebTransportConstants.DEFAULT_DEV_PORT
        assert config["connection_timeout"] == WebTransportConstants.DEFAULT_KEEPALIVE_TIMEOUT

    def test_get_server_config_returns_copy(self) -> None:
        config1 = Defaults.get_server_config()
        config2 = Defaults.get_server_config()
        assert config1 is not config2

        config1["max_connections"] = 9999
        assert Defaults.get_server_config()["max_connections"] == 1000
