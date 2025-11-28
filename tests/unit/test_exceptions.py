"""Unit tests for the pywebtransport.exceptions module."""

from typing import Any

import pytest

from pywebtransport import (
    ClientError,
    ConfigurationError,
    ConnectionError,
    DatagramError,
    ProtocolError,
    ServerError,
    SessionError,
    StreamError,
    TimeoutError,
    WebTransportError,
)
from pywebtransport.constants import ErrorCodes
from pywebtransport.exceptions import (
    AuthenticationError,
    CertificateError,
    FlowControlError,
    HandshakeError,
    SerializationError,
    certificate_not_found,
    datagram_too_large,
    get_error_category,
    invalid_config,
    is_fatal_error,
    is_retriable_error,
    session_not_ready,
    stream_closed,
)
from pywebtransport.types import SessionState, StreamState


class TestExceptionClasses:

    def test_stream_error_custom_str(self) -> None:
        exc_no_id = StreamError(message="No ID")
        exc_with_id = StreamError(message="With ID", stream_id=5)

        assert str(exc_no_id) == f"[{hex(exc_no_id.error_code)}] No ID"
        assert str(exc_with_id) == f"[{hex(exc_with_id.error_code)}] With ID (stream_id=5)"

    @pytest.mark.parametrize(
        "exc_class, args, expected_attrs, default_code, expected_repr",
        [
            (
                AuthenticationError,
                {"auth_method": "token"},
                {"auth_method": "token"},
                ErrorCodes.APP_AUTHENTICATION_FAILED,
                "AuthenticationError(message='Test message', error_code=0x1001, auth_method='token')",
            ),
            (
                CertificateError,
                {"certificate_path": "/c.pem", "certificate_error": "expired"},
                {"certificate_path": "/c.pem", "certificate_error": "expired"},
                ErrorCodes.APP_AUTHENTICATION_FAILED,
                (
                    "CertificateError(message='Test message', error_code=0x1001, "
                    "certificate_path='/c.pem', certificate_error='expired')"
                ),
            ),
            (
                ClientError,
                {"target_url": "https://a.com"},
                {"target_url": "https://a.com"},
                ErrorCodes.APP_INVALID_REQUEST,
                "ClientError(message='Test message', error_code=0x1004, target_url='https://a.com')",
            ),
            (
                ConfigurationError,
                {"config_key": "timeout", "config_value": -1},
                {"config_key": "timeout", "config_value": -1},
                ErrorCodes.APP_INVALID_REQUEST,
                "ConfigurationError(message='Test message', error_code=0x1004, config_key='timeout', config_value=-1)",
            ),
            (
                ConnectionError,
                {"remote_address": ("1.1.1.1", 443)},
                {"remote_address": ("1.1.1.1", 443)},
                ErrorCodes.CONNECTION_REFUSED,
                "ConnectionError(message='Test message', error_code=0x2, remote_address=('1.1.1.1', 443))",
            ),
            (
                DatagramError,
                {"datagram_size": 9000, "max_size": 1500},
                {"datagram_size": 9000, "max_size": 1500},
                ErrorCodes.INTERNAL_ERROR,
                "DatagramError(message='Test message', error_code=0x1, datagram_size=9000, max_size=1500)",
            ),
            (
                FlowControlError,
                {"stream_id": 1, "limit_exceeded": 100},
                {"stream_id": 1, "limit_exceeded": 100},
                ErrorCodes.FLOW_CONTROL_ERROR,
                (
                    "FlowControlError(message='Test message', error_code=0x3, "
                    "stream_id=1, limit_exceeded=100, current_value=None)"
                ),
            ),
            (
                HandshakeError,
                {"handshake_stage": "alpn"},
                {"handshake_stage": "alpn"},
                ErrorCodes.INTERNAL_ERROR,
                "HandshakeError(message='Test message', error_code=0x1, handshake_stage='alpn')",
            ),
            (
                ProtocolError,
                {"frame_type": 0x41},
                {"frame_type": 0x41},
                ErrorCodes.PROTOCOL_VIOLATION,
                "ProtocolError(message='Test message', error_code=0xa, frame_type=65)",
            ),
            (
                SerializationError,
                {"original_exception": ValueError("bad data")},
                {"original_exception": ValueError("bad data")},
                ErrorCodes.INTERNAL_ERROR,
                "SerializationError(message='Test message', error_code=0x1, original_exception=ValueError('bad data'))",
            ),
            (
                ServerError,
                {"bind_address": ("0.0.0.0", 4433)},
                {"bind_address": ("0.0.0.0", 4433)},
                ErrorCodes.APP_SERVICE_UNAVAILABLE,
                "ServerError(message='Test message', error_code=0x1005, bind_address=('0.0.0.0', 4433))",
            ),
            (
                SessionError,
                {"session_id": "abc", "session_state": SessionState.CONNECTED},
                {"session_id": "abc", "session_state": SessionState.CONNECTED},
                ErrorCodes.INTERNAL_ERROR,
                (
                    "SessionError(message='Test message', error_code=0x1, "
                    "session_id='abc', session_state=<SessionState.CONNECTED: 'connected'>)"
                ),
            ),
            (
                StreamError,
                {"stream_id": 5, "stream_state": StreamState.OPEN},
                {"stream_id": 5, "stream_state": StreamState.OPEN},
                ErrorCodes.STREAM_STATE_ERROR,
                (
                    "StreamError(message='Test message', error_code=0x5, "
                    "stream_id=5, stream_state=<StreamState.OPEN: 'open'>)"
                ),
            ),
            (
                TimeoutError,
                {"timeout_duration": 10.0, "operation": "read"},
                {"timeout_duration": 10.0, "operation": "read"},
                ErrorCodes.APP_CONNECTION_TIMEOUT,
                "TimeoutError(message='Test message', error_code=0x1000, timeout_duration=10.0, operation='read')",
            ),
        ],
    )
    def test_subclass_exceptions(
        self,
        exc_class: type[WebTransportError],
        args: dict[str, Any],
        expected_attrs: dict[str, Any],
        default_code: ErrorCodes,
        expected_repr: str,
    ) -> None:
        exc = exc_class(message="Test message", **args)
        exc_default = exc_class(message="Default code")

        assert isinstance(exc, WebTransportError)
        assert repr(exc) == expected_repr

        for key, expected_value in expected_attrs.items():
            actual_value = getattr(exc, key)
            if isinstance(expected_value, Exception):
                assert isinstance(actual_value, type(expected_value))
                assert str(actual_value) == str(expected_value)
            else:
                assert actual_value == expected_value

        data = exc.to_dict()
        assert data["type"] == exc_class.__name__
        for key, value in expected_attrs.items():
            if isinstance(value, Exception):
                serialized_value = str(value)
            elif hasattr(value, "value"):
                serialized_value = value.value
            else:
                serialized_value = value
            assert data[key] == serialized_value

        assert exc_default.error_code == default_code

    def test_webtransport_error_base(self) -> None:
        details = {"info": "abc"}

        exc = WebTransportError(message="Base error", error_code=100, details=details)

        assert exc.message == "Base error"
        assert exc.error_code == 100
        assert exc.details == {"info": "abc"}
        assert str(exc) == "[0x64] Base error"
        assert repr(exc) == "WebTransportError(message='Base error', error_code=0x64)"
        assert exc.to_dict() == {
            "type": "WebTransportError",
            "message": "Base error",
            "error_code": 100,
            "details": {"info": "abc"},
        }

    def test_webtransport_error_defaults(self) -> None:
        exc = WebTransportError(message="Default error")

        assert exc.error_code == ErrorCodes.INTERNAL_ERROR
        assert exc.details == {}


