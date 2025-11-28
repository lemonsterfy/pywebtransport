"""Unit tests for the pywebtransport.client.fleet module."""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from _pytest.logging import LogCaptureFixture
from pytest_asyncio import fixture as asyncio_fixture
from pytest_mock import MockerFixture

from pywebtransport import ClientError, ConnectionError, WebTransportClient, WebTransportSession
from pywebtransport.client import ClientFleet


class TestClientFleet:
    @asyncio_fixture
    async def fleet(self, fleet_unactivated: ClientFleet) -> AsyncGenerator[ClientFleet, None]:
        async with fleet_unactivated as activated_fleet:
            yield activated_fleet

    @pytest.fixture
    def fleet_unactivated(self, mock_clients: list[Any]) -> ClientFleet:
        return ClientFleet(clients=mock_clients)

    @pytest.fixture
    def mock_clients(self, mocker: MockerFixture) -> list[Any]:
        clients = []
        for i in range(3):
            client = mocker.create_autospec(WebTransportClient, instance=True, name=f"Client-{i}")
            client.__aenter__ = mocker.AsyncMock(return_value=client)
            client.close = mocker.AsyncMock()
            client.connect = mocker.AsyncMock(return_value=mocker.create_autospec(WebTransportSession))
            clients.append(client)
        return clients

    @pytest.mark.asyncio
    async def test_aenter_and_aexit_success(self, fleet_unactivated: ClientFleet, mock_clients: list[Any]) -> None:
        async with fleet_unactivated:
            assert isinstance(fleet_unactivated._lock, asyncio.Lock)
            for client in mock_clients:
                cast(AsyncMock, client.__aenter__).assert_awaited_once()

        for client in mock_clients:
            cast(AsyncMock, client.close).assert_awaited_once()
        assert fleet_unactivated.get_client_count() == 0

    @pytest.mark.asyncio
    async def test_aenter_failure_and_cleanup(self, mock_clients: list[Any], caplog: LogCaptureFixture) -> None:
        failing_client = mock_clients[1]
        error = RuntimeError("Activation failed")
        cast(AsyncMock, failing_client.__aenter__).side_effect = error
        fleet = ClientFleet(clients=mock_clients)

        with pytest.raises(ExceptionGroup) as exc_info:
            async with fleet:
                pass

        assert exc_info.value.exceptions[0] is error
        for client in mock_clients:
            cast(AsyncMock, client.close).assert_awaited_once()
        assert "Failed to activate clients in fleet" in caplog.text

    @pytest.mark.asyncio
    async def test_aenter_failure_during_cleanup(self, mock_clients: list[Any], caplog: LogCaptureFixture) -> None:
        cast(AsyncMock, mock_clients[1].__aenter__).side_effect = RuntimeError("Activation failed")
        cast(AsyncMock, mock_clients[2].close).side_effect = IOError("Cleanup failed")
        fleet = ClientFleet(clients=mock_clients)

        with pytest.raises(ExceptionGroup):
            async with fleet:
                pass

        assert "Errors during client fleet startup cleanup" in caplog.text

    @pytest.mark.asyncio
    async def test_close_all_with_failures(
        self, fleet: ClientFleet, mock_clients: list[Any], caplog: LogCaptureFixture
    ) -> None:
        cast(AsyncMock, mock_clients[0].close).side_effect = IOError("Close failed")

        await fleet.close_all()

        for client in mock_clients:
            cast(AsyncMock, client.close).assert_awaited_once()
        assert fleet.get_client_count() == 0
        assert "Errors occurred while closing client fleet" in caplog.text

    @pytest.mark.asyncio
    async def test_connect_all_after_close(self, fleet: ClientFleet) -> None:
        await fleet.close_all()

        results = await fleet.connect_all(url="https://example.com")

        assert results == []

    @pytest.mark.asyncio
    async def test_connect_all_with_mixed_results(
        self, fleet: ClientFleet, mock_clients: list[Any], caplog: LogCaptureFixture
    ) -> None:
        url = "https://example.com"
        error = ConnectionError(message="Failed to connect")
        cast(AsyncMock, mock_clients[1].connect).side_effect = error

        sessions = await fleet.connect_all(url=url)

        assert len(sessions) == len(mock_clients) - 1
        cast(AsyncMock, mock_clients[0].connect).assert_awaited_once_with(url=url)
        cast(AsyncMock, mock_clients[2].connect).assert_awaited_once_with(url=url)
        assert "Some clients in the fleet failed to connect" in caplog.text
        assert f"Client 1 in the fleet failed to connect: {error}" in caplog.text

    @pytest.mark.asyncio
    async def test_get_client_after_close(self, fleet: ClientFleet) -> None:
        await fleet.close_all()
        with pytest.raises(ClientError, match="No clients available"):
            await fleet.get_client()

    @pytest.mark.asyncio
    async def test_get_client_round_robin(self, fleet: ClientFleet, mock_clients: list[Any]) -> None:
        client_order = [await fleet.get_client() for _ in range(len(mock_clients) + 1)]

        assert client_order[0] is mock_clients[0]
        assert client_order[1] is mock_clients[1]
        assert client_order[2] is mock_clients[2]
        assert client_order[3] is mock_clients[0]

    def test_get_client_count(self, fleet_unactivated: ClientFleet, mock_clients: list[Any]) -> None:
        assert fleet_unactivated.get_client_count() == len(mock_clients)

    def test_init_success(self, mock_clients: list[Any]) -> None:
        fleet = ClientFleet(clients=mock_clients)
        assert fleet.get_client_count() == len(mock_clients)
        assert fleet._lock is None

    def test_init_with_no_clients(self) -> None:
        with pytest.raises(ValueError, match="ClientFleet requires at least one client instance"):
            ClientFleet(clients=[])

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method_name", ["close_all", "connect_all", "get_client"])
    async def test_methods_raise_if_not_activated(self, fleet_unactivated: ClientFleet, method_name: str) -> None:
        method_to_test = getattr(fleet_unactivated, method_name)
        kwargs = {"url": "https://url"} if method_name == "connect_all" else {}

        with pytest.raises(ClientError, match="ClientFleet has not been activated"):
            await method_to_test(**kwargs)
