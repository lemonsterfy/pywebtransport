"""Unit tests for the pywebtransport.pubsub.manager module."""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
import pytest_asyncio
from pytest_mock import MockerFixture

from pywebtransport import ConnectionError, WebTransportStream
from pywebtransport.constants import ErrorCodes
from pywebtransport.pubsub import (
    NotSubscribedError,
    PubSubError,
    PubSubManager,
    PubSubStats,
    Subscription,
    SubscriptionFailedError,
)
from pywebtransport.pubsub.manager import logger as manager_logger


@pytest.fixture
def mock_stream(mocker: MockerFixture) -> MagicMock:
    stream = mocker.create_autospec(WebTransportStream, instance=True)
    stream.is_closed = False

    async def mock_close(**kwargs: Any) -> None:
        stream.is_closed = True

    async def wait_forever(*args: Any, **kwargs: Any) -> None:
        await asyncio.Future()

    stream.close = AsyncMock(side_effect=mock_close)
    stream.write = AsyncMock()
    stream.readline = AsyncMock(side_effect=wait_forever)
    stream.readexactly = AsyncMock()
    return stream


@pytest.fixture
def pubsub_manager(mock_stream: MagicMock) -> PubSubManager:
    return PubSubManager(stream=mock_stream, max_queue_size=10)


@pytest_asyncio.fixture
async def running_manager(pubsub_manager: PubSubManager) -> AsyncGenerator[PubSubManager, None]:
    async with pubsub_manager as manager:
        yield manager


