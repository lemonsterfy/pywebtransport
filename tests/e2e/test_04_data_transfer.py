"""
E2E Test 04: WebTransport data transfer.
Tests performance and integrity with various data sizes.
"""

import asyncio
import hashlib
import logging
import ssl
import sys
import time
from typing import Awaitable, Callable, List, Tuple

from pywebtransport.client import WebTransportClient
from pywebtransport.config import ClientConfig

DEBUG_MODE = "--debug" in sys.argv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
if DEBUG_MODE:
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("aioquic").setLevel(logging.DEBUG)
    logging.getLogger("pywebtransport").setLevel(logging.DEBUG)

logger = logging.getLogger("test_data_transfer")


def generate_test_data(size: int) -> bytes:
    """Generates a block of test data of a specified size."""
    pattern = b"WebTransport Test Data 1234567890 " * (size // 34 + 1)
    return pattern[:size]


def calculate_checksum(data: bytes) -> str:
    """Calculates the MD5 checksum for a block of data."""
    return hashlib.md5(data).hexdigest()


async def test_small_data() -> bool:
    """Tests small data transfers (< 1KB)."""
    logger.info("Test 04A: Small Data Transfer")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    test_sizes = [10, 100, 500, 1000]
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=5.0,
        write_timeout=5.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-04a/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            for size in test_sizes:
                logger.info(f"Testing {size} bytes...")
                test_data = generate_test_data(size)
                stream = await session.create_bidirectional_stream()

                start_time = time.time()
                await stream.write_all(test_data)
                response = await stream.read_all()
                duration = time.time() - start_time

                expected = b"ECHO: " + test_data
                if response != expected:
                    logger.error(f"{size} bytes: Data mismatch")
                    return False

                speed = size / duration / 1024 if duration > 0 else float("inf")
                logger.info(f"{size} bytes: OK ({duration:.3f}s, {speed:.1f} KB/s)")

            await session.close()
            logger.info("Small data transfer test completed successfully!")
            return True
    except Exception as e:
        logger.error(f"Small data transfer test failed: {e}", exc_info=True)
        return False


async def test_medium_data() -> bool:
    """Tests medium data transfers (1KB - 64KB)."""
    logger.info("Test 04B: Medium Data Transfer")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    test_sizes = [1024, 4096, 16384, 65536]
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=15.0,
        write_timeout=15.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-04b/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            for size in test_sizes:
                size_kb = size / 1024
                logger.info(f"Testing {size_kb:.1f} KB...")
                test_data = generate_test_data(size)
                stream = await session.create_bidirectional_stream()

                start_time = time.time()
                await stream.write_all(test_data)
                response_data = await stream.read_all()
                duration = time.time() - start_time

                expected = b"ECHO: " + test_data
                if response_data != expected:
                    logger.error(f"{size_kb:.1f} KB: Data mismatch")
                    logger.error(f"   Expected size: {len(expected)}")
                    logger.error(f"   Received size: {len(response_data)}")
                    return False

                speed = size / duration / 1024 if duration > 0 else float("inf")
                logger.info(f"{size_kb:.1f} KB: OK ({duration:.3f}s, {speed:.1f} KB/s)")
                await asyncio.sleep(0.1)

            await session.close()
            logger.info("Medium data transfer test completed successfully!")
            return True
    except Exception as e:
        logger.error(f"Medium data transfer test failed: {e}", exc_info=True)
        return False


async def test_chunked_transfer() -> bool:
    """Tests transferring data in multiple chunks."""
    logger.info("Test 04C: Chunked Transfer")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    total_size = 32768
    chunk_size = 4096
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=10.0,
        write_timeout=10.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-04c/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            test_data = generate_test_data(total_size)
            logger.info(f"Generated {total_size} bytes test data")
            stream = await session.create_bidirectional_stream()

            start_time = time.time()
            bytes_sent = 0
            for i in range(0, total_size, chunk_size):
                chunk = test_data[i : i + chunk_size]
                is_last_chunk = (i + chunk_size) >= total_size
                await stream.write(chunk, end_stream=is_last_chunk)
                bytes_sent += len(chunk)
                if (i // chunk_size + 1) % 4 == 0:
                    progress = bytes_sent / total_size * 100
                    logger.info(f"Sent {bytes_sent} bytes ({progress:.1f}%)")
            logger.info(f"All data sent ({bytes_sent} bytes)")

            response_data = await stream.read_all()
            duration = time.time() - start_time

            expected = b"ECHO: " + test_data
            if response_data != expected:
                logger.error("FAILED: Chunked data mismatch")
                logger.error(f"   Expected size: {len(expected)}")
                logger.error(f"   Received size: {len(response_data)}")
                return False

            speed = total_size / duration / 1024 if duration > 0 else float("inf")
            logger.info("SUCCESS: Chunked transfer completed!")
            logger.info(f"   Total size: {total_size} bytes")
            logger.info(f"   Duration: {duration:.3f}s")
            logger.info(f"   Speed: {speed:.1f} KB/s")
            await session.close()
            return True
    except Exception as e:
        logger.error(f"Chunked transfer test failed: {e}", exc_info=True)
        return False


async def test_binary_data() -> bool:
    """Tests the transfer of raw binary data."""
    logger.info("Test 04D: Binary Data Transfer")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=10.0,
        write_timeout=10.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-04d/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            binary_data = bytes(range(256)) * 100
            logger.info(f"Generated {len(binary_data)} bytes of binary data")
            stream = await session.create_bidirectional_stream()

            start_time = time.time()
            await stream.write_all(binary_data)
            response_data = await stream.read_all()
            duration = time.time() - start_time

            expected = b"ECHO: " + binary_data
            if response_data != expected:
                logger.error("FAILED: Binary data corrupted")
                return False

            speed = len(binary_data) / duration / 1024 if duration > 0 else float("inf")
            logger.info("SUCCESS: Binary data transfer completed!")
            logger.info(f"   Size: {len(binary_data)} bytes")
            logger.info(f"   Duration: {duration:.3f}s")
            logger.info(f"   Speed: {speed:.1f} KB/s")
            logger.info("   All byte values preserved: OK")
            await session.close()
            return True
    except Exception as e:
        logger.error(f"Binary data transfer test failed: {e}", exc_info=True)
        return False


async def test_performance_benchmark() -> bool:
    """Performs a performance benchmark with a 1MB payload."""
    logger.info("Test 04E: Performance Benchmark")
    logger.info("-" * 40)

    server_url = "https://127.0.0.1:4433/"
    test_size = 1024 * 1024
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,
        read_timeout=30.0,
        write_timeout=30.0,
        debug=DEBUG_MODE,
        headers={"user-agent": "pywebtransport-test-04e/1.0"},
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            session = await client.connect(server_url)
            logger.info(f"Connected, session: {session.session_id}")

            test_data = generate_test_data(test_size)
            logger.info(f"Generated {test_size / 1024 / 1024:.1f} MB test data")
            stream = await session.create_bidirectional_stream()

            logger.info("Starting performance benchmark...")
            overall_start = time.time()

            send_start = time.time()
            await stream.write_all(test_data)
            send_duration = time.time() - send_start
            logger.info(f"Send completed in {send_duration:.3f}s")

            receive_start = time.time()
            response_data = await stream.read_all()
            receive_duration = time.time() - receive_start
            overall_duration = time.time() - overall_start

            expected = b"ECHO: " + test_data
            if response_data != expected:
                logger.error("FAILED: Performance test data corrupted")
                return False

            send_speed = test_size / send_duration / 1024 / 1024 if send_duration > 0 else float("inf")
            receive_speed = test_size / receive_duration / 1024 / 1024 if receive_duration > 0 else float("inf")
            overall_speed = test_size / overall_duration / 1024 / 1024 if overall_duration > 0 else float("inf")
            logger.info("PERFORMANCE BENCHMARK RESULTS:")
            logger.info(f"   Data size: {test_size / 1024 / 1024:.1f} MB")
            logger.info(f"   Send time: {send_duration:.3f}s ({send_speed:.2f} MB/s)")
            logger.info(f"   Receive time: {receive_duration:.3f}s ({receive_speed:.2f} MB/s)")
            logger.info(f"   Round-trip time: {overall_duration:.3f}s ({overall_speed:.2f} MB/s)")
            await session.close()
            return True
    except Exception as e:
        logger.error(f"Performance benchmark failed: {e}", exc_info=True)
        return False


async def main() -> int:
    """Main entry point for the data transfer tests."""
    logger.info("Starting Test 04: Data Transfer")
    logger.info("")
    if DEBUG_MODE:
        logger.info("Debug mode enabled - verbose logging active")
    logger.info("Target server: https://127.0.0.1:4433/")
    logger.info("")

    tests: List[Tuple[str, Callable[[], Awaitable[bool]]]] = [
        ("Small Data Transfer", test_small_data),
        ("Medium Data Transfer", test_medium_data),
        ("Chunked Transfer", test_chunked_transfer),
        ("Binary Data Transfer", test_binary_data),
        ("Performance Benchmark", test_performance_benchmark),
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
        await asyncio.sleep(2)

    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Test 04 Results: {passed}/{total} passed")

    if passed == total:
        logger.info("TEST 04 PASSED: All data transfer tests successful!")
        logger.info("Ready to proceed to Test 05")
        return 0
    else:
        logger.error("TEST 04 FAILED: Some data transfer tests failed!")
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
