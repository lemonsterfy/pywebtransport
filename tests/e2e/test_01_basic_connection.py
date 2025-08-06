"""
E2E Test 01: Basic WebTransport connection.
Validates that the client can successfully connect to the server.
"""

import asyncio
import logging
import socket
import ssl
import sys
import time

from pywebtransport.client import WebTransportClient
from pywebtransport.config import ClientConfig
from pywebtransport.exceptions import ConnectionError

DEBUG_MODE = "--debug" in sys.argv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
if DEBUG_MODE:
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("aioquic").setLevel(logging.DEBUG)
    logging.getLogger("pywebtransport").setLevel(logging.DEBUG)

logger = logging.getLogger("test_basic_connection")


async def test_server_reachability() -> bool:
    """Performs a pre-check for server reachability via UDP."""
    logger.info("Pre-check: Testing server reachability...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2)
        try:
            sock.sendto(b"ping", ("127.0.0.1", 4433))
            logger.info("Server port 4433 (UDP) is reachable")
            return True
        except socket.error as e:
            logger.warning(f"UDP probe failed: {e}")
            logger.info("This might be normal - WebTransport server may be running")
            return True
        finally:
            sock.close()
    except Exception as e:
        logger.error(f"Reachability check failed: {e}")
        return False


async def test_basic_connection() -> bool:
    """Tests the establishment of a basic WebTransport connection."""
    logger.info("Test 01: Basic WebTransport Connection")
    logger.info("=" * 50)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=15.0,
        debug=True,
        headers={"user-agent": "pywebtransport-test-01/1.0"},
    )

    logger.info(f"Target server: {server_url}")
    logger.info(f"Config: timeout={config.connect_timeout}s, verify_ssl=False")

    try:
        async with WebTransportClient.create(config=config) as client:
            logger.info("Client activated, attempting connection...")
            start_time = time.time()
            session = await client.connect(server_url)
            connect_time = time.time() - start_time

            logger.info("Connection established!")
            logger.info(f"   Connection time: {connect_time:.3f}s")
            logger.info(f"   Session ID: {session.session_id}")
            logger.info(f"   Session path: {session.path}")
            logger.info(f"   Session state: {session.state}")
            logger.info(f"   Session ready: {session.is_ready}")

            if not session.is_ready:
                logger.error("FAILED: Session not ready after connection")
                return False

            logger.info("SUCCESS: Session is ready for communication!")
            if session.connection:
                logger.info(f"   Remote address: {session.connection.remote_address}")
                logger.info(f"   Connection state: {session.connection.state}")

            logger.info("Closing session...")
            await session.close()
            logger.info("Session closed successfully")
            return True

    except asyncio.TimeoutError:
        logger.error(f"FAILED: Connection timeout after {config.connect_timeout}s")
        logger.error("Check if server is running on 127.0.0.1:4433")
        return False
    except ConnectionError as e:
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
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Test crashed: {e}", exc_info=True)
        sys.exit(1)
