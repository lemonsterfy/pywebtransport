"""E2E test for WebTransport datagram functionality."""

import asyncio
import logging
import ssl
import sys
import time
from collections.abc import Awaitable, Callable
from typing import Final

from pywebtransport import ClientConfig, ConnectionError, DatagramError, TimeoutError, WebTransportClient

SERVER_HOST: Final[str] = "127.0.0.1"
SERVER_PORT: Final[int] = 4433
SERVER_URL: Final[str] = f"https://{SERVER_HOST}:{SERVER_PORT}/"
DEBUG_MODE: Final[bool] = "--debug" in sys.argv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
if DEBUG_MODE:
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("aioquic").setLevel(logging.DEBUG)
    logging.getLogger("pywebtransport").setLevel(logging.DEBUG)

logger = logging.getLogger("test_datagrams")


async def test_basic_datagram() -> bool:
    """Test sending a single datagram and receiving its echo."""
    logger.info("--- Test 05A: Basic Datagram Echo ---")
    config = ClientConfig(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=5.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )

    try:
        async with WebTransportClient(config=config) as client:
            session = await client.connect(url=SERVER_URL)
            datagram_transport = await session.create_datagram_transport()
            logger.info("Datagram transport ready (Max size: %s bytes).", datagram_transport.max_datagram_size)

            test_message = b"Hello, Datagram!"
            expected_response = b"ECHO: " + test_message

            logger.info("Sending datagram: %r", test_message)
            await datagram_transport.send(data=test_message)

            logger.info("Waiting for echo...")
            response = await datagram_transport.receive()

            if response == expected_response:
                logger.info("SUCCESS: Received correct datagram echo.")
                return True
            else:
                logger.error("FAILURE: Datagram echo mismatch.")
                return False
    except (TimeoutError, ConnectionError) as e:
        logger.error("FAILURE: Test failed due to connection or timeout issue: %s", e)
        return False
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_multiple_datagrams() -> bool:
    """Test sending multiple datagrams sequentially."""
    logger.info("--- Test 05B: Multiple Datagrams ---")
    num_datagrams = 10
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
            datagram_transport = await session.create_datagram_transport()

            logger.info("Sending %d datagrams sequentially...", num_datagrams)
            for i in range(num_datagrams):
                await datagram_transport.send(data=f"Datagram message {i + 1}".encode())

            stats = datagram_transport.diagnostics.stats.to_dict()
            if stats.get("datagrams_sent", 0) >= num_datagrams:
                logger.info("SUCCESS: %s datagrams sent.", stats.get("datagrams_sent", 0))
                return True
            else:
                logger.error(
                    "FAILURE: Expected %d sent, but stats show %s.", num_datagrams, stats.get("datagrams_sent", 0)
                )
                return False
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_datagram_sizes() -> bool:
    """Test sending datagrams of various sizes, including oversized ones."""
    logger.info("--- Test 05C: Datagram Size Limits ---")
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
            datagram_transport = await session.create_datagram_transport()
            max_size = datagram_transport.max_datagram_size
            logger.info("Max datagram size: %s bytes.", max_size)

            logger.info("Testing oversized datagram...")
            try:
                oversized_data = b"X" * (max_size + 1)
                await datagram_transport.send(data=oversized_data)
                logger.error("FAILURE: Sending oversized datagram should have raised an exception.")
                return False
            except DatagramError:
                logger.info("SUCCESS: Oversized datagram correctly raised DatagramError.")
                return True
            except Exception as e:
                logger.error("FAILURE: Unexpected exception for oversized datagram: %s", e)
                return False
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_datagram_priority() -> bool:
    """Test sending datagrams with different priority levels (conceptual)."""
    logger.info("--- Test 05D: Datagram Priority ---")
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
            datagram_transport = await session.create_datagram_transport()

            logger.info("Sending datagrams with different priorities...")
            await datagram_transport.send(data=b"Priority 0", priority=0)
            await datagram_transport.send(data=b"Priority 1", priority=1)
            await datagram_transport.send(data=b"Priority 2", priority=2)

            logger.info("SUCCESS: Datagrams sent with priority parameter.")
            return True
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_datagram_ttl() -> bool:
    """Test sending datagrams with a Time-To-Live (TTL) (conceptual)."""
    logger.info("--- Test 05E: Datagram TTL ---")
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
            datagram_transport = await session.create_datagram_transport()

            logger.info("Sending datagrams with different TTLs...")
            await datagram_transport.send(data=b"TTL 1.0s", ttl=1.0)
            await datagram_transport.send(data=b"TTL 5.0s", ttl=5.0)

            logger.info("SUCCESS: Datagrams sent with TTL parameter.")
            return True
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_json_datagrams() -> bool:
    """Test sending datagrams with JSON-formatted payloads."""
    logger.info("--- Test 05F: JSON Datagrams ---")
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
            datagram_transport = await session.create_datagram_transport()
            json_payload = {"type": "greeting", "message": "Hello, JSON!"}

            logger.info("Sending JSON payload: %s", json_payload)
            await datagram_transport.send_json(data=json_payload)

            await asyncio.sleep(0.1)

            stats = datagram_transport.diagnostics.stats.to_dict()
            if stats.get("datagrams_sent", 0) >= 1:
                logger.info("SUCCESS: JSON datagram sent successfully.")
                return True
            else:
                logger.error("FAILURE: JSON datagram was not sent according to stats.")
                return False
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_datagram_burst() -> bool:
    """Test a burst of datagrams sent concurrently."""
    logger.info("--- Test 05G: Datagram Burst ---")
    burst_size = 50
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
            datagram_transport = await session.create_datagram_transport()
            logger.info("Starting burst of %d datagrams...", burst_size)
            start_time = time.time()

            tasks = [datagram_transport.send(data=f"Burst {i}".encode()) for i in range(burst_size)]
            await asyncio.gather(*tasks)
            duration = time.time() - start_time
            rate = burst_size / duration if duration > 0 else float("inf")

            logger.info("SUCCESS: Sent %d datagrams in %.3fs (%.1f dgrams/s).", burst_size, duration, rate)
            return True
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_datagram_queue_behavior() -> bool:
    """Test the inspection of datagram send/receive queues."""
    logger.info("--- Test 05H: Datagram Queue Behavior ---")
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
            datagram_transport = await session.create_datagram_transport()

            logger.info("Initial send buffer size: %s", datagram_transport.get_send_buffer_size())
            await datagram_transport.send(data=b"Queue test")
            logger.info("Send buffer size after sending: %s", datagram_transport.get_send_buffer_size())

            await asyncio.sleep(0.1)
            logger.info("Send buffer size after delay: %s", datagram_transport.get_send_buffer_size())

            logger.info("SUCCESS: Datagram queue inspection methods are available.")
            return True
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def main() -> int:
    """Run the main entry point for the datagrams test suite."""
    logger.info("--- Starting Test 05: Datagrams ---")

    tests: list[tuple[str, Callable[[], Awaitable[bool]]]] = [
        ("Basic Datagram Echo", test_basic_datagram),
        ("Multiple Datagrams", test_multiple_datagrams),
        ("Datagram Size Limits", test_datagram_sizes),
        ("Datagram Priority", test_datagram_priority),
        ("Datagram TTL", test_datagram_ttl),
        ("JSON Datagrams", test_json_datagrams),
        ("Datagram Burst", test_datagram_burst),
        ("Datagram Queue Behavior", test_datagram_queue_behavior),
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
        except Exception as e:
            logger.error("%s: CRASHED - %s", test_name, e, exc_info=True)
        await asyncio.sleep(1)

    logger.info("")
    logger.info("=" * 60)
    logger.info("Test 05 Results: %d/%d passed", passed, total)

    if passed == total:
        logger.info("TEST 05 PASSED: All datagram tests successful!")
        return 0
    else:
        logger.error("TEST 05 FAILED: Some datagram tests failed!")
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
