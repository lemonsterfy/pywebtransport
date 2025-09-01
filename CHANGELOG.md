# Changelog

All notable changes to PyWebTransport will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned for future release

_(No planned changes for the next release yet.)_

## [0.4.1] - 2025-09-01

This is a critical stability and quality release focused on hardening the library for production use. It addresses deep-seated concurrency flaws in all pooling mechanisms, improves the robustness of the core protocol engine, enhances error handling and diagnostics, and continues the systematic modernization of the codebase.

### Added

- **Enhanced Error Diagnostics**: Added several specific H3 and QPACK error codes to the `ErrorCodes` enum, allowing for more granular and precise protocol-level error reporting.
- **Improved Test Coverage**: Significantly increased unit test coverage from 91% to 96%, enhancing the reliability and correctness of the entire library.

### Changed

- **Modernized Codebase Style**: Systematically modernized type hint imports across the entire codebase (including `app`, `events`, `middleware`, `session`, `stream`, `types`, and `utils` modules) by migrating from the `typing` module to `collections.abc` in accordance with Python 3.11+ best practices.

### Fixed

- **Fixed Critical Concurrency Flaws in All Pooling Mechanisms**:
  - Re-architected `client.PooledClient`, `connection.ConnectionPool`, and `stream.StreamPool` to use a robust **`asyncio.Condition`**-based pattern. This resolves fundamental correctness issues, properly enforces resource limits (`pool_size`/`max_size`), and eliminates performance bottlenecks caused by "thundering herd" problems in previous implementations.
- **Improved Robustness of the Core Protocol Engine**:
  - Fixed multiple correctness and robustness issues in the `WebTransportH3Engine`, including correctly handling the non-fatal `pylsqpack.StreamBlocked` signal, improving the logical flow of unidirectional stream parsing, and propagating more specific error codes.
- **Improved Error Handling Consistency and Usability**:
  - Fixed an issue in `ServerCluster` where exceptions during `stop_all` and `get_cluster_stats` were silently ignored; they are now correctly propagated as an `ExceptionGroup`.
  - Changed the string representation of all `WebTransportError` exceptions to display error codes in hexadecimal format for better readability and alignment with protocol specifications.
- **Fixed Silent Failure in `DatagramQueue`**:
  - The `clear()` method on an uninitialized `DatagramQueue` no longer fails silently and now correctly raises a `DatagramError`, ensuring consistent fail-fast behavior across the component's API.

## [0.4.0] - 2025-08-26

This is a major architectural release that marks a significant milestone in the library's maturity. The core of this update is the complete re-architecture of the protocol layer, replacing the generic, `aioquic`-derived H3 component with a specialized, in-house `WebTransportH3Engine`. This change dramatically improves maintainability, reduces complexity, and perfectly aligns the protocol implementation with the specific needs of WebTransport, solidifying the library's foundation as a truly independent and production-grade solution.

**Note on Versioning:** While originally slated as a patch release (`v0.3.2`), the complete re-architecture of the core protocol engine represents a major architectural milestone for the library. To accurately reflect the significance and value of this change, it has been designated as `v0.4.0`.

### Added

- **Exposed `StreamId` and `SessionId` in the Public API**:
  - The `StreamId` and `SessionId` type aliases are now available for direct import from the top-level `pywebtransport` package. This improves the developer experience for users employing type hinting in their applications.
- **Added Comprehensive Unit Tests for the New Protocol Engine**:
  - Implemented a robust and highly-structured test suite for the new `WebTransportH3Engine` and its associated events. The tests utilize extensive mocking and parametrization to ensure correctness, protocol compliance, and resilience against errors.

### Changed

- **Re-architected the Core Protocol Engine**:
  - Replaced the general-purpose `H3Connection` with `WebTransportH3Engine`, a new, purpose-built protocol engine exclusively designed for WebTransport-over-H3. This change removes all unnecessary HTTP/3 features (like Server Push), resulting in a simpler, more efficient, and highly maintainable codebase.
  - Decoupled the protocol layer from underlying `aioquic` types by introducing a dedicated internal event system (`pywebtransport.protocol.events`). The engine now emits library-native, structured events, creating a clean and stable abstraction boundary.
  - Improved internal API ergonomics by transitioning header representation from `list[tuple[bytes, bytes]]` to the more Pythonic `dict[str, str]`, simplifying the logic in the `WebTransportProtocolHandler`.

