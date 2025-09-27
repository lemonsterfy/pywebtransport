"""Unit tests for the pywebtransport.config module."""

import ssl
from typing import Any

import pytest
from pytest_mock import MockerFixture

from pywebtransport import CertificateError, ClientConfig, ConfigurationError, ServerConfig
from pywebtransport import __version__ as real_version
from pywebtransport.config import ConfigBuilder, ProxyConfig, _validate_port, _validate_timeout
from pywebtransport.constants import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_FLOW_CONTROL_WINDOW_SIZE,
    DEFAULT_INITIAL_MAX_DATA,
    DEFAULT_READ_TIMEOUT,
    DEFAULT_RPC_CONCURRENCY_LIMIT,
    DEFAULT_SERVER_MAX_CONNECTIONS,
)


@pytest.fixture
def mock_path_exists(mocker: MockerFixture) -> Any:
    return mocker.patch("pywebtransport.config.Path.exists", return_value=True)


class TestProxyConfig:
    def test_initialization(self) -> None:
        proxy = ProxyConfig(url="http://proxy.example.com:8080", connect_timeout=5.0)
        assert proxy.url == "http://proxy.example.com:8080"
        assert proxy.headers == {}
        assert proxy.connect_timeout == 5.0


class TestClientConfig:
    def test_default_initialization(self) -> None:
        config = ClientConfig()

        assert config.connect_timeout == DEFAULT_CONNECT_TIMEOUT
        assert config.verify_mode == ssl.CERT_REQUIRED
        assert config.user_agent == f"pywebtransport/{real_version}"
        assert config.headers["user-agent"] == f"pywebtransport/{real_version}"
        assert config.congestion_control_algorithm == "cubic"
        assert config.auto_reconnect is False
        assert config.flow_control_window_size == DEFAULT_FLOW_CONTROL_WINDOW_SIZE
        assert config.initial_max_data == DEFAULT_INITIAL_MAX_DATA
        assert config.proxy is None
        assert config.rpc_concurrency_limit == DEFAULT_RPC_CONCURRENCY_LIMIT

    def test_initialization_with_proxy(self) -> None:
        proxy = ProxyConfig(url="http://proxy.com")
        config = ClientConfig(proxy=proxy)
        assert config.proxy is proxy

    def test_post_init_preserves_user_agent(self) -> None:
        config = ClientConfig(headers={"user-agent": "custom-agent/1.0"})

        assert config.user_agent == f"pywebtransport/{real_version}"
        assert config.headers["user-agent"] == "custom-agent/1.0"

    def test_post_init_normalizes_headers(self, mocker: MockerFixture) -> None:
        mock_normalize = mocker.patch("pywebtransport.config.normalize_headers", return_value={})

        ClientConfig(headers={"X-Custom": "Value"})

        mock_normalize.assert_called_once_with(headers={"X-Custom": "Value"})

    def test_create_factory_method(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "pywebtransport.config.Defaults.get_client_config",
            return_value={"max_retries": 1},
        )

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
        proxy = ProxyConfig(url="http://proxy.com")
        config1 = ClientConfig(proxy=proxy)

        config2 = config1.copy()
        config2.max_retries = 99
        assert config2.proxy is not None
        config2.proxy.url = "http://new-proxy.com"

        assert config1 is not config2
        assert config1.max_retries != 99
        assert config1.proxy is not config2.proxy
        assert config1.proxy is not None
        assert config1.proxy.url == "http://proxy.com"

    def test_update_method(self) -> None:
        config = ClientConfig()
        proxy = ProxyConfig(url="http://proxy.com")

        new_config = config.update(connect_timeout=15.0, auto_reconnect=True, proxy=proxy)

        assert new_config.connect_timeout == 15.0
        assert new_config.auto_reconnect is True
        assert new_config.proxy is proxy
        assert config.connect_timeout == DEFAULT_CONNECT_TIMEOUT
        assert config.auto_reconnect is False
        assert config.proxy is None
        assert new_config is not config
        with pytest.raises(ConfigurationError, match="unknown configuration key"):
            config.update(unknown_key="value")

    def test_merge_method(self, mocker: MockerFixture) -> None:
        config1 = ClientConfig(read_timeout=10, max_retries=1)
        mocker.patch.object(ClientConfig, "validate", return_value=None)
        invalid_max_retries: Any = None
        config2 = ClientConfig(read_timeout=20, write_timeout=25, max_retries=invalid_max_retries)
        mocker.stopall()

        merged_config = config1.merge(other=config2)
        merged_from_dict = config1.merge(other={"write_timeout": 35})

        assert merged_config.read_timeout == 20
        assert merged_config.write_timeout == 25
        assert merged_config.max_retries == 1
        assert merged_from_dict.read_timeout == 10
        assert merged_from_dict.write_timeout == 35
        with pytest.raises(TypeError):
            invalid_value: Any = 123
            config1.merge(other=invalid_value)

    def test_to_dict_method(self) -> None:
        proxy = ProxyConfig(url="http://proxy.com")
        config = ClientConfig(verify_mode=ssl.CERT_OPTIONAL, debug=True, auto_reconnect=True, proxy=proxy)

        data = config.to_dict()

        assert data["verify_mode"] == "CERT_OPTIONAL"
        assert data["debug"] is True
        assert data["auto_reconnect"] is True
        assert data["proxy"] is proxy

    @pytest.mark.parametrize(
        "invalid_attrs, error_match",
        [
            ({"alpn_protocols": []}, "cannot be empty"),
            ({"certfile": "a.pem", "keyfile": None}, "both must be provided together"),
            ({"congestion_control_algorithm": "invalid_algo"}, "must be one of"),
            ({"connect_timeout": -1}, "invalid timeout value"),
            ({"connection_idle_timeout": 0}, "invalid timeout value"),
            ({"flow_control_window_size": 0}, "must be positive"),
            ({"max_connections": 0}, "must be positive"),
            ({"max_datagram_size": 0}, "must be 1-65535"),
            ({"max_datagram_size": 65536}, "must be 1-65535"),
            ({"max_incoming_streams": -1}, "must be positive"),
            ({"max_pending_events_per_session": 0}, "must be positive"),
            ({"max_stream_buffer_size": 100, "stream_buffer_size": 200}, "must be >= stream_buffer_size"),
            ({"max_streams": 0}, "must be positive"),
            ({"max_total_pending_events": 0}, "must be positive"),
            ({"pending_event_ttl": 0}, "invalid timeout value"),
            ({"rpc_concurrency_limit": 0}, "must be positive"),
            ({"stream_buffer_size": -10}, "must be positive"),
            ({"stream_flow_control_increment_bidi": 0}, "must be positive"),
            ({"stream_flow_control_increment_uni": 0}, "must be positive"),
            ({"verify_mode": "INVALID"}, "invalid SSL verify mode"),
        ],
    )
    def test_validation_failures(self, invalid_attrs: dict[str, Any], error_match: str, mock_path_exists: Any) -> None:
        base_config = ClientConfig.create().to_dict()
        test_config = {**base_config, **invalid_attrs}

        with pytest.raises(ConfigurationError, match=error_match):
            ClientConfig(**test_config)

    def test_validation_failure_with_proxy(self) -> None:
        with pytest.raises(ConfigurationError, match="proxy.connect_timeout.*invalid timeout value"):
            ClientConfig(proxy=ProxyConfig(url="http://p.com", connect_timeout=-5))

    @pytest.mark.parametrize(
        "invalid_attrs, error_match",
        [
            ({"max_retries": -1}, "must be non-negative"),
            ({"max_retry_delay": -10.0}, "must be positive"),
            ({"retry_backoff": 0.9}, "must be >= 1.0"),
            ({"retry_delay": 0}, "must be positive"),
        ],
    )
    def test_validation_failures_retry_logic(self, invalid_attrs: dict[str, Any], error_match: str) -> None:
        base_config = ClientConfig.create().to_dict()
        test_config = {**base_config, **invalid_attrs}

        with pytest.raises(ConfigurationError, match=error_match):
            ClientConfig(**test_config)

    def test_validation_certfile_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.config.Path.exists", return_value=False)

        with pytest.raises(CertificateError, match="not found"):
            ClientConfig(certfile="cert.pem", keyfile="key.pem")

    def test_validation_keyfile_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.config.Path.exists", side_effect=[True, False])

        with pytest.raises(CertificateError, match="not found"):
            ClientConfig(certfile="cert.pem", keyfile="key.pem")

    def test_validation_cacerts_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.config.Path.exists", return_value=False)

        with pytest.raises(CertificateError, match="not found"):
            ClientConfig(ca_certs="ca.pem")


