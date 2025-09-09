"""Unit tests for the pywebtransport.client.pool module."""

import logging
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from _pytest.logging import LogCaptureFixture
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig, ClientError, WebTransportClient, WebTransportSession
from pywebtransport.client import ClientPool


class TestClientPool:
    @pytest.fixture
    def mock_client_config(self, mocker: MockerFixture) -> Any:
        return mocker.MagicMock(spec=ClientConfig)

    @pytest.fixture
    def mock_client_constructor(self, mocker: MockerFixture, mock_webtransport_client: Any) -> Any:
        return mocker.patch(
            "pywebtransport.client.pool.WebTransportClient",
            return_value=mock_webtransport_client,
        )

    @pytest.fixture
    def mock_webtransport_client(self, mocker: MockerFixture) -> Any:
        client = mocker.create_autospec(WebTransportClient, instance=True)
        client.__aenter__ = mocker.AsyncMock(return_value=client)
        client.close = mocker.AsyncMock()
        client.connect = mocker.AsyncMock()
        return client

    @pytest.fixture
    async def pool(self, mock_client_constructor: Any) -> AsyncGenerator[ClientPool, None]:
        pool_instance = ClientPool.create(num_clients=3)
        async with pool_instance as activated_pool:
            yield activated_pool

    def test_create_factory(self, mock_client_config: Any) -> None:
        pool = ClientPool.create(num_clients=5, base_config=mock_client_config)

        assert len(pool._configs) == 5
        assert all(c is mock_client_config for c in pool._configs)

    def test_init_with_empty_configs(self) -> None:
        with pytest.raises(ValueError, match="ClientPool requires at least one client configuration."):
            ClientPool(configs=[])

    @pytest.mark.asyncio
    async def test_aenter_and_aexit(
        self, mocker: MockerFixture, mock_webtransport_client: Any, mock_client_constructor: Any
    ) -> None:
        num_clients = 3
        pool = ClientPool.create(num_clients=num_clients)

        async with pool as returned_pool:
            assert returned_pool is pool
            assert mock_client_constructor.call_count == num_clients
            assert pool.get_client_count() == num_clients
            assert all(c is mock_webtransport_client for c in pool._clients)
            assert mock_webtransport_client.__aenter__.call_count == num_clients

        assert mock_webtransport_client.close.call_count == num_clients
        assert pool.get_client_count() == 0

    @pytest.mark.asyncio
    async def test_aenter_is_reentrant(self, pool: ClientPool) -> None:
        initial_client_count = pool.get_client_count()

        async with pool as p:
            assert p is pool
            assert pool.get_client_count() == initial_client_count

    @pytest.mark.asyncio
    async def test_get_client_round_robin(self, pool: ClientPool) -> None:
        num_clients = 3
        clients = pool._clients

        retrieved_clients = [await pool.get_client() for _ in range(num_clients)]

        assert retrieved_clients == clients
        assert await pool.get_client() is clients[0]
        assert await pool.get_client() is clients[1]

    @pytest.mark.asyncio
    async def test_connect_all_success(
        self, pool: ClientPool, mocker: MockerFixture, mock_webtransport_client: Any
    ) -> None:
        mock_session = mocker.MagicMock(spec=WebTransportSession)
        mock_webtransport_client.connect.return_value = mock_session
        url = "https://example.com"

        sessions = await pool.connect_all(url=url)

        assert len(sessions) == 3
        assert all(s is mock_session for s in sessions)
        assert mock_webtransport_client.connect.call_count == 3
        mock_webtransport_client.connect.assert_awaited_with(url=url)

    @pytest.mark.asyncio
    async def test_aenter_activation_failure_and_cleanup_failure(
        self, mocker: MockerFixture, caplog: LogCaptureFixture
    ) -> None:
        failing_client = mocker.create_autospec(WebTransportClient, instance=True)
        failing_client.__aenter__ = mocker.AsyncMock(side_effect=ValueError("Activation failed"))
        failing_client.close = mocker.AsyncMock(side_effect=IOError("Cleanup failed"))
        mocker.patch("pywebtransport.client.pool.WebTransportClient", return_value=failing_client)
        pool = ClientPool.create(num_clients=1)

        with pytest.raises(ExceptionGroup) as exc_info:
            async with pool:
                pass

        match, _ = exc_info.value.split(ValueError)
        assert match and str(match.exceptions[0]) == "Activation failed"
        assert "Errors during client pool startup cleanup" in caplog.text
        assert "Cleanup failed" in caplog.text

    @pytest.mark.asyncio
    async def test_connect_all_partial_failure(self, mocker: MockerFixture, caplog: LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING)
        mock_session = mocker.MagicMock(spec=WebTransportSession)
        successful_client = mocker.create_autospec(WebTransportClient, instance=True)
        successful_client.__aenter__ = mocker.AsyncMock(return_value=successful_client)
        successful_client.connect = mocker.AsyncMock(return_value=mock_session)
        failing_client = mocker.create_autospec(WebTransportClient, instance=True)
        failing_client.__aenter__ = mocker.AsyncMock(return_value=failing_client)
        failing_client.connect = mocker.AsyncMock(side_effect=ClientError("Connection failed"))
        mocker.patch(
            "pywebtransport.client.pool.WebTransportClient",
            side_effect=[successful_client, failing_client],
        )
        pool = ClientPool.create(num_clients=2)

        async with pool:
            sessions = await pool.connect_all(url="https://example.com")

            assert len(sessions) == 1
            assert sessions[0] is mock_session
            assert "Client 1 in the pool failed to connect" in caplog.text
            assert "Connection failed" in caplog.text

    @pytest.mark.asyncio
    async def test_close_all_with_failures(
        self, pool: ClientPool, mock_webtransport_client: Any, caplog: LogCaptureFixture
    ) -> None:
        mock_webtransport_client.close.side_effect = IOError("Close failed")

        await pool.close_all()

        assert "Errors occurred while closing client pool" in caplog.text
        assert "Close failed" in caplog.text
        assert pool.get_client_count() == 0

    @pytest.mark.asyncio
    async def test_methods_on_activated_empty_pool(self, mock_client_constructor: Any) -> None:
        pool = ClientPool.create(num_clients=1)
        async with pool:
            await pool.close_all()
            assert pool.get_client_count() == 0

            assert await pool.connect_all(url="https://example.com") == []
            with pytest.raises(ClientError, match="No clients available"):
                await pool.get_client()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name, kwargs",
        [
            ("get_client", {}),
            ("connect_all", {"url": "https://example.com"}),
            ("close_all", {}),
        ],
    )
    async def test_methods_raise_if_not_activated(self, method_name: str, kwargs: dict[str, Any]) -> None:
        pool = ClientPool.create(num_clients=1)
        method_to_test = getattr(pool, method_name)

        with pytest.raises(ClientError, match="ClientPool has not been activated"):
            await method_to_test(**kwargs)
