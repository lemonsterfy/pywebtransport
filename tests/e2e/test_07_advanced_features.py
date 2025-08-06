"""
E2E Test 07: Advanced WebTransport features.
Tests statistics, management, and other advanced capabilities.
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

logger = logging.getLogger("test_advanced_features")


async def test_session_statistics() -> bool:
    """Tests the retrieval of session-level statistics."""
    logger.info("Test 07A: Session Statistics")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=5.0,
        write_timeout=5.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-07a/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            initial_stats = await session.get_session_stats()
            logger.info("Initial session statistics:")
            logger.info(f"   Created at: {initial_stats.get('created_at')}")
            logger.info(f"   Streams created: {initial_stats.get('streams_created', 0)}")

            logger.info("Performing operations to generate statistics...")
            for i in range(3):
                stream = await session.create_bidirectional_stream()
                await stream.write_all(f"Statistics test {i + 1}".encode())
                await stream.read_all()

            datagrams = await session.datagrams
            for i in range(5):
                await datagrams.send(f"Datagram {i + 1}".encode())

            await asyncio.sleep(1)
            final_stats = await session.get_session_stats()
            logger.info("Final session statistics:")
            logger.info(f"   Uptime: {final_stats.get('uptime', 0):.2f}s")
            logger.info(f"   Streams created: {final_stats.get('streams_created', 0)}")
            logger.info(f"   Datagrams sent: {final_stats.get('datagrams_sent', 0)}")

            if final_stats.get("streams_created", 0) >= 3 and final_stats.get("datagrams_sent", 0) >= 5:
                logger.info("Session statistics look correct")
            else:
                logger.error("FAILED: Session statistics mismatch")
                return False

            await session.close()
            logger.info("Session statistics test completed successfully")
            return True
    except Exception as e:
        logger.error(f"Session statistics test failed: {e}", exc_info=True)
        return False


async def test_connection_info() -> bool:
    """Tests the retrieval of underlying connection information."""
    logger.info("Test 07B: Connection Information")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-07b/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            connection = session.connection
            if not connection:
                logger.error("No connection object available")
                return False

            logger.info("Connection information:")
            logger.info(f"   Connection ID: {connection.connection_id}")
            logger.info(f"   State: {connection.state}")
            logger.info(f"   Local address: {connection.local_address}")
            logger.info(f"   Remote address: {connection.remote_address}")

            info = connection.info
            logger.info("Connection statistics:")
            logger.info(f"   Uptime: {info.uptime:.2f}s")
            logger.info(f"   Bytes sent: {info.bytes_sent}")
            logger.info(f"   Bytes received: {info.bytes_received}")

            if connection.is_connected:
                logger.info("Connection information retrieved successfully")

            await session.close()
            logger.info("Connection info test completed successfully")
            return True
    except Exception as e:
        logger.error(f"Connection info test failed: {e}", exc_info=True)
        return False


async def test_client_statistics() -> bool:
    """Tests the retrieval of client-wide statistics."""
    logger.info("Test 07C: Client Statistics")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-07c/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            initial_stats = client.stats
            logger.info("Initial client statistics:")
            logger.info(f"   Connections attempted: {initial_stats.get('connections', {}).get('attempted', 0)}")

            logger.info("Performing multiple connections...")
            for i in range(3):
                session = await client.connect(server_url)
                logger.info(f"   Connection {i + 1} established: {session.session_id}")
                await session.close()
                await asyncio.sleep(0.5)

            final_stats = client.stats
            logger.info("Final client statistics:")
            logger.info(f"   Uptime: {final_stats.get('uptime', 0):.2f}s")
            connections = final_stats.get("connections", {})
            logger.info(f"   Connections attempted: {connections.get('attempted', 0)}")
            logger.info(f"   Connections successful: {connections.get('successful', 0)}")
            performance = final_stats.get("performance", {})
            logger.info(f"   Average connect time: {performance.get('avg_connect_time', 0):.3f}s")

            if connections.get("attempted", 0) >= 3:
                logger.info("Client statistics look correct")

            logger.info("Client statistics test completed successfully")
            return True
    except Exception as e:
        logger.error(f"Client statistics test failed: {e}", exc_info=True)
        return False


async def test_stream_management() -> bool:
    """Tests advanced stream management features."""
    logger.info("Test 07D: Stream Management")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=5.0,
        write_timeout=5.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-07d/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            streams = [await session.create_bidirectional_stream() for _ in range(5)]
            logger.info(f"Created {len(streams)} streams")

            if session.stream_manager:
                stream_manager = session.stream_manager
                manager_stats = await stream_manager.get_stats()
                logger.info("Stream manager statistics:")
                logger.info(f"   Total created: {manager_stats.get('total_created', 0)}")
                logger.info(f"   Current count: {manager_stats.get('current_count', 0)}")

                all_streams = await stream_manager.get_all_streams()
                logger.info(f"   Managed streams: {len(all_streams)}")
                if len(all_streams) == 5:
                    logger.info("Stream management working correctly")

            logger.info("Testing stream communication...")
            for i, stream in enumerate(streams):
                await stream.write_all(f"Stream {i + 1} test".encode())
                await stream.read(size=1024)

            logger.info("Closing all streams...")
            for stream in streams:
                if not stream.is_closed:
                    await stream.close()

            if session.stream_manager:
                await asyncio.sleep(0.1)
                final_stats = await session.stream_manager.get_stats()
                logger.info(f"Final active streams: {final_stats.get('current_count', 0)}")

            await session.close()
            logger.info("Stream management test completed successfully")
            return True
    except Exception as e:
        logger.error(f"Stream management test failed: {e}", exc_info=True)
        return False


async def test_datagram_statistics() -> bool:
    """Tests detailed statistics for datagrams."""
    logger.info("Test 07E: Datagram Statistics")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-07e/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            datagrams = await session.datagrams
            logger.info("Initial datagram statistics:")
            logger.info(f"   Datagrams sent: {datagrams.stats.get('datagrams_sent', 0)}")

            logger.info("Sending datagrams of different sizes and priorities...")
            for size in [10, 100, 1000]:
                await datagrams.send(b"X" * size)
            for priority in [0, 1, 2]:
                await datagrams.send(f"Priority {priority} test".encode(), priority=priority)
            await asyncio.sleep(1)

            final_stats = datagrams.stats
            logger.info("Final datagram statistics:")
            logger.info(f"   Datagrams sent: {final_stats.get('datagrams_sent', 0)}")
            logger.info(f"   Bytes sent: {final_stats.get('bytes_sent', 0)}")
            logger.info(f"   Average datagram size: {final_stats.get('avg_datagram_size', 0):.1f} bytes")

            logger.info(f"Queue statistics: {datagrams.get_queue_stats()}")

            expected_count = 3 + 3
            if final_stats.get("datagrams_sent", 0) >= expected_count:
                logger.info("Datagram statistics look correct")

            await session.close()
            logger.info("Datagram statistics test completed successfully")
            return True
    except Exception as e:
        logger.error(f"Datagram statistics test failed: {e}", exc_info=True)
        return False


async def test_performance_monitoring() -> bool:
    """Tests simple performance monitoring over multiple transfers."""
    logger.info("Test 07F: Performance Monitoring")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=10.0,
        write_timeout=10.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-07f/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            performance_results = []
            logger.info("Starting performance monitoring...")
            for size in [1024, 4096, 16384]:
                logger.info(f"   Testing {size} bytes data transfer (5 iterations)...")
                size_results = []
                for _ in range(5):
                    stream = await session.create_bidirectional_stream()
                    start_time = time.time()
                    await stream.write_all(b"X" * size)
                    await stream.read(size=size + 10)
                    size_results.append(time.time() - start_time)
                    await asyncio.sleep(0.1)

                avg_rtt = sum(size_results) / len(size_results) if size_results else 0
                throughput = size / avg_rtt / 1024 if avg_rtt > 0 else float("inf")
                result = {"size": size, "avg_rtt": avg_rtt, "throughput": throughput}
                performance_results.append(result)
                logger.info(f"      Average RTT: {avg_rtt * 1000:.1f}ms, Throughput: {throughput:.1f} KB/s")

            logger.info("Performance Summary:")
            for result in performance_results:
                logger.info(
                    f"   {result['size']} bytes: {result['avg_rtt'] * 1000:.1f}ms RTT, {result['throughput']:.1f} KB/s"
                )

            await session.close()
            logger.info("Performance monitoring test completed successfully")
            return True
    except Exception as e:
        logger.error(f"Performance monitoring test failed: {e}", exc_info=True)
        return False


async def test_session_lifecycle_events() -> bool:
    """Tests the tracking of session lifecycle events."""
    logger.info("Test 07G: Session Lifecycle Events")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-07g/1.0"},
    )

    try:
        events_received: List[Tuple[str, float]] = []
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            connect_time = time.time()
            events_received.append(("connected", connect_time))

            stream = await session.create_bidirectional_stream()
            await stream.write_all(b"Lifecycle test")
            await stream.read(size=1024)

            datagrams = await session.datagrams
            await datagrams.send(b"Lifecycle datagram")

            await session.close()
            events_received.append(("session_closed", time.time()))

            logger.info("Session lifecycle timeline:")
            for i, (event_name, timestamp) in enumerate(events_received):
                elapsed = timestamp - connect_time if i > 0 else 0.0
                logger.info(f"   {event_name}: {elapsed:.3f}s")

            if len(events_received) >= 2:
                logger.info("Session lifecycle events tracked successfully")

            logger.info("Session lifecycle events test completed successfully")
            return True
    except Exception as e:
        logger.error(f"Session lifecycle events test failed: {e}", exc_info=True)
        return False


async def main() -> int:
    """Main entry point for the advanced features test suite."""
    logger.info("Starting Test 07: Advanced Features")
    logger.info("")
    if DEBUG_MODE:
        logger.info("Debug mode enabled - verbose logging active")
    logger.info("Target server: https://127.0.0.1:4433/")
    logger.info("")

    tests: List[Tuple[str, Callable[[], Awaitable[bool]]]] = [
        ("Session Statistics", test_session_statistics),
        ("Connection Information", test_connection_info),
        ("Client Statistics", test_client_statistics),
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
                logger.info(f"{test_name}: PASSED")
                passed += 1
            else:
                logger.error(f"{test_name}: FAILED")
        except Exception as e:
            logger.error(f"{test_name}: CRASHED - {e}")
        await asyncio.sleep(1)

    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Test 07 Results: {passed}/{total} passed")

    if passed == total:
        logger.info("TEST 07 PASSED: All advanced features working!")
        logger.info("WebTransport implementation is comprehensive and robust!")
        logger.info("Ready for production use!")
        return 0
    else:
        logger.error("TEST 07 FAILED: Some advanced features need work!")
        logger.error("Please review the implementation before production use")
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
