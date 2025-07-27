try:
result = await pywebtransport.test_client_connectivity(
self.target_url,
timeout=10.0
)

            self.results['connectivity'] = {
                'success': result['success'],
                'connect_time': result.get('connect_time', 0),
                'error': result.get('error')
            }

            if result['success']:
                print(f"✓ Connection successful ({result['connect_time']:.3f}s)")
            else:
                print(f"✗ Connection failed: {result.get('error')}")

        except Exception as e:
            self.results['connectivity'] = {
                'success': False,
                'error': str(e)
            }
            print(f"✗ Connectivity test failed: {e}")

    async def test_connection_performance(self):
        """Test connection establishment performance"""
        print("Testing connection performance...")

        connect_times = []
        successful_connections = 0

        for i in range(5):
            try:
                start_time = time.time()
                client = pywebtransport.WebTransportClient()
                session = await client.connect(self.target_url)
                await session.ready()
                connect_time = time.time() - start_time

                connect_times.append(connect_time)
                successful_connections += 1

                await session.close()
                await client.close()

            except Exception as e:
                print(f"Connection {i+1} failed: {e}")

        if connect_times:
            avg_time = sum(connect_times) / len(connect_times)
            min_time = min(connect_times)
            max_time = max(connect_times)

            self.results['connection_performance'] = {
                'successful_connections': successful_connections,
                'total_attempts': 5,
                'avg_connect_time': avg_time,
                'min_connect_time': min_time,
                'max_connect_time': max_time,
                'connect_times': connect_times
            }

            print(f"✓ Avg connect time: {avg_time:.3f}s (min: {min_time:.3f}s, max: {max_time:.3f}s)")
        else:
            self.results['connection_performance'] = {
                'successful_connections': 0,
                'total_attempts': 5,
                'error': 'No successful connections'
            }
            print("✗ No successful connections")

    async def test_datagram_performance(self):
        """Test datagram performance"""
        print("Testing datagram performance...")

        try:
            client = pywebtransport.WebTransportClient()
            session = await client.connect(self.target_url)
            await session.ready()

            # Test message sizes
            message_sizes = [64, 256, 1024, 4096]
            results = {}

            for size in message_sizes:
                print(f"  Testing {size} byte messages...")

                message = b'x' * size
                send_times = []
                successful_sends = 0

                for i in range(10):
                    try:
                        start_time = time.time()
                        await session.datagrams.send(message)

                        # Try to receive echo (if server echoes)
                        try:
                            await session.datagrams.receive(timeout=1.0)
                            send_time = time.time() - start_time
                            send_times.append(send_time)
                            successful_sends += 1
                        except asyncio.TimeoutError:
                            # No echo, just measure send time
                            send_time = time.time() - start_time
                            send_times.append(send_time)
                            successful_sends += 1

                    except Exception as e:
                        print(f"    Send {i+1} failed: {e}")

                if send_times:
                    avg_time = sum(send_times) / len(send_times)
                    results[size] = {
                        'successful_sends': successful_sends,
                        'avg_round_trip_time': avg_time,
                        'throughput_mbps': (size * 8 * successful_sends) / (sum(send_times) * 1024 * 1024)
                    }
                    print(f"    ✓ {size}B: {avg_time:.3f}s avg, {successful_sends}/10 successful")

            self.results['datagram_performance'] = results

            await session.close()
            await client.close()

        except Exception as e:
            self.results['datagram_performance'] = {'error': str(e)}
            print(f"✗ Datagram test failed: {e}")

    async def test_stream_performance(self):
        """Test stream performance"""
        print("Testing stream performance...")

        try:
            client = pywebtransport.WebTransportClient()
            session = await client.connect(self.target_url)
            await session.ready()

            # Test stream creation
            start_time = time.time()
            streams = []

            for i in range(10):
                stream = await session.create_bidirectional_stream()
                streams.append(stream)

            stream_creation_time = time.time() - start_time

            # Test data transfer
            test_data = b'x' * 1024  # 1KB
            transfer_times = []

            for stream in streams:
                try:
                    start_time = time.time()
                    await stream.write(test_data)

                    # Try to read response
                    try:
                        await stream.read()
                    except:
                        pass  # May not have echo server

                    transfer_time = time.time() - start_time
                    transfer_times.append(transfer_time)

                except Exception as e:
                    print(f"    Stream transfer failed: {e}")
                finally:
                    await stream.close()

            if transfer_times:
                avg_transfer_time = sum(transfer_times) / len(transfer_times)

                self.results['stream_performance'] = {
                    'streams_created': len(streams),
                    'stream_creation_time': stream_creation_time,
                    'avg_stream_creation_time': stream_creation_time / len(streams),
                    'successful_transfers': len(transfer_times),
                    'avg_transfer_time': avg_transfer_time,
                    'throughput_mbps': (1024 * 8 * len(transfer_times)) / (sum(transfer_times) * 1024 * 1024)
                }

                print(f"✓ Created {len(streams)} streams in {stream_creation_time:.3f}s")
                print(f"✓ Avg transfer time: {avg_transfer_time:.3f}s")

            await session.close()
            await client.close()

        except Exception as e:
            self.results['stream_performance'] = {'error': str(e)}
            print(f"✗ Stream test failed: {e}")

    async def test_error_scenarios(self):
        """Test error handling scenarios"""
        print("Testing error scenarios...")

        error_tests = {}

        # Test connection to invalid URL
        try:
            client = pywebtransport.WebTransportClient()
            await client.connect("https://invalid.example.com:9999/", timeout=5.0)
            error_tests['invalid_host'] = {'connected': True, 'error': 'Should have failed'}
        except Exception as e:
            error_tests['invalid_host'] = {'connected': False, 'error': str(e)}
            print("✓ Invalid host properly rejected")

        # Test timeout scenarios
        try:
            config = pywebtransport.ClientConfig(connect_timeout=0.001)  # Very short timeout
            client = pywebtransport.WebTransportClient(config)
            await client.connect(self.target_url)
            error_tests['timeout'] = {'connected': True, 'error': 'Should have timed out'}
        except Exception as e:
            error_tests['timeout'] = {'connected': False, 'error': str(e)}
            print("✓ Timeout handling works")

        self.results['error_scenarios'] = error_tests

    def print_summary(self):
        """Print diagnostic summary"""
        print("\n" + "="*60)
        print("DIAGNOSTIC SUMMARY")
        print("="*60)

        # Connectivity
        if 'connectivity' in self.results:
            conn = self.results['connectivity']
            if conn['success']:
                print(f"✓ Connectivity: OK ({conn['connect_time']:.3f}s)")
            else:
                print(f"✗ Connectivity: FAILED - {conn.get('error')}")

        # Connection Performance
        if 'connection_performance' in self.results:
            perf = self.results['connection_performance']
            if perf['successful_connections'] > 0:
                print(f"✓ Connection Performance: {perf['successful_connections']}/5 successful")
                print(f"  Average: {perf['avg_connect_time']:.3f}s")
            else:
                print("✗ Connection Performance: No successful connections")

        # Datagram Performance
        if 'datagram_performance' in self.results:
            dg_perf = self.results['datagram_performance']
            if 'error' not in dg_perf:
                print("✓ Datagram Performance:")
                for size, data in dg_perf.items():
                    print(f"  {size}B: {data['successful_sends']}/10 msgs, {data['avg_round_trip_time']:.3f}s avg")
            else:
                print(f"✗ Datagram Performance: {dg_perf['error']}")

        # Stream Performance
        if 'stream_performance' in self.results:
            stream_perf = self.results['stream_performance']
            if 'error' not in stream_perf:
                print(f"✓ Stream Performance: {stream_perf['streams_created']} streams created")
                print(f"  Avg creation time: {stream_perf['avg_stream_creation_time']:.3f}s")
                print(f"  Avg transfer time: {stream_perf['avg_transfer_time']:.3f}s")
            else:
                print(f"✗ Stream Performance: {stream_perf['error']}")

        print("\nDiagnostics complete!")

# Performance benchmarking tool

