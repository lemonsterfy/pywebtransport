"""Unit tests for the pywebtransport.datagram.broadcaster module."""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from _pytest.logging import LogCaptureFixture
from pytest_asyncio import fixture as asyncio_fixture
from pytest_mock import MockerFixture

from pywebtransport import SessionError, WebTransportSession
from pywebtransport.datagram import DatagramBroadcaster


@pytest.mark.asyncio
class TestDatagramBroadcaster:

    @asyncio_fixture
    async def broadcaster(self) -> AsyncGenerator[DatagramBroadcaster, None]:
        async with DatagramBroadcaster() as b:
            yield b

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> Any:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        session.send_datagram = mocker.AsyncMock()
        session.is_closed = False
        session.session_id = "test_session_id"
        return session

    async def test_add_session(self, broadcaster: DatagramBroadcaster, mock_session: Any) -> None:
        assert await broadcaster.get_session_count() == 0

        await broadcaster.add_session(session=mock_session)

        assert await broadcaster.get_session_count() == 1

    async def test_add_session_idempotent(self, broadcaster: DatagramBroadcaster, mock_session: Any) -> None:
        await broadcaster.add_session(session=mock_session)
        await broadcaster.add_session(session=mock_session)

        assert await broadcaster.get_session_count() == 1

    async def test_aexit_uninitialized(self) -> None:
        broadcaster = DatagramBroadcaster()

        await broadcaster.__aexit__(None, None, None)

    async def test_broadcast_all_fail(
        self, broadcaster: DatagramBroadcaster, mock_session: Any, mocker: MockerFixture
    ) -> None:
        session1 = mock_session
        session1.send_datagram.side_effect = Exception("Failure 1")
        session2 = mocker.create_autospec(WebTransportSession, instance=True)
        session2.is_closed = True
        await broadcaster.add_session(session=session1)
        await broadcaster.add_session(session=session2)
        assert await broadcaster.get_session_count() == 2

        sent_count = await broadcaster.broadcast(data=b"data")

        assert sent_count == 0
        assert await broadcaster.get_session_count() == 0

    async def test_broadcast_empty(self, broadcaster: DatagramBroadcaster) -> None:
        sent_count = await broadcaster.broadcast(data=b"data")

        assert sent_count == 0

    async def test_broadcast_handles_race_condition_on_remove(
        self, broadcaster: DatagramBroadcaster, mock_session: Any, mocker: MockerFixture
    ) -> None:
        session_to_remove = mock_session
        session_to_remove.send_datagram.side_effect = Exception("Send failed")
        await broadcaster.add_session(session=session_to_remove)
        assert await broadcaster.get_session_count() == 1
        original_gather = asyncio.gather

        async def gather_side_effect(*tasks: Any, **kwargs: Any) -> list[Any]:
            await broadcaster.remove_session(session=session_to_remove)
            return cast(list[Any], await original_gather(*tasks, **kwargs))

        mocker.patch(
            "pywebtransport.datagram.broadcaster.asyncio.gather",
            side_effect=gather_side_effect,
        )

        sent_count = await broadcaster.broadcast(data=b"data")

        assert sent_count == 0
        assert await broadcaster.get_session_count() == 0

    async def test_broadcast_success_all(
        self, broadcaster: DatagramBroadcaster, mock_session: Any, mocker: MockerFixture
    ) -> None:
        session1 = mock_session
        session2 = mocker.create_autospec(WebTransportSession, instance=True)
        session2.send_datagram = mocker.AsyncMock()
        session2.is_closed = False
        await broadcaster.add_session(session=session1)
        await broadcaster.add_session(session=session2)

        sent_count = await broadcaster.broadcast(data=b"ping")

        assert sent_count == 2
        cast(AsyncMock, session1.send_datagram).assert_awaited_once_with(data=b"ping")
        cast(AsyncMock, session2.send_datagram).assert_awaited_once_with(data=b"ping")
        assert await broadcaster.get_session_count() == 2

    async def test_broadcast_with_pre_closed_session(
        self, broadcaster: DatagramBroadcaster, mock_session: Any, mocker: MockerFixture
    ) -> None:
        healthy_session = mock_session
        closed_session = mocker.create_autospec(WebTransportSession, instance=True)
        closed_session.send_datagram = mocker.AsyncMock()
        closed_session.is_closed = True
        await broadcaster.add_session(session=healthy_session)
        await broadcaster.add_session(session=closed_session)
        assert await broadcaster.get_session_count() == 2

        sent_count = await broadcaster.broadcast(data=b"data")

        assert sent_count == 1
        cast(AsyncMock, healthy_session.send_datagram).assert_awaited_once_with(data=b"data")
        cast(AsyncMock, closed_session.send_datagram).assert_not_awaited()
        assert await broadcaster.get_session_count() == 1

    async def test_broadcast_with_send_failure(
        self,
        broadcaster: DatagramBroadcaster,
        mock_session: Any,
        mocker: MockerFixture,
        caplog: LogCaptureFixture,
    ) -> None:
        healthy_session = mock_session
        failing_session = mocker.create_autospec(WebTransportSession, instance=True)
        failing_session.session_id = "fail_session"
        failing_session.send_datagram = mocker.AsyncMock(side_effect=SessionError(message="Send failed"))
        failing_session.is_closed = False
        await broadcaster.add_session(session=healthy_session)
        await broadcaster.add_session(session=failing_session)
        assert await broadcaster.get_session_count() == 2

        sent_count = await broadcaster.broadcast(data=b"data")

        assert sent_count == 1
        cast(AsyncMock, healthy_session.send_datagram).assert_awaited_once()
        cast(AsyncMock, failing_session.send_datagram).assert_awaited_once()
        assert await broadcaster.get_session_count() == 1
        assert "Failed to broadcast to session" in caplog.text
        assert "Send failed" in caplog.text

    @pytest.mark.parametrize(
        "method_name, kwargs",
        [
            ("add_session", {"session": AsyncMock()}),
            ("remove_session", {"session": AsyncMock()}),
            ("broadcast", {"data": b"data"}),
            ("get_session_count", {}),
        ],
    )
    async def test_methods_on_uninitialized_raises_error(self, method_name: str, kwargs: dict[str, Any]) -> None:
        broadcaster = DatagramBroadcaster()
        method = getattr(broadcaster, method_name)

        with pytest.raises(SessionError, match="has not been activated"):
            await method(**kwargs)

    async def test_remove_nonexistent_session(self, broadcaster: DatagramBroadcaster, mock_session: Any) -> None:
        assert await broadcaster.get_session_count() == 0

        await broadcaster.remove_session(session=mock_session)

        assert await broadcaster.get_session_count() == 0

    async def test_remove_session(self, broadcaster: DatagramBroadcaster, mock_session: Any) -> None:
        await broadcaster.add_session(session=mock_session)
        assert await broadcaster.get_session_count() == 1

        await broadcaster.remove_session(session=mock_session)

        assert await broadcaster.get_session_count() == 0

    async def test_shutdown_clears_sessions(self, broadcaster: DatagramBroadcaster, mock_session: Any) -> None:
        await broadcaster.add_session(session=mock_session)
        assert await broadcaster.get_session_count() == 1

        await broadcaster.shutdown()

        assert await broadcaster.get_session_count() == 0