### Fixed

- **Improved Code Consistency in the Test Suite**:
  - Updated the test suites for `WebTransportProtocolHandler`, `WebTransportStream`, and `StreamManager` to align with the new protocol engine APIs and the newly exposed public types, ensuring the entire codebase follows a consistent and modern approach.

## [0.3.1] - 2025-08-25

This is a landmark release focused on solidifying the library's architecture for production use. It addresses deep-seated concurrency flaws, enhances performance across the entire stack, and systematically modernizes the codebase to align with the latest asynchronous best practices.

### Added

- **Enhanced Testing Capability** by adding the `pytest-repeat` dependency, a powerful tool for identifying and fixing non-deterministic, flaky tests in complex asynchronous code.

### Changed

- **Refined CI/CD and Quality Assurance Infrastructure**:
  - Migrated the test coverage reporting and Codecov upload functionality from GitLab CI to GitHub Actions to consolidate quality checks for community contributions.
- **Modernized Concurrency Model across the Entire Library**:
  - Systematically refactored all concurrent operations (lifecycle management, cleanup, batch processing) in all high-level components to use the more robust **`asyncio.TaskGroup`** (Python 3.11+).
  - Re-architected the `WebTransportSendStream` to use a robust **producer-consumer pattern** with proper locking and events for writing data and handling backpressure.
- **Vastly Improved Concurrency Performance**:
  - Re-architected `ConnectionPool` and `PooledClient` from a single global lock to a highly concurrent **per-key locking mechanism**, eliminating a major performance bottleneck when handling multiple endpoints.
  - Drastically improved the performance of all manager classes (`ConnectionManager`, `SessionManager`, `StreamManager`) by making their periodic cleanup operations **atomic and efficient** with a single-lock strategy.
  - Optimized the `ConnectionLoadBalancer`'s health checks and the `StreamPool`'s filling mechanism by making them **fully concurrent**.
  - Made the `DatagramReliabilityLayer`'s retry mechanism concurrent for faster recovery from packet loss.
- **Modernized Codebase Style**:
  - Upgraded all `Enum` classes to **`StrEnum`** and simplified all dependent code by removing redundant `.value` calls, improving ergonomics.
  - Modernized conditional logic throughout the codebase to use **`match-case`** syntax for improved clarity and readability.
- **Updated Test Suites and Documentation**:
  - Comprehensively updated the entire test suite (unit, integration, E2E) and API documentation to align with the extensive architectural refactoring and ensure full coverage of the new concurrency models and fixed behaviors.

### Fixed

- **Fixed Critical Race Conditions in Core Protocol Handling**:
  - Eliminated a major stability issue in the low-level QUIC event processing loop (for both client and server) by implementing a robust, ordered **`asyncio.Queue`-based pipeline**, which replaced a fragile "fire-and-forget" task creation model. This change ensures strict event ordering, which, after performance evaluation, was proven to be more stable and performant than a parallelized model for this specific workload.
  - Fixed a race condition in the protocol handler's `StreamReset` processing by ensuring it is handled synchronously before other events.
  - Resolved a race condition where data on a new stream could be discarded. The protocol handler now reliably associates new streams by **correctly using the parent session context already provided in H3 protocol events**.
- **Fixed Critical Concurrency Bugs in High-Level Components**:
  - Resolved a severe **"thundering herd"** problem in `ConnectionLoadBalancer`, `ConnectionPool`, and `PooledClient` that caused redundant, wasteful resource creation under concurrent demand.
  - Fixed a critical concurrency flaw in the `DatagramReliabilityLayer` by adding proper `asyncio.Lock` protection for all shared state.
- **Fixed Major Resource and Stability Issues**:
  - Fixed a critical stability issue in `StreamBuffer` by replacing a fragile recursive implementation with a robust iterative one, preventing potential `RecursionError` crashes.
  - Fixed major bugs in the bidirectional `WebTransportStream` implementation that caused resource leaks and incomplete initialization.
  - Fixed a potential resource leak in `ServerCluster` by ensuring server instances are cleaned up correctly if startup fails.

## [0.3.0] - 2025-08-18

This is a major release focused on production-readiness, significantly enhancing the library's robustness, resource management, performance, and configurability.

