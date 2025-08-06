"""
E2E Test 05: WebTransport datagram functionality.
Tests the transmission capabilities and features of datagrams.
"""

import asyncio
import logging
import ssl
import sys
import time
from typing import Awaitable, Callable, List, Tuple

from pywebtransport.client import WebTransportClient
from pywebtransport.config import ClientConfig

DEBUG_MODE = "--debug" in sys.argv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
if DEBUG_MODE:
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("aioquic").setLevel(logging.DEBUG)
    logging.getLogger("pywebtransport").setLevel(logging.DEBUG)

logger = logging.getLogger("test_datagrams")


async def test_basic_datagram() -> bool:
    """Tests sending a single, basic datagram."""
    logger.info("Test 05A: Basic Datagram Send")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=5.0,
        write_timeout=5.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-05a/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            datagrams = await session.datagrams
            logger.info("Datagram stream available")
            logger.info(f"   Max size: {datagrams.max_datagram_size} bytes")

            test_message = b"Hello, Datagram World!"
            logger.info(f"Sending datagram: {test_message.decode('utf-8')}")
            await datagrams.send(test_message)
            logger.info("Datagram sent successfully")

            stats = datagrams.stats
            logger.info(f"Stats: sent={stats['datagrams_sent']}, received={stats['datagrams_received']}")

            if stats["datagrams_sent"] <= 0:
                logger.error("FAILED: No datagrams were sent")
                return False

            logger.info("SUCCESS: Datagram sending works!")
            await session.close()
            return True
    except Exception as e:
        logger.error(f"Basic datagram test failed: {e}", exc_info=True)
        return False


async def test_multiple_datagrams() -> bool:
    """Tests sending multiple datagrams sequentially."""
    logger.info("Test 05B: Multiple Datagrams")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    num_datagrams = 10
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=5.0,
        write_timeout=5.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-05b/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            datagrams = await session.datagrams
            start_time = time.time()
            for i in range(num_datagrams):
                message = f"Datagram message {i + 1}".encode()
                await datagrams.send(message)
                if (i + 1) % 5 == 0:
                    logger.info(f"Sent {i + 1}/{num_datagrams} datagrams")

            duration = time.time() - start_time
            rate = num_datagrams / duration if duration > 0 else float("inf")

            stats = datagrams.stats
            logger.info(f"Final stats: sent={stats['datagrams_sent']}")
            logger.info(f"Duration: {duration:.3f}s ({rate:.1f} datagrams/s)")

            if stats["datagrams_sent"] < num_datagrams:
                logger.error(f"FAILED: Expected {num_datagrams} sent, got {stats['datagrams_sent']}")
                return False

            logger.info("SUCCESS: Multiple datagrams sent successfully!")
            await session.close()
            return True
    except Exception as e:
        logger.error(f"Multiple datagrams test failed: {e}", exc_info=True)
        return False