async def benchmark_server(target_url: str, duration: int = 60, concurrency: int = 10):
"""Benchmark server performance"""
print(f"Benchmarking {target_url} for {duration}s with {concurrency} concurrent connections")

    try:
        results = await pywebtransport.benchmark_client_performance(
            url=target_url,
            concurrent_connections=concurrency
        )

        print("\n" + "="*50)
        print("BENCHMARK RESULTS")
        print("="*50)
        print(f"Duration: {duration}s")
        print(f"Concurrent connections: {concurrency}")
        print(f"Total requests: {results.get('total_requests', 'N/A')}")
        print(f"Successful requests: {results.get('successful_requests', 'N/A')}")
        print(f"Failed requests: {results.get('failed_requests', 'N/A')}")
        print(f"Requests/second: {results.get('requests_per_second', 0):.1f}")
        print(f"Average latency: {results.get('avg_latency', 0):.3f}s")
        print(f"Error rate: {results.get('error_rate', 0):.1%}")

        return results

    except Exception as e:
        print(f"Benchmark failed: {e}")
        return None

# Main diagnostic CLI

async def main():
"""Main diagnostic tool"""
import sys

    if len(sys.argv) < 2:
        print("Usage: python diagnostic_tool.py <server_url> [benchmark]")
        print("Example: python diagnostic_tool.py https://localhost:4433/")
        print("Example: python diagnostic_tool.py https://localhost:4433/ benchmark")
        sys.exit(1)

    target_url = sys.argv[1]

    if len(sys.argv) > 2 and sys.argv[2] == "benchmark":
        # Run benchmark
        await benchmark_server(target_url)
    else:
        # Run diagnostics
        diagnostics = WebTransportDiagnostics(target_url)
        await diagnostics.run_full_diagnostics()
        diagnostics.print_summary()

        # Save results to file
        with open('diagnostic_results.json', 'w') as f:
            json.dump(diagnostics.results, f, indent=2)
        print(f"\nDetailed results saved to diagnostic_results.json")

if **name** == "**main**":
asyncio.run(main())

````

### Testing Framework Integration

**Use Case**: Integration with testing frameworks for automated testing.