class TestExceptionFactories:

    def test_certificate_not_found(self) -> None:
        exc = certificate_not_found(path="/path/to/cert.pem")

        assert isinstance(exc, CertificateError)
        assert exc.certificate_path == "/path/to/cert.pem"
        assert exc.certificate_error == "file_not_found"
        assert "/path/to/cert.pem" in exc.message

    def test_datagram_too_large(self) -> None:
        exc = datagram_too_large(size=9000, max_size=1500)

        assert isinstance(exc, DatagramError)
        assert exc.datagram_size == 9000
        assert exc.max_size == 1500
        assert "9000" in exc.message and "1500" in exc.message

    def test_invalid_config(self) -> None:
        exc = invalid_config(key="retries", value=-1, reason="must be non-negative")

        assert isinstance(exc, ConfigurationError)
        assert exc.config_key == "retries"
        assert exc.config_value == -1
        assert "retries" in exc.message and "must be non-negative" in exc.message

    def test_session_not_ready(self) -> None:
        exc = session_not_ready(session_id="sess_123", current_state=SessionState.CONNECTING)

        assert isinstance(exc, SessionError)
        assert exc.session_id == "sess_123"
        assert exc.session_state == SessionState.CONNECTING
        assert "sess_123" in exc.message and "connecting" in exc.message

    def test_stream_closed(self) -> None:
        exc = stream_closed(stream_id=5, reason="shutdown")

        assert isinstance(exc, StreamError)
        assert exc.stream_id == 5
        assert exc.error_code == ErrorCodes.STREAM_STATE_ERROR
        assert "Stream 5" in exc.message and "shutdown" in exc.message


class TestHelperFunctions:

    @pytest.mark.parametrize(
        "exception_instance, expected_category",
        [
            (AuthenticationError(message=""), "authentication"),
            (CertificateError(message=""), "certificate"),
            (ClientError(message=""), "client"),
            (ConfigurationError(message=""), "configuration"),
            (ConnectionError(message=""), "connection"),
            (DatagramError(message=""), "datagram"),
            (FlowControlError(message=""), "flow_control"),
            (HandshakeError(message=""), "handshake"),
            (ProtocolError(message=""), "protocol"),
            (SerializationError(message=""), "serialization"),
            (ServerError(message=""), "server"),
            (SessionError(message=""), "session"),
            (StreamError(message=""), "stream"),
            (TimeoutError(message=""), "timeout"),
            (WebTransportError(message=""), "unknown"),
            (ValueError(""), "unknown"),
        ],
    )
    def test_get_error_category(self, exception_instance: Exception, expected_category: str) -> None:
        category = get_error_category(exception=exception_instance)

        assert category == expected_category

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
        exc = WebTransportError(message="Test", error_code=error_code)

        assert is_fatal_error(exception=exc) is is_fatal

    def test_is_fatal_error_with_standard_exception(self) -> None:
        exc = ValueError("Standard error")

        assert is_fatal_error(exception=exc) is True

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
        exc = WebTransportError(message="Test", error_code=error_code)

        assert is_retriable_error(exception=exc) is is_retriable

    def test_is_retriable_error_with_standard_exception(self) -> None:
        exc = ValueError("Standard error")

        assert is_retriable_error(exception=exc) is False
