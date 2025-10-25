"""Unit tests for the pywebtransport.protocol._pending_event_manager module."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig
from pywebtransport.constants import ErrorCodes
from pywebtransport.protocol._pending_event_manager import _PendingEventManager
from pywebtransport.protocol.events import DatagramReceived, WebTransportStreamDataReceived


@pytest.fixture
def manager(
    mock_config: MagicMock,
    mock_abort_stream: MagicMock,
    mock_process_buffered_events: AsyncMock,
) -> _PendingEventManager:
    return _PendingEventManager(
        config=mock_config,
        abort_stream=mock_abort_stream,
        process_buffered_events=mock_process_buffered_events,
    )


@pytest.fixture
def mock_abort_stream() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_config() -> MagicMock:
    config = MagicMock(spec=ClientConfig)
    config.pending_event_ttl = 10
    config.max_total_pending_events = 100
    config.max_pending_events_per_session = 10
    return config


@pytest.fixture
def mock_process_buffered_events() -> AsyncMock:
    return AsyncMock()


class TestPendingEventManager:
    def test_buffer_event_disabled(self, manager: _PendingEventManager, mock_config: MagicMock) -> None:
        mock_config.pending_event_ttl = 0
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"", stream_ended=False)
        result = manager.buffer_event(session_stream_id=0, event=event)

        assert result is False
        assert manager._pending_events_count == 0

    def test_buffer_event_global_limit_not_stream_data(
        self,
        manager: _PendingEventManager,
        mock_config: MagicMock,
        mock_abort_stream: MagicMock,
    ) -> None:
        mock_config.max_total_pending_events = 0
        event = DatagramReceived(stream_id=0, data=b"")
        result = manager.buffer_event(session_stream_id=0, event=event)

        assert result is False
        mock_abort_stream.assert_not_called()

    def test_buffer_event_global_limit_reached(
        self,
        manager: _PendingEventManager,
        mock_config: MagicMock,
        mock_abort_stream: MagicMock,
    ) -> None:
        mock_config.max_total_pending_events = 0
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"", stream_ended=False)
        result = manager.buffer_event(session_stream_id=0, event=event)

        assert result is False
        mock_abort_stream.assert_called_once_with(stream_id=4, error_code=ErrorCodes.WT_BUFFERED_STREAM_REJECTED)

    def test_buffer_event_session_limit_not_stream_data(
        self,
        manager: _PendingEventManager,
        mock_config: MagicMock,
        mock_abort_stream: MagicMock,
    ) -> None:
        mock_config.max_pending_events_per_session = 0
        event = DatagramReceived(stream_id=0, data=b"")
        result = manager.buffer_event(session_stream_id=0, event=event)

        assert result is False
        mock_abort_stream.assert_not_called()

    def test_buffer_event_session_limit_reached(
        self,
        manager: _PendingEventManager,
        mock_config: MagicMock,
        mock_abort_stream: MagicMock,
    ) -> None:
        mock_config.max_pending_events_per_session = 0
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"", stream_ended=False)
        result = manager.buffer_event(session_stream_id=0, event=event)

        assert result is False
        mock_abort_stream.assert_called_once_with(stream_id=4, error_code=ErrorCodes.WT_BUFFERED_STREAM_REJECTED)

    def test_buffer_event_success(self, manager: _PendingEventManager) -> None:
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"", stream_ended=False)
        result = manager.buffer_event(session_stream_id=0, event=event)

        assert result is True
        assert manager._pending_events_count == 1
        assert manager._pending_events[0][0][1] is event

    @pytest.mark.asyncio
    async def test_cleanup_loop(
        self,
        manager: _PendingEventManager,
        mock_config: MagicMock,
        mock_abort_stream: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        mocker.patch(
            "pywebtransport.protocol._pending_event_manager.get_timestamp",
            side_effect=[0, 0, 11],
        )
        mock_sleep = mocker.patch("asyncio.sleep", side_effect=asyncio.CancelledError)
        stream_event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"", stream_ended=False)
        other_event = DatagramReceived(stream_id=0, data=b"")
        manager.buffer_event(session_stream_id=0, event=stream_event)
        manager.buffer_event(session_stream_id=0, event=other_event)

        try:
            await manager._cleanup_pending_events_loop()
        except asyncio.CancelledError:
            pass

        mock_sleep.assert_awaited_once_with(mock_config.pending_event_ttl)
        assert not manager._pending_events
        mock_abort_stream.assert_called_once_with(stream_id=4, error_code=ErrorCodes.WT_BUFFERED_STREAM_REJECTED)

    @pytest.mark.asyncio
    async def test_close(self, manager: _PendingEventManager) -> None:
        task = asyncio.create_task(asyncio.sleep(10))
        manager._cleanup_pending_events_task = task

        await manager.close()

        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_close_no_task(self, manager: _PendingEventManager) -> None:
        await manager.close()

    @pytest.mark.asyncio
    async def test_process_pending_events(
        self, manager: _PendingEventManager, mock_process_buffered_events: AsyncMock
    ) -> None:
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"", stream_ended=False)
        manager.buffer_event(session_stream_id=0, event=event)
        manager.process_pending_events(connect_stream_id=0)
        await asyncio.sleep(0)

        mock_process_buffered_events.assert_awaited_once()
        assert not manager._pending_events
        assert manager._pending_events_count == 0

    def test_process_pending_events_no_events(
        self, manager: _PendingEventManager, mock_process_buffered_events: AsyncMock
    ) -> None:
        manager.process_pending_events(connect_stream_id=99)
        mock_process_buffered_events.assert_not_awaited()

    def test_start(self, manager: _PendingEventManager, mocker: MockerFixture) -> None:
        mock_task = MagicMock()
        mock_create_task = mocker.patch("asyncio.create_task", return_value=mock_task)
        manager.start()

        mock_create_task.assert_called_once()
        coro = mock_create_task.call_args[0][0]
        coro.close()
        assert manager._cleanup_pending_events_task is mock_task

    def test_start_disabled(self, manager: _PendingEventManager, mock_config: MagicMock, mocker: MockerFixture) -> None:
        mock_config.pending_event_ttl = 0
        mock_create_task = mocker.patch("asyncio.create_task")
        manager.start()
        mock_create_task.assert_not_called()
