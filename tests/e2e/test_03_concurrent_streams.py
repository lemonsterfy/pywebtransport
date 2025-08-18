"""
E2E test for concurrent WebTransport stream handling.
"""

import asyncio
import logging
import ssl
import sys
import time
from collections.abc import Awaitable, Callable
from typing import Final

from pywebtransport import (
    ClientConfig,
    ConnectionError,
    StreamError,
    TimeoutError,
    WebTransportClient,
    WebTransportSession,
)

SERVER_HOST: Final[str] = "127.0.0.1"
SERVER_PORT: Final[int] = 4433
SERVER_URL: Final[str] = f"https://{SERVER_HOST}:{SERVER_PORT}/"
DEBUG_MODE: Final[bool] = "--debug" in sys.argv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
if DEBUG_MODE:
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("aioquic").setLevel(logging.DEBUG)
    logging.getLogger("pywebtransport").setLevel(logging.DEBUG)

logger = logging.getLogger("test_concurrent_streams")


async def test_sequential_streams() -> bool:
    """Tests creating and using multiple streams sequentially in one session."""
    logger.info("--- Test 03A: Sequential Multiple Streams ---")
    num_streams = 3
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=10.0, read_timeout=5.0)

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(SERVER_URL)
            logger.info(f"Connected, session ID: {session.session_id}")

            for i in range(num_streams):
                stream_num = i + 1
                logger.info(f"Creating and testing stream {stream_num}/{num_streams}...")
                stream = await session.create_bidirectional_stream()
                test_msg = f"Sequential stream {stream_num}".encode()
                await stream.write_all(test_msg)
                response = await stream.read_all()

                expected = b"ECHO: " + test_msg
                if response != expected:
                    logger.error(f"FAILURE: Stream {stream_num} echo failed.")
                    return False
                logger.info(f"Stream {stream_num} echo successful.")

            logger.info("SUCCESS: All sequential streams worked correctly.")
            return True

    except (TimeoutError, ConnectionError) as e:
        logger.error(f"FAILURE: Test failed due to connection or timeout issue: {e}")
        return False
    except Exception as e:
        logger.error(f"FAILURE: An unexpected error occurred: {e}", exc_info=True)
        return False


async def test_concurrent_streams() -> bool:
    """Tests handling multiple streams concurrently using asyncio tasks."""
    logger.info("--- Test 03B: Concurrent Streams ---")
    num_streams = 10
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=10.0, read_timeout=10.0)

    async def stream_task(session: WebTransportSession, task_id: int) -> bool:
        """Defines the work for a single concurrent stream test."""
        try:
            stream = await session.create_bidirectional_stream()
            logger.debug(f"Task {task_id}: Stream created (ID={stream.stream_id})")
            test_msg = f"Concurrent stream {task_id}".encode()
            await stream.write_all(test_msg)
            response = await stream.read_all()

            expected = b"ECHO: " + test_msg
            if response == expected:
                logger.debug(f"Task {task_id}: Echo successful.")
                return True
            else:
                logger.error(f"Task {task_id}: Echo failed.")
                return False
        except Exception as e:
            logger.error(f"Task {task_id}: Failed with an exception: {e}")
            return False

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(SERVER_URL)
            logger.info(f"Starting {num_streams} concurrent stream tasks...")
            start_time = time.time()

            tasks = [asyncio.create_task(stream_task(session, i + 1)) for i in range(num_streams)]
            results = await asyncio.gather(*tasks)
            duration = time.time() - start_time
            logger.info(f"All tasks completed in {duration:.2f}s.")

            success_count = sum(1 for result in results if result is True)
            if success_count == num_streams:
                logger.info("SUCCESS: All concurrent streams completed successfully!")
                return True
            else:
                logger.error(f"FAILURE: {num_streams - success_count}/{num_streams} concurrent streams failed.")
                return False

    except (TimeoutError, ConnectionError) as e:
        logger.error(f"FAILURE: Test failed due to connection or timeout issue: {e}")
        return False
    except Exception as e:
        logger.error(f"FAILURE: An unexpected error occurred: {e}", exc_info=True)
        return False


async def test_stream_lifecycle() -> bool:
    """Tests the full lifecycle management of a single stream."""
    logger.info("--- Test 03C: Stream Lifecycle Management ---")
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=10.0, read_timeout=5.0)

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(SERVER_URL)
            stream = await session.create_bidirectional_stream()
            logger.info(f"Stream created: {stream.stream_id}, State: {stream.state.value}")

            await stream.write_all(b"Lifecycle test")
            await stream.read_all()
            logger.info(f"Data exchanged. State after write_all/read_all: {stream.state.value}")

            try:
                await stream.write(b"This should fail")
                logger.error("FAILURE: Write on a half-closed stream should not succeed.")
                return False
            except StreamError:
                logger.info("SUCCESS: Write on a half-closed stream correctly failed.")
                return True
            except Exception as e:
                logger.error(f"FAILURE: Unexpected error on second write: {e}")
                return False

    except Exception as e:
        logger.error(f"FAILURE: An unexpected error occurred: {e}", exc_info=True)
        return False


async def test_stream_stress() -> bool:
    """Performs a stress test by rapidly creating and using streams."""
    logger.info("--- Test 03D: Stream Stress Test ---")
    num_iterations = 20
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=10.0, read_timeout=5.0)

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(SERVER_URL)
            logger.info(f"Starting stress test with {num_iterations} iterations...")

            start_time = time.time()
            for i in range(num_iterations):
                stream = await session.create_bidirectional_stream()
                test_msg = f"Stress test {i + 1}".encode()
                await stream.write_all(test_msg)
                response = await stream.read_all()
                expected = b"ECHO: " + test_msg
                if response != expected:
                    logger.error(f"FAILURE: Iteration {i + 1} echo mismatch.")
                    return False

            duration = time.time() - start_time
            rate = num_iterations / duration if duration > 0 else float("inf")
            logger.info(f"SUCCESS: {num_iterations} stream operations in {duration:.2f}s ({rate:.1f} ops/s).")
            return True

    except Exception as e:
        logger.error(f"FAILURE: An unexpected error occurred: {e}", exc_info=True)
        return False


async def main() -> int:
    """Main entry point for the concurrent streams test."""
    logger.info("--- Starting Test 03: Concurrent Streams ---")

    tests: list[tuple[str, Callable[[], Awaitable[bool]]]] = [
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