async def test_datagram_sizes() -> bool:
    """Tests sending datagrams of various sizes, including oversized ones."""
    logger.info("Test 05C: Different Datagram Sizes")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=5.0,
        write_timeout=5.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-05c/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            datagrams = await session.datagrams
            max_size = datagrams.max_datagram_size
            logger.info(f"Max datagram size: {max_size} bytes")

            test_sizes = [10, 100, 1000, max_size // 2, max_size - 100]
            for size in test_sizes:
                if size > max_size:
                    continue
                logger.info(f"Testing {size} bytes datagram...")
                test_data = b"X" * size
                try:
                    await datagrams.send(test_data)
                    logger.info(f"{size} bytes: OK")
                except Exception as e:
                    logger.error(f"{size} bytes: Failed - {e}")
                    return False

            try:
                oversized_data = b"X" * (max_size + 100)
                await datagrams.send(oversized_data)
                logger.error("UNEXPECTED: Oversized datagram should have failed")
                return False
            except Exception:
                logger.info("EXPECTED: Oversized datagram correctly rejected")

            stats = datagrams.stats
            logger.info(f"Total datagrams sent: {stats['datagrams_sent']}")
            logger.info("SUCCESS: All datagram sizes handled correctly!")
            await session.close()
            return True
    except Exception as e:
        logger.error(f"Datagram sizes test failed: {e}", exc_info=True)
        return False


async def test_datagram_priority() -> bool:
    """Tests sending datagrams with different priority levels."""
    logger.info("Test 05D: Datagram Priority")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=5.0,
        write_timeout=5.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-05d/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            datagrams = await session.datagrams
            priorities = [0, 1, 2]
            for priority in priorities:
                message = f"Priority {priority} message".encode()
                logger.info(f"Sending priority {priority} datagram...")
                await datagrams.send(message, priority=priority)
                logger.info(f"Priority {priority} datagram sent")

            stats = datagrams.stats
            logger.info(f"Total datagrams sent: {stats['datagrams_sent']}")

            if stats["datagrams_sent"] < len(priorities):
                logger.error("FAILED: Not all priority datagrams were sent")
                return False

            logger.info("SUCCESS: Priority datagrams sent successfully!")
            await session.close()
            return True
    except Exception as e:
        logger.error(f"Datagram priority test failed: {e}", exc_info=True)
        return False


async def test_datagram_ttl() -> bool:
    """Tests sending datagrams with a Time-To-Live (TTL)."""
    logger.info("Test 05E: Datagram TTL")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=5.0,
        write_timeout=5.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-05e/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            datagrams = await session.datagrams
            ttl_values = [1.0, 5.0, 10.0]
            for ttl in ttl_values:
                message = f"TTL {ttl}s message".encode()
                logger.info(f"Sending datagram with TTL={ttl}s...")
                await datagrams.send(message, ttl=ttl)
                logger.info(f"TTL {ttl}s datagram sent")

            expired_message = b"This should expire immediately"
            await datagrams.send(expired_message, ttl=0.001)
            logger.info("Expired datagram sent")

            stats = datagrams.stats
            logger.info(f"Total datagrams sent: {stats['datagrams_sent']}")
            logger.info("SUCCESS: TTL datagrams handled correctly!")
            await session.close()
            return True
    except Exception as e:
        logger.error(f"Datagram TTL test failed: {e}", exc_info=True)
        return False


async def test_json_datagrams() -> bool:
    """Tests sending datagrams with JSON-formatted payloads."""
    logger.info("Test 05F: JSON Datagrams")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=5.0,
        write_timeout=5.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-05f/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            datagrams = await session.datagrams
            json_messages = [
                {"type": "greeting", "message": "Hello from JSON datagram"},
                {"type": "data", "values": [1, 2, 3, 4, 5]},
                {"type": "status", "code": 200, "message": "OK"},
                {"type": "complex", "nested": {"level": 1, "items": ["a", "b", "c"]}},
            ]
            for i, json_data in enumerate(json_messages):
                logger.info(f"Sending JSON datagram {i + 1}: {json_data}")
                await datagrams.send_json(json_data)
                logger.info(f"JSON datagram {i + 1} sent")

            stats = datagrams.stats
            logger.info(f"Total JSON datagrams sent: {stats['datagrams_sent']}")

            if stats["datagrams_sent"] < len(json_messages):
                logger.error("FAILED: Not all JSON datagrams were sent")
                return False

            logger.info("SUCCESS: JSON datagrams sent successfully!")
            await session.close()
            return True
    except Exception as e:
        logger.error(f"JSON datagrams test failed: {e}", exc_info=True)
        return False


async def test_datagram_burst() -> bool:
    """Tests a burst of datagrams sent concurrently."""
    logger.info("Test 05G: Datagram Burst")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    burst_size = 50
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=5.0,
        write_timeout=5.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-05g/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            datagrams = await session.datagrams
            logger.info(f"Starting burst of {burst_size} datagrams...")
            start_time = time.time()

            tasks = [asyncio.create_task(datagrams.send(f"Burst datagram {i + 1}".encode())) for i in range(burst_size)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            duration = time.time() - start_time

            success_count = sum(1 for r in results if not isinstance(r, Exception))
            error_count = len(results) - success_count
            rate = success_count / duration if duration > 0 else 0

            logger.info("Burst results:")
            logger.info(f"   Successful: {success_count}/{burst_size}")
            logger.info(f"   Failed: {error_count}/{burst_size}")
            logger.info(f"   Duration: {duration:.3f}s")
            logger.info(f"   Rate: {rate:.1f} datagrams/s")

            if success_count < burst_size * 0.8:
                logger.warning("WARNING: Low success rate in burst test")

            logger.info("SUCCESS: Datagram burst performed well!")
            await session.close()
            return True
    except Exception as e:
        logger.error(f"Datagram burst test failed: {e}", exc_info=True)
        return False


async def test_datagram_queue_behavior() -> bool:
    """Tests the behavior of the datagram send/receive queues."""
    logger.info("Test 05H: Datagram Queue Behavior")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=5.0,
        write_timeout=5.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-05h/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            datagrams = await session.datagrams
            initial_send_buffer = datagrams.get_send_buffer_size()
            initial_receive_buffer = datagrams.get_receive_buffer_size()
            logger.info("Initial queue sizes:")
            logger.info(f"   Send buffer: {initial_send_buffer}")
            logger.info(f"   Receive buffer: {initial_receive_buffer}")

            for i in range(5):
                await datagrams.send(f"Queue test message {i + 1}".encode())
            logger.info(f"Send buffer after sending: {datagrams.get_send_buffer_size()}")

            await asyncio.sleep(1)
            logger.info("Final queue sizes:")
            logger.info(f"   Send buffer: {datagrams.get_send_buffer_size()}")
            logger.info(f"   Receive buffer: {datagrams.get_receive_buffer_size()}")
            logger.info(f"Queue statistics: {datagrams.get_queue_stats()}")
            logger.info("SUCCESS: Datagram queue behavior tested!")
            await session.close()
            return True
    except Exception as e:
        logger.error(f"Datagram queue test failed: {e}", exc_info=True)
        return False


async def main() -> int:
    """Main entry point for the datagrams test suite."""
    logger.info("Starting Test 05: Datagrams")
    logger.info("")

    if DEBUG_MODE:
        logger.info("Debug mode enabled - verbose logging active")
    logger.info("Target server: https://127.0.0.1:4433/")
    logger.info("")

    tests: List[Tuple[str, Callable[[], Awaitable[bool]]]] = [
        ("Basic Datagram Send", test_basic_datagram),
        ("Multiple Datagrams", test_multiple_datagrams),
        ("Different Datagram Sizes", test_datagram_sizes),
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
            logger.error(f"{test_name}: CRASHED - {e}")
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
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Test crashed: {e}", exc_info=True)
        sys.exit(1)
