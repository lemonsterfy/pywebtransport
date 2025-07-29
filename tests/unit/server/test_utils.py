"""Unit tests for the pywebtransport.server.utils module."""

import asyncio
from typing import Any, AsyncGenerator

import pytest
from pytest_mock import MockerFixture

from pywebtransport import (
    ConnectionError,
    ServerConfig,
    WebTransportSession,
    WebTransportStream,
    create_development_server,
)
from pywebtransport.server import create_echo_server_app, create_simple_app, echo_handler, health_check_handler
from pywebtransport.server.utils import _echo_datagrams, _echo_single_stream, _echo_streams


@pytest.fixture
def mock_session(mocker: MockerFixture) -> Any:
    mock = mocker.create_autospec(WebTransportSession, instance=True)
    mock.datagrams = mocker.AsyncMock()
    mock.is_closed = False
    return mock


@pytest.fixture
def mock_stream(mocker: MockerFixture) -> Any:
    mock = mocker.create_autospec(WebTransportStream, instance=True)
    mock.stream_id = 1
    return mock


class TestAppFactories:
    @pytest.mark.parametrize(
        "generate_certs, certs_exist, expect_generation",
        [
            (True, True, True),
            (True, False, True),
            (False, True, False),
            (False, False, True),
        ],
    )
    def test_create_development_server(
        self,
        mocker: MockerFixture,
        generate_certs: bool,
        certs_exist: bool,
        expect_generation: bool,
    ) -> None:
        mocker.patch("pathlib.Path.exists", return_value=certs_exist)
        mock_generate_cert = mocker.patch("pywebtransport.server.utils.generate_self_signed_cert")
        mock_server_config = mocker.patch("pywebtransport.config.ServerConfig.create_for_development")
        mock_app = mocker.patch("pywebtransport.server.utils.ServerApp")
        host, port = "test.local", 1234

        create_development_server(host=host, port=port, generate_certs=generate_certs)

        if expect_generation:
            mock_generate_cert.assert_called_once_with(host)
        else:
            mock_generate_cert.assert_not_called()
        mock_server_config.assert_called_once_with(
            host=host,
            port=port,
            certfile=f"{host}.crt",
            keyfile=f"{host}.key",
        )
        mock_app.assert_called_once_with(config=mock_server_config.return_value)

    def test_create_echo_server_app(self, mocker: MockerFixture) -> None:
        mock_app_class = mocker.patch("pywebtransport.server.utils.ServerApp")
        mock_app_instance = mock_app_class.return_value
        mock_config = mocker.create_autospec(ServerConfig, instance=True)

        app = create_echo_server_app(config=mock_config)

        mock_app_class.assert_called_once_with(config=mock_config)
        mock_app_instance.route.assert_called_once_with("/")
        mock_app_instance.route.return_value.assert_called_once_with(echo_handler)
        assert app == mock_app_instance

    def test_create_simple_app(self, mocker: MockerFixture) -> None:
        mock_app_class = mocker.patch("pywebtransport.server.utils.ServerApp")
        mock_app_instance = mock_app_class.return_value

        app = create_simple_app()

        mock_app_class.assert_called_once_with()
        health_route_call = mocker.call("/health")
        health_handler_call = mocker.call(health_check_handler)
        echo_route_call = mocker.call("/echo")
        echo_handler_call = mocker.call(echo_handler)
        mock_app_instance.route.assert_has_calls([health_route_call, echo_route_call], any_order=True)
        mock_app_instance.route.return_value.assert_has_calls([health_handler_call, echo_handler_call], any_order=True)
        assert app == mock_app_instance


@pytest.mark.asyncio
class TestHandlers:
    async def test_health_check_handler_success(self, mock_session: Any) -> None:
        await health_check_handler(mock_session)

        mock_session.datagrams.send.assert_awaited_once_with(b'{"status": "healthy"}')
        mock_session.close.assert_awaited_once()

    async def test_health_check_handler_send_fails(self, mocker: MockerFixture, mock_session: Any) -> None:
        mock_logger = mocker.patch("pywebtransport.server.utils.logger")
        mock_session.datagrams.send.side_effect = ConnectionError("Send failed")

        await health_check_handler(mock_session)

        mock_session.datagrams.send.assert_awaited_once()
        mock_logger.error.assert_called_once()
        mock_session.close.assert_awaited_once()

    async def test_echo_handler_creates_tasks(self, mocker: MockerFixture, mock_session: Any) -> None:
        mock_create_task = mocker.patch("asyncio.create_task")
        mock_gather = mocker.patch("asyncio.gather", new_callable=mocker.AsyncMock)
        mock_echo_datagrams = mocker.patch("pywebtransport.server.utils._echo_datagrams", new_callable=mocker.MagicMock)
        mock_echo_streams = mocker.patch("pywebtransport.server.utils._echo_streams", new_callable=mocker.MagicMock)

        await echo_handler(mock_session)

        mock_echo_datagrams.assert_called_once_with(mock_session)
        mock_echo_streams.assert_called_once_with(mock_session)
        mock_create_task.assert_has_calls(
            [
                mocker.call(mock_echo_datagrams.return_value),
                mocker.call(mock_echo_streams.return_value),
            ],
            any_order=True,
        )
        assert mock_gather.await_count == 1
        assert len(mock_gather.await_args.args) == 2

    async def test_echo_handler_exception(self, mocker: MockerFixture, mock_session: Any) -> None:
        mock_logger = mocker.patch("pywebtransport.server.utils.logger")
        mocker.patch("asyncio.gather", new_callable=mocker.AsyncMock, side_effect=ValueError("Test Error"))
        mocker.patch("pywebtransport.server.utils._echo_datagrams")
        mocker.patch("pywebtransport.server.utils._echo_streams")

        await echo_handler(mock_session)

        mock_logger.error.assert_called_once()
        assert "Test Error" in mock_logger.error.call_args[0][0]


