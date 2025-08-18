"""
E2E test for WebTransport error handling and edge cases.
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
    ClientError,
    ConnectionError,
    DatagramError,
    SessionError,
    StreamError,
    TimeoutError,
    WebTransportClient,
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

logger = logging.getLogger("test_error_handling")


async def test_connection_timeout() -> bool:
    """Tests the handling of a connection timeout to an unreachable port."""
    logger.info("--- Test 06A: Connection Timeout ---")
    unreachable_url = f"https://{SERVER_HOST}:9999/"
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=2.0)

    logger.info(f"Attempting connection to unreachable server: {unreachable_url}")
    start_time = time.time()
    try:
        async with WebTransportClient.create(config=config) as client:
            await client.connect(unreachable_url)
        logger.error("FAILURE: Connection should have failed but it succeeded.")
        return False
    except (TimeoutError, ConnectionError, ClientError):
        duration = time.time() - start_time
        logger.info(f"SUCCESS: Connection correctly failed after {duration:.1f}s.")
        return True
    except Exception as e:
        logger.error(f"FAILURE: An unexpected exception was caught: {type(e).__name__}", exc_info=True)
        return False


async def test_invalid_server_address() -> bool:
    """Tests handling of various invalid server addresses."""
    logger.info("--- Test 06B: Invalid Server Address ---")
    invalid_urls = [
        "https://invalid-hostname-for-testing.local/",
        "http://127.0.0.1:4433/",
    ]
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=3.0)

    try:
        async with WebTransportClient.create(config=config) as client:
            for i, invalid_url in enumerate(invalid_urls):
                logger.info(f"Testing invalid URL {i + 1}: {invalid_url}")
                try:
                    await client.connect(invalid_url)
                    logger.error(f"FAILURE: Connection to {invalid_url} should have failed.")
                    return False
                except Exception:
                    logger.info(f"   - SUCCESS: Connection to {invalid_url} correctly failed.")
            return True
    except Exception as e:
        logger.error(f"FAILURE: An unexpected error occurred in the test setup: {e}", exc_info=True)
        return False


async def test_stream_errors() -> bool:
    """Tests error handling for various stream operations."""
    logger.info("--- Test 06C: Stream Error Handling ---")
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=10.0)

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(SERVER_URL)
            stream = await session.create_bidirectional_stream()
            await stream.close()
            logger.info("Stream closed for testing subsequent operations.")

            logger.info("Testing write operation on a closed stream...")
            try:
                await stream.write(b"This should fail")
                logger.error("FAILURE: Write on a closed stream should have failed.")
                return False
            except StreamError:
                logger.info("   - SUCCESS: Write on a closed stream correctly failed.")
            except Exception as e:
                logger.error(f"   - FAILURE: Unexpected error on write: {e}")
                return False

            return True
    except Exception as e:
        logger.error(f"FAILURE: An unexpected error occurred: {e}", exc_info=True)
        return False


async def test_read_timeout() -> bool:
    """Tests the handling of a stream read timeout."""
    logger.info("--- Test 06D: Stream Read Timeout ---")
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, read_timeout=1.0)

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(SERVER_URL)
            stream = await session.create_bidirectional_stream()
            logger.info("Attempting to read from a stream with no data (should time out)...")
            start_time = time.time()
            try:
                await stream.read(size=1024)
                logger.error("FAILURE: Read operation should have timed out.")
                return False
            except TimeoutError:
                duration = time.time() - start_time
                logger.info(f"SUCCESS: Read correctly timed out after {duration:.1f}s.")
                return True
            except Exception as e:
                logger.error(f"FAILURE: Unexpected exception during read: {e}")
                return False
    except Exception as e:
        logger.error(f"FAILURE: An unexpected error occurred: {e}", exc_info=True)
        return False


async def test_session_closure_handling() -> bool:
    """Tests that operations on a closed session correctly raise errors."""
    logger.info("--- Test 06E: Operations on Closed Session ---")
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=10.0)

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(SERVER_URL)
            logger.info(f"Connected, session ID: {session.session_id}")
            await session.close()
            logger.info("Session closed.")

            logger.info("Testing stream creation on closed session...")
            try:
                await session.create_bidirectional_stream()
                logger.error("FAILURE: Stream creation on closed session should have failed.")
                return False
            except (StreamError, SessionError, ClientError):
                logger.info("   - SUCCESS: Stream creation correctly failed.")
            except Exception as e:
                logger.error(f"   - FAILURE: Unexpected error: {e}")
                return False

            logger.info("Testing datagram send on closed session...")
            try:
                datagrams = await session.datagrams
                await datagrams.send(b"This should fail")
                logger.error("FAILURE: Datagram send on closed session should have failed.")
                return False
            except (DatagramError, SessionError, ClientError):
                logger.info("   - SUCCESS: Datagram send correctly failed.")
            except Exception as e:
                logger.error(f"   - FAILURE: Unexpected error: {e}")
                return False

            return True
    except Exception as e:
        logger.error(f"FAILURE: An unexpected error occurred: {e}", exc_info=True)
        return False


async def test_datagram_errors() -> bool:
    """Tests error handling for datagram operations, like oversized payloads."""
    logger.info("--- Test 06F: Datagram Error Handling ---")
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
                logger.error("FAILURE: Oversized datagram send should have failed.")
                return False
            except DatagramError:
                logger.info("   - SUCCESS: Oversized datagram correctly failed with DatagramError.")
            except Exception as e:
                logger.error(f"   - FAILURE: Unexpected error for oversized datagram: {e}")
                return False

            return True
    except Exception as e:
        logger.error(f"FAILURE: An unexpected error occurred: {e}", exc_info=True)
        return False


async def test_resource_exhaustion() -> bool:
    """Tests handling of resource exhaustion, specifically the stream limit."""
    logger.info("--- Test 06G: Resource Exhaustion (Stream Limit) ---")
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=10.0)

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(SERVER_URL)
            logger.info("Attempting to create streams until limit is reached...")
            streams = []
            max_attempts = 200
            limit_hit = False
            for i in range(max_attempts):
                try:
                    stream = await session.create_bidirectional_stream()
                    streams.append(stream)
                except StreamError:
                    logger.info(f"SUCCESS: Stream creation limit correctly hit after {i} streams.")
                    limit_hit = True
                    break
            else:
                logger.warning(f"WARNING: Created all {max_attempts} streams without hitting a limit.")

            for stream in streams:
                await stream.close()

            return limit_hit
    except Exception as e:
        logger.error(f"FAILURE: An unexpected error occurred: {e}", exc_info=True)
        return False


async def test_malformed_operations() -> bool:
    """Tests handling of malformed API operations."""
    logger.info("--- Test 06H: Malformed Operations ---")
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=10.0)

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(SERVER_URL)
            stream = await session.create_bidirectional_stream()

            logger.info("Testing invalid write data (None)...")
            try:
                await stream.write(None)  # type: ignore  # Expected failure with None input
                logger.error("FAILURE: Writing None should have failed.")
                return False
            except TypeError:
                logger.info("   - SUCCESS: Writing None correctly failed with TypeError.")
            except Exception as e:
                logger.error(f"   - FAILURE: Unexpected error for None write: {e}")
                return False

            return True
    except Exception as e:
        logger.error(f"FAILURE: An unexpected error occurred: {e}", exc_info=True)
        return False


async def main() -> int:
    """Main entry point for the error handling test suite."""
    logger.info("--- Starting Test 06: Error Handling ---")

    tests: list[tuple[str, Callable[[], Awaitable[bool]]]] = [
        ("Connection Timeout", test_connection_timeout),
        ("Invalid Server Address", test_invalid_server_address),
        ("Stream Error Handling", test_stream_errors),
        ("Read Timeout", test_read_timeout),
        ("Operations on Closed Session", test_session_closure_handling),
        ("Datagram Error Handling", test_datagram_errors),
        ("Resource Exhaustion", test_resource_exhaustion),
        ("Malformed Operations", test_malformed_operations),
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
    logger.info(f"Test 06 Results: {passed}/{total} passed")

    if passed == total:
        logger.info("TEST 06 PASSED: All error handling tests successful!")
        logger.info("Ready to proceed to Test 07")
        return 0
    else:
        logger.error("TEST 06 FAILED: Some error handling tests failed!")
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
