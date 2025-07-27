"""
E2E Test 02: Simple bidirectional stream operations.
Verifies stream creation and basic data exchange after connection.
"""

import asyncio
import logging
import ssl
import sys

from pywebtransport.client import WebTransportClient
from pywebtransport.config import ClientConfig

# Module-level constants
DEBUG_MODE = "--debug" in sys.argv

# Module-level configuration and variables
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
if DEBUG_MODE:
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("aioquic").setLevel(logging.DEBUG)
    logging.getLogger("pywebtransport").setLevel(logging.DEBUG)

logger = logging.getLogger("test_simple_stream")


async def test_stream_creation() -> bool:
    """Tests the stream creation functionality."""
    logger.info("Test 02A: Stream Creation")
    logger.info("-" * 30)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=10.0, debug=True)

    try:
        async with WebTransportClient.create(config=config) as client:
            logger.info("Connecting to server...")
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            logger.info("Creating bidirectional stream...")
            stream = await session.create_bidirectional_stream()

            logger.info("Stream created successfully!")
            logger.info(f"   Stream ID: {stream.stream_id}")
            logger.info(f"   Stream direction: {stream.direction}")
            logger.info(f"   Stream state: {stream.state}")
            logger.info(f"   Is readable: {stream.is_readable}")
            logger.info(f"   Is writable: {stream.is_writable}")

            logger.info("Closing stream...")
            await stream.close()
            logger.info("Stream closed")

            await session.close()
            logger.info("Session closed")
            return True

    except Exception as e:
        logger.error(f"Stream creation failed: {e}", exc_info=True)
        return False


async def test_simple_echo() -> bool:
    """Tests the simple echo functionality on a bidirectional stream."""
    logger.info("Test 02B: Simple Echo")
    logger.info("-" * 30)

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

            test_message = b"Hello, WebTransport!"
            logger.info(f"Sending: {test_message!r}")

            await stream.write_all(test_message)
            logger.info("Data sent and write end closed")

            logger.info("Waiting for echo response...")
            response_data = await stream.read_all()
            logger.info(f"Complete response: {response_data!r}")

            expected_response = b"ECHO: " + test_message
            if response_data == expected_response:
                logger.info("SUCCESS: Echo response matches expected!")
                logger.info(f"   Data length: {len(test_message)} bytes")
                logger.info(f"   Response length: {len(response_data)} bytes")
                await session.close()
                logger.info("Cleanup completed")
                return True
            else:
                logger.error("FAILED: Echo response mismatch!")
                logger.error(f"   Expected: {expected_response!r}")
                logger.error(f"   Received: {response_data!r}")
                return False

    except asyncio.TimeoutError:
        logger.error("FAILED: Timeout waiting for echo response")
        logger.error("Server might not be implementing echo correctly")
        return False
    except Exception as e:
        logger.error(f"Simple echo failed: {e}", exc_info=True)
        return False


async def test_multiple_messages() -> bool:
    """Tests sending multiple messages, each on a separate stream."""
    logger.info("Test 02C: Multiple Messages")
    logger.info("-" * 30)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE, connect_timeout=10.0, read_timeout=5.0, write_timeout=5.0, debug=True
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)

            messages = [b"Message 1", b"Message 2", b"Message 3"]
            success_count = 0

            for i, message in enumerate(messages):
                logger.info(f"Sending message {i+1}: {message!r}")
                stream = await session.create_bidirectional_stream()
                try:
                    await stream.write_all(message)
                    response_data = await stream.read_all()

                    expected = b"ECHO: " + message
                    if response_data == expected:
                        logger.info(f"Message {i+1} echo successful")
                        success_count += 1
                    else:
                        logger.error(f"Message {i+1} echo failed")
                        logger.error(f"   Expected: {expected!r}")
                        logger.error(f"   Received: {response_data!r}")
                finally:
                    if not stream.is_closed:
                        await stream.close()

            if success_count == len(messages):
                logger.info(f"SUCCESS: All {len(messages)} messages echoed correctly!")
            else:
                logger.error(f"FAILED: Only {success_count}/{len(messages)} messages successful")
                return False

            await session.close()
            return True

    except Exception as e:
        logger.error(f"Multiple messages test failed: {e}", exc_info=True)
        return False


async def main() -> int:
    """Main entry point for the simple stream operations test."""
    logger.info("Starting Test 02: Simple Stream Operations")
    logger.info("")

    tests = [
        ("Stream Creation", test_stream_creation),
        ("Simple Echo", test_simple_echo),
        ("Multiple Messages", test_multiple_messages),
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
    logger.info("=" * 50)
    logger.info(f"Test 02 Results: {passed}/{total} passed")

    if passed == total:
        logger.info("TEST 02 PASSED: All stream operations successful!")
        logger.info("Ready to proceed to Test 03")
        return 0
    else:
        logger.error("TEST 02 FAILED: Some stream operations failed!")
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
