"""E2E test for WebTransport error handling and edge cases."""

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
    """Test the handling of a connection timeout to an unreachable port."""
    logger.info("--- Test 06A: Connection Timeout ---")
    unreachable_url = f"https://{SERVER_HOST}:9999/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=2.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )

    logger.info("Attempting connection to unreachable server: %s", unreachable_url)
    start_time = time.time()
    try:
        async with WebTransportClient(config=config) as client:
            await client.connect(url=unreachable_url)
        logger.error("FAILURE: Connection should have failed but it succeeded.")
        return False
    except (TimeoutError, ConnectionError, ClientError):
        duration = time.time() - start_time
        logger.info("SUCCESS: Connection correctly failed after %.1fs.", duration)
        return True
    except Exception as e:
        logger.error("FAILURE: An unexpected exception was caught: %s", type(e).__name__, exc_info=True)
        return False


async def test_invalid_server_address() -> bool:
    """Test handling of various invalid server addresses."""
    logger.info("--- Test 06B: Invalid Server Address ---")
    invalid_urls = [
        "https://invalid-hostname-for-testing.local/",
        "http://127.0.0.1:4433/",
    ]
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=3.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )

    try:
        async with WebTransportClient(config=config) as client:
            for i, invalid_url in enumerate(invalid_urls):
                logger.info("Testing invalid URL %d: %s", i + 1, invalid_url)
                try:
                    await client.connect(url=invalid_url)
                    logger.error("FAILURE: Connection to %s should have failed.", invalid_url)
                    return False
                except Exception:
                    logger.info("   - SUCCESS: Connection to %s correctly failed.", invalid_url)
            return True
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred in the test setup: %s", e, exc_info=True)
        return False


async def test_stream_errors() -> bool:
    """Test error handling for various stream operations."""
    logger.info("--- Test 06C: Stream Error Handling ---")
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
            stream = await session.create_bidirectional_stream()
            await stream.close()
            logger.info("Stream closed for testing subsequent operations.")

            logger.info("Testing write operation on a closed stream...")
            try:
                await stream.write(data=b"This should fail")
                logger.error("FAILURE: Write on a closed stream should have failed.")
                return False
            except StreamError:
                logger.info("   - SUCCESS: Write on a closed stream correctly failed.")
            except Exception as e:
                logger.error("   - FAILURE: Unexpected error on write: %s", e)
                return False

            return True
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_read_timeout() -> bool:
    """Test the handling of a stream read timeout."""
    logger.info("--- Test 06D: Stream Read Timeout ---")
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        read_timeout=1.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )

    try:
        async with WebTransportClient(config=config) as client:
            session = await client.connect(url=SERVER_URL)
            stream = await session.create_bidirectional_stream()
            logger.info("Attempting to read from a stream with no data (should time out)...")
            start_time = time.time()
            try:
                await stream.read(size=1024)
                logger.error("FAILURE: Read operation should have timed out.")
                return False
            except TimeoutError:
                duration = time.time() - start_time
                logger.info("SUCCESS: Read correctly timed out after %.1fs.", duration)
                return True
            except Exception as e:
                logger.error("FAILURE: Unexpected exception during read: %s", e)
                return False
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_session_closure_handling() -> bool:
    """Test that operations on a closed session correctly raise errors."""
    logger.info("--- Test 06E: Operations on Closed Session ---")
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
            logger.info("Connected, session ID: %s", session.session_id)
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
                logger.error("   - FAILURE: Unexpected error: %s", e)
                return False

            logger.info("Testing datagram send on closed session...")
            try:
                datagram_transport = await session.datagrams
                await datagram_transport.send(data=b"This should fail")
                logger.error("FAILURE: Datagram send on closed session should have failed.")
                return False
            except (DatagramError, SessionError, ClientError):
                logger.info("   - SUCCESS: Datagram send correctly failed.")
            except Exception as e:
                logger.error("   - FAILURE: Unexpected error: %s", e)
                return False

            return True
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_datagram_errors() -> bool:
    """Test error handling for datagram operations, like oversized payloads."""
    logger.info("--- Test 06F: Datagram Error Handling ---")
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
            max_size = datagram_transport.max_datagram_size
            logger.info("Max datagram size: %s bytes.", max_size)

            logger.info("Testing oversized datagram...")
            try:
                oversized_data = b"X" * (max_size + 1)
                await datagram_transport.send(data=oversized_data)
                logger.error("FAILURE: Oversized datagram send should have failed.")
                return False
            except DatagramError:
                logger.info("   - SUCCESS: Oversized datagram correctly failed with DatagramError.")
            except Exception as e:
                logger.error("   - FAILURE: Unexpected error for oversized datagram: %s", e)
                return False

            return True
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_resource_exhaustion() -> bool:
    """Test handling of resource exhaustion, specifically the stream limit."""
    logger.info("--- Test 06G: Resource Exhaustion (Stream Limit) ---")
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
            logger.info("Attempting to create streams until limit is reached...")
            streams = []
            max_attempts = 200
            limit_hit = False
            for i in range(max_attempts):
                try:
                    stream = await session.create_bidirectional_stream()
                    streams.append(stream)
                except StreamError:
                    logger.info("SUCCESS: Stream creation limit correctly hit after %d streams.", i)
                    limit_hit = True
                    break
            else:
                logger.warning("WARNING: Created all %d streams without hitting a limit.", max_attempts)

            for stream in streams:
                await stream.close()

            return limit_hit
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_malformed_operations() -> bool:
    """Test handling of malformed API operations."""
    logger.info("--- Test 06H: Malformed Operations ---")
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
            stream = await session.create_bidirectional_stream()

            logger.info("Testing invalid write data (None)...")
            try:
                await stream.write(data=None)  # type: ignore
                logger.error("FAILURE: Writing None should have failed.")
                return False
            except TypeError:
                logger.info("   - SUCCESS: Writing None correctly failed with TypeError.")
            except Exception as e:
                logger.error("   - FAILURE: Unexpected error for None write: %s", e)
                return False

            return True
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def main() -> int:
    """Run the main entry point for the error handling test suite."""
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
                logger.info("%s: PASSED", test_name)
                passed += 1
            else:
                logger.error("%s: FAILED", test_name)
        except Exception as e:
            logger.error("%s: CRASHED - %s", test_name, e, exc_info=True)
        await asyncio.sleep(1)

    logger.info("")
    logger.info("=" * 60)
    logger.info("Test 06 Results: %d/%d passed", passed, total)

    if passed == total:
        logger.info("TEST 06 PASSED: All error handling tests successful!")
        return 0
    else:
        logger.error("TEST 06 FAILED: Some error handling tests failed!")
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
