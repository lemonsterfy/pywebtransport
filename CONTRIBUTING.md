# Contributing to PyWebTransport

Thank you for your interest in contributing to PyWebTransport! This document provides guidelines and information for contributors.

## Code of Conduct

This project adheres to a [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## Getting Started

### Prerequisites

- Python 3.8 or higher
- Git
- Virtual environment tool (venv, virtualenv, or conda)

### Development Setup

1. **Fork and clone the repository**:

   ```bash
   git clone https://github.com/lemonsterfy/pywebtransport.git
   cd pywebtransport
   ```

2. **Create a virtual environment**:

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install development dependencies**:

   ```bash
   pip install -e ".[dev]"
   ```

4. **Install pre-commit hooks**:

   ```bash
   pre-commit install
   ```

5. **Verify installation**:
   ```bash
   python -c "import pywebtransport; print('Installation successful')"
   pytest --version
   ```

## Development Workflow

### Making Changes

1. **Create a feature branch**:

   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following the coding standards below

3. **Write or update tests** for your changes

4. **Run the test suite**:

   ```bash
   pytest
   ```

5. **Run code formatting and linting**:

   ```bash
   black src tests
   flake8 src tests
   mypy src
   ```

6. **Commit your changes**:
   ```bash
   git add .
   git commit -m "Add feature: brief description"
   ```

## Coding Standards

### Code Style

We use the following tools to maintain code quality:

- **Black**: Code formatting
- **flake8**: Linting and style checking
- **mypy**: Type checking
- **isort**: Import sorting

### Type Hints

- All public functions and methods must include type hints
- Use modern Python typing syntax (Python 3.8+)
- For complex types, prefer explicit imports from `typing`

Example:

```python
from typing import Optional, List, Dict, Any
import asyncio

async def connect_to_server(
    url: str,
    timeout: Optional[float] = None,
    headers: Optional[Dict[str, str]] = None
) -> WebTransportSession:
    """Connect to WebTransport server."""
    # Implementation here
```

### Documentation

- All public APIs must have docstrings
- Use Google-style docstrings
- Include examples for complex functions

Example:

````python
async def create_bidirectional_stream(self) -> WebTransportStream:
    """Create a new bidirectional stream.

    Returns:
        WebTransportStream: A new bidirectional stream instance.

    Raises:
        ConnectionError: If the connection is not established.
        StreamError: If stream creation fails.

    Example:
        ```python
        stream = await session.create_bidirectional_stream()
        await stream.write(b"Hello WebTransport")
        response = await stream.read()
        ```
    """
````

### Error Handling

- Use specific exception types from `pywebtransport.exceptions`
- Include descriptive error messages
- Properly handle async context managers and cleanup

### WebTransport Specific Guidelines

- Follow RFC 9114 (HTTP/3) and draft WebTransport specifications
- Ensure proper QUIC stream management
- Handle connection multiplexing correctly
- Implement proper flow control and backpressure

## Testing

### Test Structure

Tests are organized by type and mirror the source code structure. This makes it easy to find the tests corresponding to a specific module.

```
tests/
├── e2e/              # End-to-end tests that run a client against a server.
├── integration/      # Tests for interactions between components.
├── performance/      # Performance and benchmark tests.
└── unit/             # Unit tests for individual components.
    ├── client/       # Tests for the `src/pywebtransport/client` module.
    │   └── test_client.py
    ├── server/       # Tests for the `src/pywebtransport/server` module.
    │   └── test_server.py
    ├── connection/
    ├── datagram/
    ├── protocol/
    ├── session/
    ├── stream/
    └── test_config.py  # Tests for `src/pywebtransport/config.py`
```

### Writing Tests

- Write tests for all new functionality
- Include both positive and negative test cases
- Test error conditions and edge cases
- Use pytest fixtures for common setup

Example test:

```python
import pytest
import asyncio
from pywebtransport import WebTransportClient

@pytest.mark.asyncio
async def test_client_connection():
    """Test basic client connection functionality."""
    client = WebTransportClient()

    # Test successful connection
    session = await client.connect("https://localhost:4433/")
    assert session.is_ready

    # Test basic functionality
    await session.datagrams.send(b"test data")

    # Cleanup
    await session.close()
    await client.close()
```

### Running Tests

```bash
# Run all tests discovered by pytest
pytest

# Run a specific test file by its full path
pytest tests/unit/client/test_client.py

# Run all tests within a specific category directory
pytest tests/performance/

# Run tests with a specific marker
pytest -m integration

# Run all tests and generate a coverage report
pytest --cov=pywebtransport --cov-report=html
```

### WebTransport Testing Requirements

- Test both client and server implementations
- Test stream multiplexing scenarios
- Test connection failure and recovery
- Test certificate validation
- Include performance benchmarks for critical paths

## Documentation

### API Documentation

- Document all public APIs with examples
- Keep examples up-to-date with API changes
- Include performance characteristics where relevant

### Contributing Documentation

When updating documentation:

1. Update docstrings for code changes
2. Update README.md if adding major features
3. Add examples to `examples/` directory for new functionality
4. Update architecture documentation for significant changes

## Pull Request Process

### Before Submitting

1. **Ensure all tests pass**:

   ```bash
   pytest
   ```

2. **Run the full code quality check**:

   ```bash
   black src tests
   flake8 src tests
   mypy src
   ```

3. **Update documentation** if needed

4. **Add entries to CHANGELOG.md** for user-facing changes

### Pull Request Guidelines

- **Title**: Use a clear, descriptive title
- **Description**: Explain what the PR does and why
- **Testing**: Describe how the changes were tested
- **Breaking Changes**: Clearly mark any breaking changes
- **Links**: Reference related issues

### PR Template

```markdown
## Description

Brief description of changes

## Type of Change

- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing

- [ ] All existing tests pass
- [ ] New tests added for new functionality
- [ ] Manual testing completed

## Checklist

- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] CHANGELOG.md updated
```

## Release Process

### Versioning

We follow [Semantic Versioning](https://semver.org/):

- **MAJOR**: Breaking changes
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes (backward compatible)

### Release Steps

1. Update version in `__version__.py`
2. Update CHANGELOG.md
3. Create release PR
4. Tag release after merge
5. Publish to PyPI

## Issue Reporting

### Bug Reports

When reporting bugs, please include:

- Python version and operating system
- PyWebTransport version
- Minimal code example reproducing the issue
- Full error traceback
- Expected vs. actual behavior

### Feature Requests

For feature requests:

- Describe the use case and motivation
- Provide examples of the proposed API
- Consider backward compatibility
- Reference relevant WebTransport specifications

## Community

### Getting Help

- **GitHub Discussions**: General questions and discussions
- **GitHub Issues**: Bug reports and feature requests
- **Email**: lemonsterfy@gmail.com for security issues

### Contributing Beyond Code

- Report bugs and suggest features
- Improve documentation
- Help other users in discussions
- Review pull requests
- Write blog posts or tutorials

## Performance Considerations

When contributing performance-sensitive code:

- Include benchmarks for significant changes
- Consider memory allocation patterns
- Test with realistic WebTransport workloads
- Profile critical code paths
- Document performance characteristics

## WebTransport Protocol Compliance

Ensure contributions maintain compliance with:

- [RFC 9114 (HTTP/3)](https://tools.ietf.org/rfc/rfc9114.txt)
- [WebTransport over HTTP/3 Draft](https://datatracker.ietf.org/doc/draft-ietf-webtrans-http3/)
- [WebTransport Generic Draft](https://datatracker.ietf.org/doc/draft-ietf-webtrans-overview/)

## Recognition

Contributors are recognized in:

- CHANGELOG.md for significant contributions
- GitHub contributors page
- Release notes for major contributions

---

Thank you for contributing to PyWebTransport! Your efforts help advance the WebTransport ecosystem in Python.
