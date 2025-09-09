"""Unit tests for the pywebtransport.client.pooled module."""

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from _pytest.logging import LogCaptureFixture
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig, ClientError, ConnectionError, WebTransportClient, WebTransportSession
from pywebtransport.client import PooledClient


class TestPooledClient:
    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> Any:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        session.is_ready = True
        session.path = "/"
        session.connection = mocker.MagicMock()
        session.connection.remote_address = ("example.com", 443)
        session.close = mocker.AsyncMock()
        return session

    @pytest.fixture
    def mock_underlying_client(self, mocker: MockerFixture) -> Any:
        client = mocker.create_autospec(WebTransportClient, instance=True)
        client.__aenter__ = mocker.AsyncMock(return_value=client)
        client.connect = mocker.AsyncMock()
        client.close = mocker.AsyncMock()
        return client

    @pytest.fixture(autouse=True)
    def setup_common_mocks(self, mocker: MockerFixture, mock_underlying_client: Any) -> None:
        mocker.patch(
            "pywebtransport.client.pooled.WebTransportClient",
            return_value=mock_underlying_client,
        )
        mocker.patch(
            "pywebtransport.client.pooled.parse_webtransport_url",
            return_value=("example.com", 443, "/"),
        )

    def test_create_factory(self, mocker: MockerFixture) -> None:
        mock_init = mocker.patch("pywebtransport.client.pooled.PooledClient.__init__", return_value=None)
        mock_config = mocker.MagicMock(spec=ClientConfig)

        PooledClient.create(config=mock_config, pool_size=5, cleanup_interval=30.0)

        mock_init.assert_called_once_with(config=mock_config, pool_size=5, cleanup_interval=30.0)

    @pytest.mark.parametrize("invalid_size", [0, -1])
    def test_init_with_invalid_pool_size(self, invalid_size: int) -> None:
        with pytest.raises(ValueError, match="pool_size must be a positive integer"):
            PooledClient(pool_size=invalid_size)

    @pytest.mark.asyncio
    async def test_aenter_and_aexit(self, mocker: MockerFixture, mock_underlying_client: Any) -> None:
        mock_start_cleanup = mocker.patch("pywebtransport.client.pooled.PooledClient._start_cleanup_task")
        completed_task = asyncio.create_task(asyncio.sleep(0))
        await asyncio.sleep(0)

        async with PooledClient() as pool:
            pool._cleanup_task = completed_task
            mock_underlying_client.__aenter__.assert_awaited_once()
            mock_start_cleanup.assert_called_once()

        assert completed_task.cancelled()
        cast(AsyncMock, mock_underlying_client.close).assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_with_sessions_and_failures(
        self, mocker: MockerFixture, mock_session: Any, caplog: LogCaptureFixture
    ) -> None:
        async with PooledClient() as pool:
            failing_session = mocker.create_autospec(WebTransportSession, instance=True)
            failing_session.close.side_effect = IOError("Close failed")
            pool._pools["key1"] = [mock_session]
            pool._pools["key2"] = [failing_session]
            mock_underlying_client = pool._client

            await pool.close()

            cast(AsyncMock, mock_session.close).assert_awaited_once()
            failing_session.close.assert_awaited_once()
            cast(AsyncMock, mock_underlying_client.close).assert_awaited_once()
            assert "Errors occurred while closing pooled sessions" in caplog.text

    @pytest.mark.asyncio
    async def test_get_session_from_pool(self, mock_underlying_client: Any, mock_session: Any) -> None:
        async with PooledClient() as pool:
            pool._pools["example.com:443/"] = [mock_session]

            session = await pool.get_session(url="https://example.com")

            assert session is mock_session
            assert not pool._pools["example.com:443/"]
            cast(AsyncMock, mock_underlying_client.connect).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_return_session(self, mock_session: Any) -> None:
        async with PooledClient() as pool:
            await pool.return_session(session=mock_session)

            assert pool._pools["example.com:443/"] == [mock_session]
            cast(AsyncMock, mock_session.close).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_session_discards_stale_and_creates_new(
        self, mock_underlying_client: Any, mock_session: Any, mocker: MockerFixture
    ) -> None:
        async with PooledClient() as pool:
            stale_session = mocker.create_autospec(WebTransportSession, instance=True, is_ready=False)
            mock_underlying_client.connect.return_value = mock_session
            pool._pools["example.com:443/"] = [stale_session]
            pool._total_sessions["example.com:443/"] = 1

            session = await pool.get_session(url="https://example.com")

            assert session is mock_session
            assert not pool._pools["example.com:443/"]
            assert pool._total_sessions["example.com:443/"] == 1
            cast(AsyncMock, mock_underlying_client.connect).assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_session_creation_failure_decrements_count(self, mock_underlying_client: Any) -> None:
        mock_underlying_client.connect.side_effect = ConnectionError("Failed")

        async with PooledClient() as pool:
            pool_key = "example.com:443/"

            with pytest.raises(ConnectionError):
                await pool.get_session(url="https://example.com")

            assert pool._total_sessions[pool_key] == 0

    @pytest.mark.asyncio
    async def test_return_session_to_full_pool_closes_it(self, mock_session: Any, mocker: MockerFixture) -> None:
        async with PooledClient(pool_size=1) as pool:
            pool._pools["example.com:443/"].append(mock_session)
            pool._total_sessions["example.com:443/"] = 1
            another_session = mocker.create_autospec(WebTransportSession, instance=True, is_ready=True)
            another_session.connection = mocker.MagicMock()
            another_session.connection.remote_address = ("example.com", 443)
            another_session.path = "/"
            another_session.close = mocker.AsyncMock()

            await pool.return_session(session=another_session)

            assert len(pool._pools["example.com:443/"]) == 1
            another_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_return_stale_session_updates_count(self, mock_session: Any) -> None:
        async with PooledClient() as pool:
            pool_key = "example.com:443/"
            pool._total_sessions[pool_key] = 1
            mock_session.is_ready = False

            await pool.return_session(session=mock_session)

            assert not pool._pools.get(pool_key)
            assert pool._total_sessions[pool_key] == 0
            cast(AsyncMock, mock_session.close).assert_awaited_once()

    @pytest.mark.asyncio
    async def test_return_session_with_no_connection_closes_it(self, mock_session: Any) -> None:
        async with PooledClient() as pool:
            mock_session.connection = None
            pool._total_sessions["unknown"] = 1

            await pool.return_session(session=mock_session)

            cast(AsyncMock, mock_session.close).assert_awaited_once()
            assert not pool._pools

    @pytest.mark.asyncio
    async def test_get_session_concurrent_requests_respects_pool_size(
        self, mock_underlying_client: Any, mock_session: Any
    ) -> None:
        async with PooledClient(pool_size=1) as pool:
            mock_underlying_client.connect.return_value = mock_session
            task_a = asyncio.create_task(pool.get_session(url="https://example.com"))
            await asyncio.sleep(0.01)
            task_b = asyncio.create_task(pool.get_session(url="https://example.com"))
            await asyncio.sleep(0.01)

            cast(AsyncMock, mock_underlying_client.connect).assert_awaited_once()
            assert not task_b.done()

            session_a = await task_a
            await pool.return_session(session=session_a)
            session_b = await asyncio.wait_for(task_b, timeout=1.0)

            assert session_b is mock_session
            cast(AsyncMock, mock_underlying_client.connect).assert_awaited_once()

    @pytest.mark.asyncio
    async def test_periodic_cleanup_handles_all_cases(
        self, mocker: MockerFixture, mock_session: Any, caplog: LogCaptureFixture
    ) -> None:
        mocker.patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError])
        stale_session = mocker.create_autospec(WebTransportSession, instance=True, is_ready=False)
        failing_stale_session = mocker.create_autospec(WebTransportSession, instance=True, is_ready=False)
        pool_key1, pool_key2, pool_key3 = "key1", "key2_empty", "key3_failing"

        async with PooledClient(cleanup_interval=0.01) as pool:
            pool._pools[pool_key1] = [mock_session, stale_session]
            pool._total_sessions[pool_key1] = 2
            pool._pools[pool_key2] = []
            pool._total_sessions[pool_key2] = 0
            pool._pools[pool_key3] = [failing_stale_session]
            pool._total_sessions[pool_key3] = 1

            with pytest.raises(asyncio.CancelledError):
                await pool._periodic_cleanup()

            assert pool._pools[pool_key1] == [mock_session]
            assert pool._total_sessions[pool_key1] == 1
            assert not pool._pools.get(pool_key2)
            assert not pool._pools.get(pool_key3)
            assert pool._total_sessions[pool_key3] == 0

    def test_get_pool_key_with_invalid_url(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.client.pooled.parse_webtransport_url", side_effect=ValueError)
        pool = PooledClient()
        url = "invalid-url"

        key = pool._get_pool_key(url=url)

        assert key == url

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method_name", ["close", "get_session", "return_session"])
    async def test_methods_raise_if_not_activated(self, method_name: str, mock_session: Any) -> None:
        pool = PooledClient()
        method = getattr(pool, method_name)
        kwargs: dict[str, Any] = {}
        if method_name == "return_session":
            kwargs["session"] = mock_session
        elif method_name == "get_session":
            kwargs["url"] = "https://url"

        with pytest.raises(ClientError, match="PooledClient has not been activated"):
            await method(**kwargs)
