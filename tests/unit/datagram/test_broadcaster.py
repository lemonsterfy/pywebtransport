"""Unit tests for the pywebtransport.datagram.broadcaster module."""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any, cast
from unittest import mock

import pytest
from _pytest.logging import LogCaptureFixture
from pytest_mock import MockerFixture

from pywebtransport import ConnectionError, DatagramError, WebTransportDatagramTransport
from pywebtransport.datagram import DatagramBroadcaster


class TestDatagramBroadcaster:
    @pytest.fixture
    async def broadcaster(self) -> AsyncGenerator[DatagramBroadcaster, None]:
        async with DatagramBroadcaster.create() as b:
            yield b

    @pytest.fixture
    def mock_transport(self, mocker: MockerFixture) -> Any:
        transport = mocker.create_autospec(WebTransportDatagramTransport, instance=True)
        transport.send = mocker.AsyncMock()
        type(transport).is_closed = mocker.PropertyMock(return_value=False)
        return transport

    @pytest.mark.asyncio
    async def test_create(self) -> None:
        async with DatagramBroadcaster.create() as b:
            assert isinstance(b, DatagramBroadcaster)
            assert await b.get_transport_count() == 0

    @pytest.mark.asyncio
    async def test_add_transport(self, broadcaster: DatagramBroadcaster, mock_transport: Any) -> None:
        assert await broadcaster.get_transport_count() == 0

        await broadcaster.add_transport(transport=mock_transport)

        assert await broadcaster.get_transport_count() == 1

    @pytest.mark.asyncio
    async def test_add_transport_idempotent(self, broadcaster: DatagramBroadcaster, mock_transport: Any) -> None:
        await broadcaster.add_transport(transport=mock_transport)
        await broadcaster.add_transport(transport=mock_transport)

        assert await broadcaster.get_transport_count() == 1

    @pytest.mark.asyncio
    async def test_remove_transport(self, broadcaster: DatagramBroadcaster, mock_transport: Any) -> None:
        await broadcaster.add_transport(transport=mock_transport)
        assert await broadcaster.get_transport_count() == 1

        await broadcaster.remove_transport(transport=mock_transport)

        assert await broadcaster.get_transport_count() == 0

    @pytest.mark.asyncio
    async def test_remove_nonexistent_transport(self, broadcaster: DatagramBroadcaster, mock_transport: Any) -> None:
        assert await broadcaster.get_transport_count() == 0

        await broadcaster.remove_transport(transport=mock_transport)

        assert await broadcaster.get_transport_count() == 0

    @pytest.mark.asyncio
    async def test_broadcast_success_all(
        self, broadcaster: DatagramBroadcaster, mock_transport: Any, mocker: MockerFixture
    ) -> None:
        transport1 = mock_transport
        transport2 = mocker.create_autospec(WebTransportDatagramTransport, instance=True)
        transport2.send = mocker.AsyncMock()
        type(transport2).is_closed = mocker.PropertyMock(return_value=False)
        await broadcaster.add_transport(transport=transport1)
        await broadcaster.add_transport(transport=transport2)

        sent_count = await broadcaster.broadcast(data=b"ping", priority=1, ttl=10.0)

        assert sent_count == 2
        cast(mock.AsyncMock, transport1.send).assert_awaited_once_with(data=b"ping", priority=1, ttl=10.0)
        cast(mock.AsyncMock, transport2.send).assert_awaited_once_with(data=b"ping", priority=1, ttl=10.0)
        assert await broadcaster.get_transport_count() == 2

    @pytest.mark.asyncio
    async def test_broadcast_empty(self, broadcaster: DatagramBroadcaster) -> None:
        sent_count = await broadcaster.broadcast(data=b"data")

        assert sent_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_with_pre_closed_transport(
        self, broadcaster: DatagramBroadcaster, mock_transport: Any, mocker: MockerFixture
    ) -> None:
        healthy_transport = mock_transport
        closed_transport = mocker.create_autospec(WebTransportDatagramTransport, instance=True)
        closed_transport.send = mocker.AsyncMock()
        type(closed_transport).is_closed = mocker.PropertyMock(return_value=True)
        await broadcaster.add_transport(transport=healthy_transport)
        await broadcaster.add_transport(transport=closed_transport)
        assert await broadcaster.get_transport_count() == 2

        sent_count = await broadcaster.broadcast(data=b"data")

        assert sent_count == 1
        cast(mock.AsyncMock, healthy_transport.send).assert_awaited_once_with(data=b"data", priority=0, ttl=None)
        cast(mock.AsyncMock, closed_transport.send).assert_not_awaited()
        assert await broadcaster.get_transport_count() == 1

    @pytest.mark.asyncio
    async def test_broadcast_with_send_failure(
        self,
        broadcaster: DatagramBroadcaster,
        mock_transport: Any,
        mocker: MockerFixture,
        caplog: LogCaptureFixture,
    ) -> None:
        healthy_transport = mock_transport
        failing_transport = mocker.create_autospec(WebTransportDatagramTransport, instance=True)
        failing_transport.send = mocker.AsyncMock(side_effect=ConnectionError("Send failed"))
        type(failing_transport).is_closed = mocker.PropertyMock(return_value=False)
        await broadcaster.add_transport(transport=healthy_transport)
        await broadcaster.add_transport(transport=failing_transport)
        assert await broadcaster.get_transport_count() == 2

        sent_count = await broadcaster.broadcast(data=b"data")

        assert sent_count == 1
        cast(mock.AsyncMock, healthy_transport.send).assert_awaited_once()
        cast(mock.AsyncMock, failing_transport.send).assert_awaited_once()
        assert await broadcaster.get_transport_count() == 1
        assert "Failed to broadcast to transport" in caplog.text
        assert "Send failed" in caplog.text

    @pytest.mark.asyncio
    async def test_broadcast_all_fail(
        self, broadcaster: DatagramBroadcaster, mock_transport: Any, mocker: MockerFixture
    ) -> None:
        transport1 = mock_transport
        transport1.send.side_effect = Exception("Failure 1")
        transport2 = mocker.create_autospec(WebTransportDatagramTransport, instance=True)
        type(transport2).is_closed = mocker.PropertyMock(return_value=True)
        await broadcaster.add_transport(transport=transport1)
        await broadcaster.add_transport(transport=transport2)
        assert await broadcaster.get_transport_count() == 2

        sent_count = await broadcaster.broadcast(data=b"data")

        assert sent_count == 0
        assert await broadcaster.get_transport_count() == 0

    @pytest.mark.asyncio
    async def test_broadcast_handles_race_condition_on_remove(
        self, broadcaster: DatagramBroadcaster, mock_transport: Any, mocker: MockerFixture
    ) -> None:
        transport_to_remove = mock_transport
        transport_to_remove.send.side_effect = Exception("Send failed")
        await broadcaster.add_transport(transport=transport_to_remove)
        assert await broadcaster.get_transport_count() == 1
        original_gather = asyncio.gather

        async def gather_side_effect(*tasks: Any, **kwargs: Any) -> list[Any]:
            await broadcaster.remove_transport(transport=transport_to_remove)
            return cast(list[Any], await original_gather(*tasks, **kwargs))

        mocker.patch("pywebtransport.datagram.broadcaster.asyncio.gather", side_effect=gather_side_effect)

        sent_count = await broadcaster.broadcast(data=b"data")

        assert sent_count == 0
        assert await broadcaster.get_transport_count() == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name, kwargs",
        [
            ("add_transport", {"transport": mock.MagicMock()}),
            ("remove_transport", {"transport": mock.MagicMock()}),
            ("broadcast", {"data": b"data"}),
            ("get_transport_count", {}),
        ],
    )
    async def test_methods_on_uninitialized_raises_error(self, method_name: str, kwargs: dict[str, Any]) -> None:
        broadcaster = DatagramBroadcaster.create()
        method = getattr(broadcaster, method_name)

        with pytest.raises(DatagramError, match="has not been activated"):
            await method(**kwargs)

    @pytest.mark.asyncio
    async def test_aexit_uninitialized(self) -> None:
        broadcaster = DatagramBroadcaster.create()

        await broadcaster.__aexit__(None, None, None)
