"""Unit tests for the pywebtransport.utils module."""

import asyncio
import hashlib
import logging
import socket
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import pytest
from pytest_mock import MockerFixture

from pywebtransport import CertificateError, ConfigurationError, TimeoutError
from pywebtransport.constants import DEFAULT_PORT, MAX_STREAM_ID
from pywebtransport.utils import (
    Timer,
    build_webtransport_url,
    calculate_checksum,
    chunked_read,
    create_task_with_timeout,
    ensure_bytes,
    ensure_str,
    format_bytes,
    format_duration,
    format_timestamp,
    generate_connection_id,
    generate_request_id,
    generate_self_signed_cert,
    generate_session_id,
    get_logger,
    get_timestamp,
    is_ipv4_address,
    is_ipv6_address,
    load_certificate,
    merge_configs,
    normalize_headers,
    parse_webtransport_url,
    resolve_address,
    run_with_timeout,
    setup_logging,
    validate_address,
    validate_error_code,
    validate_port,
    validate_session_id,
    validate_stream_id,
    validate_url,
    wait_for_condition,
)


class TestLoggingUtils:
    def test_get_logger(self) -> None:
        logger = get_logger(name="test")

        assert isinstance(logger, logging.Logger)
        assert logger.name == "pywebtransport.test"

    def test_setup_logging(self, caplog: pytest.LogCaptureFixture) -> None:
        logger_name = "test_logger_unique"
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()

        with caplog.at_level(logging.DEBUG):
            setup_logging(level="DEBUG", logger_name=logger_name)
            logger.debug("Test message")

        assert "Test message" in caplog.text
        assert logger.level == logging.DEBUG
        assert len(logger.handlers) == 1
        handler_count = len(logger.handlers)
        setup_logging(level="INFO", logger_name=logger_name)
        assert len(logger.handlers) == handler_count
        with pytest.raises(ValueError, match="Invalid log level: invalid"):
            setup_logging(level="invalid", logger_name="another_logger")


class TestIdGenerators:
    @pytest.mark.parametrize(
        "func, length",
        [
            (generate_connection_id, 12),
            (generate_request_id, 8),
            (generate_session_id, 16),
        ],
    )
    def test_id_generators(self, mocker: MockerFixture, func: Any, length: int) -> None:
        mock_token = mocker.patch("pywebtransport.utils.secrets.token_urlsafe")
        mock_token.return_value = "test-id"

        result = func()

        assert result == "test-id"
        mock_token.assert_called_once_with(length)


