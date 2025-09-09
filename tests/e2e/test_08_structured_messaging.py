"""
E2E test for the structured message layer.
"""

import asyncio
import logging
import ssl
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final, Type

from pywebtransport import ClientConfig, ConnectionError, Serializer, TimeoutError, WebTransportClient
from pywebtransport.serializer import JSONSerializer, MsgPackSerializer

SERVER_HOST: Final[str] = "127.0.0.1"
SERVER_PORT: Final[int] = 4433
SERVER_URL: Final[str] = f"https://{SERVER_HOST}:{SERVER_PORT}/"
DEBUG_MODE: Final[bool] = "--debug" in sys.argv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
if DEBUG_MODE:
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("aioquic").setLevel(logging.DEBUG)
    logging.getLogger("pywebtransport").setLevel(logging.DEBUG)

logger = logging.getLogger("test_structured_messaging")


@dataclass(kw_only=True)
class UserData:
    """Represents user data structure."""

    id: int
    name: str
    email: str


@dataclass(kw_only=True)
class StatusUpdate:
    """Represents a status update message."""

    status: str
    timestamp: float


MESSAGE_REGISTRY: dict[int, Type[Any]] = {1: UserData, 2: StatusUpdate}


async def run_structured_test(*, serializer: Serializer, path: str, serializer_name: str) -> bool:
    """Core logic for testing a specific serializer end-to-end."""
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
    )

    try:
        async with WebTransportClient(config=config) as client:
            session = await client.connect(url=SERVER_URL + path)
            logger.info("Connected for %s test, session: %s", serializer_name.upper(), session.session_id)

            logger.info("[%s] Testing StructuredStream...", serializer_name.upper())
            s_stream = await session.create_structured_stream(serializer=serializer, registry=MESSAGE_REGISTRY)

            user_obj = UserData(id=1, name="test", email="test@example.com")
            logger.info("   - Sending stream object: %s", user_obj)
            await s_stream.send_obj(obj=user_obj)
            received_user_obj = await s_stream.receive_obj()
            logger.info("   - Received stream object: %s", received_user_obj)
            if user_obj != received_user_obj:
                logger.error("FAILURE: Stream object mismatch for UserData.")
                return False

            status_obj = StatusUpdate(status="active", timestamp=time.time())
            logger.info("   - Sending stream object: %s", status_obj)
            await s_stream.send_obj(obj=status_obj)
            received_status_obj = await s_stream.receive_obj()
            logger.info("   - Received stream object: %s", received_status_obj)
            if status_obj.status != received_status_obj.status:
                logger.error("FAILURE: Stream object mismatch for StatusUpdate.")
                return False
            logger.info("   - SUCCESS: StructuredStream echo correct.")
            await s_stream.close()

            logger.info("[%s] Testing StructuredDatagramStream...", serializer_name.upper())
            s_datagram = await session.create_structured_datagram_stream(
                serializer=serializer, registry=MESSAGE_REGISTRY
            )

            datagram_obj = UserData(id=99, name="datagram_user", email="dg@example.com")
            logger.info("   - Sending datagram object: %s", datagram_obj)
            await s_datagram.send_obj(obj=datagram_obj)
            received_datagram_obj = await s_datagram.receive_obj(timeout=5.0)
            logger.info("   - Received datagram object: %s", received_datagram_obj)
            if datagram_obj != received_datagram_obj:
                logger.error("FAILURE: Datagram object mismatch.")
                return False
            logger.info("   - SUCCESS: StructuredDatagramStream echo correct.")

            return True

    except (TimeoutError, ConnectionError) as e:
        logger.error("FAILURE: Test failed due to connection or timeout issue: %s", e)
        return False
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_json_messaging() -> bool:
    """Tests the structured message layer using the JSON serializer."""
    logger.info("--- Test 08A: Structured Messaging (JSON) ---")
    return await run_structured_test(serializer=JSONSerializer(), path="structured-echo/json", serializer_name="json")


async def test_msgpack_messaging() -> bool:
    """Tests the structured message layer using the MsgPack serializer."""
    return await run_structured_test(
        serializer=MsgPackSerializer(), path="structured-echo/msgpack", serializer_name="msgpack"
    )


async def main() -> int:
    """Main entry point for the structured messaging test suite."""
    logger.info("--- Starting Test 08: Structured Messaging ---")

    tests: list[tuple[str, Callable[[], Awaitable[bool]]]] = [
        ("JSON Messaging", test_json_messaging),
        ("MsgPack Messaging", test_msgpack_messaging),
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
    logger.info("Test 08 Results: %d/%d passed", passed, total)

    if passed == total:
        logger.info("TEST 08 PASSED: All structured messaging tests successful!")
        return 0
    else:
        logger.error("TEST 08 FAILED: Some structured messaging tests failed!")
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
