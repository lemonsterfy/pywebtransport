"""Unit tests for the pywebtransport.client.pool module."""

import asyncio
from typing import Any, AsyncGenerator, cast

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig, ClientError, WebTransportClient, WebTransportSession
from pywebtransport.client import ClientPool


class TestClientPool:
    @pytest.fixture
    def mock_client_config(self, mocker: MockerFixture) -> Any:
        return mocker.MagicMock(spec=ClientConfig)

    @pytest.fixture
    def mock_client_create(self, mocker: MockerFixture, mock_webtransport_client: Any) -> Any:
        return mocker.patch(
            "pywebtransport.client.pool.WebTransportClient.create",
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
    async def pool(self, mock_client_create: Any) -> AsyncGenerator[ClientPool, None]:
        pool_instance = ClientPool.create(num_clients=3)
        async with pool_instance as activated_pool:
            yield activated_pool

    def test_init_with_empty_configs(self) -> None:
        with pytest.raises(ValueError):
            ClientPool(configs=[])

    def test_create_factory(self, mock_client_config: Any) -> None:
        pool = ClientPool.create(num_clients=5, base_config=mock_client_config)

        assert len(pool._configs) == 5
        assert all(c is mock_client_config for c in pool._configs)

    @pytest.mark.asyncio
    async def test_aenter_and_aexit(
        self, mocker: MockerFixture, mock_webtransport_client: Any, mock_client_create: Any
    ) -> None:
        num_clients = 3
        mock_gather = mocker.patch("pywebtransport.client.pool.asyncio.gather", wraps=asyncio.gather)
        pool = ClientPool.create(num_clients=num_clients)

        async with pool as returned_pool:
            assert returned_pool is pool
            assert mock_client_create.call_count == num_clients
            assert mock_gather.call_count == 1
            assert len(pool._clients) == num_clients
            assert all(c is mock_webtransport_client for c in pool._clients)

        assert mock_gather.call_count == 2
        assert mock_webtransport_client.close.call_count == num_clients
        assert len(pool._clients) == 0

    @pytest.mark.asyncio
    async def test_aenter_activation_failure(
        self, mocker: MockerFixture, mock_webtransport_client: Any, mock_client_create: Any
    ) -> None:
        original_gather = asyncio.gather

        async def stateful_gather_mock(*tasks: Any, **kwargs: Any) -> list[Any]:
            call_count = getattr(stateful_gather_mock, "call_count", 0)
            setattr(stateful_gather_mock, "call_count", call_count + 1)
            if call_count == 0:
                await original_gather(*tasks)
                raise ValueError("Activation failed")
            return cast(list[Any], await original_gather(*tasks, **kwargs))

        mocker.patch("pywebtransport.client.pool.asyncio.gather", side_effect=stateful_gather_mock)
        pool = ClientPool.create(num_clients=2)

        with pytest.raises(ValueError, match="Activation failed"):
            async with pool:
                pass

        assert mock_webtransport_client.close.call_count == 2
        assert len(pool._clients) == 0

    @pytest.mark.asyncio
    async def test_get_client_round_robin(self, pool: ClientPool, mocker: MockerFixture) -> None:
        num_clients = 3
        clients = pool._clients

        retrieved_clients = [await pool.get_client() for _ in range(num_clients)]

        assert retrieved_clients == clients
        assert await pool.get_client() is clients[0]
        assert await pool.get_client() is clients[1]

    @pytest.mark.asyncio
    async def test_get_client_before_start(self) -> None:
        pool = ClientPool.create(num_clients=1)
        pool._lock = asyncio.Lock()

        with pytest.raises(ClientError, match="No clients available"):
            await pool.get_client()

    @pytest.mark.asyncio
    async def test_connect_all_success(
        self, pool: ClientPool, mocker: MockerFixture, mock_webtransport_client: Any
    ) -> None:
        mock_session = mocker.MagicMock(spec=WebTransportSession)
        mock_webtransport_client.connect.return_value = mock_session

        sessions = await pool.connect_all("https://example.com")

        assert len(sessions) == 3
        assert all(s is mock_session for s in sessions)
        assert mock_webtransport_client.connect.call_count == 3

    @pytest.mark.asyncio
    async def test_connect_all_partial_failure(self, mocker: MockerFixture) -> None:
        mock_session = mocker.MagicMock(spec=WebTransportSession)
        successful_client = mocker.create_autospec(WebTransportClient, instance=True)
        successful_client.connect = mocker.AsyncMock(return_value=mock_session)
        failing_client = mocker.create_autospec(WebTransportClient, instance=True)
        failing_client.connect = mocker.AsyncMock(side_effect=ClientError("Connection failed"))
        pool = ClientPool.create(num_clients=2)
        pool._lock = asyncio.Lock()
        pool._clients = [successful_client, failing_client]

        sessions = await pool.connect_all("https://example.com")

        assert len(sessions) == 1
        assert sessions[0] is mock_session
        successful_client.connect.assert_awaited_once()
        failing_client.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_all_on_empty_pool(self) -> None:
        pool = ClientPool.create(num_clients=1)
        pool._lock = asyncio.Lock()

        await pool.close_all()

        assert len(pool._clients) == 0
