"""
E2E Test 06: WebTransport error handling and edge cases.
Tests the handling of various error scenarios and exceptions.
"""

import asyncio
import logging
import ssl
import sys
import time
from typing import Awaitable, Callable, List, Tuple

from pywebtransport.client import WebTransportClient
from pywebtransport.config import ClientConfig
from pywebtransport.exceptions import ClientError, ConnectionError, DatagramError, StreamError, TimeoutError

# Module-level constants
DEBUG_MODE = "--debug" in sys.argv

# Module-level configuration and variables
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
if DEBUG_MODE:
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("aioquic").setLevel(logging.DEBUG)
    logging.getLogger("pywebtransport").setLevel(logging.DEBUG)

logger = logging.getLogger("test_error_handling")


async def test_connection_timeout() -> bool:
    """Tests the handling of a connection timeout."""
    logger.info("Test 06A: Connection Timeout")
    logger.info("-" * 40)

    invalid_url = "https://127.0.0.1:9999/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=2.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-06a/1.0"},
    )

    start_time = time.time()
    try:
        async with WebTransportClient.create(config=config) as client:
            logger.info(f"Attempting connection to invalid server: {invalid_url}")
            await client.connect(invalid_url)
        logger.error("UNEXPECTED: Connection should have failed but it succeeded.")
        return False
    except (TimeoutError, ConnectionError, ClientError) as e:
        duration = time.time() - start_time
        logger.info(f"EXPECTED: Connection failed as expected after {duration:.1f}s.")
        logger.info(f"   Caught Error Type: {type(e).__name__}")
        logger.info(f"   Error Message: {e}")
        if "timeout" in str(e).lower():
            logger.info("   Validation: The error is confirmed to be a timeout.")
            return True
        else:
            logger.error("FAILED: An exception was caught, but it wasn't a timeout error.")
            return False
    except Exception as e:
        logger.error(f"FAILED: An unexpected exception type was caught: {type(e).__name__}", exc_info=True)
        return False


async def test_invalid_server_address() -> bool:
    """Tests handling of invalid server addresses."""
    logger.info("Test 06B: Invalid Server Address")
    logger.info("-" * 40)

    invalid_urls = [
        "https://invalid-hostname-12345.local:4433/",
        "https://256.256.256.256:4433/",
        "http://127.0.0.1:4433/",
    ]
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=3.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-06b/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            for i, invalid_url in enumerate(invalid_urls):
                logger.info(f"Testing invalid URL {i+1}: {invalid_url}")
                try:
                    session = await client.connect(invalid_url)
                    logger.error(f"UNEXPECTED: Connection to {invalid_url} should have failed")
                    await session.close()
                    return False
                except Exception as e:
                    logger.info(f"EXPECTED: {invalid_url} failed with {type(e).__name__}")
            logger.info("SUCCESS: All invalid addresses correctly rejected!")
            return True
    except Exception as e:
        logger.error(f"Unexpected error in invalid address test: {e}", exc_info=True)
        return False


async def test_stream_errors() -> bool:
    """Tests error handling for stream operations."""
    logger.info("Test 06C: Stream Error Handling")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=3.0,
        write_timeout=3.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-06c/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            stream = await session.create_bidirectional_stream()
            logger.info(f"Stream created: {stream.stream_id}")
            logger.info("Testing operations on closed stream...")
            await stream.close()
            try:
                await stream.write(b"This should fail")
                logger.error("UNEXPECTED: Write on closed stream succeeded")
                return False
            except (StreamError, Exception) as e:
                logger.info(f"EXPECTED: Write on closed stream failed with {type(e).__name__}")
            try:
                data = await stream.read(size=100)
                logger.info(f"Read on closed stream returned: {len(data) if data else 0} bytes")
            except Exception as e:
                logger.info(f"Read on closed stream failed with {type(e).__name__}")

            logger.info("Testing oversized data write...")
            stream2 = await session.create_bidirectional_stream()
            try:
                huge_data = b"X" * (10 * 1024 * 1024)
                await asyncio.wait_for(stream2.write(huge_data), timeout=5.0)
                logger.warning("Large data write succeeded (might be OK)")
            except (asyncio.TimeoutError, StreamError) as e:
                logger.info(f"EXPECTED: Large data write failed/timed out with {type(e).__name__}")
            await stream2.close()
            await session.close()
            return True
    except Exception as e:
        logger.error(f"Stream error handling test failed: {e}", exc_info=True)
        return False


async def test_read_timeout() -> bool:
    """Tests the handling of a stream read timeout."""
    logger.info("Test 06D: Read Timeout")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=2.0,
        write_timeout=5.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-06d/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            stream = await session.create_bidirectional_stream()
            logger.info(f"Stream created: {stream.stream_id}")
            logger.info("Attempting read without sending data (should timeout)...")
            start_time = time.time()
            try:
                data = await stream.read(size=1024)
                if not data:
                    logger.info("Read returned empty data (connection closed)")
                else:
                    logger.warning(f"Unexpected: Read returned data: {data!r}")
            except (asyncio.TimeoutError, TimeoutError) as e:
                duration = time.time() - start_time
                logger.info(f"EXPECTED: Read timeout after {duration:.1f}s")
                logger.info(f"   Error: {type(e).__name__}")
            await stream.close()
            await session.close()
            return True
    except Exception as e:
        logger.error(f"Read timeout test failed: {e}", exc_info=True)
        return False


