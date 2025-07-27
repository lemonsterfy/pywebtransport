"""Unit tests for the pywebtransport.server.middleware module."""

import asyncio
import logging

import pytest
from _pytest.logging import LogCaptureFixture
from pytest_mock import MockerFixture

from pywebtransport.server import (
    MiddlewareManager,
    create_auth_middleware,
    create_cors_middleware,
    create_logging_middleware,
    create_rate_limit_middleware,
)
from pywebtransport.server.middleware import RateLimiter
from pywebtransport.session import WebTransportSession


class TestMiddlewareManager:
    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> WebTransportSession:
        return mocker.create_autospec(WebTransportSession, instance=True)

    @pytest.mark.asyncio
    async def test_add_remove_middleware(self) -> None:
        manager = MiddlewareManager()
        assert manager.get_middleware_count() == 0

        async def middleware1(session: WebTransportSession) -> bool:
            return True

        manager.add_middleware(middleware1)
        assert manager.get_middleware_count() == 1

        manager.remove_middleware(middleware1)
        assert manager.get_middleware_count() == 0

        manager.remove_middleware(middleware1)
        assert manager.get_middleware_count() == 0

    @pytest.mark.asyncio
    async def test_process_request_all_pass(self, mock_session: WebTransportSession, mocker: MockerFixture) -> None:
        manager = MiddlewareManager()
        middleware1 = mocker.AsyncMock(return_value=True)
        middleware2 = mocker.AsyncMock(return_value=True)
        manager.add_middleware(middleware1)
        manager.add_middleware(middleware2)

        result = await manager.process_request(mock_session)

        assert result is True
        middleware1.assert_awaited_once_with(mock_session)
        middleware2.assert_awaited_once_with(mock_session)

    @pytest.mark.asyncio
    async def test_process_request_one_fails(self, mock_session: WebTransportSession, mocker: MockerFixture) -> None:
        manager = MiddlewareManager()
        middleware1 = mocker.AsyncMock(return_value=True)
        middleware2 = mocker.AsyncMock(return_value=False)
        middleware3 = mocker.AsyncMock(return_value=True)
        manager.add_middleware(middleware1)
        manager.add_middleware(middleware2)
        manager.add_middleware(middleware3)

        result = await manager.process_request(mock_session)

        assert result is False
        middleware1.assert_awaited_once_with(mock_session)
        middleware2.assert_awaited_once_with(mock_session)
        middleware3.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_request_exception(
        self, mock_session: WebTransportSession, mocker: MockerFixture, caplog: LogCaptureFixture
    ) -> None:
        manager = MiddlewareManager()
        middleware1 = mocker.AsyncMock(side_effect=ValueError("Middleware error"))
        manager.add_middleware(middleware1)

        result = await manager.process_request(mock_session)

        assert result is False
        assert "Middleware error: Middleware error" in caplog.text


class TestMiddlewareFactories:
    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> WebTransportSession:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        session.path = "/test"
        session.headers = {"origin": "https://example.com", "x-auth": "good-token"}
        session.connection.remote_address = ("1.2.3.4", 12345)
        return session

    def test_create_rate_limit_middleware(self) -> None:
        limiter = create_rate_limit_middleware(max_requests=50, window_seconds=30)

        assert isinstance(limiter, RateLimiter)
        assert limiter._max_requests == 50
        assert limiter._window_seconds == 30

    @pytest.mark.asyncio
    async def test_create_logging_middleware(
        self, mock_session: WebTransportSession, caplog: LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)
        logging_middleware = create_logging_middleware()

        result = await logging_middleware(mock_session)

        assert result is True
        assert "Session request: path='/test' from=1.2.3.4:12345" in caplog.text

    @pytest.mark.asyncio
    async def test_create_logging_middleware_no_remote_address(
        self, mocker: MockerFixture, caplog: LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)
        session = mocker.create_autospec(WebTransportSession, instance=True)
        session.path = "/no-addr"
        session.connection.remote_address = None
        logging_middleware = create_logging_middleware()

        await logging_middleware(session)

        assert "from=unknown" in caplog.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("auth_result", [True, False])
    async def test_create_auth_middleware(
        self, mock_session: WebTransportSession, auth_result: bool, mocker: MockerFixture
    ) -> None:
        auth_handler = mocker.AsyncMock(return_value=auth_result)
        auth_middleware = create_auth_middleware(auth_handler=auth_handler)

        result = await auth_middleware(mock_session)

        assert result is auth_result
        auth_handler.assert_awaited_once_with(mock_session.headers)

    @pytest.mark.asyncio
    async def test_create_auth_middleware_handler_exception(
        self, mock_session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        auth_handler = mocker.AsyncMock(side_effect=ValueError("Auth error"))
        auth_middleware = create_auth_middleware(auth_handler=auth_handler)

        result = await auth_middleware(mock_session)

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
        self, mock_session: WebTransportSession, origin: str, allowed_origins: list, expected_result: bool
    ) -> None:
        mock_session.headers = {"origin": origin} if origin else {}
        cors_middleware = create_cors_middleware(allowed_origins=allowed_origins)

        result = await cors_middleware(mock_session)

        assert result is expected_result


