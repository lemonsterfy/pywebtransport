"""
E2E Test 03: Concurrent WebTransport stream handling.
Tests the ability to handle multiple streams simultaneously.
"""

import asyncio
import logging
import ssl
import sys
import time

from pywebtransport.client import WebTransportClient
from pywebtransport.config import ClientConfig
from pywebtransport.session import WebTransportSession

DEBUG_MODE = "--debug" in sys.argv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
if DEBUG_MODE:
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("aioquic").setLevel(logging.DEBUG)
    logging.getLogger("pywebtransport").setLevel(logging.DEBUG)

logger = logging.getLogger("test_concurrent_streams")


async def test_sequential_streams() -> bool:
    """Tests creating and using multiple streams sequentially."""
    logger.info("Test 03A: Sequential Multiple Streams")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    num_streams = 3
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE, connect_timeout=10.0, read_timeout=5.0, write_timeout=5.0, debug=True
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            streams = []
            for i in range(num_streams):
                logger.info(f"Creating stream {i + 1}/{num_streams}...")
                stream = await session.create_bidirectional_stream()
                streams.append(stream)
                logger.info(f"Stream {i + 1} created: ID={stream.stream_id}")

            logger.info(f"All {num_streams} streams created successfully")

            for i, stream in enumerate(streams):
                test_msg = f"Stream {i + 1} test message".encode()
                logger.info(f"Testing stream {i + 1}: {test_msg!r}")
                await stream.write_all(test_msg)
                response = await stream.read_all()

                expected = b"ECHO: " + test_msg
                if response != expected:
                    logger.error(f"Stream {i + 1} echo failed")
                    logger.error(f"   Expected: {expected!r}")
                    logger.error(f"   Received: {response!r}")
                    return False
                logger.info(f"Stream {i + 1} echo successful")

            await session.close()
            logger.info("Session closed")
            return True

    except Exception as e:
        logger.error(f"Sequential streams test failed: {e}", exc_info=True)
        return False


async def test_concurrent_streams() -> bool:
    """Tests handling multiple streams concurrently using asyncio tasks."""
    logger.info("Test 03B: Concurrent Streams")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    num_streams = 5
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=10.0,
        write_timeout=10.0,
        debug=True,
    )

    async def stream_task(session: WebTransportSession, stream_id: int) -> bool:
        """Defines the task for handling a single stream test."""
        try:
            stream = await session.create_bidirectional_stream()
            logger.info(f"Task {stream_id}: Stream created (ID={stream.stream_id})")

            test_msg = f"Concurrent stream {stream_id} message".encode()
            await stream.write_all(test_msg)
            response = await stream.read_all()

            expected = b"ECHO: " + test_msg
            if response == expected:
                logger.info(f"Task {stream_id}: Echo successful")
                return True
            else:
                logger.error(f"Task {stream_id}: Echo failed")
                return False

        except Exception as e:
            logger.error(f"Task {stream_id}: Failed - {e}")
            return False

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            logger.info(f"Starting {num_streams} concurrent stream tasks...")
            start_time = time.time()

            tasks = [asyncio.create_task(stream_task(session, i + 1)) for i in range(num_streams)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            duration = time.time() - start_time
            logger.info(f"All tasks completed in {duration:.2f}s")

            success_count = sum(1 for result in results if result is True)
            error_count = sum(1 for result in results if isinstance(result, Exception))
            logger.info(
                f"Results: {success_count} successful, {len(results) - success_count} failed, {error_count} errors"
            )

            if success_count != num_streams:
                logger.error("FAILED: Some concurrent streams failed")
                return False

            logger.info("SUCCESS: All concurrent streams worked!")
            await session.close()
            return True

    except Exception as e:
        logger.error(f"Concurrent streams test failed: {e}", exc_info=True)
        return False


async def test_stream_lifecycle() -> bool:
    """Tests the full lifecycle management of a single stream."""
    logger.info("Test 03C: Stream Lifecycle Management")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE, connect_timeout=10.0, read_timeout=5.0, write_timeout=5.0, debug=True
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            stream = await session.create_bidirectional_stream()
            logger.info(f"Stream created: {stream.stream_id}")
            logger.info(f"Initial state: {stream.state}")
            logger.info(f"Is readable: {stream.is_readable}")
            logger.info(f"Is writable: {stream.is_writable}")
            logger.info(f"Is closed: {stream.is_closed}")

            test_msg = b"Lifecycle test message"
            await stream.write_all(test_msg)
            response = await stream.read_all()

            expected = b"ECHO: " + test_msg
            if response != expected:
                logger.error("Stream communication failed")
                logger.error(f"   Expected: {expected!r}")
                logger.error(f"   Received: {response!r}")
                return False
            logger.info("Stream communication successful")

            logger.info(f"After write_all - Is closed: {stream.is_closed}")
            logger.info(f"After write_all - State: {stream.state}")

            try:
                await stream.write(b"This should fail")
                logger.error("UNEXPECTED: Write on closed stream succeeded")
                return False
            except Exception:
                logger.info("EXPECTED: Write on closed stream correctly failed")

            await session.close()
            return True

    except Exception as e:
        logger.error(f"Stream lifecycle test failed: {e}", exc_info=True)
        return False


async def test_stream_stress() -> bool:
    """Performs a stress test by rapidly creating and closing streams."""
    logger.info("Test 03D: Stream Stress Test")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    num_iterations = 10
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE, connect_timeout=10.0, read_timeout=3.0, write_timeout=3.0, debug=True
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            start_time = time.time()
            for i in range(num_iterations):
                stream = await session.create_bidirectional_stream()
                test_msg = f"Stress test {i + 1}".encode()
                await stream.write_all(test_msg)
                response = await stream.read_all()

                expected = b"ECHO: " + test_msg
                if response != expected:
                    logger.error(f"Iteration {i + 1}: Echo mismatch")
                    logger.error(f"   Expected: {expected!r}")
                    logger.error(f"   Received: {response!r}")
                    return False

                if (i + 1) % 5 == 0:
                    logger.info(f"Completed {i + 1}/{num_iterations} iterations")

            duration = time.time() - start_time
            rate = num_iterations / duration
            logger.info(f"SUCCESS: {num_iterations} stream operations in {duration:.2f}s ({rate:.1f} ops/s)")

            await session.close()
            return True

    except Exception as e:
        logger.error(f"Stream stress test failed: {e}", exc_info=True)
        return False


async def main() -> int:
    """Main entry point for the concurrent streams test."""
    logger.info("Starting Test 03: Concurrent Streams")
    logger.info("")

    tests = [
        ("Sequential Multiple Streams", test_sequential_streams),
        ("Concurrent Streams", test_concurrent_streams),
        ("Stream Lifecycle Management", test_stream_lifecycle),
        ("Stream Stress Test", test_stream_stress),
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
    logger.info(f"Test 03 Results: {passed}/{total} passed")

    if passed == total:
        logger.info("TEST 03 PASSED: All concurrent stream tests successful!")
        logger.info("Ready to proceed to Test 04")
        return 0
    else:
        logger.error("TEST 03 FAILED: Some concurrent stream tests failed!")
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
