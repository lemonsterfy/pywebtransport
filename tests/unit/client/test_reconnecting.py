"""Unit tests for the pywebtransport.client.reconnecting module."""

import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest
from _pytest.logging import LogCaptureFixture
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig, ClientError, ConnectionError, WebTransportSession
from pywebtransport.client import ReconnectingClient, WebTransportClient


class TestReconnectingClient:
    URL = "https://example.com"

    @pytest.fixture
    def mock_client_config(self, mocker: MockerFixture) -> Any:
        return mocker.MagicMock(spec=ClientConfig)

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> Any:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        session.is_ready = True
        return session

    @pytest.fixture
    def mock_underlying_client(self, mocker: MockerFixture) -> Any:
        client = mocker.create_autospec(WebTransportClient, instance=True)
        client.__aenter__.return_value = client
        client.close = mocker.AsyncMock()
        return client

    @pytest.fixture(autouse=True)
    def setup_mocks(self, mocker: MockerFixture, mock_underlying_client: Any) -> None:
        mocker.patch(
            "pywebtransport.client.reconnecting.WebTransportClient.create",
            return_value=mock_underlying_client,
        )
        mocker.patch("pywebtransport.client.reconnecting.ClientConfig.create")

    def test_create_factory(self, mocker: MockerFixture) -> None:
        mock_init = mocker.patch("pywebtransport.client.reconnecting.ReconnectingClient.__init__", return_value=None)
        mock_config = mocker.MagicMock(spec=ClientConfig)

        ReconnectingClient.create(self.URL, config=mock_config, max_retries=10, retry_delay=0.5, backoff_factor=1.5)

        mock_init.assert_called_once_with(
            self.URL, config=mock_config, max_retries=10, retry_delay=0.5, backoff_factor=1.5
        )

    def test_init_with_infinite_retries(self, mocker: MockerFixture) -> None:
        client = ReconnectingClient(self.URL, max_retries=-1)

        assert client._max_retries == float("inf")

    @pytest.mark.asyncio
    async def test_aenter_and_aexit(self, mocker: MockerFixture, mock_underlying_client: Any) -> None:
        created_task: asyncio.Task[None]
        original_create_task = asyncio.create_task

        def spy_and_capture(coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
            nonlocal created_task
            task = original_create_task(coro)
            created_task = task
            return task

        mocker.patch("asyncio.create_task", side_effect=spy_and_capture)
        client = ReconnectingClient(self.URL)
        mocker.patch.object(client, "_reconnect_loop", new_callable=mocker.AsyncMock)

        async with client:
            mock_underlying_client.__aenter__.assert_awaited_once()
            assert client._reconnect_task is created_task

        assert created_task.cancelled()
        mock_underlying_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_idempotency(self, mock_underlying_client: Any) -> None:
        client = ReconnectingClient(self.URL)
        client._reconnect_task = asyncio.create_task(asyncio.sleep(0))

        await client.close()
        await client.close()

        mock_underlying_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_without_starting(self, mock_underlying_client: Any) -> None:
        client = ReconnectingClient(self.URL)
        assert client._reconnect_task is None

        await client.close()

        mock_underlying_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_session_when_connected(self, mock_session: Any) -> None:
        client = ReconnectingClient(self.URL)
        client._session = mock_session

        session = await client.get_session()

        assert session is mock_session

    @pytest.mark.asyncio
    async def test_get_session_waits_for_connection(self, mocker: MockerFixture, mock_session: Any) -> None:
        client = ReconnectingClient(self.URL)

        async def sleep_side_effect(*args: Any, **kwargs: Any) -> None:
            if mock_sleep.call_count == 3:
                client._session = mock_session

        mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock, side_effect=sleep_side_effect)

        session = await client.get_session()

        assert session is mock_session
        assert mock_sleep.call_count == 3

    @pytest.mark.asyncio
    async def test_reconnect_loop_success_and_disconnect(self, mock_underlying_client: Any, mock_session: Any) -> None:
        mock_underlying_client.connect.return_value = mock_session
        mock_session.wait_closed.side_effect = asyncio.CancelledError
        client = ReconnectingClient(self.URL)

        await client._reconnect_loop()

        mock_underlying_client.connect.assert_awaited_once_with(self.URL)
        mock_session.wait_closed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reconnect_loop_logs_on_unexpected_disconnect(
        self, mock_underlying_client: Any, mock_session: Any, caplog: LogCaptureFixture
    ) -> None:
        mock_underlying_client.connect.side_effect = [mock_session, ConnectionError("Reconnect failed")]
        mock_session.wait_closed.return_value = None
        client = ReconnectingClient(self.URL, max_retries=0)

        await client._reconnect_loop()

        assert f"Connection to {self.URL} lost, attempting to reconnect..." in caplog.text

    @pytest.mark.asyncio
    async def test_reconnect_loop_with_backoff(
        self, mocker: MockerFixture, mock_underlying_client: Any, mock_session: Any
    ) -> None:
        mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        client = ReconnectingClient(self.URL, retry_delay=0.1, backoff_factor=2.0)
        mock_emit = mocker.patch.object(client, "emit", new_callable=mocker.AsyncMock)
        mock_underlying_client.connect.side_effect = [
            ConnectionError("Fail 1"),
            ConnectionError("Fail 2"),
            mock_session,
        ]
        mock_session.wait_closed.side_effect = asyncio.CancelledError

        await client._reconnect_loop()

        assert mock_underlying_client.connect.call_count == 3
        mock_sleep.assert_has_awaits([mocker.call(0.1), mocker.call(0.2)])
        mock_emit.assert_awaited_once_with("reconnected", data={"session": mock_session})

    @pytest.mark.asyncio
    async def test_reconnect_loop_max_retries_exceeded(
        self, mocker: MockerFixture, mock_underlying_client: Any
    ) -> None:
        mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        client = ReconnectingClient(self.URL, max_retries=2)
        mock_emit = mocker.patch.object(client, "emit", new_callable=mocker.AsyncMock)
        mock_underlying_client.connect.side_effect = ConnectionError("Failed")

        await client._reconnect_loop()

        assert mock_underlying_client.connect.call_count == 3
        mock_emit.assert_awaited_once_with("failed", data={"reason": "max_retries_exceeded"})

    @pytest.mark.asyncio
    async def test_reconnect_loop_exits_gracefully_on_close(
        self, mocker: MockerFixture, mock_underlying_client: Any, mock_session: Any
    ) -> None:
        mock_logger_warning = mocker.patch("pywebtransport.client.reconnecting.logger.warning")
        mock_underlying_client.connect.return_value = mock_session
        client = ReconnectingClient(self.URL)
        mock_session.wait_closed = mocker.AsyncMock(side_effect=lambda: setattr(client, "_closed", True))

        await client._reconnect_loop()

        mock_logger_warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_aenter_on_closed_client(self, mocker: MockerFixture) -> None:
        client = ReconnectingClient(self.URL)
        mocker.patch.object(client, "_reconnect_loop", new_callable=mocker.AsyncMock)
        await client.close()

        with pytest.raises(ClientError, match="Client is already closed"):
            async with client:
                pass

    @pytest.mark.asyncio
    async def test_get_session_timeout(self, mocker: MockerFixture) -> None:
        mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        client = ReconnectingClient(self.URL)

        session = await client.get_session()

        assert session is None
