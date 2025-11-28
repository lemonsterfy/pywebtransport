"""Unit tests for the pywebtransport.server.middleware module."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from _pytest.logging import LogCaptureFixture
from pytest_asyncio import fixture as asyncio_fixture
from pytest_mock import MockerFixture

from pywebtransport import ServerError, WebTransportSession
from pywebtransport.server import (
    MiddlewareManager,
    create_auth_middleware,
    create_cors_middleware,
    create_logging_middleware,
    create_rate_limit_middleware,
)
from pywebtransport.server.middleware import RateLimiter


class TestMiddlewareFactories:
    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> Any:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        session.path = "/test"
        session.headers = {"origin": "https://example.com", "x-auth": "good-token"}
        mock_conn = mocker.MagicMock()
        mock_conn.remote_address = ("1.2.3.4", 12345)
        session._connection = mock_conn
        return session

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auth_result", [True, False])
    async def test_create_auth_middleware(self, mock_session: Any, auth_result: bool, mocker: MockerFixture) -> None:
        auth_handler = mocker.AsyncMock(return_value=auth_result)
        auth_middleware = create_auth_middleware(auth_handler=auth_handler)

        result = await auth_middleware(session=mock_session)

        assert result is auth_result
        auth_handler.assert_awaited_once_with(headers=mock_session.headers)

    @pytest.mark.asyncio
    async def test_create_auth_middleware_handler_exception(self, mock_session: Any, mocker: MockerFixture) -> None:
        auth_handler = mocker.AsyncMock(side_effect=ValueError("Auth error"))
        auth_middleware = create_auth_middleware(auth_handler=auth_handler)

        result = await auth_middleware(session=mock_session)

        assert result is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "origin, allowed_origins, expected_result",
        [
            ("https://example.com", ["https://example.com"], True),
            ("https://evil.com", ["https://example.com"], False),
            ("https://any.com", ["*"], True),
            (None, ["https://example.com"], False),
        ],
    )
    async def test_create_cors_middleware(
        self, mock_session: Any, origin: Any, allowed_origins: list[str], expected_result: bool
    ) -> None:
        mock_session.headers = {"origin": origin} if origin else {}
        cors_middleware = create_cors_middleware(allowed_origins=allowed_origins)

        result = await cors_middleware(session=mock_session)

        assert result is expected_result

    @pytest.mark.asyncio
    async def test_create_logging_middleware(self, mock_session: Any, caplog: LogCaptureFixture) -> None:
        caplog.set_level(logging.INFO)
        logging_middleware = create_logging_middleware()

        result = await logging_middleware(session=mock_session)

        assert result is True
        assert "Session request: path='/test' from=1.2.3.4:12345" in caplog.text

    @pytest.mark.asyncio
    async def test_create_logging_middleware_empty_remote_address(
        self, mocker: MockerFixture, caplog: LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)
        session = mocker.create_autospec(WebTransportSession, instance=True)
        session.path = "/no-addr"
        mock_conn = mocker.MagicMock()
        mock_conn.remote_address = ()
        session._connection = mock_conn
        logging_middleware = create_logging_middleware()

        await logging_middleware(session=session)

        assert "from=unknown" in caplog.text

    @pytest.mark.asyncio
    async def test_create_logging_middleware_no_remote_address(
        self, mocker: MockerFixture, caplog: LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)
        session = mocker.create_autospec(WebTransportSession, instance=True)
        session.path = "/no-addr"
        mock_conn = mocker.MagicMock()
        mock_conn.remote_address = None
        session._connection = mock_conn
        logging_middleware = create_logging_middleware()

        await logging_middleware(session=session)

        assert "from=unknown" in caplog.text

    def test_create_rate_limit_middleware(self) -> None:
        limiter = create_rate_limit_middleware(max_requests=50, window_seconds=30)

        assert isinstance(limiter, RateLimiter)
        assert limiter._max_requests == 50
        assert limiter._window_seconds == 30


@pytest.mark.asyncio
class TestMiddlewareManager:
    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> Any:
        return mocker.create_autospec(WebTransportSession, instance=True)

    async def test_add_remove_middleware(self) -> None:
        manager = MiddlewareManager()
        assert manager.get_middleware_count() == 0

        async def middleware1(*, session: WebTransportSession) -> bool:
            return True

        manager.add_middleware(middleware=middleware1)
        assert manager.get_middleware_count() == 1

        manager.remove_middleware(middleware=middleware1)
        assert manager.get_middleware_count() == 0

        manager.remove_middleware(middleware=middleware1)
        assert manager.get_middleware_count() == 0

    async def test_process_request_all_pass(self, mock_session: Any, mocker: MockerFixture) -> None:
        manager = MiddlewareManager()
        middleware1 = mocker.AsyncMock(return_value=True)
        middleware2 = mocker.AsyncMock(return_value=True)
        manager.add_middleware(middleware=middleware1)
        manager.add_middleware(middleware=middleware2)

        result = await manager.process_request(session=mock_session)

        assert result is True
        middleware1.assert_awaited_once_with(session=mock_session)
        middleware2.assert_awaited_once_with(session=mock_session)

    async def test_process_request_exception(
        self, mock_session: Any, mocker: MockerFixture, caplog: LogCaptureFixture
    ) -> None:
        manager = MiddlewareManager()
        middleware1 = mocker.AsyncMock(side_effect=ValueError("Middleware error"))
        manager.add_middleware(middleware=middleware1)

        result = await manager.process_request(session=mock_session)

        assert result is False
        assert "Middleware error: Middleware error" in caplog.text

    async def test_process_request_one_fails(self, mock_session: Any, mocker: MockerFixture) -> None:
        manager = MiddlewareManager()
        middleware1 = mocker.AsyncMock(return_value=True)
        middleware2 = mocker.AsyncMock(return_value=False)
        middleware3 = mocker.AsyncMock(return_value=True)
        manager.add_middleware(middleware=middleware1)
        manager.add_middleware(middleware=middleware2)
        manager.add_middleware(middleware=middleware3)

        result = await manager.process_request(session=mock_session)

        assert result is False
        middleware1.assert_awaited_once_with(session=mock_session)
        middleware2.assert_awaited_once_with(session=mock_session)
        middleware3.assert_not_called()


@pytest.mark.asyncio
class TestRateLimiter:
    @asyncio_fixture
    async def rate_limiter(self) -> AsyncGenerator[RateLimiter, None]:
        limiter = RateLimiter(max_requests=2, window_seconds=10)
        async with limiter as activated_limiter:
            yield activated_limiter

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> Any:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        mock_conn = mocker.MagicMock()
        mock_conn.remote_address = ("1.2.3.4", 12345)
        session._connection = mock_conn
        return session

    async def test_aexit_no_cleanup_task(self) -> None:
        limiter = RateLimiter()
        limiter._cleanup_task = None
        await limiter.__aexit__(None, None, None)
        assert limiter._is_closing

    async def test_call_empty_remote_address(self, mocker: MockerFixture, rate_limiter: RateLimiter) -> None:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        mock_conn = mocker.MagicMock()
        mock_conn.remote_address = ()
        session._connection = mock_conn

        assert await rate_limiter(session=session) is True

    async def test_call_no_connection(self, mocker: MockerFixture, rate_limiter: RateLimiter) -> None:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        session._connection = None

        assert await rate_limiter(session=session) is True

    async def test_call_no_remote_address(self, mocker: MockerFixture, rate_limiter: RateLimiter) -> None:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        mock_conn = mocker.MagicMock()
        mock_conn.remote_address = None
        session._connection = mock_conn

        assert await rate_limiter(session=session) is True

    async def test_lifecycle_and_cleanup(self, mocker: MockerFixture, caplog: LogCaptureFixture) -> None:
        caplog.set_level(logging.DEBUG)
        original_sleep = asyncio.sleep
        proceed_event = asyncio.Event()

        async def sleep_mock(delay: float) -> None:
            if delay > 0:
                proceed_event.set()
            await original_sleep(0)

        mocker.patch("asyncio.sleep", side_effect=sleep_mock)
        mock_timestamp = mocker.patch("pywebtransport.server.middleware.get_timestamp")
        rate_limiter = RateLimiter(window_seconds=10, cleanup_interval=30)

        async with rate_limiter as rl:
            assert rl._lock is not None
            async with rl._lock:
                rl._requests["active_ip"] = [210.0]
                rl._requests["stale_ip"] = [100.0]
                rl._requests["empty_ip"] = []

            mock_timestamp.return_value = 215.0
            await proceed_event.wait()
            await asyncio.sleep(0)

            assert "Cleaned up 2 stale IP entries" in caplog.text
            assert rl._lock is not None
            async with rl._lock:
                assert "active_ip" in rl._requests
                assert "stale_ip" not in rl._requests
                assert "empty_ip" not in rl._requests

    async def test_periodic_cleanup_empty_timestamps(self, mocker: MockerFixture) -> None:
        mocker.patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError])
        mocker.patch("pywebtransport.server.middleware.get_timestamp", return_value=100.0)

        async with RateLimiter() as rate_limiter:
            assert rate_limiter._lock is not None
            async with rate_limiter._lock:
                rate_limiter._requests["empty_ip"] = []

            with pytest.raises(asyncio.CancelledError):
                await rate_limiter._periodic_cleanup()

            assert "empty_ip" not in rate_limiter._requests

    async def test_periodic_cleanup_exit_on_closing(self, mocker: MockerFixture) -> None:
        mocker.patch("asyncio.sleep", return_value=None)
        rate_limiter = RateLimiter()
        rate_limiter._is_closing = True
        rate_limiter._lock = mocker.MagicMock()

        await rate_limiter._periodic_cleanup()

        cast(MagicMock, rate_limiter._lock).assert_not_called()

    async def test_periodic_cleanup_no_lock(self, caplog: LogCaptureFixture) -> None:
        limiter = RateLimiter()

        with caplog.at_level(logging.ERROR):
            await limiter._periodic_cleanup()

        assert "RateLimiter cleanup task cannot run without a lock" in caplog.text

    async def test_periodic_cleanup_no_stale_ips(self, mocker: MockerFixture) -> None:
        mocker.patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError])
        mock_timestamp = mocker.patch("pywebtransport.server.middleware.get_timestamp")

        async with RateLimiter() as rate_limiter:
            assert rate_limiter._lock is not None
            async with rate_limiter._lock:
                rate_limiter._requests["active_ip"] = [100.0]
            mock_timestamp.return_value = 105.0

            with pytest.raises(asyncio.CancelledError):
                await rate_limiter._periodic_cleanup()

            assert "active_ip" in rate_limiter._requests

    async def test_rate_limiter_call_not_activated(self, mock_session: Any) -> None:
        limiter = RateLimiter()

        with pytest.raises(ServerError, match="RateLimiter has not been activated"):
            await limiter(session=mock_session)

    async def test_rate_limiting_logic(
        self, mock_session: Any, mocker: MockerFixture, caplog: LogCaptureFixture, rate_limiter: RateLimiter
    ) -> None:
        mock_timestamp = mocker.patch("pywebtransport.server.middleware.get_timestamp")

        mock_timestamp.return_value = 100.0
        assert await rate_limiter(session=mock_session) is True

        mock_timestamp.return_value = 101.0
        assert await rate_limiter(session=mock_session) is True

        mock_timestamp.return_value = 102.0
        assert await rate_limiter(session=mock_session) is False
        assert "Rate limit exceeded for IP 1.2.3.4" in caplog.text

        mock_timestamp.return_value = 110.1
        assert await rate_limiter(session=mock_session) is True

    async def test_start_cleanup_task_idempotent(self, mocker: MockerFixture) -> None:
        dummy_coroutine_obj = mocker.MagicMock(name="dummy_coroutine_obj")
        sync_mock_callable = mocker.MagicMock(return_value=dummy_coroutine_obj)

        mocker.patch("pywebtransport.server.middleware.RateLimiter._periodic_cleanup", new=sync_mock_callable)
        mock_create_task = mocker.patch("asyncio.create_task")
        rate_limiter = RateLimiter()

        rate_limiter._start_cleanup_task()
        sync_mock_callable.assert_called_once()
        mock_create_task.assert_called_once_with(coro=dummy_coroutine_obj)

        task = mock_create_task.return_value
        task.done.return_value = False
        rate_limiter._start_cleanup_task()

        sync_mock_callable.assert_called_once()
        mock_create_task.assert_called_once()

        task.done.return_value = True
        rate_limiter._start_cleanup_task()

        assert sync_mock_callable.call_count == 2
        assert mock_create_task.call_count == 2