class TestServerConfig:
    def test_default_initialization(self) -> None:
        config = ServerConfig()

        assert config.bind_host == "localhost"
        assert config.max_connections == DEFAULT_SERVER_MAX_CONNECTIONS
        assert config.congestion_control_algorithm == "cubic"
        assert config.flow_control_window_size == DEFAULT_FLOW_CONTROL_WINDOW_SIZE
        assert config.initial_max_data == DEFAULT_INITIAL_MAX_DATA
        assert config.rpc_concurrency_limit == DEFAULT_RPC_CONCURRENCY_LIMIT

    def test_create_factory_method(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "pywebtransport.config.Defaults.get_server_config",
            return_value={"max_sessions": 1},
        )

        config = ServerConfig.create(max_sessions=100, debug=True)

        assert config.max_sessions == 100
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

    def test_create_for_development_factory_one_cert(self, mock_path_exists: Any) -> None:
        config = ServerConfig.create_for_development(certfile="c.pem")

        assert config.certfile == ""
        assert config.keyfile == ""

    def test_create_for_production_factory(self, mock_path_exists: Any) -> None:
        config = ServerConfig.create_for_production(
            host="prodhost",
            port=443,
            certfile="c.pem",
            keyfile="k.pem",
            ca_certs="ca.pem",
        )

        assert config.debug is False
        assert config.bind_host == "prodhost"
        assert config.bind_port == 443
        assert config.certfile == "c.pem"
        assert config.verify_mode == ssl.CERT_OPTIONAL

    def test_get_bind_address(self) -> None:
        config = ServerConfig(bind_host="127.0.0.1", bind_port=8888)

        result = config.get_bind_address()

        assert result == ("127.0.0.1", 8888)

    def test_merge_method(self, mocker: MockerFixture) -> None:
        config1 = ServerConfig(max_connections=100, max_sessions=50)
        mocker.patch.object(ServerConfig, "validate", return_value=None)
        invalid_max_sessions: Any = None
        config2 = ServerConfig(max_connections=200, max_sessions=invalid_max_sessions)
        mocker.stopall()

        merged = config1.merge(other=config2)

        assert merged.max_connections == 200
        assert merged.max_sessions == 50
        with pytest.raises(TypeError):
            invalid_value: Any = 123
            config1.merge(other=invalid_value)

    def test_to_dict_method(self) -> None:
        config = ServerConfig(verify_mode=ssl.CERT_REQUIRED, debug=False)

        data = config.to_dict()

        assert data["verify_mode"] == "CERT_REQUIRED"
        assert data["debug"] is False

    def test_update_method(self) -> None:
        config = ServerConfig()

        with pytest.raises(ConfigurationError, match="unknown configuration key"):
            config.update(unknown_key="value")

    @pytest.mark.parametrize(
        "invalid_attrs, error_match",
        [
            ({"alpn_protocols": []}, "cannot be empty"),
            ({"bind_host": ""}, "cannot be empty"),
            ({"bind_port": 0}, "Port must be an integer"),
            ({"certfile": "a.pem", "keyfile": ""}, "certfile and keyfile must be provided together"),
            ({"congestion_control_algorithm": "invalid_algo"}, "must be one of"),
            ({"connection_keepalive_timeout": 0}, "invalid timeout value"),
            ({"flow_control_window_size": 0}, "must be positive"),
            ({"max_connections": 0}, "must be positive"),
            ({"max_datagram_size": 0}, "must be 1-65535"),
            ({"max_datagram_size": 65536}, "must be 1-65535"),
            ({"max_incoming_streams": 0}, "must be positive"),
            ({"max_pending_events_per_session": 0}, "must be positive"),
            ({"max_sessions": 0}, "must be positive"),
            ({"max_stream_buffer_size": 100, "stream_buffer_size": 200}, "must be >= stream_buffer_size"),
            ({"max_streams_per_connection": 0}, "must be positive"),
            ({"max_total_pending_events": 0}, "must be positive"),
            ({"pending_event_ttl": -1.0}, "invalid timeout value"),
            ({"rpc_concurrency_limit": 0}, "must be positive"),
            ({"stream_buffer_size": 0}, "must be positive"),
            ({"stream_flow_control_increment_bidi": 0}, "must be positive"),
            ({"stream_flow_control_increment_uni": 0}, "must be positive"),
            ({"verify_mode": "INVALID"}, "invalid SSL verify mode"),
        ],
    )
    def test_validation_failures(self, invalid_attrs: dict[str, Any], error_match: str, mock_path_exists: Any) -> None:
        base_config = ServerConfig.create().to_dict()
        base_config.pop("backlog", None)
        test_config = {**base_config, **invalid_attrs}

        with pytest.raises(ConfigurationError, match=error_match):
            ServerConfig(**test_config)

    def test_validation_certfile_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.config.Path.exists", return_value=False)

        with pytest.raises(CertificateError, match="not found"):
            ServerConfig(certfile="cert.pem", keyfile="key.pem")

    def test_validation_keyfile_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.config.Path.exists", side_effect=[True, False])

        with pytest.raises(CertificateError, match="not found"):
            ServerConfig(certfile="cert.pem", keyfile="key.pem")

    def test_validation_cacerts_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.config.Path.exists", return_value=False)

        with pytest.raises(CertificateError, match="not found"):
            ServerConfig(certfile="cert.pem", keyfile="key.pem", ca_certs="ca.pem")