@pytest.mark.asyncio
class TestPubSubManager:

    async def test_aenter_is_idempotent(self, running_manager: PubSubManager) -> None:
        initial_task = running_manager._ingress_task

        await running_manager.__aenter__()

        assert running_manager._ingress_task is initial_task

    async def test_close_cancels_pending_subscriptions(self, running_manager: PubSubManager) -> None:
        subscribe_task = asyncio.create_task(coro=running_manager.subscribe(topic="pending"))
        await asyncio.sleep(delay=0)
        assert "pending" in running_manager._pending_subscriptions
        pending_future = running_manager._pending_subscriptions["pending"][0]

        await running_manager.close()

        with pytest.raises(PubSubError, match="PubSubManager is closing."):
            await pending_future
        with pytest.raises(PubSubError):
            await subscribe_task

    async def test_close_handles_done_pending_future(self, running_manager: PubSubManager) -> None:
        future: asyncio.Future[Any] = asyncio.Future()
        future.set_result(None)
        running_manager._pending_subscriptions["done"] = (future, MagicMock())

        await running_manager.close()

        assert "done" not in running_manager._pending_subscriptions

    async def test_close_handles_full_queue(self, running_manager: PubSubManager) -> None:
        sub = Subscription(topic="full", manager=running_manager, max_queue_size=1)
        async with sub:
            assert sub._queue is not None
            sub._queue.put_nowait(b"msg")
            running_manager._subscriptions["full"] = {sub}

            await running_manager.close()

            assert sub._queue.full()

    async def test_close_handles_subscription_without_queue(self, running_manager: PubSubManager) -> None:
        sub = Subscription(topic="no_queue", manager=running_manager, max_queue_size=1)
        assert sub._queue is None
        running_manager._subscriptions["no_queue"] = {sub}

        await running_manager.close()

    async def test_close_idempotency(self, running_manager: PubSubManager, mocker: MockerFixture) -> None:
        assert running_manager._ingress_task is not None
        cancel_spy = mocker.spy(running_manager._ingress_task, "cancel")

        await running_manager.close()
        await running_manager.close()

        cancel_spy.assert_called_once()

    async def test_close_on_already_closed_stream(self, running_manager: PubSubManager, mock_stream: MagicMock) -> None:
        await running_manager.close()
        running_manager._is_closing = False
        mock_stream.is_closed = True
        mock_stream.close.reset_mock()

        await running_manager.close()

        mock_stream.close.assert_not_awaited()

    async def test_close_terminates_active_queues(self, running_manager: PubSubManager) -> None:
        sub = Subscription(topic="active", manager=running_manager, max_queue_size=10)
        async with sub:
            running_manager._subscriptions["active"] = {sub}

            await running_manager.close()

            assert sub._queue is not None
            assert await sub._queue.get() is None

    async def test_context_manager_flow(self, pubsub_manager: PubSubManager, mock_stream: MagicMock) -> None:
        mock_stream.readline.side_effect = asyncio.CancelledError

        async with pubsub_manager:
            assert pubsub_manager._ingress_task is not None
            assert not pubsub_manager._ingress_task.done()

        await asyncio.sleep(delay=0)
        mock_stream.close.assert_awaited_once_with(error_code=ErrorCodes.APPLICATION_ERROR)
        assert pubsub_manager._ingress_task.done()

    async def test_ingress_loop_continuity(self, running_manager: PubSubManager, mock_stream: MagicMock) -> None:
        sub = Subscription(topic="t1", manager=running_manager, max_queue_size=1)
        running_manager._subscriptions["t1"] = {sub}
        fut_ok: asyncio.Future[Any] = asyncio.Future()
        running_manager._pending_subscriptions["t2"] = (fut_ok, MagicMock())
        fut_fail: asyncio.Future[Any] = asyncio.Future()
        running_manager._pending_subscriptions["t3"] = (fut_fail, MagicMock())
        mock_stream.readline.side_effect = [b"MSG t1 4\n", b"SUB-OK t2\n", b"SUB-FAIL t3 reason\n", b""]
        mock_stream.readexactly.return_value = b"data"

        async with sub:
            await running_manager._ingress_loop()

        assert running_manager.stats.messages_received == 1
        assert fut_ok.done()
        assert "t2" not in running_manager._pending_subscriptions
        assert fut_fail.done()
        with pytest.raises(SubscriptionFailedError):
            await fut_fail
        assert "t3" not in running_manager._pending_subscriptions

    async def test_ingress_loop_does_not_run_if_stream_closed(
        self, pubsub_manager: PubSubManager, mock_stream: MagicMock
    ) -> None:
        mock_stream.is_closed = True

        async with pubsub_manager:
            await asyncio.sleep(delay=0)
            assert pubsub_manager._ingress_task is not None
            assert pubsub_manager._ingress_task.done()

        mock_stream.readline.assert_not_called()

    async def test_ingress_loop_exception_while_closing(
        self, running_manager: PubSubManager, mock_stream: MagicMock, mocker: MockerFixture
    ) -> None:
        running_manager._is_closing = True
        mock_stream.readline.side_effect = ValueError("Closing error")
        mock_logger_error = mocker.patch.object(manager_logger, "error")

        await running_manager._ingress_loop()

        mock_logger_error.assert_not_called()

    async def test_ingress_loop_handles_full_queue(
        self, running_manager: PubSubManager, mock_stream: MagicMock, mocker: MockerFixture
    ) -> None:
        mocked_warning = mocker.patch.object(manager_logger, "warning")
        sub = Subscription(topic="news", manager=running_manager, max_queue_size=1)
        async with sub:
            assert sub._queue is not None
            sub._queue.put_nowait(b"first")
            running_manager._subscriptions["news"] = {sub}
            mock_stream.readline.side_effect = [b"MSG news 5\n", ConnectionError("end")]
            mock_stream.readexactly.return_value = b"second"

            await running_manager._ingress_loop()

            assert sub._queue.full()
            mocked_warning.assert_called_once_with(
                "Subscription queue for topic '%s' is full. Dropping message.", "news"
            )

    async def test_ingress_loop_handles_generic_exception(
        self, running_manager: PubSubManager, mock_stream: MagicMock
    ) -> None:
        mock_stream.readline.side_effect = ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            await running_manager._ingress_loop()

    @pytest.mark.parametrize("line", [b"", b"GARBAGE\n", b"MSG news\n", b"SUB-OK\n", b"SUB-FAIL news\n"])
    async def test_ingress_loop_handles_malformed_lines(
        self, running_manager: PubSubManager, mock_stream: MagicMock, line: bytes
    ) -> None:
        mock_stream.readline.side_effect = [line, ConnectionError("end")]

        await running_manager._ingress_loop()

    async def test_ingress_loop_handles_messages(self, running_manager: PubSubManager, mock_stream: MagicMock) -> None:
        subscription = Subscription(topic="news", manager=running_manager, max_queue_size=1)
        async with subscription:
            running_manager._subscriptions = {"news": {subscription}}
            mock_stream.readline.side_effect = [b"MSG news 5\n", ConnectionError("end")]
            mock_stream.readexactly.return_value = b"hello"

            await running_manager._ingress_loop()

            assert subscription._queue is not None
            assert await subscription._queue.get() == b"hello"
            assert running_manager.stats.messages_received == 1

    async def test_ingress_loop_handles_msg_to_unsubscribed_topic(
        self, running_manager: PubSubManager, mock_stream: MagicMock
    ) -> None:
        mock_stream.readline.side_effect = [b"MSG news 5\n", ConnectionError("end")]
        mock_stream.readexactly.return_value = b"hello"

        await running_manager._ingress_loop()

        assert running_manager.stats.messages_received == 0

    @pytest.mark.parametrize("command", [b"SUB-OK", b"SUB-FAIL"])
    async def test_ingress_loop_handles_sub_ack_for_done_future(
        self, running_manager: PubSubManager, mock_stream: MagicMock, command: bytes
    ) -> None:
        future: asyncio.Future[Any] = asyncio.Future()
        future.set_result(None)
        running_manager._pending_subscriptions["news"] = (future, MagicMock())
        line = command + b" news reason\n" if command == b"SUB-FAIL" else command + b" news\n"
        mock_stream.readline.side_effect = [line, ConnectionError("end")]

        await running_manager._ingress_loop()

        assert "news" not in running_manager._pending_subscriptions

    async def test_ingress_loop_handles_subscription_without_queue(
        self, running_manager: PubSubManager, mock_stream: MagicMock
    ) -> None:
        sub = Subscription(topic="news", manager=running_manager, max_queue_size=1)
        running_manager._subscriptions["news"] = {sub}
        mock_stream.readline.side_effect = [b"MSG news 5\n", b""]
        mock_stream.readexactly.return_value = b"hello"

        await running_manager._ingress_loop()

        assert running_manager.stats.messages_received == 1

    async def test_ingress_loop_handles_unsolicited_acks(
        self, running_manager: PubSubManager, mock_stream: MagicMock
    ) -> None:
        mock_stream.readline.side_effect = [b"SUB-OK unsolicited\n", b""]

        await running_manager._ingress_loop()

        assert not running_manager._pending_subscriptions

    async def test_ingress_loop_msg_to_inactive_subscription(
        self, running_manager: PubSubManager, mock_stream: MagicMock
    ) -> None:
        sub = Subscription(topic="news", manager=running_manager, max_queue_size=1)
        running_manager._subscriptions["news"] = {sub}
        mock_stream.readline.side_effect = [b"MSG news 5\n", ConnectionError("end")]
        mock_stream.readexactly.return_value = b"hello"

        await running_manager._ingress_loop()

        assert running_manager.stats.messages_received == 1

    @pytest.mark.parametrize("method_name", ["publish", "subscribe", "unsubscribe"])
    async def test_methods_fail_if_not_activated(self, method_name: str, pubsub_manager: PubSubManager) -> None:
        with pytest.raises(PubSubError, match="has not been activated"):
            if method_name == "publish":
                await pubsub_manager.publish(topic="t", data=b"d")
            elif method_name == "subscribe":
                await pubsub_manager.subscribe(topic="t")
            else:
                await pubsub_manager.unsubscribe(topic="t")

    @pytest.mark.parametrize(
        "is_closing, is_cancelled, exception",
        [(True, False, None), (False, True, None), (False, False, ValueError("test error")), (False, False, None)],
    )
    async def test_on_ingress_done_scenarios(
        self,
        pubsub_manager: PubSubManager,
        mocker: MockerFixture,
        is_closing: bool,
        is_cancelled: bool,
        exception: Exception | None,
    ) -> None:
        pubsub_manager._is_closing = is_closing
        mock_close = mocker.patch.object(pubsub_manager, "close", new_callable=AsyncMock)
        mock_task = mocker.create_autospec(asyncio.Task, instance=True)
        mock_task.cancelled.return_value = is_cancelled
        mock_task.exception.return_value = exception

        pubsub_manager._on_ingress_done(mock_task)
        await asyncio.sleep(delay=0)

        should_close = not is_closing
        assert mock_close.call_count == (1 if should_close else 0)

    async def test_publish_on_closed_stream(self, running_manager: PubSubManager, mock_stream: MagicMock) -> None:
        type(mock_stream).is_closed = PropertyMock(return_value=True)

        with pytest.raises(PubSubError, match="stream is not available"):
            await running_manager.publish(topic="t", data=b"d")

    async def test_publish_success(self, running_manager: PubSubManager, mock_stream: MagicMock) -> None:
        await running_manager.publish(topic="news", data="hello")

        expected_command = b"PUB news 5\nhello"
        mock_stream.write.assert_awaited_with(data=expected_command)
        assert running_manager.stats.messages_published == 1

    async def test_subscribe_fail_response(self, pubsub_manager: PubSubManager, mock_stream: MagicMock) -> None:
        mock_stream.readline.side_effect = [b"SUB-FAIL news unauthorized\n", ConnectionError("end")]

        async with pubsub_manager:
            with pytest.raises(SubscriptionFailedError, match="unauthorized"):
                await pubsub_manager.subscribe(topic="news")
            assert pubsub_manager.stats.subscription_errors == 1
            assert "news" not in pubsub_manager._pending_subscriptions

    async def test_subscribe_generic_exception(self, running_manager: PubSubManager) -> None:
        subscribe_task = asyncio.create_task(coro=running_manager.subscribe(topic="news"))
        await asyncio.sleep(delay=0)
        pending_future = running_manager._pending_subscriptions["news"][0]
        pending_future.set_exception(ValueError("test"))

        with pytest.raises(ValueError, match="test"):
            await subscribe_task

        assert "news" not in running_manager._pending_subscriptions
        assert running_manager.stats.subscription_errors == 1

    async def test_subscribe_invalid_queue_size(self, running_manager: PubSubManager) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            await running_manager.subscribe(topic="news", max_queue_size=0)

    async def test_subscribe_on_closed_stream(self, running_manager: PubSubManager, mock_stream: MagicMock) -> None:
        type(mock_stream).is_closed = PropertyMock(return_value=True)

        with pytest.raises(PubSubError, match="stream is not available"):
            await running_manager.subscribe(topic="news")

    async def test_subscribe_success(self, pubsub_manager: PubSubManager, mock_stream: MagicMock) -> None:
        mock_stream.readline.side_effect = [b"SUB-OK news\n", ConnectionError("end")]

        async with pubsub_manager:
            subscription = await pubsub_manager.subscribe(topic="news")
            assert isinstance(subscription, Subscription)
            assert pubsub_manager.stats.topics_subscribed == 1
            mock_stream.write.assert_awaited_with(data=b"SUB news\n")

    async def test_subscribe_timeout(self, running_manager: PubSubManager) -> None:
        with pytest.raises(SubscriptionFailedError, match="timed out"):
            await running_manager.subscribe(topic="news", timeout=0.01)

        assert running_manager.stats.subscription_errors == 1
        assert "news" not in running_manager._pending_subscriptions

    async def test_subscribe_uses_default_queue_size(
        self, pubsub_manager: PubSubManager, mock_stream: MagicMock
    ) -> None:
        mock_stream.readline.side_effect = [b"SUB-OK news\n", ConnectionError("end")]

        async with pubsub_manager:
            subscription = await pubsub_manager.subscribe(topic="news")
            async with subscription:
                assert subscription._queue is not None
                assert subscription._queue.maxsize == 10

    async def test_subscribe_uses_provided_queue_size(
        self, pubsub_manager: PubSubManager, mock_stream: MagicMock
    ) -> None:
        mock_stream.readline.side_effect = [b"SUB-OK news\n", ConnectionError("end")]

        async with pubsub_manager:
            subscription = await pubsub_manager.subscribe(topic="news", max_queue_size=5)
            async with subscription:
                assert subscription._queue is not None
                assert subscription._queue.maxsize == 5

    async def test_subscribe_when_pending(self, running_manager: PubSubManager) -> None:
        _ = asyncio.create_task(coro=running_manager.subscribe(topic="news"))
        await asyncio.sleep(delay=0)

        with pytest.raises(PubSubError, match="is already pending"):
            await running_manager.subscribe(topic="news")

    async def test_unsubscribe_closes_active_subscription_queue(
        self, pubsub_manager: PubSubManager, mock_stream: MagicMock
    ) -> None:
        mock_stream.readline.side_effect = [b"SUB-OK news\n", ConnectionError("end")]

        async with pubsub_manager:
            subscription = await pubsub_manager.subscribe(topic="news")
            async with subscription:
                assert subscription._queue is not None
                await pubsub_manager.unsubscribe(topic="news")
                assert not subscription._queue.empty()
                assert subscription._queue.get_nowait() is None

    async def test_unsubscribe_flow(self, pubsub_manager: PubSubManager, mock_stream: MagicMock) -> None:
        mock_stream.readline.side_effect = [b"SUB-OK news\n", ConnectionError("end")]

        async with pubsub_manager:
            subscription = await pubsub_manager.subscribe(topic="news")
            await subscription.unsubscribe()
            assert pubsub_manager.stats.topics_subscribed == 0
            mock_stream.write.assert_awaited_with(data=b"UNSUB news\n")

    async def test_unsubscribe_not_subscribed(self, running_manager: PubSubManager, mock_stream: MagicMock) -> None:
        await running_manager.unsubscribe(topic="news")

        mock_stream.write.assert_not_awaited()

    async def test_unsubscribe_on_closed_stream(self, running_manager: PubSubManager, mock_stream: MagicMock) -> None:
        sub = Subscription(topic="news", manager=running_manager, max_queue_size=1)
        running_manager._subscriptions["news"].add(sub)
        type(mock_stream).is_closed = PropertyMock(return_value=True)

        with pytest.raises(NotSubscribedError, match="stream is not available"):
            await running_manager.unsubscribe(topic="news")

    async def test_unsubscribe_with_full_queue(self, running_manager: PubSubManager) -> None:
        sub = Subscription(topic="news", manager=running_manager, max_queue_size=1)
        running_manager._subscriptions["news"].add(sub)
        async with sub:
            assert sub._queue is not None
            sub._queue.put_nowait(b"full")

            await running_manager.unsubscribe(topic="news")

            assert sub._queue.full()
            assert sub._queue.get_nowait() == b"full"