```python
# test_webtransport_integration.py
import pytest
import asyncio
import json
import tempfile
from pathlib import Path
import pywebtransport

class TestWebTransportIntegration:
    """Integration tests for WebTransport applications"""

    @pytest.fixture
    async def server(self):
        """Create test server fixture"""
        # Create test server
        async def test_handler(session):
            try:
                # Handle datagrams
                async for data in session.datagrams.receive_iter():
                    # Echo datagram
                    await session.datagrams.send(b"Echo: " + data)
            except Exception:
                pass

        server = pywebtransport.WebTransportServer()
        await server.listen("localhost", 4433, test_handler)

        # Start server in background
        server_task = asyncio.create_task(server.serve_forever())

        yield server

        # Cleanup
        server_task.cancel()
        await server.close()

    @pytest.fixture
    async def client(self):
        """Create test client fixture"""
        client = pywebtransport.WebTransportClient()
        yield client
        await client.close()

    @pytest.mark.asyncio
    async def test_basic_connection(self, server, client):
        """Test basic connection establishment"""
        session = await client.connect("https://localhost:4433/")
        await session.ready()

        assert session.is_ready
        assert session.session_id is not None

        await session.close()

    @pytest.mark.asyncio
    async def test_datagram_echo(self, server, client):
        """Test datagram echo functionality"""
        session = await client.connect("https://localhost:4433/")
        await session.ready()

        # Send test message
        test_message = b"Hello WebTransport"
        await session.datagrams.send(test_message)

        # Receive echo
        response = await session.datagrams.receive(timeout=5.0)
        assert response == b"Echo: " + test_message

        await session.close()

    @pytest.mark.asyncio
    async def test_multiple_connections(self, server):
        """Test multiple concurrent connections"""
        clients = []
        sessions = []

        try:
            # Create multiple clients
            for i in range(5):
                client = pywebtransport.WebTransportClient()
                session = await client.connect("https://localhost:4433/")
                await session.ready()

                clients.append(client)
                sessions.append(session)

            # Test concurrent communication
            tasks = []
            for i, session in enumerate(sessions):
                task = asyncio.create_task(self._test_session_communication(session, i))
                tasks.append(task)

            results = await asyncio.gather(*tasks)

            # Verify all sessions worked
            assert all(results)

        finally:
            # Cleanup
            for session in sessions:
                await session.close()
            for client in clients:
                await client.close()

    async def _test_session_communication(self, session, session_id):
        """Test communication for a single session"""
        try:
            message = f"Test message {session_id}".encode()
            await session.datagrams.send(message)

            response = await session.datagrams.receive(timeout=5.0)
            expected = b"Echo: " + message

            return response == expected
        except Exception:
            return False

    @pytest.mark.asyncio
    async def test_error_handling(self, client):
        """Test error handling scenarios"""

        # Test connection to invalid server
        with pytest.raises(Exception):
            await client.connect("https://invalid.localhost:9999/", timeout=1.0)

    @pytest.mark.asyncio
    async def test_performance_baseline(self, server, client):
        """Test performance meets baseline requirements"""
        session = await client.connect("https://localhost:4433/")
        await session.ready()

        # Measure message round-trip time
        start_time = asyncio.get_event_loop().time()

        for i in range(100):
            message = f"Performance test {i}".encode()
            await session.datagrams.send(message)
            await session.datagrams.receive(timeout=5.0)

        end_time = asyncio.get_event_loop().time()
        total_time = end_time - start_time
        avg_time = total_time / 100

        # Assert performance baseline (adjust as needed)
        assert avg_time < 0.1, f"Average round-trip time {avg_time:.3f}s exceeds 100ms baseline"

        await session.close()

# Load testing utilities
class LoadTestRunner:
    """Load testing utility for WebTransport applications"""

    def __init__(self, target_url: str):
        self.target_url = target_url
        self.results = []

    async def run_load_test(self, duration: int, concurrent_users: int, requests_per_user: int):
        """Run load test with specified parameters"""
        print(f"Starting load test: {concurrent_users} users, {requests_per_user} requests each, {duration}s duration")

        # Create semaphore to limit concurrency
        semaphore = asyncio.Semaphore(concurrent_users)

        # Create user tasks
        tasks = []
        for user_id in range(concurrent_users):
            task = asyncio.create_task(self._simulate_user(semaphore, user_id, requests_per_user, duration))
            tasks.append(task)

        # Wait for completion
        start_time = asyncio.get_event_loop().time()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = asyncio.get_event_loop().time()

        # Analyze results
        self._analyze_results(results, end_time - start_time)

    async def _simulate_user(self, semaphore, user_id: int, requests: int, duration: int):
        """Simulate a single user"""
        async with semaphore:
            client = pywebtransport.WebTransportClient()
            user_results = {
                'user_id': user_id,
                'requests_sent': 0,
                'requests_successful': 0,
                'errors': [],
                'response_times': []
            }

            try:
                session = await client.connect(self.target_url)
                await session.ready()

                end_time = asyncio.get_event_loop().time() + duration

                for i in range(requests):
                    if asyncio.get_event_loop().time() > end_time:
                        break

                    try:
                        start_time = asyncio.get_event_loop().time()

                        # Send request
                        message = f"User {user_id} Request {i}".encode()
                        await session.datagrams.send(message)

                        # Wait for response
                        await session.datagrams.receive(timeout=10.0)

                        response_time = asyncio.get_event_loop().time() - start_time
                        user_results['response_times'].append(response_time)
                        user_results['requests_successful'] += 1

                    except Exception as e:
                        user_results['errors'].append(str(e))

                    user_results['requests_sent'] += 1

                await session.close()

            except Exception as e:
                user_results['errors'].append(f"Connection error: {e}")
            finally:
                await client.close()

            return user_results

    def _analyze_results(self, results, duration):
        """Analyze load test results"""
        total_requests = 0
        successful_requests = 0
        total_errors = 0
        all_response_times = []

        for result in results:
            if isinstance(result, Exception):
                total_errors += 1
                continue

            total_requests += result['requests_sent']
            successful_requests += result['requests_successful']
            total_errors += len(result['errors'])
            all_response_times.extend(result['response_times'])

        # Calculate statistics
        success_rate = successful_requests / max(1, total_requests)
        error_rate = total_errors / max(1, total_requests)
        rps = total_requests / duration

        if all_response_times:
            avg_response_time = sum(all_response_times) / len(all_response_times)
            min_response_time = min(all_response_times)
            max_response_time = max(all_response_times)

            # Calculate percentiles
            sorted_times = sorted(all_response_times)
            p95_index = int(len(sorted_times) * 0.95)
            p95_response_time = sorted_times[p95_index] if p95_index < len(sorted_times) else max_response_time
        else:
            avg_response_time = min_response_time = max_response_time = p95_response_time = 0

        # Print results
        print(f"\n{'='*50}")
        print("LOAD TEST RESULTS")
        print(f"{'='*50}")
        print(f"Duration: {duration:.1f}s")
        print(f"Total requests: {total_requests}")
        print(f"Successful requests: {successful_requests}")
        print(f"Failed requests: {total_errors}")
        print(f"Success rate: {success_rate:.1%}")
        print(f"Error rate: {error_rate:.1%}")
        print(f"Requests/second: {rps:.1f}")
        print(f"Avg response time: {avg_response_time:.3f}s")
        print(f"Min response time: {min_response_time:.3f}s")
        print(f"Max response time: {max_response_time:.3f}s")
        print(f"95th percentile: {p95_response_time:.3f}s")

# Example load test
async def run_example_load_test():
    """Run example load test"""
    runner = LoadTestRunner("https://localhost:4433/")
    await runner.run_load_test(
        duration=30,  # 30 seconds
        concurrent_users=10,
        requests_per_user=100
    )

# Run tests
if __name__ == "__main__":
    # Run pytest for integration tests
    pytest.main([__file__, "-v"])

    # Or run load test
    # asyncio.run(run_example_load_test())
````

## Summary

This examples guide provides complete, production-ready implementations covering:

### **Basic Patterns**

- Echo server/client foundation
- HTTP-like request/response protocol
- Basic error handling and resource management

### **Real Applications**

- Multi-user chat with room management
- Reliable file transfer with progress tracking
- Real-time data streaming with backpressure

### **High-Performance Scenarios**

- Connection pooling and load balancing
- Concurrent request handling
- Performance monitoring and optimization

### **Production Integration**

- Microservice with database integration
- Comprehensive monitoring and logging
- Authentication and rate limiting middleware

### **Development Tools**

- Connection diagnostics and debugging
- Performance benchmarking utilities
- Automated testing framework integration

Each example includes:

- **Complete runnable code** with proper error handling
- **Clear use case descriptions** and key implementation points
- **Production considerations** like monitoring, security, and scalability
- **Extension possibilities** for adapting to specific needs

These examples serve as templates for building real WebTransport applications, from simple prototypes to production-grade systems.

## Next Steps

After exploring these examples, continue your PyWebTransport journey:

- **[Client Guide](client.md)** - Detailed client development patterns and best practices
- **[Server Guide](server.md)** - Server development and production deployment strategies
- **[Configuration](configuration.md)** - Advanced configuration options and optimization
- **[API Reference](../api-reference/)** - Complete API documentation and method details
  print(f"Downloading {filename} ({file_size} bytes)")

            # Receive file data
            hasher = hashlib.sha256()
            bytes_received = 0

            with open(save_path, 'wb') as f:
                while bytes_received < file_size:
                    chunk = await stream.read(8192)
                    if not chunk:
                        break

                    f.write(chunk)
                    hasher.update(chunk)
                    bytes_received += len(chunk)

                    # Read progress updates
                    try:
                        response_data = await self.read_length_prefixed(stream)
                        response = json.loads(response_data.decode())

                        if response.get("type") == "progress":
                            progress = response["bytes_sent"] / file_size * 100
                            print(f"Progress: {progress:.1f}%")
                    except:
                        pass

            # Verify checksum
            calculated_checksum = hasher.hexdigest()
            if calculated_checksum != expected_checksum:
                save_path.unlink()  # Delete corrupted file
                print("Download failed: Checksum mismatch")
                return False

            print(f"Download successful: {filename}")
            return True

        finally:
            await stream.close()

  async def list_files(self) -> list:
  """List available files on server"""
  stream = await self.session.create_bidirectional_stream()
  try:
  request = {"operation": "list"}
  await self.send_length_prefixed(stream, json.dumps(request).encode())

            response_data = await self.read_length_prefixed(stream)
            response = json.loads(response_data.decode())

            if response.get("type") == "file_list":
                return response["files"]
            else:
                print(f"List failed: {response.get('message', 'Unknown error')}")
                return []

        finally:
            await stream.close()

  async def send_length_prefixed(self, stream, data: bytes):
  """Send data with length prefix"""
  length = len(data)
  length_bytes = length.to_bytes(4, 'big')
  await stream.write(length_bytes + data)
  async def read_length_prefixed(self, stream) -> bytes:
  """Read data with length prefix"""
  length_bytes = await stream.read(4)
  if len(length_bytes) != 4:
  raise ValueError("Invalid length prefix")
  length = int.from_bytes(length_bytes, 'big')
  data = await stream.read(length)

        if len(data) != length:
            raise ValueError("Incomplete data")

        return data

# Interactive client

async def interactive_client():
"""Interactive file transfer client"""
client = FileTransferClient()

    try:
        await client.connect("https://localhost:4433/")
        print("Connected to file transfer server!")

        while True:
            print("\nOptions:")
            print("1. List files")
            print("2. Upload file")
            print("3. Download file")
            print("4. Quit")

            choice = input("Enter choice (1-4): ").strip()

            if choice == "1":
                files = await client.list_files()
                if files:
                    print("\nAvailable files:")
                    for file_info in files:
                        print(f"  {file_info['name']} ({file_info['size']} bytes)")
                else:
                    print("No files available")

            elif choice == "2":
                file_path = input("Enter file path to upload: ").strip()
                if file_path:
                    await client.upload_file(Path(file_path))

            elif choice == "3":
                filename = input("Enter filename to download: ").strip()
                if filename:
                    save_path = Path(f"./downloads/{filename}")
                    save_path.parent.mkdir(exist_ok=True)
                    await client.download_file(filename, save_path)

            elif choice == "4":
                break

            else:
                print("Invalid choice")

    except Exception as e:
        print(f"Client error: {e}")
    finally:
        if client.session:
            await client.session.close()

if **name** == "**main**":
asyncio.run(interactive_client())

````

**Key Points**:
- Uses streams for reliable file transfer
- Implements progress tracking and checksum verification
- Handles large files efficiently with chunked transfer
- Provides both upload and download functionality

## High-Performance Applications

### Connection Pool Example

**Use Case**: High-throughput applications requiring efficient connection management.

```python
# high_performance_client.py
import asyncio
import time
import statistics
from typing import List
import pywebtransport

