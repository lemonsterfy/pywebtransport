# Changelog

All notable changes to PyWebTransport will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned for future release

- **[Feature]** Introduce a high-performance, concurrent event processing model using `asyncio.TaskGroup`.

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

[Unreleased]: https://github.com/lemonsterfy/pywebtransport/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/lemonsterfy/pywebtransport/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/lemonsterfy/pywebtransport/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/lemonsterfy/pywebtransport/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/lemonsterfy/pywebtransport/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/lemonsterfy/pywebtransport/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/lemonsterfy/pywebtransport/releases/tag/v0.1.0
