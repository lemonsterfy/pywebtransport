"""E2E test for the RPC (Remote Procedure Call) layer."""

import asyncio
import logging
import ssl
import sys
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Final

from pywebtransport import ClientConfig, ConnectionError, TimeoutError, WebTransportClient
from pywebtransport.rpc import RpcError, RpcManager, RpcTimeoutError

SERVER_HOST: Final[str] = "127.0.0.1"
SERVER_PORT: Final[int] = 4433
SERVER_URL: Final[str] = f"https://{SERVER_HOST}:{SERVER_PORT}/rpc"
DEBUG_MODE: Final[bool] = "--debug" in sys.argv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
if DEBUG_MODE:
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("aioquic").setLevel(logging.DEBUG)
    logging.getLogger("pywebtransport").setLevel(logging.DEBUG)

logger = logging.getLogger("test_rpc")


@dataclass(kw_only=True)
class UserData:
    """Represents user data structure for RPC tests."""

    id: int
    name: str


async def test_rpc_basic_add() -> bool:
    """Test a basic RPC call with arguments and a return value."""
    logger.info("--- Test 09A: Basic RPC Call (add) ---")
    config = ClientConfig(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )
    try:
        async with WebTransportClient(config=config) as client:
            session = await client.connect(url=SERVER_URL)
            async with session:
                rpc_stream = await session.create_bidirectional_stream()
                async with RpcManager(stream=rpc_stream, session_id=session.session_id) as rpc:
                    logger.info("Calling remote procedure: add(a=2, b=3)")
                    result = await rpc.call("add", 2, 3)
                    logger.info("Received result: %s", result)

                    if result == 5:
                        logger.info("SUCCESS: Basic RPC call returned the correct value.")
                        return True
                    else:
                        logger.error("FAILURE: Expected result 5, but got %s.", result)
                        return False
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_rpc_complex_types() -> bool:
    """Test RPC with dictionary representations of custom objects."""
    logger.info("--- Test 09B: Complex Data Types (UserData) ---")
    config = ClientConfig(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )
    try:
        async with WebTransportClient(config=config) as client:
            session = await client.connect(url=SERVER_URL)
            async with session:
                rpc_stream = await session.create_bidirectional_stream()
                async with RpcManager(stream=rpc_stream, session_id=session.session_id) as rpc:
                    user_id = 123
                    logger.info("Calling remote procedure: get_user(user_id=%d)", user_id)
                    result_dict = await rpc.call("get_user", user_id)
                    logger.info("Received result: %s", result_dict)

                    expected_obj = UserData(id=user_id, name=f"User {user_id}")
                    if result_dict == asdict(expected_obj):
                        logger.info("SUCCESS: RPC with complex types returned the correct dictionary.")
                        return True
                    else:
                        logger.error("FAILURE: Expected %s, but got %s.", asdict(expected_obj), result_dict)
                        return False
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_rpc_notification() -> bool:
    """Test an RPC call with no return value (a notification)."""
    logger.info("--- Test 09C: Notification (No Return Value) ---")
    config = ClientConfig(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )
    try:
        async with WebTransportClient(config=config) as client:
            session = await client.connect(url=SERVER_URL)
            async with session:
                rpc_stream = await session.create_bidirectional_stream()
                async with RpcManager(stream=rpc_stream, session_id=session.session_id) as rpc:
                    message = "This is a test notification."
                    logger.info("Calling remote procedure: log_message('%s')", message)
                    result = await rpc.call("log_message", message)
                    logger.info("Received result: %s", result)

                    if result is None:
                        logger.info("SUCCESS: Notification call completed successfully.")
                        return True
                    else:
                        logger.error("FAILURE: Expected None for notification, but got %s.", result)
                        return False
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_rpc_error_handling() -> bool:
    """Test that a remote exception is correctly propagated to the client."""
    logger.info("--- Test 09D: Remote Error Handling ---")
    config = ClientConfig(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )
    try:
        async with WebTransportClient(config=config) as client:
            session = await client.connect(url=SERVER_URL)
            async with session:
                rpc_stream = await session.create_bidirectional_stream()
                async with RpcManager(stream=rpc_stream, session_id=session.session_id) as rpc:
                    logger.info("Calling remote procedure that will raise an error: divide(10, 0)")
                    try:
                        await rpc.call("divide", 10, 0)
                        logger.error("FAILURE: RPC call should have raised an exception.")
                        return False
                    except RpcError as e:
                        logger.info("SUCCESS: Correctly caught RpcError: %s", e)
                        if "division by zero" in str(e):
                            logger.info("   - Error message contains expected text.")
                            return True
                        else:
                            logger.error("   - FAILURE: Error message is not as expected.")
                            return False
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_rpc_concurrency() -> bool:
    """Test making multiple RPC calls concurrently."""
    logger.info("--- Test 09E: Concurrent RPC Calls ---")
    config = ClientConfig(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )
    try:
        async with WebTransportClient(config=config) as client:
            session = await client.connect(url=SERVER_URL)
            async with session:
                rpc_stream = await session.create_bidirectional_stream()
                async with RpcManager(stream=rpc_stream, session_id=session.session_id) as rpc:
                    calls = [rpc.call("add", i, i) for i in range(5)]
                    logger.info("Dispatching 5 concurrent 'add' calls...")
                    results = await asyncio.gather(*calls)
                    logger.info("Received results: %s", results)

                    expected = [0, 2, 4, 6, 8]
                    if results == expected:
                        logger.info("SUCCESS: All concurrent calls returned correct results.")
                        return True
                    else:
                        logger.error("FAILURE: Concurrent call results mismatch. Expected %s.", expected)
                        return False
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def test_rpc_timeout() -> bool:
    """Test that an RPC call correctly times out if the server is too slow."""
    logger.info("--- Test 09F: RPC Timeout ---")
    config = ClientConfig(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )
    try:
        async with WebTransportClient(config=config) as client:
            session = await client.connect(url=SERVER_URL)
            async with session:
                rpc_stream = await session.create_bidirectional_stream()
                async with RpcManager(stream=rpc_stream, session_id=session.session_id) as rpc:
                    logger.info("Calling slow remote procedure with a 1s timeout...")
                    try:
                        await rpc.call("slow_operation", 2, timeout=1.0)
                        logger.error("FAILURE: RPC call should have timed out.")
                        return False
                    except RpcTimeoutError:
                        logger.info("SUCCESS: Correctly caught RpcTimeoutError.")
                        return True
    except Exception as e:
        logger.error("FAILURE: An unexpected error occurred: %s", e, exc_info=True)
        return False


async def main() -> int:
    """Run the main entry point for the RPC test suite."""
    logger.info("--- Starting Test 09: Remote Procedure Call (RPC) ---")

    tests: list[tuple[str, Callable[[], Awaitable[bool]]]] = [
        ("Basic RPC Call", test_rpc_basic_add),
        ("Complex Data Types", test_rpc_complex_types),
        ("Notification", test_rpc_notification),
        ("Remote Error Handling", test_rpc_error_handling),
        ("Concurrency", test_rpc_concurrency),
        ("Timeout", test_rpc_timeout),
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
        except (TimeoutError, ConnectionError) as e:
            logger.error("%s: FAILED - %s", test_name, e)
        except Exception as e:
            logger.error("%s: CRASHED - %s", test_name, e, exc_info=True)
        await asyncio.sleep(1)

    logger.info("")
    logger.info("=" * 60)
    logger.info("Test 09 Results: %d/%d passed", passed, total)

    if passed == total:
        logger.info("TEST 09 PASSED: All RPC tests successful!")
        return 0
    else:
        logger.error("TEST 09 FAILED: Some RPC tests failed!")
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