class TestConfigBuilder:
    def test_client_build_flow(self, mock_path_exists: Any) -> None:
        builder = ConfigBuilder(config_type="client")

        config = (
            builder.debug(enabled=True, log_level="INFO")
            .timeout(connect=15, read=45, write=30)
            .security(
                certfile="c.pem",
                keyfile="k.pem",
                ca_certs="ca.pem",
                verify_mode=ssl.CERT_OPTIONAL,
            )
            .performance(max_streams=50, buffer_size=12345)
            .build()
        )

        assert isinstance(config, ClientConfig)
        assert config.debug is True
        assert config.connect_timeout == 15
        assert config.read_timeout == 45
        assert config.write_timeout == 30
        assert config.max_streams == 50
        assert config.ca_certs == "ca.pem"
        assert config.verify_mode == ssl.CERT_OPTIONAL

    def test_server_build_flow(self, mock_path_exists: Any) -> None:
        builder = ConfigBuilder(config_type="server")

        config = (
            builder.bind(host="0.0.0.0", port=8000)
            .performance(max_connections=500, max_streams=25)
            .security(certfile="s.pem", keyfile="s.key")
            .build()
        )

        assert isinstance(config, ServerConfig)
        assert config.bind_host == "0.0.0.0"
        assert config.max_connections == 500

    def test_builder_with_flow_control(self) -> None:
        builder = ConfigBuilder(config_type="client")

        config = builder.flow_control(
            window_size=2048,
            initial_max_data=1024,
            stream_increment_bidi=5,
            window_auto_scale=False,
        ).build()

        assert isinstance(config, ClientConfig)
        assert config.flow_control_window_size == 2048
        assert config.initial_max_data == 1024
        assert config.stream_flow_control_increment_bidi == 5
        assert config.flow_control_window_auto_scale is False

    def test_builder_with_partial_params(self, mock_path_exists: Any) -> None:
        builder = ConfigBuilder()
        config = builder.timeout(connect=10).security(certfile="cert.pem", keyfile="key.pem").build()

        assert isinstance(config, ClientConfig)
        assert config.connect_timeout == 10.0
        assert config.read_timeout == DEFAULT_READ_TIMEOUT
        assert config.certfile == "cert.pem"
        assert config.keyfile == "key.pem"

    def test_builder_invalid_method_for_type(self) -> None:
        builder = ConfigBuilder(config_type="client")

        with pytest.raises(ConfigurationError, match="bind\\(\\) can only be used with server config"):
            builder.bind(host="localhost", port=8080)

    def test_client_builder_ignores_server_options(self) -> None:
        builder = ConfigBuilder(config_type="client")

        builder.performance(max_connections=999)

        assert "max_connections" not in builder._config_dict

    def test_builder_unknown_type(self) -> None:
        builder = ConfigBuilder(config_type="unknown")

        with pytest.raises(ConfigurationError, match="Unknown config type: unknown"):
            builder.build()


class TestConfigHelpers:
    @pytest.mark.parametrize("value", [5, 10.5, None])
    def test_validate_timeout_valid(self, value: Any) -> None:
        _validate_timeout(timeout=value)

    @pytest.mark.parametrize("value", [0, -1, -10.5])
    def test_validate_timeout_invalid_value(self, value: Any) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            _validate_timeout(timeout=value)

    def test_validate_timeout_invalid_type(self) -> None:
        invalid_value: Any = "abc"

        with pytest.raises(TypeError, match="must be a number or None"):
            _validate_timeout(timeout=invalid_value)

    @pytest.mark.parametrize("value", [1, 80, 4433, 65535])
    def test_validate_port_valid(self, value: int) -> None:
        _validate_port(port=value)

    @pytest.mark.parametrize("value", [0, 65536, -1, "80", 80.5])
    def test_validate_port_invalid(self, value: Any) -> None:
        with pytest.raises(ValueError, match="Port must be an integer between 1 and 65535"):
            _validate_port(port=value)