class TestTimer:
    def test_timer_init(self) -> None:
        timer = Timer(name="my-timer")

        assert timer.name == "my-timer"
        assert timer.elapsed == 0.0

    def test_timer_timing(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.utils.time.time", side_effect=[1000.0, 1005.5])
        timer = Timer()

        timer.start()
        elapsed = timer.stop()

        assert elapsed == 5.5
        assert timer.elapsed == 5.5

    def test_timer_context_manager(self, mocker: MockerFixture) -> None:
        mocker.patch("time.time", side_effect=[2000.0, 2002.3, 2002.3])
        mocker.patch("pywebtransport.utils.format_duration", return_value="2.3s")
        mock_logger = mocker.patch("pywebtransport.utils.get_logger").return_value

        with Timer(name="context-timer") as timer:
            assert timer.start_time == 2000.0
            assert timer.elapsed > 0

        assert timer.end_time == 2002.3
        mock_logger.debug.assert_called_once_with("%s took %s", "context-timer", "2.3s")

    def test_timer_stop_before_start(self) -> None:
        timer = Timer()

        with pytest.raises(RuntimeError, match="Timer not started"):
            timer.stop()


class TestTimestamp:
    def test_get_timestamp(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.utils.time.time", return_value=12345.678)

        timestamp = get_timestamp()

        assert timestamp == 12345.678


class TestUrlAndAddressUtils:
    @pytest.mark.parametrize(
        "host, expected",
        [("192.0.2.1", True), ("example.com", False), ("::1", False)],
    )
    def test_is_ipv4_address(self, host: str, expected: bool) -> None:
        result = is_ipv4_address(host=host)

        assert result is expected

    @pytest.mark.parametrize(
        "host, expected",
        [
            ("::1", True),
            ("2001:db8::1", True),
            ("192.0.2.1", False),
            ("example.com", False),
        ],
    )
    def test_is_ipv6_address(self, host: str, expected: bool) -> None:
        result = is_ipv6_address(host=host)

        assert result is expected

    @pytest.mark.parametrize(
        "host, port, secure, query_params, expected",
        [
            ("example.com", 443, True, None, "https://example.com/"),
            ("example.com", 80, False, None, "http://example.com/"),
            ("example.com", 8443, True, None, "https://example.com:8443/"),
            ("127.0.0.1", 8080, False, None, "http://127.0.0.1:8080/"),
            ("::1", 443, True, {"key": "val"}, "https://[::1]/?key=val"),
            ("[::1]", 443, True, None, "https://[::1]/"),
        ],
    )
    def test_build_webtransport_url(
        self,
        host: str,
        port: int,
        secure: bool,
        query_params: dict[str, str] | None,
        expected: str,
    ) -> None:
        url = build_webtransport_url(host=host, port=port, secure=secure, query_params=query_params)

        assert url == expected

    @pytest.mark.parametrize(
        "url, expected",
        [
            ("https://example.com", ("example.com", 443, "/")),
            ("https://localhost:8080/path", ("localhost", 8080, "/path")),
            ("https://[::1]:9090/q?a=1#f", ("::1", 9090, "/q?a=1#f")),
        ],
    )
    def test_parse_webtransport_url(self, mocker: MockerFixture, url: str, expected: tuple[str, int, str]) -> None:
        mocker.patch("pywebtransport.utils.WEBTRANSPORT_SCHEMES", ("https", "wss"))

        parsed_url = parse_webtransport_url(url=url)

        assert parsed_url == expected

    def test_parse_webtransport_url_insecure_default_port(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.utils.WEBTRANSPORT_SCHEMES", ("https", "http"))

        hostname, port, path = parse_webtransport_url(url="http://example.com/test")

        assert port == DEFAULT_PORT

    @pytest.mark.parametrize(
        "url, error_msg",
        [
            ("ftp://example.com", "Unsupported scheme 'ftp'"),
            ("http://example.com", "Unsupported scheme 'http'"),
            ("https://", "Missing hostname in URL"),
        ],
    )
    def test_parse_webtransport_url_errors(self, mocker: MockerFixture, url: str, error_msg: str) -> None:
        mocker.patch("pywebtransport.utils.WEBTRANSPORT_SCHEMES", ("https", "wss"))

        with pytest.raises(ConfigurationError, match=error_msg):
            parse_webtransport_url(url=url)

    @pytest.mark.asyncio
    async def test_resolve_address(self, mocker: MockerFixture) -> None:
        mock_getaddrinfo = mocker.patch.object(asyncio.get_running_loop(), "getaddrinfo", new_callable=mocker.AsyncMock)
        mock_getaddrinfo.return_value = [(socket.AF_INET, socket.SOCK_DGRAM, 0, "", ("192.0.2.1", 1234))]

        result = await resolve_address(host="example.com", port=1234)

        assert result == ("192.0.2.1", 1234)
        mock_getaddrinfo.assert_awaited_once_with(
            host="example.com", port=1234, family=socket.AF_UNSPEC, type=socket.SOCK_DGRAM
        )

    @pytest.mark.asyncio
    async def test_resolve_address_no_result(self, mocker: MockerFixture) -> None:
        mock_getaddrinfo = mocker.patch.object(asyncio.get_running_loop(), "getaddrinfo", new_callable=mocker.AsyncMock)
        mock_getaddrinfo.return_value = []

        with pytest.raises(ConfigurationError, match="No address found"):
            await resolve_address(host="empty.host", port=1234)

    @pytest.mark.asyncio
    async def test_resolve_address_failure(self, mocker: MockerFixture) -> None:
        mock_getaddrinfo = mocker.patch.object(asyncio.get_running_loop(), "getaddrinfo", new_callable=mocker.AsyncMock)
        mock_getaddrinfo.side_effect = OSError("Resolution failed")

        with pytest.raises(ConfigurationError, match="Failed to resolve address"):
            await resolve_address(host="invalid.host", port=1234)


class TestDataConversionAndFormatting:
    @pytest.mark.parametrize(
        "data, expected",
        [
            ("hello", b"hello"),
            (b"world", b"world"),
            (bytearray(b"array"), b"array"),
            (memoryview(b"view"), b"view"),
        ],
    )
    def test_ensure_bytes(self, data: Any, expected: bytes) -> None:
        result = ensure_bytes(data=data)

        assert result == expected

    def test_ensure_bytes_invalid_type(self) -> None:
        with pytest.raises(TypeError):
            ensure_bytes(data=123)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "data, expected",
        [
            ("hello", "hello"),
            (b"world", "world"),
            (bytearray(b"array"), "array"),
            (memoryview(b"view"), "view"),
        ],
    )
    def test_ensure_str(self, data: Any, expected: str) -> None:
        result = ensure_str(data=data)

        assert result == expected

    def test_ensure_str_invalid_type(self) -> None:
        with pytest.raises(TypeError):
            ensure_str(data=123)  # type: ignore[arg-type]

    def test_format_bytes(self) -> None:
        short_data = b"short"
        long_data = b"a" * 120

        assert format_bytes(data=short_data) == "b'short'"
        assert format_bytes(data=long_data, max_length=50).startswith("b'aaaaaaaa")
        assert format_bytes(data=long_data, max_length=50).endswith("... (120 bytes total)")

    @pytest.mark.parametrize(
        "seconds, expected",
        [(0.1234, "123.4ms"), (5.67, "5.7s"), (90.5, "1m30.5s"), (3723.1, "1h2m3.1s")],
    )
    def test_format_duration(self, seconds: float, expected: str) -> None:
        result = format_duration(seconds=seconds)

        assert result == expected

    def test_format_timestamp(self, mocker: MockerFixture) -> None:
        ts = 1672531200.0
        expected_iso = "2023-01-01T00:00:00"
        mock_dt_class = mocker.patch("pywebtransport.utils.datetime")
        mock_dt_class.fromtimestamp.return_value.isoformat.return_value = expected_iso

        result = format_timestamp(timestamp=ts)

        assert result == expected_iso
        mock_dt_class.fromtimestamp.assert_called_once_with(ts)

    def test_normalize_headers(self) -> None:
        headers = {"Content-Type": "application/json", "X-Custom": 123}

        expected = {"content-type": "application/json", "x-custom": "123"}
        result = normalize_headers(headers=headers)

        assert result == expected


class TestAsyncUtils:
    @pytest.mark.asyncio
    async def test_create_task_with_timeout_success(self) -> None:
        async def fast_coro() -> str:
            await asyncio.sleep(0)
            return "done"

        task = await create_task_with_timeout(coro=fast_coro(), timeout=0.1)
        result = await task

        assert result == "done"

    @pytest.mark.asyncio
    async def test_create_task_with_timeout_no_timeout(self, mocker: MockerFixture) -> None:
        spy_create_task = mocker.spy(asyncio, "create_task")

        async def coro() -> str:
            return "done"

        task = await create_task_with_timeout(coro=coro())
        result = await task

        assert result == "done"
        spy_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_task_with_timeout_fails(self, mocker: MockerFixture) -> None:
        def close_and_raise(coro: Coroutine[Any, Any, Any], timeout: float) -> None:
            coro.close()
            raise asyncio.TimeoutError()

        mocker.patch("asyncio.wait_for", side_effect=close_and_raise)

        async def slow_coro() -> str:
            return "never"

        task = await create_task_with_timeout(coro=slow_coro(), timeout=0.01)

        with pytest.raises(asyncio.TimeoutError):
            await task

    @pytest.mark.asyncio
    async def test_run_with_timeout(self, mocker: MockerFixture) -> None:
        async def sample_coro() -> str:
            return "ok"

        result_ok = await run_with_timeout(coro=sample_coro(), timeout=1, default_value="fail")
        assert result_ok == "ok"

        def close_and_raise(coro: Coroutine[Any, Any, Any], timeout: float) -> None:
            coro.close()
            raise asyncio.TimeoutError()

        mocker.patch("asyncio.wait_for", side_effect=close_and_raise)
        result_fail = await run_with_timeout(coro=sample_coro(), timeout=0.01, default_value="fail")
        assert result_fail == "fail"

    @pytest.mark.asyncio
    async def test_wait_for_condition(self) -> None:
        flag = [False, False, True]
        await wait_for_condition(condition=lambda: flag.pop(0), timeout=1, interval=0.01)

        with pytest.raises(TimeoutError, match="Condition not met within 0.1s timeout"):
            await wait_for_condition(condition=lambda: False, timeout=0.1, interval=0.05)

    @pytest.mark.asyncio
    async def test_wait_for_condition_no_timeout(self) -> None:
        flag = [False, True]

        await wait_for_condition(condition=lambda: flag.pop(0), interval=0.01)

        assert not flag


class TestCryptoAndCertUtils:
    def test_calculate_checksum(self) -> None:
        data = b"pywebtransport"
        expected_sha256 = hashlib.sha256(data).hexdigest()

        checksum = calculate_checksum(data=data, algorithm="sha256")

        assert checksum == expected_sha256
        with pytest.raises(ValueError, match="Unsupported or insecure hash algorithm: nonexistent-algorithm"):
            calculate_checksum(data=data, algorithm="nonexistent-algorithm")

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

    def test_load_certificate(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.utils.Path.exists", return_value=True)
        mock_ssl_context = mocker.patch("pywebtransport.utils.ssl.SSLContext").return_value

        context = load_certificate(certfile="cert.pem", keyfile="key.pem")

        assert context == mock_ssl_context
        mock_ssl_context.load_cert_chain.assert_called_once_with(certfile="cert.pem", keyfile="key.pem")

    def test_load_certificate_load_fails(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.utils.Path.exists", return_value=True)
        mock_ssl_context = mocker.patch("pywebtransport.utils.ssl.SSLContext").return_value
        mock_ssl_context.load_cert_chain.side_effect = Exception("Load failed")

        with pytest.raises(CertificateError, match="Failed to load certificate: Load failed"):
            load_certificate(certfile="cert.pem", keyfile="key.pem")

    def test_load_certificate_certfile_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.utils.Path.exists", return_value=False)

        with pytest.raises(CertificateError, match="Certificate file not found: cert.pem"):
            load_certificate(certfile="cert.pem", keyfile="key.pem")

    def test_load_certificate_keyfile_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.utils.Path.exists", side_effect=[True, False])

        with pytest.raises(CertificateError, match="Certificate file not found: key.pem"):
            load_certificate(certfile="cert.pem", keyfile="key.pem")


class TestValidationFunctions:
    @pytest.mark.parametrize(
        "address, is_valid",
        [
            (("127.0.0.1", 80), True),
            (("::1", 65535), True),
            (None, False),
            (("127.0.0.1",), False),
            ((127001, 80), False),
            (("127.0.0.1", 0), False),
            (("127.0.0.1", 65536), False),
        ],
    )
    def test_validate_address(self, address: Any, is_valid: bool) -> None:
        if is_valid:
            validate_address(address=address)
        else:
            with pytest.raises((TypeError, ValueError)):
                validate_address(address=address)

    @pytest.mark.parametrize(
        "value, is_valid, exc_type",
        [
            (0, True, None),
            (12345, True, None),
            (2**32 - 1, True, None),
            (-1, False, ValueError),
            (2**32, False, ValueError),
            ("123", False, TypeError),
        ],
    )
    def test_validate_error_code(self, value: Any, is_valid: bool, exc_type: type[Exception] | None) -> None:
        if is_valid:
            validate_error_code(error_code=value)
        else:
            assert exc_type is not None
            with pytest.raises(exc_type):
                validate_error_code(error_code=value)

    @pytest.mark.parametrize(
        "port, is_valid",
        [(1, True), (65535, True), (0, False), (65536, False), ("80", False)],
    )
    def test_validate_port(self, port: Any, is_valid: bool) -> None:
        if is_valid:
            validate_port(port=port)
        else:
            with pytest.raises(ValueError):
                validate_port(port=port)

    @pytest.mark.parametrize(
        "value, is_valid, exc_type",
        [("", False, ValueError), (None, False, TypeError), ("some-id", True, None)],
    )
    def test_validate_session_id(self, value: Any, is_valid: bool, exc_type: type[Exception] | None) -> None:
        if is_valid:
            validate_session_id(session_id=value)
        else:
            assert exc_type is not None
            with pytest.raises(exc_type):
                validate_session_id(session_id=value)

    @pytest.mark.parametrize(
        "stream_id, is_valid",
        [
            (0, True),
            (MAX_STREAM_ID, True),
            (-1, False),
            (MAX_STREAM_ID + 1, False),
            ("1", False),
        ],
    )
    def test_validate_stream_id(self, stream_id: Any, is_valid: bool) -> None:
        if is_valid:
            validate_stream_id(stream_id=stream_id)
        else:
            with pytest.raises((ValueError, TypeError)):
                validate_stream_id(stream_id=stream_id)

    def test_validate_url(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.utils.WEBTRANSPORT_SCHEMES", ("https", "wss"))

        assert validate_url(url="https://example.com") is True
        assert validate_url(url="https://[::1]:8080/path") is True
        assert validate_url(url="http://example.com") is False
        assert validate_url(url="ftp://invalid.scheme") is False
        assert validate_url(url="not-a-url") is False


class TestMiscUtils:
    def test_merge_configs(self) -> None:
        base: dict[str, Any] = {"a": 1, "b": {"c": 2, "d": 3}}
        override = {"b": {"d": 4, "e": 5}, "f": 6}

        expected = {"a": 1, "b": {"c": 2, "d": 4, "e": 5}, "f": 6}
        result = merge_configs(base_config=base, override_config=override)

        assert result == expected
        assert base["b"]["d"] == 3

    @pytest.mark.parametrize(
        "data, chunk_size, expected",
        [
            (b"12345678", 4, [b"1234", b"5678"]),
            (b"12345", 2, [b"12", b"34", b"5"]),
            (b"", 100, []),
        ],
    )
    def test_chunked_read(self, data: bytes, chunk_size: int, expected: list[bytes]) -> None:
        result = list(chunked_read(data=data, chunk_size=chunk_size))

        assert result == expected

    def test_chunked_read_invalid_size(self) -> None:
        with pytest.raises(ValueError, match="Chunk size must be positive"):
            list(chunked_read(data=b"abc", chunk_size=0))
