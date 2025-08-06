"""Unit tests for the pywebtransport.client.pooled module."""

import asyncio
from asyncio import Task
from typing import Any, AsyncGenerator, Coroutine, cast

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig, WebTransportClient, WebTransportSession
from pywebtransport.client import PooledClient


class TestPooledClient:
    @pytest.fixture
    def mock_client_config(self, mocker: MockerFixture) -> Any:
        return mocker.MagicMock(spec=ClientConfig)

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

    @pytest.fixture
    async def pool(self) -> AsyncGenerator[PooledClient, None]:
        pool_instance = PooledClient()
        async with pool_instance as activated_pool:
            yield activated_pool

    @pytest.fixture(autouse=True)
    def setup_common_mocks(self, mocker: MockerFixture, mock_underlying_client: Any) -> None:
        mocker.patch(
            "pywebtransport.client.pooled.WebTransportClient.create",
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

    @pytest.mark.asyncio
    async def test_aenter_and_aexit(self, mocker: MockerFixture, mock_underlying_client: Any) -> None:
        mock_start_cleanup = mocker.patch("pywebtransport.client.pooled.PooledClient._start_cleanup_task")

        async with PooledClient() as pool:
            mock_underlying_client.__aenter__.assert_awaited_once()
            mock_start_cleanup.assert_called_once()
            assert pool._cleanup_task is None

        mock_underlying_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_with_no_sessions(
        self, pool: PooledClient, mocker: MockerFixture, mock_underlying_client: Any
    ) -> None:
        mock_gather = mocker.patch("asyncio.gather")

        await pool.close()

        mock_gather.assert_not_called()
        mock_underlying_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_without_starting(self, mock_underlying_client: Any) -> None:
        pool = PooledClient()
        assert pool._cleanup_task is None
        pool._lock = asyncio.Lock()

        await pool.close()

        mock_underlying_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_session_from_pool(self, pool: PooledClient, mock_session: Any) -> None:
        pool._pools["example.com:443/"] = [mock_session]

        session = await pool.get_session("https://example.com")

        assert session is mock_session
        assert not pool._pools["example.com:443/"]

    @pytest.mark.asyncio
    async def test_get_session_from_empty_pool(
        self, pool: PooledClient, mock_underlying_client: Any, mock_session: Any
    ) -> None:
        mock_underlying_client.connect.return_value = mock_session

        session = await pool.get_session("https://example.com")

        assert session is mock_session
        mock_underlying_client.connect.assert_awaited_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_get_session_with_stale_session_in_pool(
        self, pool: PooledClient, mock_underlying_client: Any, mock_session: Any, mocker: MockerFixture
    ) -> None:
        stale_session = mocker.MagicMock(spec=WebTransportSession, is_ready=False)
        mock_underlying_client.connect.return_value = mock_session
        pool._pools["example.com:443/"] = [stale_session]

        session = await pool.get_session("https://example.com")

        assert session is mock_session
        assert not pool._pools["example.com:443/"]
        mock_underlying_client.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_return_session_to_pool(self, pool: PooledClient, mock_session: Any) -> None:
        await pool.return_session(mock_session)

        assert pool._pools["example.com:443/"] == [mock_session]
        cast(Any, mock_session.close).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_return_session_to_full_pool(self, mock_session: Any, mocker: MockerFixture) -> None:
        async with PooledClient(pool_size=1) as pool:
            session_in_pool = mocker.create_autospec(WebTransportSession, instance=True)
            session_in_pool.close = mocker.AsyncMock()
            pool._pools["example.com:443/"] = [session_in_pool]

            await pool.return_session(mock_session)

            assert len(pool._pools["example.com:443/"]) == 1
            cast(Any, mock_session.close).assert_awaited_once()

    @pytest.mark.asyncio
    async def test_return_stale_session(self, pool: PooledClient, mock_session: Any) -> None:
        mock_session.is_ready = False

        await pool.return_session(mock_session)

        assert not pool._pools.get("example.com:443/")
        cast(Any, mock_session.close).assert_awaited_once()

    @pytest.mark.asyncio
    async def test_return_session_with_no_pool_key(self, pool: PooledClient, mock_session: Any) -> None:
        mock_session.connection = None

        await pool.return_session(mock_session)

        assert not pool._pools
        cast(Any, mock_session.close).assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_cleanup_task_idempotent(self, mocker: MockerFixture) -> None:
        mock_task = mocker.create_autospec(asyncio.Task, instance=True)
        mock_task.done.return_value = False

        def cleanup_side_effect(coro: Coroutine) -> asyncio.Task:
            coro.close()
            return mock_task

        mock_create_task = mocker.patch("asyncio.create_task", side_effect=cleanup_side_effect)
        pool = PooledClient()

        pool._start_cleanup_task()
        pool._start_cleanup_task()

        mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_cleanup_task_after_done(self, mocker: MockerFixture) -> None:
        mock_task = mocker.create_autospec(asyncio.Task, instance=True)

        def cleanup_side_effect(coro: Coroutine) -> asyncio.Task:
            coro.close()
            return mock_task

        mock_create_task = mocker.patch("asyncio.create_task", side_effect=cleanup_side_effect)
        pool = PooledClient()
        done_task: asyncio.Future[Any] = asyncio.Future()
        done_task.set_result(None)
        pool._cleanup_task = cast(Task, done_task)

        pool._start_cleanup_task()

        mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_periodic_cleanup(self, mocker: MockerFixture, mock_session: Any) -> None:
        mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        mock_sleep.side_effect = [None, asyncio.CancelledError]
        stale_session = mocker.create_autospec(WebTransportSession, instance=True)
        stale_session.is_ready = False

        async with PooledClient(cleanup_interval=0.01) as pool:
            pool._pools["example.com:443/"] = [mock_session, stale_session]
            cleanup_task = pool._cleanup_task
            assert cleanup_task is not None

            with pytest.raises(asyncio.CancelledError):
                await cleanup_task

            mock_sleep.assert_any_await(0.01)
            assert pool._pools["example.com:443/"] == [mock_session]
