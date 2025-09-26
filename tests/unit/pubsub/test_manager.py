"""Unit tests for the pywebtransport.pubsub.manager module."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ConnectionError, WebTransportSession, WebTransportStream
from pywebtransport.pubsub import (
    NotSubscribedError,
    PubSubError,
    PubSubManager,
    PubSubStats,
    Subscription,
    SubscriptionFailedError,
)


@pytest.fixture
def mock_session(mocker: MockerFixture) -> MagicMock:
    session = mocker.create_autospec(WebTransportSession, instance=True)
    return session


@pytest.fixture
def mock_stream(mocker: MockerFixture) -> MagicMock:
    stream = mocker.create_autospec(WebTransportStream, instance=True)
    stream.is_closed = False

    async def mock_abort() -> None:
        stream.is_closed = True

    stream.abort = AsyncMock(side_effect=mock_abort)
    stream.write = AsyncMock()
    stream.readline = AsyncMock()
    stream.readexactly = AsyncMock()
    return stream


@pytest.fixture
def pubsub_manager(mock_session: MagicMock) -> PubSubManager:
    return PubSubManager(session=mock_session)


class TestPubSubStats:
    def test_initialization_and_to_dict(self) -> None:
        timestamp = 12345.0
        stats = PubSubStats(
            created_at=timestamp,
            topics_subscribed=1,
            messages_published=2,
            messages_received=3,
            subscription_errors=4,
        )

        assert stats.created_at == timestamp
        assert stats.topics_subscribed == 1
        assert stats.messages_published == 2
        assert stats.messages_received == 3
        assert stats.subscription_errors == 4
        expected_dict = {
            "created_at": timestamp,
            "topics_subscribed": 1,
            "messages_published": 2,
            "messages_received": 3,
            "subscription_errors": 4,
        }
        assert stats.to_dict() == expected_dict


@pytest.mark.asyncio
class TestSubscription:
    async def test_aenter_idempotency(self) -> None:
        manager = MagicMock()
        manager.unsubscribe = AsyncMock()
        subscription = Subscription(topic="test.topic", manager=manager, max_queue_size=1)

        async with subscription:
            queue_1 = subscription._queue
            assert queue_1 is not None
            async with subscription:
                assert subscription._queue is queue_1

    async def test_aexit_handles_exception(self) -> None:
        manager = MagicMock()
        manager.unsubscribe = AsyncMock()
        subscription = Subscription(topic="test.topic", manager=manager, max_queue_size=1)
        with pytest.raises(ValueError, match="test error"):
            async with subscription:
                raise ValueError("test error")
        manager.unsubscribe.assert_awaited_once()

    async def test_context_unsubscribes_on_exit(self, mocker: MockerFixture) -> None:
        manager = mocker.create_autospec(PubSubManager, instance=True)
        manager.unsubscribe = AsyncMock()
        subscription = Subscription(topic="test.topic", manager=manager, max_queue_size=1)

        async with subscription:
            pass

        manager.unsubscribe.assert_awaited_once_with(topic="test.topic")

    async def test_unsubscribe(self, mocker: MockerFixture) -> None:
        manager = mocker.create_autospec(PubSubManager, instance=True)
        manager.unsubscribe = AsyncMock()
        subscription = Subscription(topic="test.topic", manager=manager, max_queue_size=1)

        await subscription.unsubscribe()

        manager.unsubscribe.assert_awaited_once_with(topic="test.topic")

    async def test_async_iteration(self) -> None:
        manager = MagicMock()
        manager.unsubscribe = AsyncMock()
        subscription = Subscription(topic="test.topic", manager=manager, max_queue_size=2)

        async with subscription:
            assert subscription._queue is not None
            await subscription._queue.put(b"message1")
            await subscription._queue.put(b"message2")

            async def consume() -> list[bytes]:
                results: list[bytes] = []
                async for message in subscription:
                    results.append(message)
                    if len(results) == 2:
                        break
                return results

            results = await asyncio.wait_for(consume(), timeout=1)

            assert results == [b"message1", b"message2"]
            assert subscription._queue.empty()

    async def test_async_iteration_without_context(self) -> None:
        subscription = Subscription(topic="test.topic", manager=MagicMock(), max_queue_size=1)

        with pytest.raises(PubSubError, match="Subscription has not been activated"):
            async for _ in subscription:
                pass

    async def test_async_iteration_cancelled(self) -> None:
        manager = MagicMock()
        manager.unsubscribe = AsyncMock()
        subscription = Subscription(topic="test.topic", manager=manager, max_queue_size=1)

        async def consume() -> list[bytes]:
            results: list[bytes] = []
            try:
                async for _ in subscription:
                    pass
            except asyncio.CancelledError:
                pass
            return results

        async with subscription:
            consume_task = asyncio.create_task(consume())
            await asyncio.sleep(0)

            consume_task.cancel()
            results = await consume_task

            assert not results


@pytest.mark.asyncio
class TestPubSubManager:
    @pytest.fixture(autouse=True)
    def setup_mocks(self, mock_session: MagicMock, mock_stream: MagicMock) -> None:
        mock_session.create_bidirectional_stream.return_value = mock_stream

    async def test_context_manager_flow(self, pubsub_manager: PubSubManager, mock_stream: MagicMock) -> None:
        async with pubsub_manager:
            assert pubsub_manager._stream is mock_stream
            assert pubsub_manager._ingress_task is not None
            assert not pubsub_manager._ingress_task.done()

        await asyncio.sleep(0)

        mock_stream.abort.assert_awaited_once()
        assert pubsub_manager._ingress_task.done()

    async def test_context_manager_reentry(self, pubsub_manager: PubSubManager, mock_session: MagicMock) -> None:
        async with pubsub_manager:
            lock_1 = pubsub_manager._lock
            stream_1 = pubsub_manager._stream
            mock_session.create_bidirectional_stream.assert_awaited_once()

            async with pubsub_manager:
                assert pubsub_manager._lock is lock_1
                assert pubsub_manager._stream is stream_1
                mock_session.create_bidirectional_stream.assert_awaited_once()

    async def test_close_on_uninitialized_manager(self, pubsub_manager: PubSubManager) -> None:
        await pubsub_manager.close()

    async def test_close_cancels_running_task(self, pubsub_manager: PubSubManager, mock_stream: MagicMock) -> None:
        async def hang_forever(*args: Any, **kwargs: Any) -> bytes:
            await asyncio.Future()
            return b""

        mock_stream.readline.side_effect = hang_forever
        task = None
        async with pubsub_manager:
            task = pubsub_manager._ingress_task
            assert task and not task.done()

        await asyncio.sleep(0)
        assert task and task.cancelled()

    async def test_close_idempotency(self, pubsub_manager: PubSubManager, mock_stream: MagicMock) -> None:
        async with pubsub_manager:
            task = pubsub_manager._ingress_task
            assert task is not None
            task.cancel()
            await asyncio.sleep(0)
            assert task.done()

        await pubsub_manager.close()

        mock_stream.abort.assert_awaited_once()

    async def test_close_with_done_pending_future(self, pubsub_manager: PubSubManager) -> None:
        async with pubsub_manager:
            future: asyncio.Future[Any] = asyncio.Future()
            future.set_result(None)
            pubsub_manager._pending_subscriptions["done"] = (future, MagicMock())

            await pubsub_manager.close()

    async def test_close_with_full_queue(self, pubsub_manager: PubSubManager, mocker: MockerFixture) -> None:
        subscription = Subscription(topic="news", manager=pubsub_manager, max_queue_size=1)
        mocker.patch.object(subscription, "unsubscribe", new_callable=AsyncMock)
        async with pubsub_manager:
            async with subscription:
                assert subscription._queue is not None
                await subscription._queue.put(b"message")
                pubsub_manager._subscriptions["news"].add(subscription)

                await pubsub_manager.close()

                assert subscription._queue.full()
                assert subscription._queue.get_nowait() == b"message"

    async def test_close_cancels_pending_subscriptions(
        self, pubsub_manager: PubSubManager, mock_stream: MagicMock
    ) -> None:
        async def hang_forever() -> bytes:
            await asyncio.Future()
            return b""

        mock_stream.readline.side_effect = hang_forever

        async with pubsub_manager:
            subscribe_task = asyncio.create_task(pubsub_manager.subscribe(topic="pending"))
            await asyncio.sleep(0)
            assert "pending" in pubsub_manager._pending_subscriptions
            pending_future = pubsub_manager._pending_subscriptions["pending"][0]

            await pubsub_manager.close()

            with pytest.raises(PubSubError, match="PubSubManager is closing."):
                await pending_future
            with pytest.raises(PubSubError):
                await subscribe_task

    @pytest.mark.parametrize("method_name", ["publish", "subscribe", "unsubscribe"])
    async def test_methods_fail_if_not_activated(self, method_name: str, mock_session: MagicMock) -> None:
        pubsub_manager = PubSubManager(session=mock_session)

        with pytest.raises(PubSubError, match="has not been activated"):
            if method_name == "publish":
                await pubsub_manager.publish(topic="t", data=b"d")
            elif method_name == "subscribe":
                await pubsub_manager.subscribe(topic="t")
            else:
                await pubsub_manager.unsubscribe(topic="t")

    async def test_publish_success(self, pubsub_manager: PubSubManager, mock_stream: MagicMock) -> None:
        async with pubsub_manager:
            await pubsub_manager.publish(topic="news", data=b"hello")

            expected_command = b"PUB news 5\nhello"
            mock_stream.write.assert_awaited_with(data=expected_command)
            assert pubsub_manager.stats.messages_published == 1

    async def test_publish_on_closed_stream(self, pubsub_manager: PubSubManager, mock_stream: MagicMock) -> None:
        async with pubsub_manager:
            mock_stream.is_closed = True

            with pytest.raises(PubSubError, match="stream is not available"):
                await pubsub_manager.publish(topic="t", data=b"d")

    async def test_subscribe_success(self, pubsub_manager: PubSubManager, mock_stream: MagicMock) -> None:
        call_count = 0

        async def readline_effect(*args: Any, **kwargs: Any) -> bytes:
            nonlocal call_count
            if call_count == 0:
                call_count += 1
                return b"SUB-OK news\n"
            await asyncio.Future()
            return b""

        mock_stream.readline.side_effect = readline_effect

        async with pubsub_manager:
            subscription = await pubsub_manager.subscribe(topic="news")

            assert isinstance(subscription, Subscription)
            assert pubsub_manager.stats.topics_subscribed == 1
            mock_stream.write.assert_awaited_with(data=b"SUB news\n")

    async def test_subscribe_fail_response(self, pubsub_manager: PubSubManager, mock_stream: MagicMock) -> None:
        async with pubsub_manager:
            mock_stream.readline.side_effect = [b"SUB-FAIL news unauthorized\n"]

            with pytest.raises(SubscriptionFailedError, match="unauthorized"):
                await pubsub_manager.subscribe(topic="news")

            assert pubsub_manager.stats.subscription_errors == 1

    async def test_subscribe_timeout(self, pubsub_manager: PubSubManager, mocker: MockerFixture) -> None:
        mocker.patch("asyncio.wait_for", side_effect=asyncio.TimeoutError)

        async with pubsub_manager:
            with pytest.raises(SubscriptionFailedError, match="timed out"):
                await pubsub_manager.subscribe(topic="news")

            assert pubsub_manager.stats.subscription_errors == 1
            assert "news" not in pubsub_manager._pending_subscriptions

    async def test_subscribe_on_closed_stream(self, pubsub_manager: PubSubManager, mock_stream: MagicMock) -> None:
        async with pubsub_manager:
            mock_stream.is_closed = True

            with pytest.raises(PubSubError, match="stream is not available"):
                await pubsub_manager.subscribe(topic="t")

    @pytest.mark.parametrize("size", [0, -1])
    async def test_subscribe_invalid_queue_size(self, pubsub_manager: PubSubManager, size: int) -> None:
        async with pubsub_manager:
            with pytest.raises(ValueError, match="max_queue_size must be positive"):
                await pubsub_manager.subscribe(topic="t", max_queue_size=size)

    async def test_subscribe_already_pending(self, pubsub_manager: PubSubManager) -> None:
        async with pubsub_manager:
            pubsub_manager._pending_subscriptions["news"] = (asyncio.Future(), MagicMock())

            with pytest.raises(PubSubError, match="already pending"):
                await pubsub_manager.subscribe(topic="news")

    async def test_subscribe_generic_exception(self, pubsub_manager: PubSubManager, mocker: MockerFixture) -> None:
        mocker.patch("asyncio.wait_for", side_effect=ValueError("test error"))

        async with pubsub_manager:
            with pytest.raises(ValueError, match="test error"):
                await pubsub_manager.subscribe(topic="news")

            assert pubsub_manager.stats.subscription_errors == 1
            assert "news" not in pubsub_manager._pending_subscriptions

    async def test_unsubscribe_flow(self, pubsub_manager: PubSubManager, mock_stream: MagicMock) -> None:
        call_count = 0

        async def readline_effect(*args: Any, **kwargs: Any) -> bytes:
            nonlocal call_count
            if call_count == 0:
                call_count += 1
                return b"SUB-OK news\n"
            await asyncio.Future()
            return b""

        mock_stream.readline.side_effect = readline_effect

        async with pubsub_manager:
            subscription = await pubsub_manager.subscribe(topic="news")
            assert pubsub_manager.stats.topics_subscribed == 1
            await asyncio.sleep(0)

            await subscription.unsubscribe()

            assert pubsub_manager.stats.topics_subscribed == 0
            assert mock_stream.write.await_count == 2
            mock_stream.write.assert_awaited_with(data=b"UNSUB news\n")

            await pubsub_manager.unsubscribe(topic="news")
            assert mock_stream.write.await_count == 2

    async def test_unsubscribe_on_closed_stream(self, pubsub_manager: PubSubManager, mock_stream: MagicMock) -> None:
        async with pubsub_manager:
            sub = Subscription(topic="news", manager=pubsub_manager, max_queue_size=1)
            pubsub_manager._subscriptions["news"].add(sub)
            mock_stream.is_closed = True

            with pytest.raises(NotSubscribedError, match="stream is not available"):
                await pubsub_manager.unsubscribe(topic="news")

    async def test_ingress_loop_exits_if_no_stream(self, pubsub_manager: PubSubManager) -> None:
        await pubsub_manager._ingress_loop()

    async def test_ingress_loop_exits_on_stream_closed(
        self, pubsub_manager: PubSubManager, mock_stream: MagicMock
    ) -> None:
        async def readline_and_close(*args: Any, **kwargs: Any) -> bytes:
            mock_stream.is_closed = True
            return b"some data\n"

        mock_stream.readline.side_effect = readline_and_close

        async with pubsub_manager:
            await asyncio.sleep(0)
            assert pubsub_manager._ingress_task is not None
            await asyncio.sleep(0)
            assert pubsub_manager._ingress_task.done()
            assert not pubsub_manager._ingress_task.cancelled()

    async def test_ingress_loop_handles_graceful_close(
        self, pubsub_manager: PubSubManager, mock_stream: MagicMock
    ) -> None:
        mock_stream.readline.side_effect = [b""]

        async with pubsub_manager:
            await asyncio.sleep(0)

            assert pubsub_manager._ingress_task is not None
            await asyncio.sleep(0)
            assert pubsub_manager._ingress_task.done()

    async def test_done_callback_on_clean_exit(self, pubsub_manager: PubSubManager, mock_stream: MagicMock) -> None:
        mock_stream.readline.side_effect = [b""]

        async with pubsub_manager:
            assert pubsub_manager._ingress_task is not None
            await pubsub_manager._ingress_task

        await asyncio.sleep(0)
        mock_stream.abort.assert_awaited_once()

    async def test_ingress_loop_handles_connection_error(
        self, pubsub_manager: PubSubManager, mock_stream: MagicMock
    ) -> None:
        mock_stream.readline.side_effect = ConnectionError(message="test")

        with pytest.raises(ConnectionError, match="test"):
            async with pubsub_manager:
                assert pubsub_manager._ingress_task is not None
                await pubsub_manager._ingress_task

    async def test_ingress_loop_handles_generic_error(
        self, pubsub_manager: PubSubManager, mock_stream: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_log = mocker.patch("pywebtransport.pubsub.manager.logger.error")
        mock_stream.readline.side_effect = ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            async with pubsub_manager:
                assert pubsub_manager._ingress_task is not None
                await pubsub_manager._ingress_task

        assert mock_log.call_count == 2

    async def test_ingress_loop_handles_various_commands(
        self, pubsub_manager: PubSubManager, mock_stream: MagicMock
    ) -> None:
        future_ok: asyncio.Future[Any] = asyncio.Future()
        future_fail: asyncio.Future[Any] = asyncio.Future()
        future_ok_done: asyncio.Future[Any] = asyncio.Future()
        future_ok_done.set_result(MagicMock())
        future_fail_done: asyncio.Future[Any] = asyncio.Future()
        future_fail_done.set_exception(ValueError("already failed"))
        sub_with_queue = Subscription(topic="news", manager=pubsub_manager, max_queue_size=1)
        sub_no_queue = Subscription(topic="alerts", manager=pubsub_manager, max_queue_size=1)
        sub_weather = Subscription(topic="weather", manager=pubsub_manager, max_queue_size=1)
        sub_stocks = Subscription(topic="stocks", manager=pubsub_manager, max_queue_size=1)
        sub_ok_done = Subscription(topic="ok_done", manager=pubsub_manager, max_queue_size=1)
        sub_fail_done = Subscription(topic="fail_done", manager=pubsub_manager, max_queue_size=1)

        async with sub_with_queue:
            pubsub_manager._subscriptions = {"news": {sub_with_queue}, "alerts": {sub_no_queue}}
            pubsub_manager._pending_subscriptions = {
                "weather": (future_ok, sub_weather),
                "stocks": (future_fail, sub_stocks),
                "ok_done": (future_ok_done, sub_ok_done),
                "fail_done": (future_fail_done, sub_fail_done),
            }
            mock_stream.readline.side_effect = [
                b"MSG news 5\n",
                b"MSG alerts 4\n",
                b"MSG phantom_topic 3\n",
                b"SUB-OK weather\n",
                b"SUB-FAIL stocks bad_topic\n",
                b"SUB-OK ok_done\n",
                b"SUB-FAIL fail_done reason\n",
                b"SUB-OK unknown_topic\n",
                b"SUB-FAIL unknown_topic_2\n",
                b"INVALID-COMMAND\n",
                b"MSG malformed\n",
                b"SUB-OK\n",
                b"SUB-FAIL malformed\n",
                ConnectionError(message="end test"),
            ]
            mock_stream.readexactly.side_effect = [b"hello", b"warn", b"foo"]

            with pytest.raises(ConnectionError, match="end test"):
                async with pubsub_manager:
                    assert pubsub_manager._ingress_task
                    await pubsub_manager._ingress_task

            assert (await future_ok)._topic == "weather"
            with pytest.raises(SubscriptionFailedError, match="bad_topic"):
                await future_fail
            with pytest.raises(ValueError, match="already failed"):
                await future_fail_done
            assert sub_with_queue._queue is not None
            assert await sub_with_queue._queue.get() == b"hello"
            assert sub_no_queue._queue is None
            assert mock_stream.readexactly.call_count == 3

    async def test_ingress_loop_full_queue(
        self, pubsub_manager: PubSubManager, mock_stream: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_log = mocker.patch("pywebtransport.pubsub.manager.logger.warning")
        subscription = Subscription(topic="news", manager=pubsub_manager, max_queue_size=1)

        async with subscription:
            pubsub_manager._subscriptions = {"news": {subscription}}
            assert subscription._queue is not None
            await subscription._queue.put(b"first")
            mock_stream.readline.side_effect = [b"MSG news 5\n", ConnectionError(message="end")]
            mock_stream.readexactly.return_value = b"extra"

            with pytest.raises(ConnectionError, match="end"):
                async with pubsub_manager:
                    assert pubsub_manager._ingress_task
                    await pubsub_manager._ingress_task

            mock_log.assert_called_once_with("Subscription queue for topic '%s' is full. Dropping message.", "news")
            assert subscription._queue.full()
            assert await subscription._queue.get() == b"first"
            assert subscription._queue.empty()
