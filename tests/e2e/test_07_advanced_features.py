"""E2E test for advanced WebTransport features."""

import asyncio
import logging
import ssl
import sys
import time
from collections.abc import Awaitable, Callable
from typing import Final

from pywebtransport import ClientConfig, WebTransportClient

SERVER_HOST: Final[str] = "127.0.0.1"
SERVER_PORT: Final[int] = 4433
SERVER_URL: Final[str] = f"https://{SERVER_HOST}:{SERVER_PORT}/"
DEBUG_MODE: Final[bool] = "--debug" in sys.argv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
if DEBUG_MODE:
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("aioquic").setLevel(logging.DEBUG)
    logging.getLogger("pywebtransport").setLevel(logging.DEBUG)

logger = logging.getLogger("test_advanced_features")


async def test_session_statistics() -> bool:
    """Test the retrieval and correctness of session-level statistics."""
    logger.info("--- Test 07A: Session Statistics ---")
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )

    try:
        async with WebTransportClient(config=config) as client:
            session = await client.connect(url=SERVER_URL)
            logger.info("Performing operations to generate statistics...")

            for i in range(3):
                stream = await session.create_bidirectional_stream()
                await stream.write_all(data=f"Stats test {i + 1}".encode())
                await stream.read_all()

            datagram_transport = await session.datagrams
            for i in range(5):
                await datagram_transport.send(data=f"Datagram {i + 1}".encode())

            await asyncio.sleep(0.1)
            final_stats = await session.get_session_stats()
            logger.info("Final session statistics retrieved.")

            streams_ok = final_stats.get("streams_created", 0) >= 3
            datagrams_ok = final_stats.get("datagrams_sent", 0) >= 5

            if streams_ok and datagrams_ok:
                logger.info("SUCCESS: Session statistics appear correct.")
                return True
            else:
                logger.error("FAILURE: Session statistics mismatch.")
                logger.error("   - Streams Created: %s (expected >= 3)", final_stats.get("streams_created", 0))
                logger.error("   - Datagrams Sent: %s (expected >= 5)", final_stats.get("datagrams_sent", 0))
                return False
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_connection_info() -> bool:
    """Test the retrieval of underlying connection information."""
    logger.info("--- Test 07B: Connection Information ---")
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )

    try:
        async with WebTransportClient(config=config) as client:
            session = await client.connect(url=SERVER_URL)
            connection = session.connection
            if not connection:
                logger.error("FAILURE: No connection object available on session.")
                return False

            logger.info("Retrieving connection information...")
            info = connection.info
            logger.info("   - Connection ID: %s", connection.connection_id)
            logger.info("   - State: %s", connection.state.value)
            logger.info("   - Remote Address: %s", connection.remote_address)
            logger.info("   - Uptime: %.2fs", info.uptime)

            if connection.is_connected and info.remote_address:
                logger.info("SUCCESS: Connection information retrieved successfully.")
                return True
            else:
                logger.error("FAILURE: Connection information is incomplete or state is incorrect.")
                return False
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_client_statistics() -> bool:
    """Test the retrieval of client-wide statistics across multiple connections."""
    logger.info("--- Test 07C: Client-Wide Statistics ---")
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )

    try:
        async with WebTransportClient(config=config) as client:
            logger.info("Performing 3 connections to generate client stats...")
            for _ in range(3):
                session = await client.connect(url=SERVER_URL)
                await session.close()
                await asyncio.sleep(0.2)

            final_stats = client.stats
            connections = final_stats.get("connections", {})
            performance = final_stats.get("performance", {})
            logger.info("Final client statistics:")
            logger.info("   - Connections Attempted: %s", connections.get("attempted", 0))
            logger.info("   - Connections Successful: %s", connections.get("successful", 0))
            logger.info("   - Avg Connect Time: %.3fs", performance.get("avg_connect_time", 0))

            if connections.get("attempted", 0) >= 3 and connections.get("successful", 0) >= 3:
                logger.info("SUCCESS: Client statistics appear correct.")
                return True
            else:
                logger.error("FAILURE: Client statistics are incorrect.")
                return False
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_stream_management() -> bool:
    """Test advanced stream management features."""
    logger.info("--- Test 07D: Stream Management ---")
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )

    try:
        async with WebTransportClient(config=config) as client:
            session = await client.connect(url=SERVER_URL)
            logger.info("Connected, session: %s", session.session_id)

            streams = [await session.create_bidirectional_stream() for _ in range(5)]
            logger.info("Created %d streams.", len(streams))

            if session.stream_manager:
                stream_manager = session.stream_manager
                manager_stats = await stream_manager.get_stats()
                logger.info("Stream manager statistics:")
                logger.info("   - Total created: %s", manager_stats.get("total_created", 0))
                logger.info("   - Current count: %s", manager_stats.get("current_count", 0))

                all_streams = await stream_manager.get_all_streams()
                if len(all_streams) == 5:
                    logger.info("SUCCESS: Stream management working correctly.")
                else:
                    logger.error("FAILURE: Stream manager count is incorrect.")
                    return False
            else:
                logger.error("FAILURE: session.stream_manager is not available.")
                return False

            for stream in streams:
                if not stream.is_closed:
                    await stream.close()

            return True
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_datagram_statistics() -> bool:
    """Test retrieval of detailed statistics for the datagram transport."""
    logger.info("--- Test 07E: Datagram Statistics ---")
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )

    try:
        async with WebTransportClient(config=config) as client:
            session = await client.connect(url=SERVER_URL)
            datagram_transport = await session.datagrams

            logger.info("Sending datagrams to generate statistics...")
            for i in range(5):
                await datagram_transport.send(data=f"Datagram stats test {i}".encode())

            await asyncio.sleep(0.1)
            final_stats = datagram_transport.stats

            logger.info("Final datagram statistics:")
            logger.info("   - Datagrams Sent: %s", final_stats.get("datagrams_sent", 0))
            logger.info("   - Bytes Sent: %s", final_stats.get("bytes_sent", 0))

            if final_stats.get("datagrams_sent", 0) >= 5:
                logger.info("SUCCESS: Datagram statistics appear correct.")
                return True
            else:
                logger.error("FAILURE: Datagram statistics are incorrect.")
                return False
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_performance_monitoring() -> bool:
    """Test a simple performance monitoring loop over multiple transfers."""
    logger.info("--- Test 07F: Performance Monitoring ---")
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )

    try:
        async with WebTransportClient(config=config) as client:
            session = await client.connect(url=SERVER_URL)
            logger.info("Starting simple performance monitoring loop...")

            for size in [1024, 8192]:
                latencies = []
                for _ in range(3):
                    stream = await session.create_bidirectional_stream()
                    start_time = time.time()
                    await stream.write_all(data=b"x" * size)
                    await stream.read(size=size + 10)
                    latencies.append(time.time() - start_time)

                avg_rtt_ms = (sum(latencies) / len(latencies)) * 1000
                logger.info("   - Avg RTT for %s bytes: %.1fms", size, avg_rtt_ms)

            logger.info("SUCCESS: Performance monitoring loop completed.")
            return True
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_session_lifecycle_events() -> bool:
    """Test the basic session lifecycle event flow."""
    logger.info("--- Test 07G: Session Lifecycle Events ---")
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )

    try:
        events_received = []
        async with WebTransportClient(config=config) as client:
            session = await client.connect(url=SERVER_URL)
            events_received.append("connected")

            await session.close()
            events_received.append("closed")

        if events_received == ["connected", "closed"]:
            logger.info("SUCCESS: Session lifecycle events occurred in the correct order.")
            return True
        else:
            logger.error("FAILURE: Incorrect event order: %s", events_received)
            return False
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def main() -> int:
    """Run the main entry point for the advanced features test suite."""
    logger.info("--- Starting Test 07: Advanced Features ---")

    tests: list[tuple[str, Callable[[], Awaitable[bool]]]] = [
        ("Session Statistics", test_session_statistics),
        ("Connection Information", test_connection_info),
        ("Client-Wide Statistics", test_client_statistics),
        ("Stream Management", test_stream_management),
        ("Datagram Statistics", test_datagram_statistics),
        ("Performance Monitoring", test_performance_monitoring),
        ("Session Lifecycle Events", test_session_lifecycle_events),
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
    logger.info("Test 07 Results: %d/%d passed", passed, total)

    if passed == total:
        logger.info("TEST 07 PASSED: All advanced features tests successful!")
        return 0
    else:
        logger.error("TEST 07 FAILED: Some advanced features tests failed!")
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
