"""E2E test for the Pub/Sub (Publish-Subscribe) layer."""

import asyncio
import logging
import ssl
import sys
from collections.abc import Awaitable, Callable
from typing import Final

from pywebtransport import ClientConfig, ConnectionError, TimeoutError, WebTransportClient
from pywebtransport.constants import DEFAULT_PUBSUB_SUBSCRIPTION_QUEUE_SIZE
from pywebtransport.pubsub import PubSubManager, Subscription

SERVER_HOST: Final[str] = "127.0.0.1"
SERVER_PORT: Final[int] = 4433
SERVER_URL: Final[str] = f"https://{SERVER_HOST}:{SERVER_PORT}/pubsub"
DEBUG_MODE: Final[bool] = "--debug" in sys.argv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
if DEBUG_MODE:
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("aioquic").setLevel(logging.DEBUG)
    logging.getLogger("pywebtransport").setLevel(logging.DEBUG)

logger = logging.getLogger("test_pubsub")


async def _receive_message(subscription: Subscription) -> bytes | None:
    """Receive the next message from a subscription, satisfying Mypy."""
    try:
        return await subscription.__aiter__().__anext__()
    except StopAsyncIteration:
        return None


async def test_pubsub_basic_echo() -> bool:
    """Test subscribing, publishing, and receiving a message on a single topic."""
    logger.info("--- Test 10A: Basic Subscribe and Publish ---")
    config = ClientConfig(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )
    topic = "news.sports"
    message = b"Team A wins the championship!"

    try:
        async with WebTransportClient(config=config) as client:
            session = await client.connect(url=SERVER_URL)
            async with session:
                pubsub_stream = await session.create_bidirectional_stream()
                async with PubSubManager(
                    stream=pubsub_stream, max_queue_size=DEFAULT_PUBSUB_SUBSCRIPTION_QUEUE_SIZE
                ) as pubsub:
                    subscription = await pubsub.subscribe(topic=topic)
                    async with subscription:
                        logger.info("Subscribed to topic '%s'.", topic)
                        receiver_task: asyncio.Task[bytes | None] = asyncio.create_task(
                            coro=_receive_message(subscription)
                        )
                        await asyncio.sleep(delay=0.1)

                        logger.info("Publishing message to '%s': %r", topic, message)
                        await pubsub.publish(topic=topic, data=message)

                        try:
                            async with asyncio.timeout(delay=2.0):
                                received_message = await receiver_task
                        except asyncio.TimeoutError:
                            receiver_task.cancel()
                            logger.error("FAILURE: Timed out waiting for message.")
                            return False

                        logger.info("Received message: %r", received_message)

                        if received_message == message:
                            logger.info("SUCCESS: Received the correct published message.")
                            return True
                        else:
                            logger.error("FAILURE: Message mismatch.")
                            return False
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_pubsub_multiple_subscribers() -> bool:
    """Test that a message is broadcast to multiple subscribers."""
    logger.info("--- Test 10B: Multiple Subscribers Broadcast ---")
    config = ClientConfig(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )
    topic = "public.announcements"
    message = b"Scheduled maintenance at midnight."

    try:
        async with WebTransportClient(config=config) as client:
            session1 = await client.connect(url=SERVER_URL)
            session2 = await client.connect(url=SERVER_URL)
            logger.info("Established two sessions: %s and %s", session1.session_id, session2.session_id)

            async with session1, session2:
                stream1 = await session1.create_bidirectional_stream()
                stream2 = await session2.create_bidirectional_stream()
                async with (
                    PubSubManager(stream=stream1, max_queue_size=DEFAULT_PUBSUB_SUBSCRIPTION_QUEUE_SIZE) as pubsub1,
                    PubSubManager(stream=stream2, max_queue_size=DEFAULT_PUBSUB_SUBSCRIPTION_QUEUE_SIZE) as pubsub2,
                ):
                    sub1 = await pubsub1.subscribe(topic=topic)
                    sub2 = await pubsub2.subscribe(topic=topic)

                    async with sub1, sub2:
                        logger.info("Both sessions subscribed to '%s'.", topic)
                        receiver1_task: asyncio.Task[bytes | None] = asyncio.create_task(coro=_receive_message(sub1))
                        receiver2_task: asyncio.Task[bytes | None] = asyncio.create_task(coro=_receive_message(sub2))
                        await asyncio.sleep(delay=0.1)

                        logger.info("Session 1 publishing message: %r", message)
                        await pubsub1.publish(topic=topic, data=message)
                        results = await asyncio.gather(receiver1_task, receiver2_task, return_exceptions=True)

                        if isinstance(results[0], bytes) and isinstance(results[1], bytes):
                            logger.info("Session 1 received: %r", results[0])
                            logger.info("Session 2 received: %r", results[1])
                            if results[0] == message and results[1] == message:
                                logger.info("SUCCESS: Both subscribers received the message.")
                                return True

                        logger.error("FAILURE: One or more subscribers failed. Results: %s", results)
                        return False
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_pubsub_unsubscribe() -> bool:
    """Test that a client stops receiving messages after unsubscribing."""
    logger.info("--- Test 10C: Unsubscribe Logic ---")
    config = ClientConfig(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )
    topic = "realtime.updates"
    message = b"Update #1"

    try:
        async with WebTransportClient(config=config) as client:
            session1 = await client.connect(url=SERVER_URL)
            session2 = await client.connect(url=SERVER_URL)

            async with session1, session2:
                stream1 = await session1.create_bidirectional_stream()
                stream2 = await session2.create_bidirectional_stream()
                async with (
                    PubSubManager(stream=stream1, max_queue_size=DEFAULT_PUBSUB_SUBSCRIPTION_QUEUE_SIZE) as pubsub1,
                    PubSubManager(stream=stream2, max_queue_size=DEFAULT_PUBSUB_SUBSCRIPTION_QUEUE_SIZE) as pubsub2,
                ):
                    sub1 = await pubsub1.subscribe(topic=topic)
                    sub2 = await pubsub2.subscribe(topic=topic)

                    async with sub1, sub2:
                        logger.info("Client 2 unsubscribing from '%s'...", topic)
                        await sub2.unsubscribe()
                        await asyncio.sleep(delay=0.1)

                        receiver1_task: asyncio.Task[bytes | None] = asyncio.create_task(coro=_receive_message(sub1))
                        logger.info("Client 1 publishing message: %r", message)
                        await pubsub1.publish(topic=topic, data=message)

                        try:
                            async with asyncio.timeout(delay=2.0):
                                received1 = await receiver1_task
                        except asyncio.TimeoutError:
                            receiver1_task.cancel()
                            logger.error("FAILURE: Client 1 timed out receiving message")
                            return False

                        assert received1 == message
                        logger.info("SUCCESS: Client 1 (still subscribed) received the message.")

                        logger.info("Verifying Client 2 (unsubscribed) does not receive the message...")
                        receiver2_task = asyncio.create_task(coro=_receive_message(sub2))
                        try:
                            async with asyncio.timeout(delay=1.0):
                                received2 = await receiver2_task
                            if received2 is None:
                                logger.info("SUCCESS: Client 2's subscription iterator ended gracefully.")
                                return True
                            else:
                                logger.error("FAILURE: Client 2 received a message after unsubscribing: %r", received2)
                                return False
                        except asyncio.TimeoutError:
                            receiver2_task.cancel()
                            logger.info("SUCCESS: Client 2 correctly timed out waiting for a message.")
                            return True
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_pubsub_multiple_topics() -> bool:
    """Test that topic subscriptions are correctly isolated."""
    logger.info("--- Test 10D: Multiple Topic Isolation ---")
    config = ClientConfig(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )
    try:
        async with WebTransportClient(config=config) as client:
            session = await client.connect(url=SERVER_URL)
            async with session:
                pubsub_stream = await session.create_bidirectional_stream()
                async with PubSubManager(
                    stream=pubsub_stream, max_queue_size=DEFAULT_PUBSUB_SUBSCRIPTION_QUEUE_SIZE
                ) as pubsub:
                    sub_a = await pubsub.subscribe(topic="topic-a")
                    sub_b = await pubsub.subscribe(topic="topic-b")

                    async with sub_a, sub_b:
                        receiver_a_task: asyncio.Task[bytes | None] = asyncio.create_task(coro=_receive_message(sub_a))
                        receiver_b_task: asyncio.Task[bytes | None] = asyncio.create_task(coro=_receive_message(sub_b))

                        message_a = b"Message for A"
                        logger.info("Publishing to 'topic-a': %r", message_a)
                        await pubsub.publish(topic="topic-a", data=message_a)

                        try:
                            async with asyncio.timeout(delay=2.0):
                                received_a = await receiver_a_task
                        except asyncio.TimeoutError:
                            receiver_a_task.cancel()
                            logger.error("FAILURE: Subscription A timed out")
                            return False

                        assert received_a == message_a
                        logger.info("SUCCESS: Subscription for 'topic-a' received the correct message.")

                        logger.info("Verifying 'topic-b' subscription did not receive the message...")
                        if receiver_b_task.done():
                            logger.error("FAILURE: 'topic-b' subscription received a message unexpectedly.")
                            return False
                        else:
                            receiver_b_task.cancel()
                            logger.info("SUCCESS: 'topic-b' subscription did not receive the message.")
                            return True
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def main() -> int:
    """Run the main entry point for the Pub/Sub test suite."""
    logger.info("--- Starting Test 10: Publish-Subscribe (Pub/Sub) ---")

    tests: list[tuple[str, Callable[[], Awaitable[bool]]]] = [
        ("Basic Subscribe and Publish", test_pubsub_basic_echo),
        ("Multiple Subscribers Broadcast", test_pubsub_multiple_subscribers),
        ("Unsubscribe Logic", test_pubsub_unsubscribe),
        ("Multiple Topic Isolation", test_pubsub_multiple_topics),
    ]
    passed = 0
    total = len(tests)

    for test_name, test_func in tests:
        logger.info("")
        try:
            if await test_func():
                logger.info("%s: PASSED", test_name)
                passed += 1
            else:
                logger.error("%s: FAILED", test_name)
        except (TimeoutError, ConnectionError) as e:
            logger.error("%s: FAILED - %s", test_name, e)
        except Exception as e:
            logger.error("%s: CRASHED - %s", test_name, e, exc_info=True)
        await asyncio.sleep(delay=1)

    logger.info("")
    logger.info("=" * 60)
    logger.info("Test 10 Results: %d/%d passed", passed, total)

    if passed == total:
        logger.info("TEST 10 PASSED: All Pub/Sub tests successful!")
        return 0
    else:
        logger.error("TEST 10 FAILED: Some Pub/Sub tests failed!")
        return 1


if __name__ == "__main__":
    exit_code = 1
    try:
        exit_code = asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("\nTest interrupted by user.")
        exit_code = 130
    except Exception as e:
        logger.critical("Test suite crashed with an unhandled exception: %s", e, exc_info=True)
    finally:
        sys.exit(exit_code)