class TestRateLimiter:
    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> WebTransportSession:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        session.connection.remote_address = ("1.2.3.4", 12345)
        return session

    @pytest.mark.asyncio
    async def test_rate_limiting_logic(
        self, mock_session: WebTransportSession, mocker: MockerFixture, caplog: LogCaptureFixture
    ) -> None:
        mock_timestamp = mocker.patch("pywebtransport.server.middleware.get_timestamp")
        rate_limiter = RateLimiter(max_requests=2, window_seconds=10)

        mock_timestamp.return_value = 100.0
        assert await rate_limiter(mock_session) is True

        mock_timestamp.return_value = 101.0
        assert await rate_limiter(mock_session) is True

        mock_timestamp.return_value = 102.0
        assert await rate_limiter(mock_session) is False
        assert "Rate limit exceeded for 1.2.3.4" in caplog.text

        mock_timestamp.return_value = 110.1
        assert await rate_limiter(mock_session) is True

    @pytest.mark.asyncio
    async def test_call_no_remote_address(self, mocker: MockerFixture) -> None:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        session.connection.remote_address = None
        rate_limiter = RateLimiter()

        assert await rate_limiter(session) is True

    @pytest.mark.asyncio
    async def test_lifecycle_and_cleanup(self, mocker: MockerFixture) -> None:
        original_sleep = asyncio.sleep
        proceed_event = asyncio.Event()

        async def sleep_mock(delay: float) -> None:
            if delay > 0:
                await proceed_event.wait()
                proceed_event.clear()
                return
            await original_sleep(0)

        mocker.patch("asyncio.sleep", side_effect=sleep_mock)
        mock_timestamp = mocker.patch("pywebtransport.server.middleware.get_timestamp")
        rate_limiter = RateLimiter(window_seconds=10, cleanup_interval=30)

        async with rate_limiter as rl:
            async with rl._lock:
                rl._requests["active_ip"] = [210.0]
                rl._requests["stale_ip"] = [100.0]

            mock_timestamp.return_value = 215.0
            proceed_event.set()
            await asyncio.sleep(0)

            async with rl._lock:
                assert "active_ip" in rl._requests
                assert "stale_ip" not in rl._requests

    @pytest.mark.asyncio
    async def test_start_cleanup_task_idempotent(self, mocker: MockerFixture) -> None:
        dummy_coroutine_obj = mocker.MagicMock(name="dummy_coroutine_obj")
        sync_mock_callable = mocker.MagicMock(return_value=dummy_coroutine_obj)
        mocker.patch("pywebtransport.server.middleware.RateLimiter._periodic_cleanup", new=sync_mock_callable)
        mock_create_task = mocker.patch("asyncio.create_task")
        rate_limiter = RateLimiter()

        rate_limiter._start_cleanup_task()
        sync_mock_callable.assert_called_once()
        mock_create_task.assert_called_once_with(dummy_coroutine_obj)

        task = mock_create_task.return_value
        task.done.return_value = False
        rate_limiter._start_cleanup_task()
        sync_mock_callable.assert_called_once()
        mock_create_task.assert_called_once()

        task.done.return_value = True
        rate_limiter._start_cleanup_task()
        assert sync_mock_callable.call_count == 2
        assert mock_create_task.call_count == 2

    @pytest.mark.asyncio
    async def test_periodic_cleanup_no_stale_ips(self, mocker: MockerFixture) -> None:
        mocker.patch("asyncio.sleep", side_effect=asyncio.CancelledError)
        mock_timestamp = mocker.patch("pywebtransport.server.middleware.get_timestamp")
        rate_limiter = RateLimiter()
        async with rate_limiter._lock:
            rate_limiter._requests["active_ip"] = [100.0]
        mock_timestamp.return_value = 105.0

        with pytest.raises(asyncio.CancelledError):
            await rate_limiter._periodic_cleanup()

        assert "active_ip" in rate_limiter._requests

    @pytest.mark.asyncio
    async def test_periodic_cleanup_empty_timestamps(self, mocker: MockerFixture) -> None:
        mocker.patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError])
        mocker.patch("pywebtransport.server.middleware.get_timestamp", return_value=100.0)
        rate_limiter = RateLimiter()
        async with rate_limiter._lock:
            rate_limiter._requests["empty_ip"] = []

        with pytest.raises(asyncio.CancelledError):
            await rate_limiter._periodic_cleanup()

        assert "empty_ip" not in rate_limiter._requests