class HighPerformanceClient:
    """High-performance client with connection pooling"""

    def __init__(self, server_url: str, pool_size: int = 20):
        self.server_url = server_url
        self.pool_size = pool_size
        self.metrics = {
            'requests_sent': 0,
            'requests_completed': 0,
            'errors': 0,
            'response_times': []
        }

    async def run_benchmark(self, total_requests: int, concurrency: int):
        """Run performance benchmark"""
        print(f"Starting benchmark: {total_requests} requests, {concurrency} concurrent")

        # Create client pool
        config = pywebtransport.ClientConfig(
            connect_timeout=5.0,
            max_streams=1000,
            stream_buffer_size=131072,  # 128KB buffers
            max_retries=3
        )

        async with pywebtransport.ClientPool(max_clients=self.pool_size, config=config) as pool:
            # Create semaphore to limit concurrency
            semaphore = asyncio.Semaphore(concurrency)

            # Create tasks
            tasks = []
            for i in range(total_requests):
                task = asyncio.create_task(self.make_request(pool, semaphore, i))
                tasks.append(task)

            # Wait for completion
            start_time = time.time()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            end_time = time.time()

            # Calculate statistics
            self.print_results(end_time - start_time, results)

    async def make_request(self, pool, semaphore, request_id: int):
        """Make a single request"""
        async with semaphore:
            start_time = time.time()

            try:
                # Acquire client from pool
                client = await pool.acquire()

                try:
                    session = await client.connect(self.server_url)

                    # Send request via datagram
                    request_data = f"Request {request_id}".encode()
                    await session.datagrams.send(request_data)

                    # Wait for response
                    response = await session.datagrams.receive(timeout=10.0)

                    # Record metrics
                    response_time = time.time() - start_time
                    self.metrics['requests_completed'] += 1
                    self.metrics['response_times'].append(response_time)

                    return response

                finally:
                    # Return client to pool
                    await pool.release(client)

            except Exception as e:
                self.metrics['errors'] += 1
                print(f"Request {request_id} failed: {e}")
                return None
            finally:
                self.metrics['requests_sent'] += 1

    def print_results(self, duration: float, results: List):
        """Print benchmark results"""
        successful = len([r for r in results if r is not None and not isinstance(r, Exception)])
        failed = len(results) - successful

        print(f"\n--- Benchmark Results ---")
        print(f"Duration: {duration:.2f} seconds")
        print(f"Total requests: {len(results)}")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"Success rate: {successful/len(results)*100:.1f}%")
        print(f"Requests/second: {len(results)/duration:.1f}")

        if self.metrics['response_times']:
            response_times = self.metrics['response_times']
            print(f"Response time stats:")
            print(f"  Mean: {statistics.mean(response_times)*1000:.1f}ms")
            print(f"  Median: {statistics.median(response_times)*1000:.1f}ms")
            print(f"  Min: {min(response_times)*1000:.1f}ms")
            print(f"  Max: {max(response_times)*1000:.1f}ms")

            if len(response_times) > 1:
                print(f"  95th percentile: {statistics.quantiles(response_times, n=20)[18]*1000:.1f}ms")

# Load testing with multiple scenarios
async def load_test_scenarios():
    """Run multiple load test scenarios"""
    client = HighPerformanceClient("https://localhost:4433/", pool_size=50)

    scenarios = [
        {"requests": 100, "concurrency": 10, "name": "Light Load"},
        {"requests": 1000, "concurrency": 50, "name": "Medium Load"},
        {"requests": 5000, "concurrency": 100, "name": "Heavy Load"},
    ]

    for scenario in scenarios:
        print(f"\n{'='*50}")
        print(f"Running scenario: {scenario['name']}")
        print(f"{'='*50}")

        await client.run_benchmark(scenario["requests"], scenario["concurrency"])

        # Reset metrics
        client.metrics = {
            'requests_sent': 0,
            'requests_completed': 0,
            'errors': 0,
            'response_times': []
        }

        # Brief pause between scenarios
        await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(load_test_scenarios())
````

### Real-time Streaming Example

**Use Case**: Real-time data streaming with flow control and backpressure handling.

```python
# streaming_server.py
import asyncio
import json
import time
import random
from typing import Set
import pywebtransport

class StreamingServer:
    """Real-time data streaming server"""

    def __init__(self):
        self.subscribers: Set[object] = set()
        self.streaming = False

    async def handle_session(self, session):
        """Handle streaming session"""
        print(f"New streaming session: {session.session_id}")

        # Handle control messages via datagrams
        control_task = asyncio.create_task(self.handle_control_messages(session))

        # Handle streaming via streams
        stream_task = asyncio.create_task(self.handle_streams(session))

        try:
            await asyncio.gather(control_task, stream_task, return_exceptions=True)
        finally:
            self.subscribers.discard(session)

    async def handle_control_messages(self, session):
        """Handle control messages"""
        try:
            async for data in session.datagrams.receive_iter():
                message = json.loads(data.decode())

                if message.get("action") == "subscribe":
                    await self.subscribe_client(session, message)
                elif message.get("action") == "unsubscribe":
                    await self.unsubscribe_client(session)
                elif message.get("action") == "get_status":
                    await self.send_status(session)

        except Exception as e:
            print(f"Control message error: {e}")

    async def handle_streams(self, session):
        """Handle incoming stream requests"""
        try:
            async for stream in session.incoming_bidirectional_streams():
                asyncio.create_task(self.handle_data_stream(stream))
        except Exception as e:
            print(f"Stream handling error: {e}")

    async def handle_data_stream(self, stream):
        """Handle individual data stream"""
        try:
            # This could be used for uploading data, configuration, etc.
            data = await stream.read()

            # Echo back confirmation
            response = {"status": "received", "bytes": len(data)}
            await stream.write(json.dumps(response).encode())

        finally:
            await stream.close()

    async def subscribe_client(self, session, message):
        """Subscribe client to data stream"""
        self.subscribers.add(session)

        response = {
            "type": "subscribed",
            "stream_type": message.get("stream_type", "default"),
            "timestamp": time.time()
        }

        await session.datagrams.send(json.dumps(response).encode())
        print(f"Client subscribed: {session.session_id}")

    async def unsubscribe_client(self, session):
        """Unsubscribe client"""
        self.subscribers.discard(session)

        response = {
            "type": "unsubscribed",
            "timestamp": time.time()
        }

        await session.datagrams.send(json.dumps(response).encode())
        print(f"Client unsubscribed: {session.session_id}")

    async def send_status(self, session):
        """Send server status"""
        status = {
            "type": "status",
            "subscribers": len(self.subscribers),
            "streaming": self.streaming,
            "timestamp": time.time()
        }

        await session.datagrams.send(json.dumps(status).encode())

    async def start_data_streaming(self):
        """Start background data streaming"""
        self.streaming = True

        while self.streaming:
            try:
                # Generate sample data
                data = {
                    "type": "data",
                    "timestamp": time.time(),
                    "values": [random.uniform(0, 100) for _ in range(10)],
                    "sequence": int(time.time() * 1000) % 1000000
                }

                # Broadcast to all subscribers
                await self.broadcast_data(data)

                # Stream at 10Hz
                await asyncio.sleep(0.1)

            except Exception as e:
                print(f"Streaming error: {e}")
                await asyncio.sleep(1)

    async def broadcast_data(self, data: dict):
        """Broadcast data to all subscribers"""
        if not self.subscribers:
            return

        message = json.dumps(data).encode()
        disconnected = []

        for session in self.subscribers.copy():
            try:
                # Use datagrams for low-latency streaming
                await session.datagrams.send(message)
            except Exception as e:
                print(f"Failed to send to {session.session_id}: {e}")
                disconnected.append(session)

        # Remove disconnected sessions
        for session in disconnected:
            self.subscribers.discard(session)

async def main():
    streaming_server = StreamingServer()
    server = pywebtransport.WebTransportServer()

    # Start streaming in background
    streaming_task = asyncio.create_task(streaming_server.start_data_streaming())

    try:
        await server.listen("localhost", 4433, streaming_server.handle_session)
        print("Streaming server started on https://localhost:4433")
        await server.serve_forever()
    except KeyboardInterrupt:
        print("Server stopped")
        streaming_server.streaming = False
    finally:
        streaming_task.cancel()
        await server.close()

if __name__ == "__main__":
    asyncio.run(main())
```

## Production Environment Examples

### Microservice with Database Integration

**Use Case**: Production microservice with database integration and comprehensive monitoring.

