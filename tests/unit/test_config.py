"""Unit tests for the pywebtransport.config module."""

import ssl
from pathlib import Path
from typing import Any, Dict

import pytest
from pytest_mock import MockerFixture

from pywebtransport import CertificateError, ClientConfig, ConfigurationError, ServerConfig
from pywebtransport import __version__ as real_version
from pywebtransport.config import ConfigBuilder, _validate_port, _validate_timeout


@pytest.fixture
def mock_path_exists(mocker: MockerFixture) -> Any:
    return mocker.patch.object(Path, "exists", return_value=True)


class TestConfigHelpers:
    @pytest.mark.parametrize("value", [5, 10.5, None])
    def test_validate_timeout_valid(self, value: Any) -> None:
        _validate_timeout(value)

    @pytest.mark.parametrize("value", [0, -1, -10.5])
    def test_validate_timeout_invalid_value(self, value: Any) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            _validate_timeout(value)

    def test_validate_timeout_invalid_type(self) -> None:
        with pytest.raises(TypeError, match="must be a number or None"):
            invalid_value: Any = "abc"
            _validate_timeout(invalid_value)

    @pytest.mark.parametrize("value", [1, 80, 4433, 65535])
    def test_validate_port_valid(self, value: int) -> None:
        _validate_port(value)

    @pytest.mark.parametrize("value", [0, 65536, -1, "80", 80.5])
    def test_validate_port_invalid(self, value: Any) -> None:
        with pytest.raises(ValueError, match="Port must be an integer between 1 and 65535"):
            _validate_port(value)


