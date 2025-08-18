"""
E2E test for WebTransport datagram functionality.
"""

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
    """Tests sending a single datagram and receiving its echo."""
    logger.info("--- Test 05A: Basic Datagram Echo ---")
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=10.0, read_timeout=5.0)

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(SERVER_URL)
            datagrams = await session.datagrams
            logger.info(f"Datagram stream ready (Max size: {datagrams.max_datagram_size} bytes).")

            test_message = b"Hello, Datagram!"
            expected_response = b"ECHO: " + test_message

            logger.info(f"Sending datagram: {test_message!r}")
            await datagrams.send(test_message)

            logger.info("Waiting for echo...")
            response = await datagrams.receive()

            if response == expected_response:
                logger.info("SUCCESS: Received correct datagram echo.")
                return True
            else:
                logger.error("FAILURE: Datagram echo mismatch.")
                return False
    except (TimeoutError, ConnectionError) as e:
        logger.error(f"FAILURE: Test failed due to connection or timeout issue: {e}")
        return False
    except Exception as e:
        logger.error(f"FAILURE: An unexpected error occurred: {e}", exc_info=True)
        return False


async def test_multiple_datagrams() -> bool:
    """Tests sending multiple datagrams sequentially."""
    logger.info("--- Test 05B: Multiple Datagrams ---")
    num_datagrams = 10
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=10.0)

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(SERVER_URL)
            datagrams = await session.datagrams

            logger.info(f"Sending {num_datagrams} datagrams sequentially...")
            for i in range(num_datagrams):
                await datagrams.send(f"Datagram message {i + 1}".encode())

            stats = datagrams.stats
            if stats.get("datagrams_sent", 0) >= num_datagrams:
                logger.info(f"SUCCESS: {stats.get('datagrams_sent', 0)} datagrams sent.")
                return True
            else:
                logger.error(
                    f"FAILURE: Expected {num_datagrams} sent, but stats show {stats.get('datagrams_sent', 0)}."
                )
                return False
    except Exception as e:
        logger.error(f"FAILURE: An unexpected error occurred: {e}", exc_info=True)
        return False


async def test_datagram_sizes() -> bool:
    """Tests sending datagrams of various sizes, including oversized ones."""
    logger.info("--- Test 05C: Datagram Size Limits ---")
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=10.0)

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(SERVER_URL)
            datagrams = await session.datagrams
            max_size = datagrams.max_datagram_size
            logger.info(f"Max datagram size: {max_size} bytes.")

            logger.info("Testing oversized datagram...")
            try:
                oversized_data = b"X" * (max_size + 1)
                await datagrams.send(oversized_data)
                logger.error("FAILURE: Sending oversized datagram should have raised an exception.")
                return False
            except DatagramError:
                logger.info("SUCCESS: Oversized datagram correctly raised DatagramError.")
                return True
            except Exception as e:
                logger.error(f"FAILURE: Unexpected exception for oversized datagram: {e}")
                return False
    except Exception as e:
        logger.error(f"FAILURE: An unexpected error occurred: {e}", exc_info=True)
        return False


async def test_datagram_priority() -> bool:
    """Tests sending datagrams with different priority levels (conceptual)."""
    logger.info("--- Test 05D: Datagram Priority ---")
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=10.0)

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(SERVER_URL)
            datagrams = await session.datagrams

            logger.info("Sending datagrams with different priorities...")
            await datagrams.send(b"Priority 0", priority=0)
            await datagrams.send(b"Priority 1", priority=1)
            await datagrams.send(b"Priority 2", priority=2)

            logger.info("SUCCESS: Datagrams sent with priority parameter.")
            return True
    except Exception as e:
        logger.error(f"FAILURE: An unexpected error occurred: {e}", exc_info=True)
        return False


