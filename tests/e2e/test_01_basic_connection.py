"""
E2E test for basic WebTransport connections.
"""

import asyncio
import logging
import socket
import ssl
import sys
import time
from typing import Final

from pywebtransport import ClientConfig, ConnectionError, TimeoutError, WebTransportClient

SERVER_HOST: Final[str] = "127.0.0.1"
SERVER_PORT: Final[int] = 4433
SERVER_URL: Final[str] = f"https://{SERVER_HOST}:{SERVER_PORT}/"
DEBUG_MODE: Final[bool] = "--debug" in sys.argv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
if DEBUG_MODE:
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("aioquic").setLevel(logging.DEBUG)
    logging.getLogger("pywebtransport").setLevel(logging.DEBUG)

logger = logging.getLogger("test_basic_connection")


async def test_server_reachability() -> bool:
    """Performs a pre-check for server reachability via a simple UDP packet."""
    logger.info("Pre-check: Testing server reachability...")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2.0)
        try:
            sock.sendto(b"ping", (SERVER_HOST, SERVER_PORT))
            logger.info(f"Server port {SERVER_PORT} (UDP) is reachable.")
            return True
        except socket.error as e:
            logger.warning(f"UDP probe failed: {e}. This might be normal.")
            return True
        finally:
            sock.close()
    except Exception as e:
        logger.error(f"Reachability pre-check failed unexpectedly: {e}")
        return False


async def test_basic_connection() -> bool:
    """Tests the establishment of a basic WebTransport connection."""
    logger.info("Test 01: Basic WebTransport Connection")
    logger.info("=" * 50)

    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=15.0,
        headers={"user-agent": "pywebtransport-e2e-test/1.0"},
    )
    logger.info(f"Target server: {SERVER_URL}")
    logger.info(f"Config: timeout={config.connect_timeout}s, verify_ssl=False")

    try:
        async with WebTransportClient.create(config=config) as client:
            logger.info("Client activated, attempting connection...")
            start_time = time.time()
            session = await client.connect(SERVER_URL)
            connect_time = time.time() - start_time

            logger.info("Connection established!")
            logger.info(f"   - Connection time: {connect_time:.3f}s")
            logger.info(f"   - Session ID: {session.session_id}")
            logger.info(f"   - Session state: {session.state.value}")
            logger.info(f"   - Session ready: {session.is_ready}")

            if not session.is_ready:
                logger.error("FAILED: Session not ready after connection")
                return False

            logger.info("SUCCESS: Session is ready for communication!")
            if session.connection:
                logger.info(f"   - Remote address: {session.connection.remote_address}")

            logger.info("Closing session...")
            await session.close()
            logger.info("Session closed successfully")
            return True

    except (TimeoutError, ConnectionError) as e:
        logger.error(f"FAILED: Connection error - {e}")
        logger.error("Possible issues:")
        logger.error("   - Server not running")
        logger.error("   - Wrong server address/port")
        logger.error("   - Network connectivity problems")
        return False
    except Exception as e:
        logger.error(f"FAILED: Unexpected error - {e}", exc_info=True)
        logger.error("This might be a bug in the WebTransport implementation")
        return False


async def main() -> int:
    """Main entry point for the basic connection test."""
    logger.info("Starting Test 01: Basic Connection")
    logger.info("")

    if not await test_server_reachability():
        logger.error("Pre-check failed. Please start the server first:")
        logger.error("   python tests/e2e/test_00_e2e_server.py")
        return 1

    logger.info("")
    success = await test_basic_connection()
    logger.info("")
    logger.info("=" * 50)

    if success:
        logger.info("TEST 01 PASSED: Basic connection successful!")
        logger.info("Ready to proceed to Test 02")
        return 0
    else:
        logger.error("TEST 01 FAILED: Basic connection failed!")
        logger.error("Please fix the connection issues before proceeding")
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