**Note on Versioning:**
While building the performance test suite for v0.2.2, we discovered a series of deep-seated resource management and robustness defects. As ensuring the library's stability in production environments is paramount, we decided to prioritize addressing these issues over the originally planned functional refactoring and release the fixes as version v0.3.0.

### BREAKING CHANGE

- **The `StreamManager` now fails immediately if the stream limit is reached.** Previously, an attempt to create a stream beyond the configured limit would block indefinitely. It now raises a `StreamError`, making resource exhaustion explicit and allowing applications to handle it gracefully.
- **`WebTransportSession.close()` now closes the underlying `WebTransportConnection` by default.** This provides a more intuitive default behavior. To close only the session without terminating the connection, use `session.close(close_connection=False)`.

### Added

- **Implemented a server-side idle connection timeout.** The server can now be configured to automatically close connections that have been inactive for a specified duration, a critical feature for production environments.
- **Introduced a performance-oriented "fire-and-forget" write mode.** The `WebTransportSendStream.write()` method now accepts a `wait_flush=False` parameter to allow high-throughput applications to buffer data without waiting for network I/O on every call.
- **Added a new `CONNECTION_CLOSED` event** to distinguish graceful connection closures from unexpected losses (`CONNECTION_LOST`), enabling more precise lifecycle management.
- **Added a comprehensive integration test suite** to validate the end-to-end behavior of the client, server, and application framework.
- **Added a new performance test suite** to measure and benchmark key metrics like connection latency, stream throughput, and resource usage.

### Changed

- **Overhauled the resource management architecture to be event-driven.** Managers (`ConnectionManager`, `SessionManager`) now use event listeners and `weakref` to clean up closed resources almost instantaneously, replacing the less efficient polling mechanism and improving responsiveness.
- **Enhanced the entire configuration system.** The `ClientConfig` and `ServerConfig` objects now include a wide range of new, fully validated parameters. This configuration is now correctly propagated from the top-level client/server down to every new session and stream.
- **Refactored background task management.** Responsibility for periodic cleanup and idle checks has been delegated from the main `WebTransportServer` to the specialized `ConnectionManager` and `SessionManager` components, improving architectural separation of concerns.
- **Updated API documentation** for 13 core components to reflect the new features, lifecycle behaviors, and configuration options.

### Fixed

- **Fixed a critical memory leak** in the protocol handler caused by a circular reference between the `WebTransportConnection` and `WebTransportProtocolHandler` objects.
- **Fixed a severe resource leak** in the `StreamManager` where the `asyncio.Semaphore` controlling the stream limit was not released upon shutdown, which could lead to deadlocks.
- **Eliminated "zombie sessions"** by correctly linking the `WebTransportSession` lifecycle to its parent `WebTransportConnection`. Sessions are now automatically cleaned up when the underlying connection is lost or closed.
- **Fixed a bug in the CI/CD pipeline** that caused inaccurate code coverage reporting for parallel test jobs.
- **Fixed bugs in the client and server application layers** where configuration values from `ClientConfig` and `ServerConfig` were not being correctly applied to new connections and sessions.

## [0.2.1] - 2025-08-07

This is a patch release focused on improving the reliability of the protocol handler and the CI/CD pipeline.

### Changed

- **Hardened the CI/CD pipeline** by fixing parallel coverage reporting, resolving Codecov repository detection issues, and ensuring the GitHub sync step is more robust.
- **Refined development dependencies** by removing `pre-commit` from the core dev setup to simplify the environment and updated the `dev-requirements.txt` lock file.
- **Improved package metadata** in `pyproject.toml` for better discoverability on PyPI.

### Fixed

- **Eliminated race condition warnings during session shutdown.** A race condition that occurred during rapid connection teardown would cause false positive warnings for late-arriving packets (both datagrams and streams). The handler now correctly and silently drops these packets, aligning with best practices and improving log clarity.

## [0.2.0] - 2025-08-06

This is a major release focused on enhancing runtime safety and modernizing the library for Python 3.11 and newer. It introduces significant, backward-incompatible changes to the asynchronous object lifecycle.

### BREAKING CHANGE

- Core components (e.g., Streams, Managers, Pools) now require activation via an `async with` block or a dedicated factory. Direct instantiation and use without proper initialization will raise a runtime error. This change is fundamental to ensuring runtime safety and event loop independence.