class TestClientConfig:
    def test_default_initialization(self) -> None:
        config = ClientConfig()
        assert config.connect_timeout == 30.0
        assert config.verify_mode == ssl.CERT_REQUIRED
        assert config.user_agent == f"pywebtransport/{real_version}"
        assert config.headers["user-agent"] == f"pywebtransport/{real_version}"

    def test_post_init_normalizes_headers(self, mocker: MockerFixture) -> None:
        mock_normalize = mocker.patch("pywebtransport.config.normalize_headers", return_value={})
        ClientConfig(headers={"X-Custom": "Value"})
        mock_normalize.assert_called_once_with({"X-Custom": "Value"})

    def test_create_factory_method(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.config.Defaults.get_client_config", return_value={"max_retries": 1})
        config = ClientConfig.create(max_retries=5, debug=True)
        assert config.max_retries == 5
        assert config.debug is True

    def test_create_for_development_factory(self) -> None:
        config = ClientConfig.create_for_development(verify_ssl=False)
        assert config.debug is True
        assert config.log_level == "DEBUG"
        assert config.verify_mode == ssl.CERT_NONE

    def test_create_for_production_factory(self, mock_path_exists: Any) -> None:
        config = ClientConfig.create_for_production(ca_certs="ca.pem")
        assert config.debug is False
        assert config.log_level == "INFO"
        assert config.ca_certs == "ca.pem"
        assert config.verify_mode == ssl.CERT_REQUIRED

    def test_copy_method(self) -> None:
        config1 = ClientConfig()
        config2 = config1.copy()
        assert config1 is not config2
        config2.max_retries = 99
        assert config1.max_retries != 99

    def test_update_method(self) -> None:
        config = ClientConfig()
        new_config = config.update(connect_timeout=15.0)
        assert new_config.connect_timeout == 15.0
        assert config.connect_timeout == 30.0
        assert new_config is not config
        with pytest.raises(ConfigurationError, match="unknown configuration key"):
            config.update(unknown_key="value")

    def test_merge_method(self, mocker: MockerFixture) -> None:
        config1 = ClientConfig(read_timeout=10, max_retries=1)
        mocker.patch.object(ClientConfig, "validate", return_value=None)

        invalid_max_retries: Any = None
        config2 = ClientConfig(read_timeout=20, write_timeout=25, max_retries=invalid_max_retries)

        mocker.stopall()
        merged_config = config1.merge(config2)
        assert merged_config.read_timeout == 20
        assert merged_config.write_timeout == 25
        assert merged_config.max_retries == 1

        merged_from_dict = config1.merge({"write_timeout": 35})
        assert merged_from_dict.read_timeout == 10
        assert merged_from_dict.write_timeout == 35

        with pytest.raises(TypeError):
            invalid_value: Any = 123
            config1.merge(invalid_value)

    def test_to_dict_method(self) -> None:
        config = ClientConfig(verify_mode=ssl.CERT_OPTIONAL, debug=True)
        data = config.to_dict()
        assert data["verify_mode"] == "CERT_OPTIONAL"
        assert data["debug"] is True

    @pytest.mark.parametrize(
        "invalid_attrs, error_match",
        [
            ({"connect_timeout": -1}, "invalid timeout value"),
            ({"max_streams": 0}, "must be positive"),
            ({"stream_buffer_size": -10}, "must be positive"),
            ({"max_stream_buffer_size": 100, "stream_buffer_size": 200}, "must be >= stream_buffer_size"),
            ({"verify_mode": "INVALID"}, "invalid SSL verify mode"),
            ({"certfile": "a.pem", "keyfile": None}, "both must be provided together"),
            ({"http_version": "1.1"}, "must be '2' or '3'"),
            ({"alpn_protocols": []}, "cannot be empty"),
        ],
    )
    def test_validation_failures(self, invalid_attrs: Dict[str, Any], error_match: str, mock_path_exists: Any) -> None:
        with pytest.raises(ConfigurationError, match=error_match):
            ClientConfig(**invalid_attrs)

    @pytest.mark.parametrize(
        "invalid_attrs, error_match",
        [
            ({"max_retries": -1}, "must be non-negative"),
            ({"retry_delay": 0}, "must be positive"),
            ({"retry_backoff": 0.9}, "must be >= 1.0"),
            ({"max_retry_delay": -10.0}, "must be positive"),
        ],
    )
    def test_validation_failures_retry_logic(self, invalid_attrs: Dict[str, Any], error_match: str) -> None:
        with pytest.raises(ConfigurationError, match=error_match):
            ClientConfig(**invalid_attrs)

    def test_validation_cert_not_found(self, mock_path_exists: Any) -> None:
        mock_path_exists.return_value = False
        with pytest.raises(CertificateError, match="Certificate file not found"):
            ClientConfig(certfile="nonexistent.pem", keyfile="nonexistent.key")


class TestServerConfig:
    def test_default_initialization(self) -> None:
        config = ServerConfig()
        assert config.bind_host == "localhost"
        assert config.max_connections == 1000

    def test_create_factory_method(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.config.Defaults.get_server_config", return_value={"backlog": 1})
        config = ServerConfig.create(backlog=100, debug=True)
        assert config.backlog == 100
        assert config.debug is True

    def test_create_for_development_factory(self, mock_path_exists: Any) -> None:
        config = ServerConfig.create_for_development(host="devhost", certfile="c.pem", keyfile="k.pem")
        assert config.debug is True
        assert config.bind_host == "devhost"
        assert config.certfile == "c.pem"

    def test_create_for_development_factory_no_certs(self) -> None:
        config = ServerConfig.create_for_development()
        assert config.certfile == ""
        assert config.keyfile == ""

    def test_create_for_production_factory(self, mock_path_exists: Any) -> None:
        config = ServerConfig.create_for_production(
            host="prodhost", port=443, certfile="c.pem", keyfile="k.pem", ca_certs="ca.pem"
        )
        assert config.debug is False
        assert config.bind_host == "prodhost"
        assert config.bind_port == 443
        assert config.certfile == "c.pem"
        assert config.verify_mode == ssl.CERT_OPTIONAL

    def test_get_bind_address(self) -> None:
        config = ServerConfig(bind_host="127.0.0.1", bind_port=8888)
        assert config.get_bind_address() == ("127.0.0.1", 8888)

    def test_merge_method(self) -> None:
        config1 = ServerConfig(max_connections=100)
        config2 = ServerConfig(max_connections=200, backlog=256)
        merged = config1.merge(config2)
        assert merged.max_connections == 200
        assert merged.backlog == 256

    def test_to_dict_method(self) -> None:
        config = ServerConfig(verify_mode=ssl.CERT_REQUIRED, reuse_port=False)
        data = config.to_dict()
        assert data["verify_mode"] == "CERT_REQUIRED"
        assert data["reuse_port"] is False

    @pytest.mark.parametrize(
        "invalid_attrs, error_match",
        [
            ({"bind_host": ""}, "cannot be empty"),
            ({"bind_port": 0}, "Port must be an integer"),
            ({"max_connections": 0}, "must be positive"),
            ({"certfile": "a.pem", "keyfile": ""}, "certfile and keyfile must be provided together"),
            ({"backlog": 0}, "must be positive"),
        ],
    )
    def test_validation_failures(self, invalid_attrs: Dict[str, Any], error_match: str, mock_path_exists: Any) -> None:
        with pytest.raises(ConfigurationError, match=error_match):
            ServerConfig(**invalid_attrs)


class TestConfigBuilder:
    def test_client_build_flow(self, mock_path_exists: Any) -> None:
        builder = ConfigBuilder(config_type="client")
        config = (
            builder.debug(log_level="INFO")
            .timeout(connect=15, read=45)
            .security(certfile="c.pem", keyfile="k.pem")
            .performance(max_streams=50, buffer_size=12345)
            .build()
        )
        assert isinstance(config, ClientConfig)
        assert config.debug is True
        assert config.connect_timeout == 15
        assert config.max_streams == 50

    def test_server_build_flow(self, mock_path_exists: Any) -> None:
        builder = ConfigBuilder(config_type="server")
        config = (
            builder.bind("0.0.0.0", 8000)
            .performance(max_connections=500, max_streams=25)
            .security(certfile="s.pem", keyfile="s.key")
            .build()
        )
        assert isinstance(config, ServerConfig)
        assert config.bind_host == "0.0.0.0"
        assert config.max_connections == 500

    def test_builder_invalid_method_for_type(self) -> None:
        builder = ConfigBuilder(config_type="client")
        with pytest.raises(ConfigurationError, match="bind\\(\\) can only be used with server config"):
            builder.bind("localhost", 8080)

    def test_builder_unknown_type(self) -> None:
        builder = ConfigBuilder(config_type="unknown")
        with pytest.raises(ConfigurationError, match="Unknown config type: unknown"):
            builder.build()
