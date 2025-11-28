"""Unit tests for the pywebtransport.config module."""

import ssl
from typing import Any

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig, ConfigurationError, ServerConfig, __version__
from pywebtransport.constants import (
    DEFAULT_ALPN_PROTOCOLS,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_FLOW_CONTROL_WINDOW_SIZE,
    DEFAULT_INITIAL_MAX_DATA,
    DEFAULT_RPC_CONCURRENCY_LIMIT,
    DEFAULT_SERVER_MAX_CONNECTIONS,
    get_default_server_config,
)
from pywebtransport.exceptions import CertificateError


@pytest.fixture
def mock_path_exists(mocker: MockerFixture) -> Any:
    return mocker.patch("pywebtransport.config.Path.exists", return_value=True)


class TestClientConfig:

    def test_copy_method(self) -> None:
        config1 = ClientConfig(alpn_protocols=["h3"])
        config2 = config1.copy()

        config2.max_retries = 99
        config2.alpn_protocols.append("h2")

        assert config1 is not config2
        assert config1.max_retries != 99
        assert config1.alpn_protocols == ["h3"]
        assert config2.alpn_protocols == ["h3", "h2"]

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

    def test_default_initialization(self) -> None:
        config = ClientConfig()

        assert config.connect_timeout == DEFAULT_CONNECT_TIMEOUT
        assert config.verify_mode == ssl.CERT_REQUIRED
        assert config.user_agent == f"pywebtransport/{__version__}"
        assert config.headers["user-agent"] == f"pywebtransport/{__version__}"
        assert config.congestion_control_algorithm == "cubic"
        assert config.auto_reconnect is False
        assert config.flow_control_window_size == DEFAULT_FLOW_CONTROL_WINDOW_SIZE
        assert config.initial_max_data == DEFAULT_INITIAL_MAX_DATA
        assert config.rpc_concurrency_limit == DEFAULT_RPC_CONCURRENCY_LIMIT
        assert config.alpn_protocols == list(DEFAULT_ALPN_PROTOCOLS)

    def test_from_dict_method(self) -> None:
        config_dict = {"max_retries": 5, "unknown_field": "should_be_ignored", "debug": True}

        config = ClientConfig.from_dict(config_dict=config_dict)

        assert config.max_retries == 5
        assert config.debug is True
        assert not hasattr(config, "unknown_field")

    def test_initialization_with_none_timeout(self) -> None:
        config = ClientConfig(read_timeout=None)

        assert config.read_timeout is None

    def test_post_init_normalizes_headers(self, mocker: MockerFixture) -> None:
        mock_normalize = mocker.patch("pywebtransport.config._normalize_headers", return_value={})

        ClientConfig(headers={"X-Custom": "Value"})

        mock_normalize.assert_called_once_with(headers={"X-Custom": "Value"})

    def test_post_init_preserves_user_agent(self) -> None:
        config = ClientConfig(headers={"user-agent": "custom-agent/1.0"})

        assert config.user_agent == f"pywebtransport/{__version__}"
        assert config.headers["user-agent"] == "custom-agent/1.0"

    def test_to_dict_method(self) -> None:
        config = ClientConfig(auto_reconnect=True, debug=True, verify_mode=ssl.CERT_OPTIONAL)

        data = config.to_dict()

        assert data["verify_mode"] == "CERT_OPTIONAL"
        assert data["debug"] is True
        assert data["auto_reconnect"] is True

    def test_update_method(self) -> None:
        config = ClientConfig()

        new_config = config.update(auto_reconnect=True, connect_timeout=15.0)

        assert new_config.connect_timeout == 15.0
        assert new_config.auto_reconnect is True
        assert config.connect_timeout == DEFAULT_CONNECT_TIMEOUT
        assert config.auto_reconnect is False
        assert new_config is not config

        with pytest.raises(ConfigurationError, match="unknown configuration key"):
            config.update(unknown_key="value")

    def test_validation_cacerts_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.config.Path.exists", return_value=False)

        with pytest.raises(CertificateError, match="not found"):
            ClientConfig(ca_certs="ca.pem")

    def test_validation_certfile_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.config.Path.exists", return_value=False)

        with pytest.raises(CertificateError, match="not found"):
            ClientConfig(certfile="cert.pem", keyfile="key.pem")

    @pytest.mark.parametrize(
        "invalid_attrs, error_match",
        [
            ({"alpn_protocols": []}, "cannot be empty"),
            ({"certfile": "a.pem", "keyfile": None}, "both must be provided together"),
            ({"congestion_control_algorithm": "invalid_algo"}, "must be one of"),
            ({"connect_timeout": -1}, "Timeout must be positive"),
            ({"connect_timeout": "invalid"}, "Timeout must be a number"),
            ({"connection_idle_timeout": 0}, "Timeout must be positive"),
            ({"flow_control_window_size": 0}, "must be positive"),
            ({"max_connections": 0}, "must be positive"),
            ({"max_datagram_size": 0}, "must be 1-65535"),
            ({"max_datagram_size": 65536}, "must be 1-65535"),
            ({"max_message_size": 0}, "must be positive"),
            ({"max_pending_events_per_session": 0}, "must be positive"),
            ({"max_sessions": 0}, "must be positive"),
            ({"max_stream_read_buffer": 0}, "must be positive"),
            ({"max_stream_write_buffer": 0}, "must be positive"),
            ({"max_total_pending_events": 0}, "must be positive"),
            ({"pending_event_ttl": 0}, "Timeout must be positive"),
            ({"pubsub_subscription_queue_size": 0}, "must be positive"),
            ({"rpc_concurrency_limit": 0}, "must be positive"),
            ({"stream_flow_control_increment_bidi": 0}, "must be positive"),
            ({"stream_flow_control_increment_uni": 0}, "must be positive"),
            ({"verify_mode": "INVALID"}, "invalid SSL verify mode"),
        ],
    )
    def test_validation_failures(self, invalid_attrs: dict[str, Any], error_match: str, mock_path_exists: Any) -> None:
        base_config = ClientConfig().to_dict()
        base_config["verify_mode"] = ClientConfig().verify_mode
        test_config = {**base_config, **invalid_attrs}

        with pytest.raises(ConfigurationError, match=error_match):
            ClientConfig(**test_config)

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
        base_config = ClientConfig().to_dict()
        base_config["verify_mode"] = ClientConfig().verify_mode
        test_config = {**base_config, **invalid_attrs}

        with pytest.raises(ConfigurationError, match=error_match):
            ClientConfig(**test_config)

    def test_validation_keyfile_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.config.Path.exists", side_effect=[True, False])

        with pytest.raises(CertificateError, match="not found"):
            ClientConfig(certfile="cert.pem", keyfile="key.pem")


