# Changelog

All notable changes to PyWebTransport will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

### Changed

- Refactored unit tests to be independent of hardcoded version strings, improving maintainability.

### Added

- A robust, end-to-end CI/CD pipeline for automated testing, coverage reporting, and deployment.
- A public-facing CI workflow on GitHub Actions for pull request validation and build status badges.

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

[Unreleased]: https://github.com/lemonsterfy/pywebtransport/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/lemonsterfy/pywebtransport/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/lemonsterfy/pywebtransport/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/lemonsterfy/pywebtransport/releases/tag/v0.1.0
