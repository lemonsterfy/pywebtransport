"""Unit tests for the pywebtransport.client.reconnecting module."""

import asyncio
from collections.abc import Coroutine
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from _pytest.logging import LogCaptureFixture
from pytest_mock import MockerFixture

from pywebtransport import (
    ClientConfig,
    ClientError,
    ConnectionError,
    TimeoutError,
    WebTransportClient,
    WebTransportSession,
)
from pywebtransport.client import ReconnectingClient
from pywebtransport.types import EventType, SessionState


class TestReconnectingClient:
    URL = "https://example.com"

    @pytest.fixture
    def client(self, mock_underlying_client: Any) -> ReconnectingClient:
        return ReconnectingClient(url=self.URL, client=mock_underlying_client)

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> Any:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        type(session).state = mocker.PropertyMock(return_value=SessionState.CONNECTED)
        session.is_closed = False
        session.close = mocker.AsyncMock(return_value=None)
        session.events = mocker.MagicMock()
        session.events.wait_for = mocker.AsyncMock()
        return session

    @pytest.fixture
    def mock_underlying_client(self, mocker: MockerFixture, mock_session: Any) -> Any:
        client = mocker.create_autospec(WebTransportClient, instance=True)
        client.connect = mocker.AsyncMock(return_value=mock_session)
        client.config = ClientConfig()
        return client

    @pytest.mark.asyncio
    async def test_aenter_and_aexit_lifecycle(self, client: ReconnectingClient, mocker: MockerFixture) -> None:
        created_task: asyncio.Task[None]
        original_create_task = asyncio.create_task

        def spy_and_capture(coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
            nonlocal created_task
            task = original_create_task(coro)
            created_task = task
            return task

        mocker.patch("asyncio.create_task", side_effect=spy_and_capture)
        connect_mock = cast(MagicMock, client._client.connect)
        connect_mock.side_effect = asyncio.CancelledError

        async with client:
            assert client._is_initialized is True
            assert client._reconnect_task is created_task
            assert not created_task.done()

        await asyncio.sleep(delay=0)
        assert created_task.cancelled()

    @pytest.mark.asyncio
    async def test_aenter_is_idempotent(self, client: ReconnectingClient, mocker: MockerFixture) -> None:
        reconnect_loop_mock = mocker.patch.object(client, "_reconnect_loop", new_callable=mocker.AsyncMock)

        async with client:
            reconnect_loop_mock.assert_called_once()
            async with client as new_client:
                assert new_client is client
            reconnect_loop_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_aenter_on_closed_client(self, client: ReconnectingClient) -> None:
        await client.close()
        with pytest.raises(ClientError, match="Client is already closed"):
            async with client:
                pass

    @pytest.mark.asyncio
    async def test_aexit_closes_on_exception(self, client: ReconnectingClient, mocker: MockerFixture) -> None:
        close_spy = mocker.spy(client, "close")
        connect_mock = cast(MagicMock, client._client.connect)
        connect_mock.side_effect = asyncio.CancelledError

        with pytest.raises(RuntimeError, match="Test exception"):
            async with client:
                raise RuntimeError("Test exception")

        close_spy.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_idempotency(self, client: ReconnectingClient, mocker: MockerFixture) -> None:
        mocker.patch.object(client, "_reconnect_loop", new_callable=mocker.AsyncMock)

        await client.__aenter__()
        assert client._reconnect_task is not None
        cancel_spy = mocker.spy(client._reconnect_task, "cancel")

        await client.close()
        cancel_spy.assert_called_once()

        await client.close()
        cancel_spy.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_with_active_session(
        self, client: ReconnectingClient, mock_session: Any, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(client, "_reconnect_loop", new_callable=mocker.AsyncMock)
        async with client:
            client._session = mock_session
            await client.close()
            mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_session_on_closed_client(self, client: ReconnectingClient) -> None:
        await client.close()
        session = await client.get_session()
        assert session is None

    @pytest.mark.asyncio
    async def test_get_session_succeeds_when_connected(self, client: ReconnectingClient, mock_session: Any) -> None:
        client._session = mock_session
        client._connected_event = asyncio.Event()
        client._connected_event.set()

        session = await client.get_session(wait_timeout=0.1)

        assert session is mock_session

    @pytest.mark.asyncio
    async def test_get_session_timeout(
        self, client: ReconnectingClient, mock_underlying_client: Any, mocker: MockerFixture
    ) -> None:
        mock_underlying_client.connect.side_effect = TimeoutError("Connection timed out")
        mock_underlying_client.config.max_retries = 0

        async with client:
            session = await client.get_session(wait_timeout=0.01)

        assert session is None

    @pytest.mark.asyncio
    async def test_get_session_waits_and_succeeds(self, client: ReconnectingClient, mock_session: Any) -> None:
        session_closed_event = asyncio.Event()

        async def wait_forever(*args: Any, **kwargs: Any) -> None:
            await session_closed_event.wait()

        mock_session.events.wait_for.side_effect = wait_forever

        async with client:
            session = await client.get_session(wait_timeout=1.0)

        assert session is mock_session

    def test_init(self, mock_underlying_client: Any) -> None:
        client = ReconnectingClient(url=self.URL, client=mock_underlying_client)

        assert client._url == self.URL
        assert client._client is mock_underlying_client
        assert client._config is mock_underlying_client.config
        assert client._session is None
        assert client._closed is False
        assert client._is_initialized is False

    @pytest.mark.parametrize(
        ("session_state", "event_is_set", "expected"),
        [
            (SessionState.CONNECTED, True, True),
            (SessionState.CONNECTING, True, False),
            (SessionState.CONNECTED, False, False),
        ],
    )
    def test_is_connected_property(
        self,
        client: ReconnectingClient,
        mock_session: Any,
        mocker: MockerFixture,
        session_state: SessionState,
        event_is_set: bool,
        expected: bool,
    ) -> None:
        type(mock_session).state = mocker.PropertyMock(return_value=session_state)
        client._session = mock_session
        client._connected_event = asyncio.Event()
        if event_is_set:
            client._connected_event.set()

        assert client.is_connected is expected

    def test_is_connected_property_when_uninitialized(self, client: ReconnectingClient) -> None:
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_no_reconnect_if_explicitly_closed(
        self, mock_underlying_client: Any, mock_session: Any, mocker: MockerFixture
    ) -> None:
        loop_is_waiting = asyncio.Event()
        closed_future: asyncio.Future[None] = asyncio.Future()

        async def wait_closed_side_effect(*args: Any, **kwargs: Any) -> None:
            loop_is_waiting.set()
            await closed_future

        mock_session.events.wait_for.side_effect = wait_closed_side_effect
        mock_underlying_client.connect.return_value = mock_session
        client = ReconnectingClient(url=self.URL, client=mock_underlying_client)
        emit_spy = mocker.spy(client, "emit")

        await client.__aenter__()
        async with asyncio.timeout(delay=1):
            await loop_is_waiting.wait()

        client._closed = True
        closed_future.set_result(None)
        await asyncio.sleep(delay=0)

        connection_lost_emitted = any(
            call.kwargs["event_type"] == EventType.CONNECTION_LOST for call in emit_spy.call_args_list
        )
        assert not connection_lost_emitted
        await client.close()

    @pytest.mark.asyncio
    async def test_reconnect_loop_cancels_during_sleep(
        self, mock_underlying_client: Any, mocker: MockerFixture
    ) -> None:
        sleep_started = asyncio.Event()
        config = ClientConfig(retry_delay=10, max_retries=1)
        mock_underlying_client.config = config
        mock_underlying_client.connect.side_effect = ConnectionError("Failed to connect")

        original_sleep = asyncio.sleep

        async def sleep_side_effect(delay: float) -> Any:
            sleep_started.set()
            await original_sleep(delay=delay)

        mocker.patch("asyncio.sleep", side_effect=sleep_side_effect)
        client = ReconnectingClient(url=self.URL, client=mock_underlying_client)

        async with client:
            async with asyncio.timeout(delay=1):
                await sleep_started.wait()
            assert client._reconnect_task
            client._reconnect_task.cancel()

    @pytest.mark.asyncio
    async def test_reconnect_loop_delay_capping(
        self, mock_underlying_client: Any, mock_session: Any, mocker: MockerFixture
    ) -> None:
        connection_established = asyncio.Event()
        mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        config = ClientConfig(retry_delay=0.1, retry_backoff=2.0, max_retry_delay=0.15)
        mock_underlying_client.config = config
        client = ReconnectingClient(url=self.URL, client=mock_underlying_client)
        mock_emit = mocker.patch.object(client, "emit", new_callable=mocker.AsyncMock)
        mock_emit.side_effect = lambda *args, **kwargs: connection_established.set()

        mock_session.events.wait_for.side_effect = asyncio.CancelledError

        mock_underlying_client.connect.side_effect = [
            ConnectionError(message="Fail 1"),
            ConnectionError(message="Fail 2"),
            mock_session,
        ]

        async with client:
            async with asyncio.timeout(delay=1):
                await connection_established.wait()

        mock_sleep.assert_has_awaits([mocker.call(delay=0.1), mocker.call(delay=0.15)])

    @pytest.mark.asyncio
    async def test_reconnect_loop_finally_branch_when_event_is_none(
        self, client: ReconnectingClient, mock_underlying_client: Any, mocker: MockerFixture
    ) -> None:
        """Test the finally block in reconnect loop when connected_event is None."""
        ready_to_cancel = asyncio.Event()

        async def connect_side_effect(*args: Any, **kwargs: Any) -> Any:
            ready_to_cancel.set()
            await asyncio.sleep(delay=10)
            return MagicMock()

        mock_underlying_client.connect.side_effect = connect_side_effect

        async with client:
            async with asyncio.timeout(delay=1.0):
                await ready_to_cancel.wait()
            client._connected_event = None

    @pytest.mark.asyncio
    async def test_reconnect_loop_max_retries_exceeded(
        self, mock_underlying_client: Any, mocker: MockerFixture
    ) -> None:
        failed_event = asyncio.Event()
        mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        config = ClientConfig(max_retries=2, retry_delay=0.01)
        mock_underlying_client.config = config
        client = ReconnectingClient(url=self.URL, client=mock_underlying_client)
        mock_emit = mocker.patch.object(client, "emit", new_callable=mocker.AsyncMock)

        async def emit_side_effect(*, event_type: EventType, data: Any) -> None:
            if event_type == EventType.CONNECTION_FAILED:
                failed_event.set()

        mock_emit.side_effect = emit_side_effect
        mock_underlying_client.connect.side_effect = ClientError(message="Failed")

        async with client:
            async with asyncio.timeout(delay=1):
                await failed_event.wait()

        assert mock_underlying_client.connect.call_count == 3
        mock_emit.assert_awaited_with(
            event_type=EventType.CONNECTION_FAILED,
            data={"reason": "max_retries_exceeded", "last_error": str(ClientError(message="Failed"))},
        )

    @pytest.mark.asyncio
    async def test_reconnect_loop_retries_multiple_times(
        self, mock_underlying_client: Any, mock_session: Any, mocker: MockerFixture
    ) -> None:
        connection_established = asyncio.Event()
        mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        config = ClientConfig(retry_delay=0.01, max_retries=5)
        mock_underlying_client.config = config
        client = ReconnectingClient(url=self.URL, client=mock_underlying_client)
        mock_emit = mocker.patch.object(client, "emit", new_callable=mocker.AsyncMock)
        mock_emit.side_effect = lambda *args, **kwargs: connection_established.set()
        mock_session.events.wait_for.side_effect = asyncio.CancelledError
        errors = [ConnectionError(message="Fail")] * 5
        mock_underlying_client.connect.side_effect = [*errors, mock_session]

        async with client:
            async with asyncio.timeout(delay=1):
                await connection_established.wait()

        assert mock_underlying_client.connect.call_count == 6
        assert mock_sleep.call_count == 5

    @pytest.mark.asyncio
    async def test_reconnect_loop_success_and_disconnect(
        self, mock_underlying_client: Any, mock_session: Any, caplog: LogCaptureFixture, mocker: MockerFixture
    ) -> None:
        first_connection_made = asyncio.Event()
        connection_lost = asyncio.Event()
        closed_future: asyncio.Future[None] = asyncio.Future()

        async def wait_for_side_effect(*args: Any, **kwargs: Any) -> None:
            await closed_future

        mock_session.events.wait_for.side_effect = wait_for_side_effect

        mock_underlying_client.connect.side_effect = [mock_session, ConnectionError(message="Reconnect failed")]
        config = ClientConfig(max_retries=0, retry_delay=0.01)
        mock_underlying_client.config = config
        client = ReconnectingClient(url=self.URL, client=mock_underlying_client)
        mock_emit = mocker.patch.object(client, "emit", new_callable=mocker.AsyncMock)

        async def emit_side_effect(*, event_type: EventType, data: Any) -> None:
            if event_type == EventType.CONNECTION_ESTABLISHED:
                first_connection_made.set()
            elif event_type == EventType.CONNECTION_LOST:
                connection_lost.set()

        mock_emit.side_effect = emit_side_effect

        async with client:
            async with asyncio.timeout(delay=1):
                await first_connection_made.wait()
            mock_session.events.wait_for.assert_called()
            closed_future.set_result(None)
            async with asyncio.timeout(delay=1):
                await connection_lost.wait()

        mock_emit.assert_any_call(
            event_type=EventType.CONNECTION_ESTABLISHED, data={"session": mock_session, "attempt": 1}
        )
        mock_emit.assert_any_call(event_type=EventType.CONNECTION_LOST, data={"url": self.URL})
        assert f"Connection to {self.URL} lost, attempting to reconnect..." in caplog.text

    @pytest.mark.asyncio
    async def test_reconnect_loop_uninitialized(self, client: ReconnectingClient, caplog: LogCaptureFixture) -> None:
        await client._reconnect_loop()
        assert "Reconnection loop started before client was properly initialized." in caplog.text

    @pytest.mark.asyncio
    async def test_reconnect_loop_with_backoff(
        self, mock_underlying_client: Any, mock_session: Any, mocker: MockerFixture
    ) -> None:
        connection_established = asyncio.Event()
        mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        config = ClientConfig(retry_delay=0.1, retry_backoff=2.0, max_retry_delay=1.0)
        mock_underlying_client.config = config
        client = ReconnectingClient(url=self.URL, client=mock_underlying_client)
        mock_emit = mocker.patch.object(client, "emit", new_callable=mocker.AsyncMock)
        mock_emit.side_effect = lambda *args, **kwargs: connection_established.set()
        mock_session.events.wait_for.side_effect = asyncio.CancelledError
        mock_underlying_client.connect.side_effect = [
            TimeoutError(message="Fail 1"),
            ConnectionError(message="Fail 2"),
            mock_session,
        ]

        async with client:
            async with asyncio.timeout(delay=1):
                await connection_established.wait()

        assert mock_underlying_client.connect.call_count == 3
        mock_sleep.assert_has_awaits([mocker.call(delay=0.1), mocker.call(delay=0.2)])
        mock_emit.assert_awaited_once_with(
            event_type=EventType.CONNECTION_ESTABLISHED, data={"session": mock_session, "attempt": 3}
        )