async def test_session_closure_handling() -> bool:
    """Tests error handling for operations on a closed session."""
    logger.info("Test 06E: Session Closure Handling")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=5.0,
        write_timeout=5.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-06e/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            stream = await session.create_bidirectional_stream()
            logger.info(f"Stream created: {stream.stream_id}")
            logger.info("Closing session...")
            await session.close()

            logger.info("Testing operations on closed session...")
            try:
                await session.create_bidirectional_stream()
                logger.error("UNEXPECTED: Stream creation on closed session succeeded")
                return False
            except Exception as e:
                logger.info(f"EXPECTED: Stream creation failed with {type(e).__name__}")
            try:
                await session.datagrams.send(b"This should fail")
                logger.error("UNEXPECTED: Datagram send on closed session succeeded")
                return False
            except Exception as e:
                logger.info(f"EXPECTED: Datagram send failed with {type(e).__name__}")
            try:
                await stream.write(b"This should fail")
                logger.error("UNEXPECTED: Stream write after session close succeeded")
                return False
            except Exception as e:
                logger.info(f"EXPECTED: Stream write failed with {type(e).__name__}")
            return True
    except Exception as e:
        logger.error(f"Session closure handling test failed: {e}", exc_info=True)
        return False


async def test_datagram_errors() -> bool:
    """Tests error handling for datagram operations."""
    logger.info("Test 06F: Datagram Error Handling")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=5.0,
        write_timeout=5.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-06f/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            datagrams = session.datagrams
            max_size = datagrams.max_datagram_size
            logger.info(f"Max datagram size: {max_size} bytes")

            logger.info("Testing oversized datagram...")
            try:
                oversized_data = b"X" * (max_size + 1000)
                await datagrams.send(oversized_data)
                logger.error("UNEXPECTED: Oversized datagram should have failed")
                return False
            except (DatagramError, Exception) as e:
                logger.info(f"EXPECTED: Oversized datagram failed with {type(e).__name__}")

            logger.info("Testing invalid priority...")
            try:
                await datagrams.send(b"Test", priority=-1)
                logger.warning("Negative priority was accepted (might be clamped)")
            except Exception as e:
                logger.info(f"Negative priority failed with {type(e).__name__}")
            try:
                await datagrams.send(b"Test", priority=999)
                logger.warning("High priority was accepted (might be clamped)")
            except Exception as e:
                logger.info(f"High priority failed with {type(e).__name__}")

            logger.info("Testing invalid TTL...")
            try:
                await datagrams.send(b"Test", ttl=-1.0)
                logger.warning("Negative TTL was accepted (might be ignored)")
            except Exception as e:
                logger.info(f"Negative TTL failed with {type(e).__name__}")
            await session.close()
            return True
    except Exception as e:
        logger.error(f"Datagram error handling test failed: {e}", exc_info=True)
        return False


async def test_resource_exhaustion() -> bool:
    """Tests handling of resource exhaustion, like stream limits."""
    logger.info("Test 06G: Resource Exhaustion")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=5.0,
        write_timeout=5.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-06g/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            logger.info("Testing stream limit...")
            streams = []
            max_attempts = 200
            for i in range(max_attempts):
                try:
                    stream = await session.create_bidirectional_stream()
                    streams.append(stream)
                    if (i + 1) % 50 == 0:
                        logger.info(f"   Created {i + 1} streams...")
                except Exception as e:
                    logger.info(f"Stream creation limit reached at {i} streams")
                    logger.info(f"   Error: {type(e).__name__}")
                    break
            else:
                logger.warning(f"Created all {max_attempts} streams (no limit encountered)")
            logger.info(f"Total streams created: {len(streams)}")

            logger.info("Cleaning up streams...")
            for i, stream in enumerate(streams):
                try:
                    await stream.close()
                    if (i + 1) % 50 == 0:
                        logger.info(f"   Closed {i + 1} streams...")
                except Exception:
                    pass
            await session.close()
            return True
    except Exception as e:
        logger.error(f"Resource exhaustion test failed: {e}", exc_info=True)
        return False


async def test_malformed_operations() -> bool:
    """Tests handling of malformed API operations."""
    logger.info("Test 06H: Malformed Operations")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=5.0,
        write_timeout=5.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-06h/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            stream = await session.create_bidirectional_stream()
            logger.info("Testing invalid read sizes...")
            try:
                await stream.read(size=0)
                logger.info("Zero read size returned 0 bytes")
            except Exception as e:
                logger.info(f"Zero read size failed with {type(e).__name__}")

            logger.info("Testing invalid write data...")
            try:
                await stream.write("This is a string, not bytes")
                logger.info("EXPECTED: String write was accepted and auto-converted to bytes")
            except Exception as e:
                logger.error(f"UNEXPECTED: String write failed with {type(e).__name__}")
                return False

            try:
                await stream.write(None)  # type: ignore  # Expected failure with None input
                logger.error("UNEXPECTED: None write should have failed")
                return False
            except Exception as e:
                logger.info(f"EXPECTED: None write failed with {type(e).__name__}")
            await stream.close()
            await session.close()
            return True
    except Exception as e:
        logger.error(f"Malformed operations test failed: {e}", exc_info=True)
        return False


async def main() -> int:
    """Main entry point for the error handling test suite."""
    logger.info("Starting Test 06: Error Handling")
    logger.info("")

    if DEBUG_MODE:
        logger.info("Debug mode enabled - verbose logging active")
    logger.info("Target server: https://127.0.0.1:4433/")
    logger.info("")

    tests: List[Tuple[str, Callable[[], Awaitable[bool]]]] = [
        ("Connection Timeout", test_connection_timeout),
        ("Invalid Server Address", test_invalid_server_address),
        ("Stream Error Handling", test_stream_errors),
        ("Read Timeout", test_read_timeout),
        ("Session Closure Handling", test_session_closure_handling),
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
            logger.error(f"{test_name}: CRASHED - {e}")
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
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Test crashed: {e}", exc_info=True)
        sys.exit(1)
