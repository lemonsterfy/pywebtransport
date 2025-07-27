"""Unit tests for the pywebtransport.datagram.broadcaster module."""

import asyncio
from typing import Any

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ConnectionError, WebTransportDatagramDuplexStream
from pywebtransport.datagram import DatagramBroadcaster


@pytest.fixture
def mock_stream(mocker: MockerFixture) -> Any:
    stream = mocker.create_autospec(WebTransportDatagramDuplexStream, instance=True)
    stream.send = mocker.AsyncMock()
    type(stream).is_closed = mocker.PropertyMock(return_value=False)
    return stream


@pytest.fixture
def broadcaster() -> DatagramBroadcaster:
    return DatagramBroadcaster.create()


class TestDatagramBroadcaster:
    @pytest.mark.asyncio
    async def test_create(self) -> None:
        b = DatagramBroadcaster.create()
        assert isinstance(b, DatagramBroadcaster)
        assert await b.get_stream_count() == 0

    @pytest.mark.asyncio
    async def test_add_stream(self, broadcaster: DatagramBroadcaster, mock_stream: Any) -> None:
        assert await broadcaster.get_stream_count() == 0
        await broadcaster.add_stream(mock_stream)
        assert await broadcaster.get_stream_count() == 1

    @pytest.mark.asyncio
    async def test_add_stream_idempotent(self, broadcaster: DatagramBroadcaster, mock_stream: Any) -> None:
        await broadcaster.add_stream(mock_stream)
        await broadcaster.add_stream(mock_stream)
        assert await broadcaster.get_stream_count() == 1

    @pytest.mark.asyncio
    async def test_remove_stream(self, broadcaster: DatagramBroadcaster, mock_stream: Any) -> None:
        await broadcaster.add_stream(mock_stream)
        assert await broadcaster.get_stream_count() == 1
        await broadcaster.remove_stream(mock_stream)
        assert await broadcaster.get_stream_count() == 0

    @pytest.mark.asyncio
    async def test_remove_nonexistent_stream(self, broadcaster: DatagramBroadcaster, mock_stream: Any) -> None:
        assert await broadcaster.get_stream_count() == 0
        await broadcaster.remove_stream(mock_stream)
        assert await broadcaster.get_stream_count() == 0

    @pytest.mark.asyncio
    async def test_broadcast_empty(self, broadcaster: DatagramBroadcaster) -> None:
        sent_count = await broadcaster.broadcast(b"data")
        assert sent_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_success_all(
        self, broadcaster: DatagramBroadcaster, mock_stream: Any, mocker: MockerFixture
    ) -> None:
        stream1 = mock_stream
        stream2 = mocker.create_autospec(WebTransportDatagramDuplexStream, instance=True)
        stream2.send = mocker.AsyncMock()
        type(stream2).is_closed = mocker.PropertyMock(return_value=False)

        await broadcaster.add_stream(stream1)
        await broadcaster.add_stream(stream2)

        sent_count = await broadcaster.broadcast(b"ping", priority=1, ttl=10.0)

        assert sent_count == 2
        stream1.send.assert_awaited_once_with(b"ping", priority=1, ttl=10.0)
        stream2.send.assert_awaited_once_with(b"ping", priority=1, ttl=10.0)
        assert await broadcaster.get_stream_count() == 2

    @pytest.mark.asyncio
    async def test_broadcast_with_pre_closed_stream(
        self, broadcaster: DatagramBroadcaster, mock_stream: Any, mocker: MockerFixture
    ) -> None:
        healthy_stream = mock_stream
        closed_stream = mocker.create_autospec(WebTransportDatagramDuplexStream, instance=True)
        closed_stream.send = mocker.AsyncMock()
        type(closed_stream).is_closed = mocker.PropertyMock(return_value=True)

        await broadcaster.add_stream(healthy_stream)
        await broadcaster.add_stream(closed_stream)
        assert await broadcaster.get_stream_count() == 2

        sent_count = await broadcaster.broadcast(b"data")

        assert sent_count == 1
        healthy_stream.send.assert_awaited_once_with(b"data", priority=0, ttl=None)
        closed_stream.send.assert_not_awaited()
        assert await broadcaster.get_stream_count() == 1

    @pytest.mark.asyncio
    async def test_broadcast_with_send_failure(
        self, broadcaster: DatagramBroadcaster, mock_stream: Any, mocker: MockerFixture, caplog
    ) -> None:
        healthy_stream = mock_stream
        failing_stream = mocker.create_autospec(WebTransportDatagramDuplexStream, instance=True)
        failing_stream.send = mocker.AsyncMock(side_effect=ConnectionError("Send failed"))
        type(failing_stream).is_closed = mocker.PropertyMock(return_value=False)

        await broadcaster.add_stream(healthy_stream)
        await broadcaster.add_stream(failing_stream)
        assert await broadcaster.get_stream_count() == 2

        sent_count = await broadcaster.broadcast(b"data")

        assert sent_count == 1
        healthy_stream.send.assert_awaited_once()
        failing_stream.send.assert_awaited_once()
        assert await broadcaster.get_stream_count() == 1
        assert "Failed to broadcast to stream" in caplog.text
        assert "Send failed" in caplog.text

    @pytest.mark.asyncio
    async def test_broadcast_all_fail(
        self, broadcaster: DatagramBroadcaster, mock_stream: Any, mocker: MockerFixture
    ) -> None:
        stream1 = mock_stream
        stream1.send.side_effect = Exception("Failure 1")
        stream2 = mocker.create_autospec(WebTransportDatagramDuplexStream, instance=True)
        type(stream2).is_closed = mocker.PropertyMock(return_value=True)

        await broadcaster.add_stream(stream1)
        await broadcaster.add_stream(stream2)
        assert await broadcaster.get_stream_count() == 2

        sent_count = await broadcaster.broadcast(b"data")

        assert sent_count == 0
        assert await broadcaster.get_stream_count() == 0

    @pytest.mark.asyncio
    async def test_broadcast_handles_race_condition_on_remove(
        self, broadcaster: DatagramBroadcaster, mock_stream: Any, mocker: MockerFixture
    ) -> None:
        stream_to_remove = mock_stream
        stream_to_remove.send.side_effect = Exception("Send failed")
        await broadcaster.add_stream(stream_to_remove)
        assert await broadcaster.get_stream_count() == 1
        original_gather = asyncio.gather

        async def gather_side_effect(*tasks, **kwargs):
            await broadcaster.remove_stream(stream_to_remove)
            return await original_gather(*tasks, **kwargs)

        mocker.patch("asyncio.gather", side_effect=gather_side_effect)
        sent_count = await broadcaster.broadcast(b"data")

        assert sent_count == 0
        assert await broadcaster.get_stream_count() == 0
