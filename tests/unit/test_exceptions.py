"""Unit tests for the pywebtransport.exceptions module."""

from typing import Any, Type

import pytest

from pywebtransport import (
    AuthenticationError,
    CertificateError,
    ClientError,
    ConfigurationError,
    ConnectionError,
    DatagramError,
    FlowControlError,
    HandshakeError,
    ProtocolError,
    ServerError,
    SessionError,
    SessionState,
    StreamError,
    StreamState,
    TimeoutError,
    WebTransportError,
)
from pywebtransport.constants import ErrorCodes
from pywebtransport.exceptions import (
    certificate_not_found,
    connection_timeout,
    datagram_too_large,
    get_error_category,
    invalid_config,
    is_fatal_error,
    is_retriable_error,
    protocol_violation,
    session_not_ready,
    stream_closed,
)


class TestExceptionClasses:
    def test_webtransport_error_base(self) -> None:
        exc = WebTransportError("Base error", error_code=100, details={"info": "abc"})

        assert exc.message == "Base error"
        assert exc.error_code == 100
        assert exc.details == {"info": "abc"}
        assert str(exc) == "[0x64] Base error"
        assert repr(exc) == "WebTransportError(message='Base error', error_code=100)"
        assert exc.to_dict() == {
            "type": "WebTransportError",
            "message": "Base error",
            "error_code": 100,
            "details": {"info": "abc"},
        }

    def test_webtransport_error_defaults(self) -> None:
        exc = WebTransportError("Default error")

        assert exc.error_code == ErrorCodes.INTERNAL_ERROR
        assert exc.details == {}

    @pytest.mark.parametrize(
        "exc_class, args, expected_attrs, default_code",
        [
            (
                AuthenticationError,
                {"auth_method": "token"},
                {"auth_method": "token"},
                ErrorCodes.APP_AUTHENTICATION_FAILED,
            ),
            (
                CertificateError,
                {"certificate_path": "/c.pem", "certificate_error": "expired"},
                {"certificate_path": "/c.pem", "certificate_error": "expired"},
                ErrorCodes.APP_AUTHENTICATION_FAILED,
            ),
            (
                ClientError,
                {"target_url": "https://a.com"},
                {"target_url": "https://a.com"},
                ErrorCodes.APP_INVALID_REQUEST,
            ),
            (
                ConfigurationError,
                {"config_key": "timeout", "config_value": -1},
                {"config_key": "timeout", "config_value": -1},
                ErrorCodes.APP_INVALID_REQUEST,
            ),
            (
                ConnectionError,
                {"remote_address": ("1.1.1.1", 443)},
                {"remote_address": ("1.1.1.1", 443)},
                ErrorCodes.CONNECTION_REFUSED,
            ),
            (
                DatagramError,
                {"datagram_size": 9000, "max_size": 1500},
                {"datagram_size": 9000, "max_size": 1500},
                ErrorCodes.INTERNAL_ERROR,
            ),
            (
                FlowControlError,
                {"stream_id": 1, "limit_exceeded": 100},
                {"stream_id": 1, "limit_exceeded": 100},
                ErrorCodes.FLOW_CONTROL_ERROR,
            ),
            (HandshakeError, {"handshake_stage": "alpn"}, {"handshake_stage": "alpn"}, ErrorCodes.INTERNAL_ERROR),
            (ProtocolError, {"frame_type": 0x41}, {"frame_type": 0x41}, ErrorCodes.PROTOCOL_VIOLATION),
            (
                ServerError,
                {"bind_address": ("0.0.0.0", 4433)},
                {"bind_address": ("0.0.0.0", 4433)},
                ErrorCodes.APP_SERVICE_UNAVAILABLE,
            ),
            (
                SessionError,
                {"session_id": "abc", "session_state": SessionState.CONNECTED},
                {"session_id": "abc", "session_state": SessionState.CONNECTED},
                ErrorCodes.INTERNAL_ERROR,
            ),
            (
                StreamError,
                {"stream_id": 5, "stream_state": StreamState.OPEN},
                {"stream_id": 5, "stream_state": StreamState.OPEN},
                ErrorCodes.STREAM_STATE_ERROR,
            ),
            (
                TimeoutError,
                {"timeout_duration": 10.0, "operation": "read"},
                {"timeout_duration": 10.0, "operation": "read"},
                ErrorCodes.APP_CONNECTION_TIMEOUT,
            ),
        ],
    )
    def test_subclass_exceptions(
        self,
        exc_class: Type[WebTransportError],
        args: dict[str, Any],
        expected_attrs: dict[str, Any],
        default_code: ErrorCodes,
    ) -> None:
        exc = exc_class("Test message", **args)
        assert isinstance(exc, WebTransportError)
        for key, value in expected_attrs.items():
            assert getattr(exc, key) == value

        data = exc.to_dict()
        assert data["type"] == exc_class.__name__
        for key, value in expected_attrs.items():
            serialized_value = value.value if hasattr(value, "value") else value
            assert data[key] == serialized_value

        exc_default = exc_class("Default code")
        assert exc_default.error_code == default_code

    def test_stream_error_custom_str(self) -> None:
        exc_no_id = StreamError("No ID")
        assert str(exc_no_id) == f"[{hex(exc_no_id.error_code)}] No ID"

        exc_with_id = StreamError("With ID", stream_id=5)
        assert str(exc_with_id) == f"[{hex(exc_with_id.error_code)}] With ID (stream_id=5)"


