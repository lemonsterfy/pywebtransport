# Performance Benchmarks

This document defines the performance characteristics of the `PyWebTransport` library. The benchmarks quantify the implementation overhead of the protocol stack—covering connection establishment, stream multiplexing, and datagram processing—isolated from physical network latency constraints.

## 1. Test Environment

The test configuration detailed below serves as the reference environment for all measurements presented in this document.

| Component            | Specification                             |
| :------------------- | :---------------------------------------- |
| **Library Version**  | `PyWebTransport v0.9.0` (Ref: `HEAD`)     |
| **Python Runtime**   | CPython 3.12.12                           |
| **Event Loop**       | `uvloop` v0.22.1+                         |
| **Cryptography**     | OpenSSL 3.0.17                            |
| **Test Suite**       | `pytest-benchmark`                        |
| **OS / Kernel**      | Debian 12.12 / Linux 6.1.0-41-amd64       |
| **CPU Architecture** | Intel(R) Xeon(R) CPU E5-2680 v4 @ 2.40GHz |
| **CPU Scaling**      | Single-threaded (GIL-bound)               |
| **vCPU Allocation**  | 4 Cores                                   |
| **Memory**           | 8 GB                                      |
| **Hypervisor**       | VMware ESXi 7.0 Update 3                  |

## 2. Methodology

The following methodologies are enforced to ensure result reproducibility and statistical significance:

- **Event Loop Policy**: `uvloop` is mandated for all test cases.
- **Garbage Collection**: Measurements incorporate Python garbage collection overhead to reflect production runtime characteristics.
- **Process Isolation**: All test cases are executed in isolated processes, restarted between runs to ensure deterministic memory states.
- **Warm-up Phase**: A warm-up cycle precedes all measurements to stabilize branch prediction and internal caching effects.
- **Measurement Metrics**:
  - **Latency**: Metrics include Minimum, Median (p50), and Maximum values to accurately quantify network jitter and tail latency characteristics.
  - **Throughput**: Reported as the mean sustained data transfer rate.
  - **Overhead**: Application logging is disabled (`CRITICAL` level) to eliminate I/O blocking.

## 3. Stream Throughput

This section details the sustained data transfer rate over reliable WebTransport streams, utilizing a 1 MB payload per stream.

| Scenario     | Result (MB/s) |
| :----------- | :------------ |
| **Upload**   | `32.00`       |
| **Download** | `9.62`        |
| **Duplex**   | `12.16`       |

## 4. Latency & RTT

This section measures the Round-Trip Time (RTT) for application-layer interactions under the methodology defined in Section 2.

| Metric                          | Min        | Median (p50) | Max        |
| :------------------------------ | :--------- | :----------- | :--------- |
| **Handshake** (Connect → Ready) | `16.01` ms | `25.02` ms   | `28.86` ms |
| **Request-Response** (64B)      | `28.96` ms | `29.87` ms   | `62.51` ms |
| **Request-Response** (1KB)      | `26.92` ms | `29.57` ms   | `36.71` ms |
| **Datagram RTT**                | `25.53` ms | `27.66` ms   | `29.88` ms |

## 5. Multiplexing Efficiency

This section evaluates connection scalability when handling concurrent flows on a single session.

| Metric                   | Result         | Description                                                                     |
| :----------------------- | :------------- | :------------------------------------------------------------------------------ |
| **Aggregate Throughput** | `24.78` MB/s   | The test manages 1,000 concurrent streams. Each stream carries a 64 KB payload. |
| **Connection Rate**      | `40.92` conn/s | Connections are established and torn down sequentially.                         |

## 6. Datagram Performance

This section measures the packet processing rate for unreliable datagrams (HTTP/3 Datagrams).

| Metric        | Result       | Description                                                          |
| :------------ | :----------- | :------------------------------------------------------------------- |
| **Send Rate** | `13,985` PPS | Tests utilize a 64-byte payload transmitted in a non-blocking burst. |

## 7. Resource Utilization

This section measures the system memory footprint per connection in a steady, idle state.

| Metric                         | Result        |
| :----------------------------- | :------------ |
| **Memory per Idle Connection** | `~ 139.77` KB |
