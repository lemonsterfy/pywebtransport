"""Unit tests for the pywebtransport.utils module."""

import logging
from pathlib import Path
from typing import Any, cast

import pytest
from pytest_mock import MockerFixture

from pywebtransport.utils import (
    Timer,
    ensure_buffer,
    format_duration,
    generate_self_signed_cert,
    generate_session_id,
    get_header,
    get_logger,
    get_timestamp,
    merge_headers,
)


class TestCertUtils:

    def test_generate_self_signed_cert(self, mocker: MockerFixture, tmp_path: Path) -> None:
        mocker.patch("cryptography.hazmat.primitives.asymmetric.rsa.generate_private_key")
        mocker.patch("cryptography.x509.CertificateBuilder")
        mocker.patch("cryptography.x509.Name")
        mocker.patch("cryptography.x509.DNSName")
        mocker.patch("cryptography.x509.SubjectAlternativeName")
        mock_open = mocker.patch("builtins.open", mocker.mock_open())
        mock_chmod = mocker.patch("os.chmod")

        cert_file, key_file = generate_self_signed_cert(hostname="localhost", output_dir=str(tmp_path))

        expected_cert_path = tmp_path / "localhost.crt"
        expected_key_path = tmp_path / "localhost.key"
        assert cert_file == str(expected_cert_path)
        assert key_file == str(expected_key_path)
        mock_open.assert_any_call(expected_cert_path, "wb")
        mock_open.assert_any_call(expected_key_path, "wb")
        mock_chmod.assert_called_once_with(expected_key_path, 0o600)


class TestDataConversionAndFormatting:

    @pytest.mark.parametrize(
        "data, expected_type, expected_content",
        [
            ("hello", bytes, b"hello"),
            (b"world", bytes, b"world"),
            (bytearray(b"array"), bytearray, bytearray(b"array")),
            (memoryview(b"view"), memoryview, b"view"),
        ],
    )
    def test_ensure_buffer(self, data: Any, expected_type: type, expected_content: Any) -> None:
        result = ensure_buffer(data=data)

        assert isinstance(result, expected_type)
        if isinstance(result, memoryview):
            assert result.tobytes() == expected_content
        else:
            assert result == expected_content

    def test_ensure_buffer_invalid_type(self) -> None:
        with pytest.raises(TypeError):
            ensure_buffer(data=cast(Any, 123))

    @pytest.mark.parametrize(
        "seconds, expected",
        [
            (1e-7, "100ns"),
            (5e-5, "50.0µs"),
            (0.1234, "123.4ms"),
            (5.67, "5.7s"),
            (90.5, "1m30.5s"),
            (3723.1, "1h2m3.1s"),
        ],
    )
    def test_format_duration(self, seconds: float, expected: str) -> None:
        result = format_duration(seconds=seconds)

        assert result == expected


class TestHeaderUtils:

    def test_get_header_from_dict(self) -> None:
        headers = {"content-type": "application/json"}

        assert get_header(headers=headers, key="content-type") == "application/json"
        assert get_header(headers=headers, key="Unknown") is None
        assert get_header(headers=headers, key="Unknown", default="default") == "default"

    def test_get_header_from_list(self) -> None:
        headers = [("Content-Type", "application/json")]

        assert get_header(headers=headers, key="content-type") == "application/json"
        assert get_header(headers=headers, key="Unknown") is None

    def test_merge_headers_dict(self) -> None:
        base = {"a": "1"}
        update = {"b": "2"}

        result = merge_headers(base=base, update=update)

        assert result == {"a": "1", "b": "2"}

    def test_merge_headers_list(self) -> None:
        base = [("a", "1")]
        update = [("b", "2")]

        result = merge_headers(base=base, update=update)

        assert result == [("a", "1"), ("b", "2")]

    def test_merge_headers_mixed(self) -> None:
        base = {"a": "1"}
        update = [("b", "2")]

        result = merge_headers(base=base, update=update)

        assert result == [("a", "1"), ("b", "2")]

    def test_merge_headers_none(self) -> None:
        base = {"a": "1"}
        base_list = [("a", "1")]

        assert merge_headers(base=base, update=None) == {"a": "1"}
        assert merge_headers(base=base_list, update=None) == [("a", "1")]


class TestIdGenerators:

    def test_generate_session_id(self, mocker: MockerFixture) -> None:
        mock_token = mocker.patch("pywebtransport.utils.secrets.token_urlsafe")
        mock_token.return_value = "test-id"

        result = generate_session_id()

        assert result == "test-id"
        mock_token.assert_called_once_with(16)


class TestLoggingUtils:

    def test_get_logger(self) -> None:
        logger = get_logger(name="test")

        assert isinstance(logger, logging.Logger)
        assert logger.name == "test"


class TestTimer:

    def test_timer_context_manager(self, mocker: MockerFixture) -> None:
        mocker.patch("time.perf_counter", side_effect=[2000.0, 2002.3, 2002.3])
        mocker.patch("pywebtransport.utils.format_duration", return_value="2.3s")
        mock_logger = mocker.patch("pywebtransport.utils.get_logger").return_value

        with Timer(name="context-timer") as timer:
            assert timer.start_time == 2000.0
            assert timer.elapsed > 0

        assert timer.end_time == 2002.3
        mock_logger.debug.assert_called_once_with("%s took %s", "context-timer", "2.3s")

    def test_timer_init(self) -> None:
        timer = Timer(name="my-timer")

        assert timer.name == "my-timer"
        assert timer.elapsed == 0.0

    def test_timer_stop_before_start(self) -> None:
        timer = Timer()

        with pytest.raises(RuntimeError, match="Timer not started"):
            timer.stop()

    def test_timer_timing(self, mocker: MockerFixture) -> None:
        mocker.patch("time.perf_counter", side_effect=[1000.0, 1005.5])
        timer = Timer()

        timer.start()
        elapsed = timer.stop()

        assert elapsed == 5.5
        assert timer.elapsed == 5.5


class TestTimestamp:

    def test_get_timestamp(self, mocker: MockerFixture) -> None:
        mocker.patch("time.perf_counter", return_value=12345.678)

        timestamp = get_timestamp()

        assert timestamp == 12345.678
