"""Unit tests for the pywebtransport.client.reconnecting module."""

import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest
from _pytest.logging import LogCaptureFixture
from pytest_mock import MockerFixture

from pywebtransport import (
    ClientConfig,
    ClientError,
    ConnectionError,
    EventType,
    TimeoutError,
    WebTransportClient,
    WebTransportSession,
)
from pywebtransport.client import ReconnectingClient
from pywebtransport.types import WebTransportProtocol


class TestReconnectingClient:
    URL = "https://example.com"

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> Any:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        session.is_ready = True
        session.protocol = mocker.MagicMock(spec=WebTransportProtocol)
        session.wait_closed = mocker.AsyncMock()
        return session

    @pytest.fixture
    def mock_underlying_client(self, mocker: MockerFixture, mock_session: Any) -> Any:
        client = mocker.MagicMock(spec=WebTransportClient)
        client.__aenter__ = mocker.AsyncMock(return_value=client)
        client.__aexit__ = mocker.AsyncMock()
        client.close = mocker.AsyncMock()
        client.connect = mocker.AsyncMock(return_value=mock_session)
        return client

    @pytest.fixture(autouse=True)
    def setup_client_mock(self, mocker: MockerFixture, mock_underlying_client: Any) -> None:
        mocker.patch("pywebtransport.client.reconnecting.WebTransportClient", return_value=mock_underlying_client)

    def test_create_factory(self, mocker: MockerFixture) -> None:
        mock_init = mocker.patch("pywebtransport.client.reconnecting.ReconnectingClient.__init__", return_value=None)
        mock_config = ClientConfig()

        ReconnectingClient.create(url=self.URL, config=mock_config)

        mock_init.assert_called_once_with(url=self.URL, config=mock_config)

    def test_init(self) -> None:
        config = ClientConfig()

        client = ReconnectingClient(url=self.URL, config=config)

        assert client._url == self.URL
        assert client._config is config
        assert client._client is None
        assert client._session is None
        assert client._closed is False
        assert client._is_initialized is False

    @pytest.mark.asyncio
    async def test_aenter_and_aexit_lifecycle(
        self, mocker: MockerFixture, mock_underlying_client: Any, mock_session: Any
    ) -> None:
        created_task: asyncio.Task[None]
        original_create_task = asyncio.create_task

        def spy_and_capture(coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
            nonlocal created_task
            task = original_create_task(coro)
            created_task = task
            return task

        mocker.patch("asyncio.create_task", side_effect=spy_and_capture)
        mock_session.wait_closed.side_effect = asyncio.CancelledError
        client = ReconnectingClient(url=self.URL, config=ClientConfig())

        async with client:
            assert client._is_initialized is True
            mock_underlying_client.__aenter__.assert_awaited_once()
            assert client._reconnect_task is created_task

        assert created_task.cancelled()
        mock_underlying_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_aenter_idempotency(self, mocker: MockerFixture) -> None:
        mock_create_task = mocker.patch("asyncio.create_task")
        client = ReconnectingClient(url=self.URL, config=ClientConfig())
        client._is_initialized = True

        await client.__aenter__()

        mock_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_idempotency(self, mock_underlying_client: Any) -> None:
        client = ReconnectingClient(url=self.URL, config=ClientConfig())
        async with client:
            pass

        await client.close()
        await client.close()

        mock_underlying_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_aenter_on_closed_client(self) -> None:
        client = ReconnectingClient(url=self.URL, config=ClientConfig())
        await client.close()

        with pytest.raises(ClientError, match="Client is already closed"):
            async with client:
                pass

    @pytest.mark.asyncio
    async def test_get_session_waits_and_succeeds(self, mocker: MockerFixture, mock_session: Any) -> None:
        client = ReconnectingClient(url=self.URL, config=ClientConfig())

        async def sleep_side_effect(*args: Any, **kwargs: Any) -> None:
            if mock_sleep.call_count == 3:
                client._session = mock_session

        mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock, side_effect=sleep_side_effect)

        session = await client.get_session(wait_timeout=0.5)

        assert session is mock_session
        assert mock_sleep.call_count == 3

    @pytest.mark.asyncio
    async def test_get_session_timeout(self, mocker: MockerFixture) -> None:
        mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        client = ReconnectingClient(url=self.URL, config=ClientConfig())

        session = await client.get_session(wait_timeout=0.1)

        assert session is None

    @pytest.mark.asyncio
    async def test_reconnect_loop_success_and_disconnect(
        self, mocker: MockerFixture, mock_underlying_client: Any, mock_session: Any, caplog: LogCaptureFixture
    ) -> None:
        first_connection_made = asyncio.Event()
        connection_lost = asyncio.Event()

        async def emit_side_effect(*, event_type: EventType, data: Any) -> None:
            if event_type == EventType.CONNECTION_ESTABLISHED:
                first_connection_made.set()
            elif event_type == EventType.CONNECTION_LOST:
                connection_lost.set()

        mock_underlying_client.connect.side_effect = [mock_session, ConnectionError("Reconnect failed")]
        mock_session.wait_closed.return_value = None
        mock_emit = mocker.patch.object(ReconnectingClient, "emit", new_callable=mocker.AsyncMock)
        mock_emit.side_effect = emit_side_effect
        config = ClientConfig(max_retries=0, retry_delay=0.01)
        client = ReconnectingClient(url=self.URL, config=config)

        async with client:
            await asyncio.wait_for(first_connection_made.wait(), timeout=1)
            await asyncio.wait_for(connection_lost.wait(), timeout=1)

        mock_emit.assert_any_call(
            event_type=EventType.CONNECTION_ESTABLISHED, data={"session": mock_session, "attempt": 1}
        )
        mock_session.wait_closed.assert_awaited_once()
        mock_emit.assert_any_call(event_type=EventType.CONNECTION_LOST, data={"url": self.URL})
        assert f"Connection to {self.URL} lost, attempting to reconnect..." in caplog.text

    @pytest.mark.asyncio
    async def test_reconnect_loop_with_backoff(
        self, mocker: MockerFixture, mock_underlying_client: Any, mock_session: Any
    ) -> None:
        connection_established = asyncio.Event()
        mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        mock_emit = mocker.patch.object(ReconnectingClient, "emit", new_callable=mocker.AsyncMock)
        mock_emit.side_effect = lambda *args, **kwargs: connection_established.set()
        mock_session.wait_closed.side_effect = asyncio.CancelledError
        config = ClientConfig(retry_delay=0.1, retry_backoff=2.0, max_retry_delay=1.0)
        client = ReconnectingClient(url=self.URL, config=config)
        mock_underlying_client.connect.side_effect = [
            TimeoutError("Fail 1"),
            ConnectionError("Fail 2"),
            mock_session,
        ]

        async with client:
            await asyncio.wait_for(connection_established.wait(), timeout=1)

        assert mock_underlying_client.connect.call_count == 3
        mock_sleep.assert_has_awaits([mocker.call(0.1), mocker.call(0.2)])
        mock_emit.assert_awaited_once_with(
            event_type=EventType.CONNECTION_ESTABLISHED, data={"session": mock_session, "attempt": 3}
        )

    @pytest.mark.asyncio
    async def test_reconnect_loop_max_retries_exceeded(
        self, mocker: MockerFixture, mock_underlying_client: Any
    ) -> None:
        failed_event = asyncio.Event()
        mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        mock_emit = mocker.patch.object(ReconnectingClient, "emit", new_callable=mocker.AsyncMock)
        mock_emit.side_effect = lambda *args, **kwargs: failed_event.set()
        config = ClientConfig(max_retries=2, retry_delay=0.01)
        client = ReconnectingClient(url=self.URL, config=config)
        mock_underlying_client.connect.side_effect = ClientError("Failed")

        async with client:
            await asyncio.wait_for(failed_event.wait(), timeout=1)

        assert mock_underlying_client.connect.call_count == 3
        mock_emit.assert_awaited_once_with(
            event_type=EventType.CONNECTION_FAILED,
            data={"reason": "max_retries_exceeded", "last_error": "[0x1004] Failed"},
        )

    @pytest.mark.asyncio
    async def test_reconnect_loop_infinite_retries(
        self, mocker: MockerFixture, mock_underlying_client: Any, mock_session: Any
    ) -> None:
        connection_established = asyncio.Event()
        mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        mock_emit = mocker.patch.object(ReconnectingClient, "emit", new_callable=mocker.AsyncMock)
        mock_emit.side_effect = lambda *args, **kwargs: connection_established.set()
        mock_session.wait_closed.side_effect = asyncio.CancelledError
        config = ClientConfig(retry_delay=0.01)
        mocker.patch.object(config, "max_retries", -1)
        client = ReconnectingClient(url=self.URL, config=config)
        errors = [ConnectionError("Fail")] * 5
        mock_underlying_client.connect.side_effect = [*errors, mock_session]

        async with client:
            await asyncio.wait_for(connection_established.wait(), timeout=1)

        assert mock_underlying_client.connect.call_count == 6
