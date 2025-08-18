"""Unit tests for the pywebtransport.server.utils module."""

import asyncio
from typing import Any, AsyncGenerator, cast

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


class FakeDatagramStream:
    def __init__(self, mocker: MockerFixture):
        self._mocker = mocker
        self.send_mock = self._mocker.AsyncMock()
        self.receive_mock = self._mocker.AsyncMock()

    async def send(self, data: bytes) -> None:
        await self.send_mock(data)

    async def receive(self) -> bytes:
        result = await self.receive_mock()
        return cast(bytes, result)


class FakeWebTransportSession(WebTransportSession):
    def __init__(self, mocker: MockerFixture):
        self._mocker = mocker
        self._datagram_stream = FakeDatagramStream(self._mocker)
        self._fake_incoming_streams: list[WebTransportStream] = []
        self.streams_iterator_error: type[BaseException] | None = None
        self.close_call_count = 0
        self.close_call_args: dict[str, Any] | None = None

    @property
    def session_id(self) -> str:
        return "fake-session-id"

    @property
    def is_closed(self) -> bool:
        return self.close_call_count > 0

    @property
    async def datagrams(self) -> Any:
        await asyncio.sleep(0)
        return self._datagram_stream

    async def close(self, *, code: int = 0, reason: str = "", close_connection: bool = True) -> None:
        self.close_call_count += 1
        self.close_call_args = {"code": code, "reason": reason, "close_connection": close_connection}
        await asyncio.sleep(0)

    async def incoming_streams(self) -> AsyncGenerator[Any, None]:
        if self.streams_iterator_error:
            raise self.streams_iterator_error

        for stream in self._fake_incoming_streams:
            await asyncio.sleep(0)
            yield stream


@pytest.fixture
def mock_session(mocker: MockerFixture) -> WebTransportSession:
    return FakeWebTransportSession(mocker)


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
        mock_server_config.assert_called_once_with(host=host, port=port, certfile=f"{host}.crt", keyfile=f"{host}.key")
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


class TestHandlers:
    @pytest.mark.asyncio
    async def test_health_check_handler_success(self, mock_session: WebTransportSession) -> None:
        fake_session = cast(FakeWebTransportSession, mock_session)

        await health_check_handler(mock_session)

        fake_session._datagram_stream.send_mock.assert_awaited_once_with(b'{"status": "healthy"}')
        assert fake_session.close_call_count == 1

    @pytest.mark.asyncio
    async def test_health_check_handler_send_fails(
        self, mocker: MockerFixture, mock_session: WebTransportSession
    ) -> None:
        fake_session = cast(FakeWebTransportSession, mock_session)
        mock_logger = mocker.patch("pywebtransport.server.utils.logger")
        fake_session._datagram_stream.send_mock.side_effect = ConnectionError("Send failed")

        await health_check_handler(mock_session)

        fake_session._datagram_stream.send_mock.assert_awaited_once()
        mock_logger.error.assert_called_once()
        assert fake_session.close_call_count == 1

    @pytest.mark.asyncio
    async def test_echo_handler_creates_tasks(self, mocker: MockerFixture, mock_session: WebTransportSession) -> None:
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

    @pytest.mark.asyncio
    async def test_echo_handler_exception(self, mocker: MockerFixture, mock_session: WebTransportSession) -> None:
        mock_logger = mocker.patch("pywebtransport.server.utils.logger")
        mocker.patch("asyncio.gather", new_callable=mocker.AsyncMock, side_effect=ValueError("Test Error"))
        mocker.patch("pywebtransport.server.utils._echo_datagrams")
        mocker.patch("pywebtransport.server.utils._echo_streams")

        await echo_handler(mock_session)

        mock_logger.error.assert_called_once()
        assert "Test Error" in mock_logger.error.call_args[0][0]


class TestEchoHelpers:
    @pytest.mark.asyncio
    async def test_echo_datagrams(self, mocker: MockerFixture, mock_session: WebTransportSession) -> None:
        fake_session = cast(FakeWebTransportSession, mock_session)
        received_data = [b"hello", b"world"]
        fake_session._datagram_stream.receive_mock.side_effect = received_data + [asyncio.CancelledError]

        await _echo_datagrams(mock_session)

        calls = [mocker.call(b"ECHO: " + data) for data in received_data]
        fake_session._datagram_stream.send_mock.assert_has_awaits(calls)
        assert fake_session._datagram_stream.receive_mock.await_count == len(received_data) + 1

    @pytest.mark.asyncio
    async def test_echo_datagrams_handles_cancellation(self, mock_session: WebTransportSession) -> None:
        fake_session = cast(FakeWebTransportSession, mock_session)
        fake_session._datagram_stream.receive_mock.side_effect = asyncio.CancelledError

        await _echo_datagrams(mock_session)

        fake_session._datagram_stream.send_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_echo_datagrams_handles_general_exception(self, mock_session: WebTransportSession) -> None:
        fake_session = cast(FakeWebTransportSession, mock_session)
        fake_session._datagram_stream.receive_mock.side_effect = ValueError("Receive failed")

        await _echo_datagrams(mock_session)

        fake_session._datagram_stream.send_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_echo_datagrams_handles_empty_data(self, mock_session: WebTransportSession) -> None:
        fake_session = cast(FakeWebTransportSession, mock_session)
        fake_session._datagram_stream.receive_mock.side_effect = [b"", asyncio.CancelledError]

        await _echo_datagrams(mock_session)

        fake_session._datagram_stream.send_mock.assert_not_awaited()
        assert fake_session._datagram_stream.receive_mock.await_count == 2

    @pytest.mark.asyncio
    async def test_echo_streams(
        self, mocker: MockerFixture, mock_session: WebTransportSession, mock_stream: Any
    ) -> None:
        fake_session = cast(FakeWebTransportSession, mock_session)
        mock_create_task = mocker.patch("asyncio.create_task")
        mock_echo_single_stream = mocker.patch(
            "pywebtransport.server.utils._echo_single_stream", new_callable=mocker.MagicMock
        )
        fake_session._fake_incoming_streams = [mock_stream, mock_stream]

        await _echo_streams(mock_session)

        assert mock_echo_single_stream.call_count == 2
        mock_echo_single_stream.assert_called_with(mock_stream)
        assert mock_create_task.call_count == 2
        mock_create_task.assert_called_with(mock_echo_single_stream.return_value)

    @pytest.mark.asyncio
    async def test_echo_streams_handles_cancellation(
        self, mocker: MockerFixture, mock_session: WebTransportSession
    ) -> None:
        fake_session = cast(FakeWebTransportSession, mock_session)
        mock_create_task = mocker.patch("asyncio.create_task")
        fake_session.streams_iterator_error = asyncio.CancelledError

        await _echo_streams(mock_session)

        mock_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_echo_streams_ignores_wrong_type(
        self, mocker: MockerFixture, mock_session: WebTransportSession
    ) -> None:
        fake_session = cast(FakeWebTransportSession, mock_session)
        mock_create_task = mocker.patch("asyncio.create_task")
        wrong_type_object = mocker.MagicMock()
        fake_session._fake_incoming_streams = [wrong_type_object]

        await _echo_streams(mock_session)

        mock_create_task.assert_not_called()

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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