class TestServerConfig:

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

    def test_create_for_development_factory_with_existing_defaults(
        self, mocker: MockerFixture, mock_path_exists: Any
    ) -> None:
        default_conf = get_default_server_config()
        default_conf["certfile"] = "default_cert.pem"
        default_conf["keyfile"] = "default_key.pem"
        mocker.patch("pywebtransport.config.get_default_server_config", return_value=default_conf)

        config = ServerConfig.create_for_development()

        assert config.certfile == "default_cert.pem"
        assert config.keyfile == "default_key.pem"

    def test_create_for_production_factory(self, mock_path_exists: Any) -> None:
        config = ServerConfig.create_for_production(
            host="prodhost", port=443, ca_certs="ca.pem", certfile="c.pem", keyfile="k.pem"
        )

        assert config.debug is False
        assert config.bind_host == "prodhost"
        assert config.bind_port == 443
        assert config.certfile == "c.pem"
        assert config.verify_mode == ssl.CERT_OPTIONAL

    def test_create_for_production_factory_no_ca_certs(self, mock_path_exists: Any) -> None:
        config = ServerConfig.create_for_production(host="prodhost", port=443, certfile="c.pem", keyfile="k.pem")

        assert config.verify_mode == ssl.CERT_NONE
        assert config.ca_certs is None

    def test_default_initialization(self) -> None:
        config = ServerConfig()

        assert config.bind_host == "localhost"
        assert config.max_connections == DEFAULT_SERVER_MAX_CONNECTIONS
        assert config.congestion_control_algorithm == "cubic"
        assert config.flow_control_window_size == DEFAULT_FLOW_CONTROL_WINDOW_SIZE
        assert config.initial_max_data == DEFAULT_INITIAL_MAX_DATA
        assert config.rpc_concurrency_limit == DEFAULT_RPC_CONCURRENCY_LIMIT
        assert config.alpn_protocols == list(DEFAULT_ALPN_PROTOCOLS)

    def test_from_dict_filtering_extra_keys(self) -> None:
        config_dict = {"max_connections": 500, "unknown_field": "should_be_ignored", "debug": True}

        config = ServerConfig.from_dict(config_dict=config_dict)

        assert config.max_connections == 500
        assert config.debug is True
        assert not hasattr(config, "unknown_field")

    def test_to_dict_method(self) -> None:
        config = ServerConfig(debug=False, verify_mode=ssl.CERT_REQUIRED)

        data = config.to_dict()

        assert data["verify_mode"] == "CERT_REQUIRED"
        assert data["debug"] is False

    def test_update_method_failure(self) -> None:
        config = ServerConfig()

        with pytest.raises(ConfigurationError, match="unknown configuration key"):
            config.update(unknown_key="value")

    def test_update_method_success(self) -> None:
        config = ServerConfig()

        new_config = config.update(debug=True, max_connections=500)

        assert new_config.max_connections == 500
        assert new_config.debug is True
        assert config.max_connections == DEFAULT_SERVER_MAX_CONNECTIONS
        assert config.debug is False
        assert new_config is not config

    def test_validation_cacerts_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.config.Path.exists", return_value=False)

        with pytest.raises(CertificateError, match="not found"):
            ServerConfig(ca_certs="ca.pem", certfile="cert.pem", keyfile="key.pem")

    def test_validation_certfile_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.config.Path.exists", return_value=False)

        with pytest.raises(CertificateError, match="not found"):
            ServerConfig(certfile="cert.pem", keyfile="key.pem")

    @pytest.mark.parametrize(
        "invalid_attrs, error_match",
        [
            ({"alpn_protocols": []}, "cannot be empty"),
            ({"bind_host": ""}, "cannot be empty"),
            ({"bind_port": 0}, "Port must be an integer"),
            ({"bind_port": "80"}, "Port must be an integer"),
            ({"certfile": "a.pem", "keyfile": ""}, "both must be provided together"),
            ({"congestion_control_algorithm": "invalid_algo"}, "must be one of"),
            ({"connection_keepalive_timeout": 0}, "Timeout must be positive"),
            ({"flow_control_window_size": 0}, "must be positive"),
            ({"max_connections": 0}, "must be positive"),
            ({"max_datagram_size": 0}, "must be 1-65535"),
            ({"max_datagram_size": 65536}, "must be 1-65535"),
            ({"max_message_size": 0}, "must be positive"),
            ({"max_pending_events_per_session": 0}, "must be positive"),
            ({"max_sessions": 0}, "must be positive"),
            ({"max_stream_read_buffer": 0}, "must be positive"),
            ({"max_stream_write_buffer": 0}, "must be positive"),
            ({"max_total_pending_events": 0}, "must be positive"),
            ({"pending_event_ttl": -1.0}, "Timeout must be positive"),
            ({"pubsub_subscription_queue_size": 0}, "must be positive"),
            ({"read_timeout": "invalid"}, "Timeout must be a number"),
            ({"rpc_concurrency_limit": 0}, "must be positive"),
            ({"stream_flow_control_increment_bidi": 0}, "must be positive"),
            ({"stream_flow_control_increment_uni": 0}, "must be positive"),
            ({"verify_mode": "INVALID"}, "invalid SSL verify mode"),
        ],
    )
    def test_validation_failures(self, invalid_attrs: dict[str, Any], error_match: str, mock_path_exists: Any) -> None:
        base_config = ServerConfig().to_dict()
        base_config["verify_mode"] = ServerConfig().verify_mode
        test_config = {**base_config, **invalid_attrs}

        with pytest.raises(ConfigurationError, match=error_match):
            ServerConfig(**test_config)

    def test_validation_keyfile_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.config.Path.exists", side_effect=[True, False])

        with pytest.raises(CertificateError, match="not found"):
            ServerConfig(certfile="cert.pem", keyfile="key.pem")