```python
# microservice_server.py
import asyncio
import json
import time
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
import pywebtransport

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class User:
    id: int
    username: str
    email: str
    created_at: float

class DatabaseService:
    """Mock database service"""

    def __init__(self):
        self.users = {}
        self.next_id = 1

    async def create_user(self, username: str, email: str) -> User:
        """Create new user"""
        user = User(
            id=self.next_id,
            username=username,
            email=email,
            created_at=time.time()
        )
        self.users[user.id] = user
        self.next_id += 1

        # Simulate database delay
        await asyncio.sleep(0.01)
        return user

    async def get_user(self, user_id: int) -> Optional[User]:
        """Get user by ID"""
        await asyncio.sleep(0.005)  # Simulate DB query
        return self.users.get(user_id)

    async def list_users(self, limit: int = 100) -> list[User]:
        """List users"""
        await asyncio.sleep(0.01)
        return list(self.users.values())[:limit]

    async def update_user(self, user_id: int, updates: dict) -> Optional[User]:
        """Update user"""
        user = self.users.get(user_id)
        if not user:
            return None

        for key, value in updates.items():
            if hasattr(user, key):
                setattr(user, key, value)

        await asyncio.sleep(0.01)
        return user

    async def delete_user(self, user_id: int) -> bool:
        """Delete user"""
        if user_id in self.users:
            del self.users[user_id]
            await asyncio.sleep(0.01)
            return True
        return False

class UserMicroservice:
    """User management microservice"""

    def __init__(self):
        self.db = DatabaseService()
        self.request_count = 0
        self.error_count = 0
        self.start_time = time.time()

    async def handle_session(self, session):
        """Handle microservice session"""
        logger.info(f"New session: {session.session_id} from {session.connection.remote_address}")

        try:
            async for stream in session.incoming_bidirectional_streams():
                asyncio.create_task(self.handle_request(stream))
        except Exception as e:
            logger.error(f"Session error: {e}")

    async def handle_request(self, stream):
        """Handle individual API request"""
        start_time = time.time()
        self.request_count += 1

        try:
            # Read request
            request_data = await stream.read()
            request = json.loads(request_data.decode())

            # Route request
            response = await self.route_request(request)

            # Send response
            response_data = json.dumps(response).encode()
            await stream.write(response_data)

            # Log request
            duration = time.time() - start_time
            logger.info(f"Request completed: {request.get('method')} {request.get('path')} - {duration:.3f}s")

        except json.JSONDecodeError:
            await self.send_error_response(stream, 400, "Invalid JSON")
            self.error_count += 1
        except Exception as e:
            logger.error(f"Request error: {e}")
            await self.send_error_response(stream, 500, "Internal server error")
            self.error_count += 1
        finally:
            await stream.close()

    async def route_request(self, request: dict) -> dict:
        """Route API request to handler"""
        method = request.get("method", "GET")
        path = request.get("path", "/")
        data = request.get("data", {})

        try:
            if method == "POST" and path == "/users":
                return await self.create_user(data)
            elif method == "GET" and path.startswith("/users/"):
                user_id = int(path.split("/")[-1])
                return await self.get_user(user_id)
            elif method == "GET" and path == "/users":
                return await self.list_users(data.get("limit", 100))
            elif method == "PUT" and path.startswith("/users/"):
                user_id = int(path.split("/")[-1])
                return await self.update_user(user_id, data)
            elif method == "DELETE" and path.startswith("/users/"):
                user_id = int(path.split("/")[-1])
                return await self.delete_user(user_id)
            elif method == "GET" and path == "/health":
                return await self.health_check()
            elif method == "GET" and path == "/metrics":
                return await self.get_metrics()
            else:
                return {"error": "Not found", "status": 404}

        except ValueError:
            return {"error": "Invalid user ID", "status": 400}
        except Exception as e:
            logger.error(f"Handler error: {e}")
            return {"error": "Internal server error", "status": 500}

    async def create_user(self, data: dict) -> dict:
        """Create user endpoint"""
        username = data.get("username")
        email = data.get("email")

        if not username or not email:
            return {"error": "Username and email required", "status": 400}

        user = await self.db.create_user(username, email)
        return {"user": asdict(user), "status": 201}

    async def get_user(self, user_id: int) -> dict:
        """Get user endpoint"""
        user = await self.db.get_user(user_id)

        if not user:
            return {"error": "User not found", "status": 404}

        return {"user": asdict(user), "status": 200}

    async def list_users(self, limit: int) -> dict:
        """List users endpoint"""
        users = await self.db.list_users(limit)
        return {
            "users": [asdict(user) for user in users],
            "count": len(users),
            "status": 200
        }

    async def update_user(self, user_id: int, data: dict) -> dict:
        """Update user endpoint"""
        user = await self.db.update_user(user_id, data)

        if not user:
            return {"error": "User not found", "status": 404}

        return {"user": asdict(user), "status": 200}

    async def delete_user(self, user_id: int) -> dict:
        """Delete user endpoint"""
        success = await self.db.delete_user(user_id)

        if not success:
            return {"error": "User not found", "status": 404}

        return {"message": "User deleted", "status": 200}

    async def health_check(self) -> dict:
        """Health check endpoint"""
        uptime = time.time() - self.start_time

        return {
            "status": "healthy",
            "uptime": uptime,
            "requests_processed": self.request_count,
            "error_count": self.error_count,
            "timestamp": time.time()
        }

    async def get_metrics(self) -> dict:
        """Metrics endpoint"""
        uptime = time.time() - self.start_time
        error_rate = self.error_count / max(1, self.request_count)

        return {
            "uptime": uptime,
            "requests_total": self.request_count,
            "errors_total": self.error_count,
            "error_rate": error_rate,
            "requests_per_second": self.request_count / max(1, uptime),
            "timestamp": time.time()
        }

    async def send_error_response(self, stream, status: int, message: str):
        """Send error response"""
        response = {"error": message, "status": status}
        response_data = json.dumps(response).encode()
        await stream.write(response_data)

# Production deployment with monitoring
async def production_main():
    """Production deployment with comprehensive setup"""

    # Configure production server
    config = pywebtransport.create_production_server_config(
        host="0.0.0.0",
        port=4433,
        certfile="server.crt",
        keyfile="server.key"
    )

    # Create microservice
    microservice = UserMicroservice()

    # Create server app with middleware
    app = pywebtransport.ServerApp(config)

    # Add middleware
    @app.middleware
    async def logging_middleware(session):
        """Log all requests"""
        logger.info(f"Session from {session.connection.remote_address}")
        return True

    @app.middleware
    async def auth_middleware(session):
        """Simple authentication check"""
        auth_header = session.headers.get("authorization")
        if not auth_header:
            logger.warning("Missing authorization header")
            # For demo, allow unauthenticated requests
        return True

    # Rate limiting
    rate_limiter = pywebtransport.create_rate_limit_middleware(
        max_requests=1000,
        window_seconds=60
    )
    app.add_middleware(rate_limiter)

    # Set session handler
    await app.listen("0.0.0.0", 4433)
    app._server.set_session_handler(microservice.handle_session)

    # Start server
    try:
        logger.info("Microservice started on https://0.0.0.0:4433")
        await app.serve_forever()
    except KeyboardInterrupt:
        logger.info("Microservice shutting down")
    finally:
        await app.close()

if __name__ == "__main__":
    asyncio.run(production_main())
```

**Client for Microservice**:

```python
# microservice_client.py
import asyncio
import json
import pywebtransport

class UserServiceClient:
    """Client for user microservice"""

    def __init__(self, server_url: str):
        self.server_url = server_url
        self.session = None

    async def connect(self):
        """Connect to microservice"""
        client = pywebtransport.WebTransportClient()
        self.session = await client.connect(self.server_url)
        await self.session.ready()

    async def request(self, method: str, path: str, data: dict = None) -> dict:
        """Make API request"""
        request = {
            "method": method,
            "path": path,
            "data": data or {}
        }

        stream = await self.session.create_bidirectional_stream()

        try:
            # Send request
            request_data = json.dumps(request).encode()
            await stream.write(request_data)

            # Read response
            response_data = await stream.read()
            return json.loads(response_data.decode())

        finally:
            await stream.close()

    async def create_user(self, username: str, email: str) -> dict:
        """Create new user"""
        return await self.request("POST", "/users", {
            "username": username,
            "email": email
        })

    async def get_user(self, user_id: int) -> dict:
        """Get user by ID"""
        return await self.request("GET", f"/users/{user_id}")

    async def list_users(self, limit: int = 100) -> dict:
        """List users"""
        return await self.request("GET", "/users", {"limit": limit})

    async def update_user(self, user_id: int, updates: dict) -> dict:
        """Update user"""
        return await self.request("PUT", f"/users/{user_id}", updates)

    async def delete_user(self, user_id: int) -> dict:
        """Delete user"""
        return await self.request("DELETE", f"/users/{user_id}")

    async def health_check(self) -> dict:
        """Check service health"""
        return await self.request("GET", "/health")

    async def get_metrics(self) -> dict:
        """Get service metrics"""
        return await self.request("GET", "/metrics")

# Example usage
async def demo_microservice():
    """Demonstrate microservice usage"""
    client = UserServiceClient("https://localhost:4433/")

    try:
        await client.connect()
        print("Connected to microservice")

        # Health check
        health = await client.health_check()
        print(f"Health: {health}")

        # Create users
        user1 = await client.create_user("alice", "alice@example.com")
        user2 = await client.create_user("bob", "bob@example.com")
        print(f"Created users: {user1}, {user2}")

        # List users
        users = await client.list_users()
        print(f"Users: {users}")

        # Update user
        if user1.get("user"):
            updated = await client.update_user(user1["user"]["id"], {"email": "alice.new@example.com"})
            print(f"Updated user: {updated}")

        # Get metrics
        metrics = await client.get_metrics()
        print(f"Metrics: {metrics}")

    finally:
        if client.session:
            await client.session.close()

if __name__ == "__main__":
    asyncio.run(demo_microservice())
```