class TestExceptionFactories:
    def test_certificate_not_found(self) -> None:
        exc = certificate_not_found("/path/to/cert.pem")

        assert isinstance(exc, CertificateError)
        assert exc.certificate_path == "/path/to/cert.pem"
        assert exc.certificate_error == "file_not_found"
        assert "/path/to/cert.pem" in exc.message

    def test_connection_timeout(self) -> None:
        exc = connection_timeout(15.5, operation="handshake")

        assert isinstance(exc, TimeoutError)
        assert exc.timeout_duration == 15.5
        assert exc.operation == "handshake"
        assert "15.5s" in exc.message

    def test_datagram_too_large(self) -> None:
        exc = datagram_too_large(9000, 1500)

        assert isinstance(exc, DatagramError)
        assert exc.datagram_size == 9000
        assert exc.max_size == 1500
        assert "9000" in exc.message and "1500" in exc.message

    def test_invalid_config(self) -> None:
        exc = invalid_config("retries", -1, "must be non-negative")

        assert isinstance(exc, ConfigurationError)
        assert exc.config_key == "retries"
        assert exc.config_value == -1
        assert "retries" in exc.message and "must be non-negative" in exc.message

    def test_protocol_violation(self) -> None:
        exc = protocol_violation("Invalid frame", frame_type=0xFF)

        assert isinstance(exc, ProtocolError)
        assert exc.frame_type == 0xFF
        assert exc.error_code == ErrorCodes.PROTOCOL_VIOLATION
        assert exc.message == "Invalid frame"

    def test_session_not_ready(self) -> None:
        exc = session_not_ready("sess_123", SessionState.CONNECTING)

        assert isinstance(exc, SessionError)
        assert exc.session_id == "sess_123"
        assert exc.session_state == SessionState.CONNECTING
        assert "sess_123" in exc.message and "connecting" in exc.message

    def test_stream_closed(self) -> None:
        exc = stream_closed(5, reason="shutdown")

        assert isinstance(exc, StreamError)
        assert exc.stream_id == 5
        assert exc.error_code == ErrorCodes.STREAM_STATE_ERROR
        assert "Stream 5" in exc.message and "shutdown" in exc.message


class TestHelperFunctions:
    @pytest.mark.parametrize(
        "exception_instance, expected_category",
        [
            (AuthenticationError(""), "authentication"),
            (CertificateError(""), "certificate"),
            (ClientError(""), "client"),
            (ConfigurationError(""), "configuration"),
            (ConnectionError(""), "connection"),
            (DatagramError(""), "datagram"),
            (FlowControlError(""), "flow_control"),
            (HandshakeError(""), "handshake"),
            (ProtocolError(""), "protocol"),
            (ServerError(""), "server"),
            (SessionError(""), "session"),
            (StreamError(""), "stream"),
            (TimeoutError(""), "timeout"),
            (WebTransportError(""), "unknown"),
            (ValueError(""), "unknown"),
        ],
    )
    def test_get_error_category(self, exception_instance: Exception, expected_category: str) -> None:
        assert get_error_category(exception_instance) == expected_category

    @pytest.mark.parametrize(
        "error_code, is_fatal",
        [
            (ErrorCodes.PROTOCOL_VIOLATION, True),
            (ErrorCodes.APP_AUTHENTICATION_FAILED, True),
            (ErrorCodes.INTERNAL_ERROR, False),
            (ErrorCodes.STREAM_STATE_ERROR, False),
        ],
    )
    def test_is_fatal_error(self, error_code: ErrorCodes, is_fatal: bool) -> None:
        exc = WebTransportError("Test", error_code=error_code)

        assert is_fatal_error(exc) is is_fatal

    def test_is_fatal_error_with_standard_exception(self) -> None:
        assert is_fatal_error(ValueError("Standard error")) is True

    @pytest.mark.parametrize(
        "error_code, is_retriable",
        [
            (ErrorCodes.APP_CONNECTION_TIMEOUT, True),
            (ErrorCodes.APP_SERVICE_UNAVAILABLE, True),
            (ErrorCodes.FLOW_CONTROL_ERROR, True),
            (ErrorCodes.INTERNAL_ERROR, False),
            (ErrorCodes.PROTOCOL_VIOLATION, False),
        ],
    )
    def test_is_retriable_error(self, error_code: ErrorCodes, is_retriable: bool) -> None:
        exc = WebTransportError("Test", error_code=error_code)

        assert is_retriable_error(exc) is is_retriable

    def test_is_retriable_error_with_standard_exception(self) -> None:
        assert is_retriable_error(ValueError("Standard error")) is False