async def test_datagram_ttl() -> bool:
    """Tests sending datagrams with a Time-To-Live (TTL) (conceptual)."""
    logger.info("--- Test 05E: Datagram TTL ---")
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=10.0)

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(SERVER_URL)
            datagrams = await session.datagrams

            logger.info("Sending datagrams with different TTLs...")
            await datagrams.send(b"TTL 1.0s", ttl=1.0)
            await datagrams.send(b"TTL 5.0s", ttl=5.0)

            logger.info("SUCCESS: Datagrams sent with TTL parameter.")
            return True
    except Exception as e:
        logger.error(f"FAILURE: An unexpected error occurred: {e}", exc_info=True)
        return False


async def test_json_datagrams() -> bool:
    """Tests sending datagrams with JSON-formatted payloads."""
    logger.info("--- Test 05F: JSON Datagrams ---")
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=10.0)

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(SERVER_URL)
            datagrams = await session.datagrams
            json_payload = {"type": "greeting", "message": "Hello, JSON!"}

            logger.info(f"Sending JSON payload: {json_payload}")
            await datagrams.send_json(json_payload)

            await asyncio.sleep(0.1)

            stats = datagrams.stats
            if stats.get("datagrams_sent", 0) >= 1:
                logger.info("SUCCESS: JSON datagram sent successfully.")
                return True
            else:
                logger.error("FAILURE: JSON datagram was not sent according to stats.")
                return False
    except Exception as e:
        logger.error(f"FAILURE: An unexpected error occurred: {e}", exc_info=True)
        return False


async def test_datagram_burst() -> bool:
    """Tests a burst of datagrams sent concurrently."""
    logger.info("--- Test 05G: Datagram Burst ---")
    burst_size = 50
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=10.0)

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(SERVER_URL)
            datagrams = await session.datagrams
            logger.info(f"Starting burst of {burst_size} datagrams...")
            start_time = time.time()

            tasks = [datagrams.send(f"Burst {i}".encode()) for i in range(burst_size)]
            await asyncio.gather(*tasks)
            duration = time.time() - start_time
            rate = burst_size / duration if duration > 0 else float("inf")

            logger.info(f"SUCCESS: Sent {burst_size} datagrams in {duration:.3f}s ({rate:.1f} dgrams/s).")
            return True
    except Exception as e:
        logger.error(f"FAILURE: An unexpected error occurred: {e}", exc_info=True)
        return False


async def test_datagram_queue_behavior() -> bool:
    """Tests the inspection of datagram send/receive queues."""
    logger.info("--- Test 05H: Datagram Queue Behavior ---")
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=10.0)

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(SERVER_URL)
            datagrams = await session.datagrams

            logger.info(f"Initial send buffer size: {datagrams.get_send_buffer_size()}")
            await datagrams.send(b"Queue test")
            logger.info(f"Send buffer size after sending: {datagrams.get_send_buffer_size()}")

            await asyncio.sleep(0.1)
            logger.info(f"Send buffer size after delay: {datagrams.get_send_buffer_size()}")

            logger.info("SUCCESS: Datagram queue inspection methods are available.")
            return True
    except Exception as e:
        logger.error(f"FAILURE: An unexpected error occurred: {e}", exc_info=True)
        return False


async def main() -> int:
    """Main entry point for the datagrams test suite."""
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
                logger.info(f"{test_name}: PASSED")
                passed += 1
            else:
                logger.error(f"{test_name}: FAILED")
        except Exception as e:
            logger.error(f"{test_name}: CRASHED - {e}", exc_info=True)
        await asyncio.sleep(1)

    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Test 05 Results: {passed}/{total} passed")

    if passed == total:
        logger.info("TEST 05 PASSED: All datagram tests successful!")
        logger.info("Ready to proceed to Test 06")
        return 0
    else:
        logger.error("TEST 05 FAILED: Some datagram tests failed!")
        logger.error("Please fix the issues before proceeding")
        return 1


if __name__ == "__main__":
    exit_code = 1
    try:
        exit_code = asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("\nTest interrupted by user.")
        exit_code = 130
    except Exception as e:
        logger.critical(f"Test suite crashed with an unhandled exception: {e}", exc_info=True)
    finally:
        sys.exit(exit_code)