### Added

- Integrated `pip-tools` to manage and lock development dependencies, ensuring fully reproducible environments.

### Changed

- **Upgraded the minimum required Python version from 3.8 to 3.11.**
- Modernized the entire codebase to use modern type hint syntax (`X | Y`, built-in generics, `typing.Self`) available in Python 3.11+.
- Refactored all core components to defer the initialization of `asyncio` primitives until runtime, decoupling object instantiation from a running event loop.
- Introduced an `initialize()` pattern for resource-like objects (Streams, Sessions) to restore a convenient "get-and-use" API while maintaining runtime safety.
- Updated project documentation, including user guides, the API reference (`docs/`), and the contributor guide (`CONTRIBUTING.md`), to reflect the new asynchronous object lifecycle and initialization patterns.
- Overhauled the unit test suite to use asynchronous fixtures, aligning with the new component lifecycle contracts.
- Refactored CI/CD pipelines to use the locked `dev-requirements.txt` for improved reliability and efficiency.
- Consolidated development tool configurations (e.g., from `tox.ini`) into `pyproject.toml`.

### Fixed

- Eliminated a critical race condition by atomically delivering the first data payload with the stream opening event, preventing data loss.
- Resolved a lifecycle violation in the server application framework where sessions were not being properly initialized.
- Replaced the deprecated `datetime.utcnow()` with the timezone-aware `datetime.now(timezone.utc)`.
- Corrected improper `await` usage for asynchronous properties throughout the test suite.

## [0.1.2] - 2025-07-30

### Added

- Introduced a `DeprecationWarning` for Python versions below 3.11, signaling the planned removal of support in v0.2.0.
- Integrated `tox` and `pyenv` configurations to streamline the development and testing workflow for contributors.

### Changed

- Refactored internal module imports to use absolute paths, improving code structure and maintainability.
- Enhanced code quality by resolving all MyPy warnings within the test suite.

### Fixed

- Corrected an issue in the CI pipeline that prevented code coverage reports from being displayed correctly.

## [0.1.1] - 2025-07-28

### Added

- A robust, end-to-end CI/CD pipeline for automated testing, coverage reporting, and deployment.
- A public-facing CI workflow on GitHub Actions for pull request validation and build status badges.

### Changed

- Refactored unit tests to be independent of hardcoded version strings, improving maintainability.

## [0.1.0] - 2025-07-27

### Added

- Implemented the core WebTransport protocol over HTTP/3 and QUIC.
- Added a high-level `ServerApp` with path-based routing and middleware capabilities.
- Added a high-level asynchronous `WebTransportClient` for establishing and managing connections.
- Implemented a robust `WebTransportSession` class to encapsulate stream and datagram operations.
- Added support for bidirectional (`WebTransportStream`) and unidirectional (`WebTransportSendStream`, `WebTransportReceiveStream`) streams.
- Added support for sending and receiving unreliable datagrams for low-latency communication.
- Implemented connection pooling utilities, available via `pywebtransport.client.ClientPool`.
- Implemented a connection load balancer, available via `pywebtransport.connection.ConnectionLoadBalancer`.
- Introduced a flexible configuration system with `ClientConfig` and `ServerConfig`.
- Added built-in utilities for SSL/TLS certificate handling and generation of self-signed certificates.
- Implemented performance statistics collection for client and server monitoring.
- Provided a comprehensive logging infrastructure for debugging purposes.
- Ensured full `async/await` API support with complete type annotations.
- Established cross-platform compatibility for Python 3.8 and newer.

### Dependencies

- aioquic (>=1.2.0,<2.0.0) for QUIC protocol support
- cryptography (>=45.0.4,<46.0.0) for SSL/TLS operations
- typing-extensions (>=4.14.0,<5.0.0) for Python <3.10 support

[Unreleased]: https://github.com/lemonsterfy/pywebtransport/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/lemonsterfy/pywebtransport/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/lemonsterfy/pywebtransport/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/lemonsterfy/pywebtransport/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/lemonsterfy/pywebtransport/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/lemonsterfy/pywebtransport/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/lemonsterfy/pywebtransport/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/lemonsterfy/pywebtransport/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/lemonsterfy/pywebtransport/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/lemonsterfy/pywebtransport/releases/tag/v0.1.0
