"""Unit tests for the pywebtransport.config module."""

import ssl
from typing import Any

import pytest

from pywebtransport import ClientConfig, ConfigurationError, ServerConfig, __version__
from pywebtransport.constants import (
    DEFAULT_ALPN_PROTOCOLS,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_FLOW_CONTROL_WINDOW_SIZE,
    DEFAULT_INITIAL_MAX_DATA,
    DEFAULT_SERVER_MAX_CONNECTIONS,
)


class TestClientConfig:

    def test_copy_method(self) -> None:
        config1 = ClientConfig(alpn_protocols=["h3"])
        config2 = config1.copy()

        config2.max_connection_retries = 99
        config2.alpn_protocols.append("h2")

        assert config1 is not config2
        assert config1.max_connection_retries != 99
        assert config1.alpn_protocols == ["h3"]
        assert config2.alpn_protocols == ["h3", "h2"]

    def test_default_initialization(self) -> None:
        config = ClientConfig()

        assert config.connect_timeout == DEFAULT_CONNECT_TIMEOUT
        assert config.verify_mode == ssl.CERT_REQUIRED
        assert config.user_agent == f"PyWebTransport/{__version__}"
        if isinstance(config.headers, dict):
            assert config.headers["user-agent"] == f"PyWebTransport/{__version__}"
        assert config.congestion_control_algorithm == "cubic"
        assert config.flow_control_window_size == DEFAULT_FLOW_CONTROL_WINDOW_SIZE
        assert config.initial_max_data == DEFAULT_INITIAL_MAX_DATA
        assert config.alpn_protocols == list(DEFAULT_ALPN_PROTOCOLS)

    def test_from_dict_method(self) -> None:
        config_dict = {"max_connection_retries": 5, "unknown_field": "should_be_ignored"}

        config = ClientConfig.from_dict(config_dict=config_dict)

        assert config.max_connection_retries == 5
        assert not hasattr(config, "unknown_field")

    def test_initialization_with_none_timeout(self) -> None:
        config = ClientConfig(read_timeout=None)

        assert config.read_timeout is None

    def test_post_init_normalizes_headers_dict(self) -> None:
        config = ClientConfig(headers={"X-Custom": "Value"})

        assert isinstance(config.headers, dict)
        assert config.headers["x-custom"] == "Value"

    def test_post_init_normalizes_headers_list(self) -> None:
        config = ClientConfig(headers=[("X-Custom", "Value")])

        assert isinstance(config.headers, list)
        assert ("x-custom", "Value") in config.headers
        assert ("user-agent", f"PyWebTransport/{__version__}") in config.headers

    def test_post_init_preserves_user_agent_dict(self) -> None:
        config = ClientConfig(headers={"user-agent": "custom-agent/1.0"})

        assert config.user_agent == f"PyWebTransport/{__version__}"
        assert isinstance(config.headers, dict)
        assert config.headers["user-agent"] == "custom-agent/1.0"

    def test_post_init_preserves_user_agent_list(self) -> None:
        config = ClientConfig(headers=[("user-agent", "custom-agent/1.0")])

        assert isinstance(config.headers, list)
        assert ("user-agent", "custom-agent/1.0") in config.headers
        assert len(config.headers) == 1

    def test_to_dict_method(self) -> None:
        config = ClientConfig(verify_mode=ssl.CERT_OPTIONAL)

        data = config.to_dict()

        assert data["verify_mode"] == "CERT_OPTIONAL"

    def test_update_method(self) -> None:
        config = ClientConfig()

        new_config = config.update(connect_timeout=15.0)

        assert new_config.connect_timeout == 15.0
        assert config.connect_timeout == DEFAULT_CONNECT_TIMEOUT
        assert new_config is not config

        with pytest.raises(ConfigurationError, match="Unknown configuration key"):
            config.update(unknown_key="value")

    @pytest.mark.parametrize(
        "invalid_attrs, error_match",
        [
            ({"alpn_protocols": []}, "cannot be empty"),
            ({"certfile": "a.pem", "keyfile": None}, "must be provided together"),
            ({"congestion_control_algorithm": "invalid_algo"}, "must be one of"),
            ({"connect_timeout": -1}, "Timeout must be positive"),
            ({"connect_timeout": "invalid"}, "Timeout must be a number"),
            ({"connection_idle_timeout": 0}, "Timeout must be positive"),
            ({"flow_control_window_size": 0}, "must be positive"),
            ({"max_connections": 0}, "must be positive"),
            ({"max_datagram_size": 0}, "must be between 1 and 65535"),
            ({"max_datagram_size": 65536}, "must be between 1 and 65535"),
            ({"max_event_history_size": -1}, "must be non-negative"),
            ({"max_event_listeners": 0}, "must be positive"),
            ({"max_event_queue_size": 0}, "must be positive"),
            ({"max_message_size": 0}, "must be positive"),
            ({"max_pending_events_per_session": 0}, "must be positive"),
            ({"max_sessions": 0}, "must be positive"),
            ({"max_stream_read_buffer": 0}, "must be positive"),
            ({"max_stream_write_buffer": 0}, "must be positive"),
            ({"max_total_pending_events": 0}, "must be positive"),
            ({"pending_event_ttl": 0}, "Timeout must be positive"),
            ({"stream_flow_control_increment_bidi": 0}, "must be positive"),
            ({"stream_flow_control_increment_uni": 0}, "must be positive"),
            ({"verify_mode": "INVALID"}, "unknown SSL verify mode"),
        ],
    )
    def test_validation_failures(self, invalid_attrs: dict[str, Any], error_match: str) -> None:
        base_config = ClientConfig().to_dict()
        base_config["verify_mode"] = ssl.CERT_REQUIRED
        test_config = {**base_config, **invalid_attrs}

        with pytest.raises(ConfigurationError, match=error_match):
            ClientConfig(**test_config)

    @pytest.mark.parametrize(
        "invalid_attrs, error_match",
        [
            ({"max_connection_retries": -1}, "must be non-negative"),
            ({"max_retry_delay": -10.0}, "must be positive"),
            ({"retry_backoff": 0.9}, "must be >= 1.0"),
            ({"retry_delay": 0}, "must be positive"),
        ],
    )
    def test_validation_failures_retry_logic(self, invalid_attrs: dict[str, Any], error_match: str) -> None:
        base_config = ClientConfig().to_dict()
        base_config["verify_mode"] = ssl.CERT_REQUIRED
        test_config = {**base_config, **invalid_attrs}

        with pytest.raises(ConfigurationError, match=error_match):
            ClientConfig(**test_config)