@pytest.mark.asyncio
class TestEchoHelpers:
    async def test_echo_datagrams(self, mocker: MockerFixture, mock_session: Any) -> None:
        received_data = [b"hello", b"world"]
        mock_session.datagrams.receive.side_effect = received_data + [asyncio.CancelledError]

        await _echo_datagrams(mock_session)

        calls = [mocker.call(b"ECHO: " + data) for data in received_data]
        mock_session.datagrams.send.assert_has_awaits(calls)
        assert mock_session.datagrams.receive.await_count == len(received_data) + 1

    async def test_echo_datagrams_handles_cancellation(self, mock_session: Any) -> None:
        mock_session.datagrams.receive.side_effect = asyncio.CancelledError

        await _echo_datagrams(mock_session)

        mock_session.datagrams.send.assert_not_awaited()

    async def test_echo_datagrams_handles_general_exception(self, mock_session: Any) -> None:
        mock_session.datagrams.receive.side_effect = ValueError("Receive failed")

        await _echo_datagrams(mock_session)

        mock_session.datagrams.send.assert_not_awaited()

    async def test_echo_datagrams_handles_empty_data(self, mock_session: Any) -> None:
        mock_session.datagrams.receive.side_effect = [b"", asyncio.CancelledError]

        await _echo_datagrams(mock_session)

        mock_session.datagrams.send.assert_not_awaited()
        assert mock_session.datagrams.receive.await_count == 2

    async def test_echo_streams(self, mocker: MockerFixture, mock_session: Any, mock_stream: Any) -> None:
        mock_create_task = mocker.patch("asyncio.create_task")
        mock_echo_single_stream = mocker.patch(
            "pywebtransport.server.utils._echo_single_stream", new_callable=mocker.MagicMock
        )

        async def stream_generator() -> AsyncGenerator[Any, None]:
            yield mock_stream
            yield mock_stream

        mock_session.incoming_streams.return_value = stream_generator()

        await _echo_streams(mock_session)

        assert mock_echo_single_stream.call_count == 2
        mock_echo_single_stream.assert_called_with(mock_stream)
        assert mock_create_task.call_count == 2
        mock_create_task.assert_called_with(mock_echo_single_stream.return_value)

    async def test_echo_streams_handles_cancellation(self, mocker: MockerFixture, mock_session: Any) -> None:
        mock_create_task = mocker.patch("asyncio.create_task")

        async def cancelled_generator() -> AsyncGenerator[Any, None]:
            raise asyncio.CancelledError
            yield  # type: ignore[unreachable]

        mock_session.incoming_streams.return_value = cancelled_generator()

        await _echo_streams(mock_session)

        mock_create_task.assert_not_called()

    async def test_echo_streams_ignores_wrong_type(self, mocker: MockerFixture, mock_session: Any) -> None:
        mock_create_task = mocker.patch("asyncio.create_task")
        wrong_type_object = mocker.MagicMock()

        async def mixed_type_generator() -> AsyncGenerator[Any, None]:
            yield wrong_type_object

        mock_session.incoming_streams.return_value = mixed_type_generator()

        await _echo_streams(mock_session)

        mock_create_task.assert_not_called()

    async def test_echo_single_stream(self, mocker: MockerFixture, mock_stream: Any) -> None:
        stream_data = [b"chunk1", b"chunk2"]

        async def data_iterator() -> AsyncGenerator[bytes, None]:
            for data in stream_data:
                yield data

        mock_stream.read_iter.return_value = data_iterator()

        await _echo_single_stream(mock_stream)

        calls = [mocker.call(b"ECHO: " + data) for data in stream_data]
        mock_stream.write.assert_has_awaits(calls)
        mock_stream.close.assert_awaited_once()

    async def test_echo_single_stream_handles_write_exception(self, mocker: MockerFixture, mock_stream: Any) -> None:
        mock_logger = mocker.patch("pywebtransport.server.utils.logger")
        mock_stream.write.side_effect = IOError("Stream broken")

        async def data_iterator() -> AsyncGenerator[bytes, None]:
            yield b"data"

        mock_stream.read_iter.return_value = data_iterator()

        await _echo_single_stream(mock_stream)

        mock_logger.error.assert_called_once()
        assert "Stream broken" in mock_logger.error.call_args[0][0]
        mock_stream.close.assert_not_awaited()

    async def test_echo_single_stream_handles_read_exception(self, mocker: MockerFixture, mock_stream: Any) -> None:
        mock_logger = mocker.patch("pywebtransport.server.utils.logger")

        async def failing_iterator() -> AsyncGenerator[bytes, None]:
            yield b"this works"
            raise ValueError("Read failed")

        mock_stream.read_iter.return_value = failing_iterator()
        mock_stream.write = mocker.AsyncMock()

        await _echo_single_stream(mock_stream)

        mock_logger.error.assert_called_once()
        assert "Read failed" in mock_logger.error.call_args[0][0]
        mock_stream.write.assert_awaited_once_with(b"ECHO: this works")
        mock_stream.close.assert_not_awaited()