class TestPubSubStats:

    def test_initialization_and_to_dict(self) -> None:
        stats = PubSubStats(
            created_at=12345.67, topics_subscribed=1, messages_published=2, messages_received=3, subscription_errors=4
        )

        data = stats.to_dict()

        assert data["created_at"] == 12345.67
        assert data["topics_subscribed"] == 1
        assert data["messages_published"] == 2
        assert data["messages_received"] == 3
        assert data["subscription_errors"] == 4


@pytest.mark.asyncio
class TestSubscription:

    @pytest.fixture
    def mock_manager(self, mocker: MockerFixture) -> MagicMock:
        manager = mocker.create_autospec(PubSubManager, instance=True)
        manager.unsubscribe = AsyncMock()
        return manager

    async def test_aenter_is_idempotent(self, mock_manager: MagicMock) -> None:
        subscription = Subscription(topic="test.topic", manager=mock_manager, max_queue_size=1)
        await subscription.__aenter__()
        initial_queue = subscription._queue
        assert initial_queue is not None

        await subscription.__aenter__()

        assert subscription._queue is initial_queue
        await subscription.__aexit__(None, None, None)

    async def test_async_iteration(self, mock_manager: MagicMock) -> None:
        subscription = Subscription(topic="test.topic", manager=mock_manager, max_queue_size=3)

        async with subscription:
            assert subscription._queue is not None
            await subscription._queue.put(b"message1")
            await subscription._queue.put(b"message2")
            await subscription._queue.put(None)
            results = [message async for message in subscription]
            assert results == [b"message1", b"message2"]

    async def test_async_iteration_cancelled(self, mock_manager: MagicMock) -> None:
        subscription = Subscription(topic="test.topic", manager=mock_manager, max_queue_size=1)

        async with subscription:
            iterator = subscription.__aiter__()

            async def get_next_item() -> None:
                await anext(iterator)

            task: asyncio.Task[None] = asyncio.create_task(coro=get_next_item())

            await asyncio.sleep(delay=0)
            task.cancel()
            with pytest.raises(StopAsyncIteration):
                await task

    async def test_async_iteration_without_context(self) -> None:
        subscription = Subscription(topic="test.topic", manager=MagicMock(), max_queue_size=1)

        with pytest.raises(PubSubError, match="Subscription has not been activated"):
            async for _ in subscription:
                pass

    async def test_context_unsubscribes_on_exit(self, mock_manager: MagicMock) -> None:
        subscription = Subscription(topic="test.topic", manager=mock_manager, max_queue_size=1)

        async with subscription:
            pass

        mock_manager.unsubscribe.assert_awaited_once_with(topic="test.topic")
