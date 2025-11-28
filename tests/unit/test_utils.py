"""Unit tests for the pywebtransport.utils module."""

import logging
from pathlib import Path
from typing import Any

import pytest
from aioquic.quic.configuration import QuicConfiguration
from pytest_mock import MockerFixture

from pywebtransport.utils import (
    Timer,
    create_quic_configuration,
    ensure_bytes,
    format_duration,
    generate_self_signed_cert,
    generate_session_id,
    get_logger,
    get_timestamp,
)


class TestCertUtils:

    def test_generate_self_signed_cert(self, mocker: MockerFixture, tmp_path: Path) -> None:
        mocker.patch("pywebtransport.utils.rsa.generate_private_key")
        mocker.patch("pywebtransport.utils.x509.CertificateBuilder")
        mocker.patch("pywebtransport.utils.x509.Name")
        mocker.patch("pywebtransport.utils.x509.DNSName")
        mocker.patch("pywebtransport.utils.x509.SubjectAlternativeName")
        mock_open = mocker.patch("builtins.open", mocker.mock_open())

        cert_file, key_file = generate_self_signed_cert(hostname="localhost", output_dir=str(tmp_path))

        expected_cert_path = tmp_path / "localhost.crt"
        expected_key_path = tmp_path / "localhost.key"
        assert cert_file == str(expected_cert_path)
        assert key_file == str(expected_key_path)
        mock_open.assert_any_call(expected_cert_path, "wb")
        mock_open.assert_any_call(expected_key_path, "wb")


class TestConfigurationUtils:

    @pytest.mark.parametrize("is_client", [True, False])
    def test_create_quic_configuration(self, mocker: MockerFixture, is_client: bool) -> None:
        mock_quic_config = mocker.patch("pywebtransport.utils.QuicConfiguration", spec=QuicConfiguration)

        config = create_quic_configuration(
            alpn_protocols=["h3"],
            congestion_control_algorithm="reno",
            idle_timeout=60.0,
            is_client=is_client,
            max_datagram_size=1200,
        )

        assert config == mock_quic_config.return_value
        mock_quic_config.assert_called_once_with(
            alpn_protocols=["h3"],
            congestion_control_algorithm="reno",
            idle_timeout=60.0,
            is_client=is_client,
            max_datagram_frame_size=1200,
        )


class TestDataConversionAndFormatting:

    @pytest.mark.parametrize(
        "data, expected",
        [("hello", b"hello"), (b"world", b"world"), (bytearray(b"array"), b"array"), (memoryview(b"view"), b"view")],
    )
    def test_ensure_bytes(self, data: Any, expected: bytes) -> None:
        result = ensure_bytes(data=data)

        assert result == expected

    def test_ensure_bytes_invalid_type(self) -> None:
        with pytest.raises(TypeError):
            ensure_bytes(data=123)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "seconds, expected", [(0.1234, "123.4ms"), (5.67, "5.7s"), (90.5, "1m30.5s"), (3723.1, "1h2m3.1s")]
    )
    def test_format_duration(self, seconds: float, expected: str) -> None:
        result = format_duration(seconds=seconds)

        assert result == expected


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
        mocker.patch("time.time", side_effect=[2000.0, 2002.3, 2002.3])
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
        mocker.patch("pywebtransport.utils.time.time", side_effect=[1000.0, 1005.5])
        timer = Timer()

        timer.start()
        elapsed = timer.stop()

        assert elapsed == 5.5
        assert timer.elapsed == 5.5


class TestTimestamp:

    def test_get_timestamp(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.utils.time.time", return_value=12345.678)

        timestamp = get_timestamp()

        assert timestamp == 12345.678