class TestServerConfig:

    def test_default_initialization(self) -> None:
        config = ServerConfig(certfile="dummy.crt", keyfile="dummy.key")

        assert config.bind_host == "localhost"
        assert config.max_connections == DEFAULT_SERVER_MAX_CONNECTIONS
        assert config.congestion_control_algorithm == "cubic"
        assert config.flow_control_window_size == DEFAULT_FLOW_CONTROL_WINDOW_SIZE
        assert config.initial_max_data == DEFAULT_INITIAL_MAX_DATA
        assert config.alpn_protocols == list(DEFAULT_ALPN_PROTOCOLS)

    def test_from_dict_coercion(self) -> None:
        config_dict = {"bind_port": "8080", "certfile": "dummy.crt", "keyfile": "dummy.key"}

        config = ServerConfig.from_dict(config_dict=config_dict)

        assert config.bind_port == 8080

    def test_from_dict_invalid_port_raises_error(self) -> None:
        config_dict = {"bind_port": "invalid", "certfile": "dummy.crt", "keyfile": "dummy.key"}

        with pytest.raises(ConfigurationError, match="Port must be an integer"):
            ServerConfig.from_dict(config_dict=config_dict)

    def test_from_dict_filtering_extra_keys(self) -> None:
        config_dict = {
            "max_connections": 500,
            "unknown_field": "should_be_ignored",
            "certfile": "dummy.crt",
            "keyfile": "dummy.key",
        }

        config = ServerConfig.from_dict(config_dict=config_dict)

        assert config.max_connections == 500
        assert not hasattr(config, "unknown_field")

    def test_initialization_fails_without_bind_host(self) -> None:
        with pytest.raises(ConfigurationError, match="cannot be empty"):
            ServerConfig(bind_host="", certfile="c", keyfile="k")

    def test_initialization_fails_without_certs(self) -> None:
        with pytest.raises(ConfigurationError, match="Server requires both certificate and key files"):
            ServerConfig(certfile="", keyfile="")

    def test_to_dict_method(self) -> None:
        config = ServerConfig(verify_mode=ssl.CERT_REQUIRED, certfile="d.crt", keyfile="d.key")

        data = config.to_dict()

        assert data["verify_mode"] == "CERT_REQUIRED"

    def test_update_method_failure(self) -> None:
        config = ServerConfig(certfile="d.crt", keyfile="d.key")

        with pytest.raises(ConfigurationError, match="Unknown configuration key"):
            config.update(unknown_key="value")

    def test_update_method_success(self) -> None:
        config = ServerConfig(certfile="d.crt", keyfile="d.key")

        new_config = config.update(max_connections=500)

        assert new_config.max_connections == 500
        assert config.max_connections == DEFAULT_SERVER_MAX_CONNECTIONS
        assert new_config is not config

    @pytest.mark.parametrize(
        "invalid_attrs, error_match",
        [
            ({"alpn_protocols": []}, "cannot be empty"),
            ({"bind_host": ""}, "cannot be empty"),
            ({"bind_port": 0}, "must be an integer"),
            ({"bind_port": "invalid"}, "must be an integer"),
            ({"congestion_control_algorithm": "invalid_algo"}, "must be one of"),
            ({"flow_control_window_size": 0}, "must be positive"),
            ({"max_connections": 0}, "must be positive"),
            ({"max_datagram_size": 0}, "must be between 1 and 65535"),
            ({"max_datagram_size": 65536}, "must be between 1 and 65535"),
            ({"max_event_history_size": -1}, "must be non-negative"),
            ({"max_event_listeners": 0}, "must be positive"),
            ({"max_event_queue_size": 0}, "must be positive"),
            ({"max_message_size": 0}, "must be positive"),
            ({"max_pending_events_per_session": 0}, "must be positive"),
            ({"max_sessions": 0}, "must be positive"),
            ({"max_stream_read_buffer": 0}, "must be positive"),
            ({"max_stream_write_buffer": 0}, "must be positive"),
            ({"max_total_pending_events": 0}, "must be positive"),
            ({"pending_event_ttl": -1.0}, "Timeout must be positive"),
            ({"read_timeout": "invalid"}, "Timeout must be a number"),
            ({"stream_flow_control_increment_bidi": 0}, "must be positive"),
            ({"stream_flow_control_increment_uni": 0}, "must be positive"),
            ({"verify_mode": "INVALID"}, "unknown SSL verify mode"),
        ],
    )
    def test_validation_failures(self, invalid_attrs: dict[str, Any], error_match: str) -> None:
        base_config = ServerConfig(certfile="dummy.crt", keyfile="dummy.key").to_dict()
        base_config["verify_mode"] = ssl.CERT_NONE
        test_config = {**base_config, **invalid_attrs}

        with pytest.raises(ConfigurationError, match=error_match):
            ServerConfig(**test_config)