## Tools and Debugging

### Connection Diagnostics Tool

**Use Case**: Debugging connection issues and performance problems.

````python
# diagnostic_tool.py
import asyncio
import time
import json
from typing import Dict, Any
import pywebtransport

class WebTransportDiagnostics:
    """Comprehensive diagnostics tool for WebTransport"""

    def __init__(self, target_url: str):
        self.target_url = target_url
        self.results = {}

    async def run_full_diagnostics(self) -> Dict[str, Any]:
        """Run complete diagnostic suite"""
        print(f"Running diagnostics for {self.target_url}")

        # Test basic connectivity
        await self.test_connectivity()

        # Test connection performance
        await self.test_connection_performance()

        # Test datagram functionality
        await self.test_datagram_performance()

        # Test stream functionality
        await self.test_stream_performance()

        # Test error handling
        await self.test_error_scenarios()

        return self.results

    async def test_connectivity(self):
        """Test basic connectivity"""
        print("Testing connectivity...")

        try:
            result = await pywebtransport.test_client_connectivity(
                self# Examples Guide

Complete collection of practical PyWebTransport examples, from basic patterns to production-ready applications. Each example provides a complete, runnable implementation with detailed explanations.

## Basic Communication Examples

### Simple Echo Server and Client

**Use Case**: Foundation for understanding WebTransport communication patterns.

**Server Implementation**:
```python
# server_echo.py
import asyncio
import pywebtransport

async def echo_handler(session):
    """Handle echo requests for both streams and datagrams"""
    print(f"New session: {session.session_id}")

    # Handle datagrams
    datagram_task = asyncio.create_task(handle_datagrams(session))

    # Handle incoming streams
    stream_task = asyncio.create_task(handle_streams(session))

    # Wait for either task to complete
    await asyncio.gather(datagram_task, stream_task, return_exceptions=True)

async def handle_datagrams(session):
    """Echo datagram messages"""
    try:
        async for datagram in session.datagrams.receive_iter():
            echo_response = b"Echo: " + datagram
            await session.datagrams.send(echo_response)
    except Exception as e:
        print(f"Datagram error: {e}")

async def handle_streams(session):
    """Echo stream data"""
    try:
        async for stream in session.incoming_bidirectional_streams():
            asyncio.create_task(echo_stream(stream))
    except Exception as e:
        print(f"Stream error: {e}")

async def echo_stream(stream):
    """Echo data from a single stream"""
    try:
        async for data in stream.read_iter():
            if data:
                await stream.write(b"Echo: " + data)
    finally:
        await stream.close()

async def main():
    server = pywebtransport.WebTransportServer()

    try:
        await server.listen("localhost", 4433, echo_handler)
        print("Echo server started on https://localhost:4433")
        await server.serve_forever()
    except KeyboardInterrupt:
        print("Server stopped")
    finally:
        await server.close()

if __name__ == "__main__":
    asyncio.run(main())
````

**Client Implementation**:

```python
# client_echo.py
import asyncio
import pywebtransport

async def test_echo_client():
    """Test client for echo server"""
    client = pywebtransport.WebTransportClient()

    try:
        # Connect to server
        session = await client.connect("https://localhost:4433/")
        await session.ready()
        print(f"Connected with session: {session.session_id}")

        # Test datagram echo
        await test_datagram_echo(session)

        # Test stream echo
        await test_stream_echo(session)

    finally:
        await session.close()
        await client.close()

async def test_datagram_echo(session):
    """Test datagram echo functionality"""
    print("\n--- Testing Datagram Echo ---")

    # Send test messages
    test_messages = [b"Hello", b"World", b"WebTransport"]

    for message in test_messages:
        await session.datagrams.send(message)
        response = await session.datagrams.receive(timeout=5.0)
        print(f"Sent: {message} | Received: {response}")

async def test_stream_echo(session):
    """Test stream echo functionality"""
    print("\n--- Testing Stream Echo ---")

    stream = await session.create_bidirectional_stream()

    try:
        # Send test data
        test_data = b"Stream test message"
        await stream.write(test_data)

        # Read echo response
        response = await stream.read()
        print(f"Sent: {test_data} | Received: {response}")

    finally:
        await stream.close()

if __name__ == "__main__":
    asyncio.run(test_echo_client())
```

**Key Points**:

- Demonstrates both datagram and stream communication
- Shows proper session and resource management
- Provides foundation for more complex applications

### HTTP-like Request/Response Pattern

**Use Case**: Building request/response protocols over WebTransport.

```python
# http_like_server.py
import asyncio
import json
import pywebtransport
from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class Request:
    method: str
    path: str
    headers: Dict[str, str]
    body: bytes

@dataclass
class Response:
    status: int
    headers: Dict[str, str]
    body: bytes

class HTTPLikeServer:
    """HTTP-like server using WebTransport streams"""

    def __init__(self):
        self.routes = {}

    def route(self, path: str, method: str = "GET"):
        """Route decorator"""
        def decorator(handler):
            self.routes[(method, path)] = handler
            return handler
        return decorator

    async def handle_session(self, session):
        """Handle incoming session"""
        async for stream in session.incoming_bidirectional_streams():
            asyncio.create_task(self.handle_request(stream))

    async def handle_request(self, stream):
        """Handle a single request stream"""
        try:
            # Parse request
            request_data = await stream.read()
            request = self.parse_request(request_data)

            # Route to handler
            handler = self.routes.get((request.method, request.path))
            if handler:
                response = await handler(request)
            else:
                response = Response(404, {}, b"Not Found")

            # Send response
            response_data = self.serialize_response(response)
            await stream.write(response_data)

        except Exception as e:
            error_response = Response(500, {}, f"Server Error: {e}".encode())
            response_data = self.serialize_response(error_response)
            await stream.write(response_data)
        finally:
            await stream.close()

    def parse_request(self, data: bytes) -> Request:
        """Parse request from bytes"""
        lines = data.decode().split('\n')
        method, path = lines[0].split(' ', 1)

        headers = {}
        body_start = 1

        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "":
                body_start = i + 1
                break
            if ':' in line:
                key, value = line.split(':', 1)
                headers[key.strip()] = value.strip()

        body = '\n'.join(lines[body_start:]).encode()
        return Request(method, path, headers, body)

    def serialize_response(self, response: Response) -> bytes:
        """Serialize response to bytes"""
        lines = [f"HTTP/1.1 {response.status}"]

        for key, value in response.headers.items():
            lines.append(f"{key}: {value}")

        lines.append("")  # Empty line before body

        result = '\n'.join(lines).encode() + response.body
        return result

# Usage example
async def main():
    server_app = HTTPLikeServer()

    @server_app.route("/", "GET")
    async def home(request: Request) -> Response:
        return Response(200, {"Content-Type": "text/plain"}, b"Hello WebTransport!")

    @server_app.route("/api/data", "POST")
    async def api_data(request: Request) -> Response:
        # Echo the received data
        response_body = json.dumps({
            "received": len(request.body),
            "echo": request.body.decode()
        }).encode()

        return Response(200, {"Content-Type": "application/json"}, response_body)

    # Start server
    server = pywebtransport.WebTransportServer()
    await server.listen("localhost", 4433, server_app.handle_session)

    print("HTTP-like server started on https://localhost:4433")
    await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
```

## Common Application Patterns

### Real-time Chat Application

**Use Case**: Multi-user chat with real-time message delivery using datagrams.

**Server Implementation**:

```python
# chat_server.py
import asyncio
import json
import time
from typing import Dict, Set
import pywebtransport

class ChatServer:
    """Real-time chat server using WebTransport datagrams"""

    def __init__(self):
        self.rooms: Dict[str, Set[object]] = {}  # room_id -> set of sessions
        self.users: Dict[object, str] = {}  # session -> username

    async def handle_session(self, session):
        """Handle new chat session"""
        print(f"New chat session: {session.session_id}")

        try:
            async for message_data in session.datagrams.receive_iter():
                await self.handle_message(session, message_data)
        except Exception as e:
            print(f"Session error: {e}")
        finally:
            await self.leave_all_rooms(session)

    async def handle_message(self, session, data: bytes):
        """Handle incoming chat message"""
        try:
            message = json.loads(data.decode())
            message_type = message.get("type")

            if message_type == "join":
                await self.handle_join(session, message)
            elif message_type == "leave":
                await self.handle_leave(session, message)
            elif message_type == "chat":
                await self.handle_chat(session, message)
            elif message_type == "ping":
                await self.handle_ping(session)
            else:
                await self.send_error(session, "Unknown message type")

        except json.JSONDecodeError:
            await self.send_error(session, "Invalid JSON")
        except Exception as e:
            await self.send_error(session, f"Error: {e}")

    async def handle_join(self, session, message):
        """Handle user joining a room"""
        room_id = message.get("room")
        username = message.get("username")

        if not room_id or not username:
            await self.send_error(session, "Room and username required")
            return

        # Add to room
        if room_id not in self.rooms:
            self.rooms[room_id] = set()

        self.rooms[room_id].add(session)
        self.users[session] = username

        # Notify room
        join_message = {
            "type": "user_joined",
            "room": room_id,
            "username": username,
            "timestamp": time.time()
        }

        await self.broadcast_to_room(room_id, join_message)

        # Send confirmation
        await self.send_message(session, {
            "type": "joined",
            "room": room_id,
            "users": [self.users[s] for s in self.rooms[room_id]]
        })

    async def handle_leave(self, session, message):
        """Handle user leaving a room"""
        room_id = message.get("room")
        await self.leave_room(session, room_id)

    async def handle_chat(self, session, message):
        """Handle chat message"""
        room_id = message.get("room")
        text = message.get("text")

        if session not in self.users:
            await self.send_error(session, "Not logged in")
            return

        if room_id not in self.rooms or session not in self.rooms[room_id]:
            await self.send_error(session, "Not in room")
            return

        # Broadcast message
        chat_message = {
            "type": "message",
            "room": room_id,
            "username": self.users[session],
            "text": text,
            "timestamp": time.time()
        }

        await self.broadcast_to_room(room_id, chat_message)

    async def handle_ping(self, session):
        """Handle ping for keepalive"""
        await self.send_message(session, {"type": "pong", "timestamp": time.time()})

    async def broadcast_to_room(self, room_id: str, message: dict):
        """Broadcast message to all users in room"""
        if room_id not in self.rooms:
            return

        message_data = json.dumps(message).encode()

        # Send to all sessions in room
        disconnected_sessions = []
        for session in self.rooms[room_id]:
            try:
                await session.datagrams.send(message_data)
            except Exception:
                disconnected_sessions.append(session)

        # Clean up disconnected sessions
        for session in disconnected_sessions:
            await self.leave_all_rooms(session)

    async def leave_room(self, session, room_id: str):
        """Remove user from specific room"""
        if room_id in self.rooms and session in self.rooms[room_id]:
            self.rooms[room_id].remove(session)

            if session in self.users:
                # Notify room about user leaving
                leave_message = {
                    "type": "user_left",
                    "room": room_id,
                    "username": self.users[session],
                    "timestamp": time.time()
                }
                await self.broadcast_to_room(room_id, leave_message)

            # Clean up empty rooms
            if not self.rooms[room_id]:
                del self.rooms[room_id]

    async def leave_all_rooms(self, session):
        """Remove user from all rooms"""
        rooms_to_leave = []
        for room_id, sessions in self.rooms.items():
            if session in sessions:
                rooms_to_leave.append(room_id)

        for room_id in rooms_to_leave:
            await self.leave_room(session, room_id)

        # Remove from users
        if session in self.users:
            del self.users[session]

    async def send_message(self, session, message: dict):
        """Send message to specific session"""
        try:
            data = json.dumps(message).encode()
            await session.datagrams.send(data)
        except Exception as e:
            print(f"Failed to send message: {e}")

    async def send_error(self, session, error: str):
        """Send error message"""
        await self.send_message(session, {"type": "error", "message": error})

async def main():
    chat_server = ChatServer()
    server = pywebtransport.WebTransportServer()

    try:
        await server.listen("localhost", 4433, chat_server.handle_session)
        print("Chat server started on https://localhost:4433")
        await server.serve_forever()
    except KeyboardInterrupt:
        print("Chat server stopped")
    finally:
        await server.close()

if __name__ == "__main__":
    asyncio.run(main())
```

**Client Implementation**:

```python
# chat_client.py
import asyncio
import json
import pywebtransport

class ChatClient:
    """Chat client implementation"""

    def __init__(self):
        self.session = None
        self.username = None
        self.current_room = None

    async def connect(self, server_url: str):
        """Connect to chat server"""
        client = pywebtransport.WebTransportClient()
        self.session = await client.connect(server_url)
        await self.session.ready()

        # Start message listener
        asyncio.create_task(self.message_listener())

    async def message_listener(self):
        """Listen for incoming messages"""
        try:
            async for data in self.session.datagrams.receive_iter():
                message = json.loads(data.decode())
                await self.handle_message(message)
        except Exception as e:
            print(f"Message listener error: {e}")

    async def handle_message(self, message: dict):
        """Handle incoming message"""
        msg_type = message.get("type")

        if msg_type == "message":
            print(f"[{message['room']}] {message['username']}: {message['text']}")
        elif msg_type == "user_joined":
            print(f"* {message['username']} joined {message['room']}")
        elif msg_type == "user_left":
            print(f"* {message['username']} left {message['room']}")
        elif msg_type == "joined":
            print(f"Joined room {message['room']}")
            print(f"Users: {', '.join(message['users'])}")
        elif msg_type == "error":
            print(f"Error: {message['message']}")
        elif msg_type == "pong":
            pass  # Keepalive response

    async def join_room(self, room: str, username: str):
        """Join a chat room"""
        self.username = username
        self.current_room = room

        message = {
            "type": "join",
            "room": room,
            "username": username
        }

        await self.send_message(message)

    async def send_chat(self, text: str):
        """Send chat message"""
        if not self.current_room:
            print("Not in a room")
            return

        message = {
            "type": "chat",
            "room": self.current_room,
            "text": text
        }

        await self.send_message(message)

    async def leave_room(self):
        """Leave current room"""
        if not self.current_room:
            return

        message = {
            "type": "leave",
            "room": self.current_room
        }

        await self.send_message(message)
        self.current_room = None

    async def send_message(self, message: dict):
        """Send message to server"""
        data = json.dumps(message).encode()
        await self.session.datagrams.send(data)

# Interactive client
async def interactive_client():
    """Interactive chat client"""
    client = ChatClient()

    try:
        await client.connect("https://localhost:4433/")
        print("Connected to chat server!")

        # Get user info
        username = input("Enter username: ")
        room = input("Enter room name: ")

        await client.join_room(room, username)

        print(f"Joined room '{room}' as '{username}'")
        print("Type 'quit' to exit, 'leave' to leave room")

        # Chat loop
        while True:
            try:
                text = await asyncio.to_thread(input, "> ")

                if text.lower() == 'quit':
                    break
                elif text.lower() == 'leave':
                    await client.leave_room()
                    print("Left room")
                elif text.strip():
                    await client.send_chat(text)

            except (EOFError, KeyboardInterrupt):
                break

    except Exception as e:
        print(f"Client error: {e}")
    finally:
        if client.session:
            await client.session.close()

if __name__ == "__main__":
    asyncio.run(interactive_client())
```

**Key Points**:

- Uses datagrams for low-latency real-time messaging
- Implements room-based chat with user management
- Handles connection cleanup and error recovery
- Provides both server and client implementations

### File Transfer Application

**Use Case**: Reliable file transfer using WebTransport streams.

```python
# file_transfer_server.py
import asyncio
import os
import json
import hashlib
from pathlib import Path
import pywebtransport

class FileTransferServer:
    """File transfer server using WebTransport streams"""

    def __init__(self, upload_dir: str = "./uploads", download_dir: str = "./files"):
        self.upload_dir = Path(upload_dir)
        self.download_dir = Path(download_dir)

        # Create directories
        self.upload_dir.mkdir(exist_ok=True)
        self.download_dir.mkdir(exist_ok=True)

    async def handle_session(self, session):
        """Handle file transfer session"""
        print(f"New file transfer session: {session.session_id}")

        try:
            async for stream in session.incoming_bidirectional_streams():
                asyncio.create_task(self.handle_stream(stream))
        except Exception as e:
            print(f"Session error: {e}")

    async def handle_stream(self, stream):
        """Handle individual file transfer stream"""
        try:
            # Read request header
            header_data = await self.read_length_prefixed(stream)
            request = json.loads(header_data.decode())

            operation = request.get("operation")

            if operation == "upload":
                await self.handle_upload(stream, request)
            elif operation == "download":
                await self.handle_download(stream, request)
            elif operation == "list":
                await self.handle_list(stream)
            else:
                await self.send_error(stream, "Unknown operation")

        except Exception as e:
            print(f"Stream error: {e}")
            await self.send_error(stream, f"Error: {e}")
        finally:
            await stream.close()

    async def handle_upload(self, stream, request):
        """Handle file upload"""
        filename = request.get("filename")
        file_size = request.get("size")
        checksum = request.get("checksum")

        if not filename or file_size is None:
            await self.send_error(stream, "Missing filename or size")
            return

        file_path = self.upload_dir / filename

        # Receive file data
        print(f"Uploading {filename} ({file_size} bytes)")

        hasher = hashlib.sha256()
        bytes_received = 0

        with open(file_path, 'wb') as f:
            while bytes_received < file_size:
                chunk = await stream.read(8192)  # 8KB chunks
                if not chunk:
                    break

                f.write(chunk)
                hasher.update(chunk)
                bytes_received += len(chunk)

                # Send progress
                progress = {
                    "type": "progress",
                    "bytes_received": bytes_received,
                    "total_bytes": file_size
                }
                await self.send_response(stream, progress)

        # Verify checksum
        calculated_checksum = hasher.hexdigest()
        if checksum and calculated_checksum != checksum:
            file_path.unlink()  # Delete corrupted file
            await self.send_error(stream, "Checksum mismatch")
            return

        # Send success response
        response = {
            "type": "upload_complete",
            "filename": filename,
            "bytes_received": bytes_received,
            "checksum": calculated_checksum
        }
        await self.send_response(stream, response)
        print(f"Upload complete: {filename}")

    async def handle_download(self, stream, request):
        """Handle file download"""
        filename = request.get("filename")

        if not filename:
            await self.send_error(stream, "Missing filename")
            return

        file_path = self.download_dir / filename

        if not file_path.exists():
            await self.send_error(stream, "File not found")
            return

        file_size = file_path.stat().st_size

        # Calculate checksum
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                hasher.update(chunk)

        # Send file info
        file_info = {
            "type": "file_info",
            "filename": filename,
            "size": file_size,
            "checksum": hasher.hexdigest()
        }
        await self.send_response(stream, file_info)

        # Send file data
        print(f"Downloading {filename} ({file_size} bytes)")

        bytes_sent = 0
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                await stream.write(chunk)
                bytes_sent += len(chunk)

                # Send progress
                progress = {
                    "type": "progress",
                    "bytes_sent": bytes_sent,
                    "total_bytes": file_size
                }
                await self.send_response(stream, progress)

        print(f"Download complete: {filename}")

    async def handle_list(self, stream):
        """Handle file list request"""
        files = []

        for file_path in self.download_dir.iterdir():
            if file_path.is_file():
                files.append({
                    "name": file_path.name,
                    "size": file_path.stat().st_size,
                    "modified": file_path.stat().st_mtime
                })

        response = {
            "type": "file_list",
            "files": files
        }
        await self.send_response(stream, response)

    async def send_response(self, stream, response: dict):
        """Send JSON response with length prefix"""
        data = json.dumps(response).encode()
        await self.send_length_prefixed(stream, data)

    async def send_error(self, stream, error: str):
        """Send error response"""
        response = {"type": "error", "message": error}
        await self.send_response(stream, response)

    async def send_length_prefixed(self, stream, data: bytes):
        """Send data with length prefix"""
        length = len(data)
        length_bytes = length.to_bytes(4, 'big')
        await stream.write(length_bytes + data)

    async def read_length_prefixed(self, stream) -> bytes:
        """Read data with length prefix"""
        length_bytes = await stream.read(4)
        if len(length_bytes) != 4:
            raise ValueError("Invalid length prefix")

        length = int.from_bytes(length_bytes, 'big')
        data = await stream.read(length)

        if len(data) != length:
            raise ValueError("Incomplete data")

        return data

async def main():
    transfer_server = FileTransferServer()
    server = pywebtransport.WebTransportServer()

    try:
        await server.listen("localhost", 4433, transfer_server.handle_session)
        print("File transfer server started on https://localhost:4433")
        await server.serve_forever()
    except KeyboardInterrupt:
        print("Server stopped")
    finally:
        await server.close()

if __name__ == "__main__":
    asyncio.run(main())
```

**Client Implementation**:

```python
# file_transfer_client.py
import asyncio
import json
import hashlib
from pathlib import Path
import pywebtransport

class FileTransferClient:
    """File transfer client"""

    def __init__(self):
        self.session = None

    async def connect(self, server_url: str):
        """Connect to file transfer server"""
        client = pywebtransport.WebTransportClient()
        self.session = await client.connect(server_url)
        await self.session.ready()

    async def upload_file(self, file_path: Path) -> bool:
        """Upload file to server"""
        if not file_path.exists():
            print(f"File not found: {file_path}")
            return False

        file_size = file_path.stat().st_size

        # Calculate checksum
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        checksum = hasher.hexdigest()

        stream = await self.session.create_bidirectional_stream()

        try:
            # Send upload request
            request = {
                "operation": "upload",
                "filename": file_path.name,
                "size": file_size,
                "checksum": checksum
            }

            await self.send_length_prefixed(stream, json.dumps(request).encode())

            # Send file data
            print(f"Uploading {file_path.name} ({file_size} bytes)")

            bytes_sent = 0
            with open(file_path, 'rb') as f:
                while chunk := f.read(8192):
                    await stream.write(chunk)
                    bytes_sent += len(chunk)

                    # Read progress updates
                    try:
                        response_data = await self.read_length_prefixed(stream)
                        response = json.loads(response_data.decode())

                        if response.get("type") == "progress":
                            progress = response["bytes_received"] / file_size * 100
                            print(f"Progress: {progress:.1f}%")
                    except:
                        pass  # Continue sending

            # Read final response
            response_data = await self.read_length_prefixed(stream)
            response = json.loads(response_data.decode())

            if response.get("type") == "upload_complete":
                print(f"Upload successful: {file_path.name}")
                return True
            else:
                print(f"Upload failed: {response.get('message', 'Unknown error')}")
                return False

        finally:
            await stream.close()

    async def download_file(self, filename: str, save_path: Path) -> bool:
        """Download file from server"""
        stream = await self.session.create_bidirectional_stream()

        try:
            # Send download request
            request = {
                "operation": "download",
                "filename": filename
            }

            await self.send_length_prefixed(stream, json.dumps(request).encode())

            # Read file info
            response_data = await self.read_length_prefixed(stream)
            response = json.loads(response_data.decode())

            if response.get("type") == "error":
                print(f"Download failed: {response['message']}")
                return False

            if response.get("type") != "file_info":
                print("Unexpected response")
                return False

            file_size = response["size"]
            expected_checksum = response["checksum"]
```

## Next Steps

- **[Client Guide](client.md)** - Client development patterns
- **[Server Guide](server.md)** - Server development patterns
- **[API Reference](../api-reference/)** - Complete API documentation
- **[Configuration API](../api-reference/config.md)** - Configuration options and builders
