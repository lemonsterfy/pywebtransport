# Contributing to PyWebTransport

Thank you for your interest in contributing to PyWebTransport! This document provides guidelines and information for contributors.

## Code of Conduct

This project adheres to a [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## Getting Started

### Prerequisites

To contribute to this project, your development environment will need the following tools:

- **Git**: For version control.
- **pyenv**: For managing multiple Python versions. This is crucial for local testing.
- **tox**: For automating tests across all supported Python versions.

We recommend installing `tox` using `pipx` for a clean, isolated installation:

```bash
pipx install tox
```

### Development Setup

1.  **Fork and clone the repository**:
    First, fork the project on GitHub. Then, clone your fork locally:

    ```bash
    git clone https://github.com/lemonsterfy/pywebtransport.git
    cd pywebtransport
    ```

2.  **Install required Python versions**:
    This project is tested across multiple Python versions. Use `pyenv` to install them. You can find the list of supported versions in the `tox.ini` file.

    ```bash
    # Example for installing a specific version
    pyenv install 3.11.13
    ```

3.  **Create your primary development environment**:
    For day-to-day development, we recommend using a recent, stable version of Python (e.g., 3.11).

    ```bash
    # Set the Python version for this project directory
    pyenv local 3.11.13

    # Create and activate a virtual environment named .venv
    python -m venv .venv
    source .venv/bin/activate  # On Windows: .venv\Scripts\activate
    ```

4.  **Install development dependencies**:
    This command will install the project in editable mode along with all tools needed for testing and quality checks.

    ```bash
    pip install -e ".[dev]"
    ```

5.  **Install pre-commit hooks**:
    This will run automated checks before each commit.
    ```bash
    pre-commit install
    ```

## Development Workflow

### Making Changes

1.  **Create a feature branch**:
    Create a new branch from `main` for your changes.

    ```bash
    git checkout -b feature/your-feature-name
    ```

2.  **Make your changes**, following the coding standards below.

3.  **Write or update tests** for your changes.

4.  **Run checks and tests**:
    While developing, you can run tests quickly against your primary environment:

    ```bash
    # Run code quality checks
    black src tests
    flake8 src tests
    mypy src

    # Run the test suite with pytest
    pytest
    ```

5.  **Run the full test suite with tox**:
    Before submitting your changes, it is **mandatory** to run the full test suite using `tox`. This ensures your changes are compatible with all supported Python versions.

    ```bash
    tox
    ```

6.  **Commit your changes**:
    ```bash
    git add .
    git commit -m "feat: A brief and descriptive commit message"
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

Tests are organized by type and mirror the source code structure.

```
tests/
├── e2e/
├── integration/
├── performance/
└── unit/
```

### Writing Tests

- Write tests for all new functionality
- Include both positive and negative test cases
- Test error conditions and edge cases
- Use pytest fixtures for common setup

### Running Tests

The primary way to run the full test suite is with `tox`.

```bash
# Run all checks and tests across all supported Python versions
tox
```

For faster, iterative development, you can run `pytest` directly in your activated virtual environment. This will only test against your primary Python version.

```bash
# Run all tests using pytest
pytest

# Run a specific test file
pytest tests/unit/client/test_client.py

# Run tests with a specific marker
pytest -m integration

# Run tests and generate a coverage report
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

1.  Update docstrings for code changes
2.  Update README.md if adding major features
3.  Add examples to `examples/` directory for new functionality
4.  Update architecture documentation for significant changes

## Pull Request Process

### Before Submitting

1.  **Ensure all tests pass with tox**:

    ```bash
    tox
    ```

2.  **Ensure code is formatted and passes quality checks**. The `pre-commit` hooks should handle this, but you can also run them manually:

    ```bash
    black src tests
    flake8 src tests
    mypy src
    ```

3.  **Update documentation** if needed.

4.  **Add entries to CHANGELOG.md** for user-facing changes.

### Submitting a Pull Request

Once your changes are ready, push your branch to your fork and open a pull request against the `main` branch of the original repository.

- **Title**: Use a clear, descriptive title following Conventional Commits.
- **Description**: Explain what the PR does and why.
- **Testing**: Describe how the changes were tested.
- **Breaking Changes**: Clearly mark any breaking changes.
- **Links**: Reference related issues.

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

- [ ] All existing tests pass via `tox`
- [ ] New tests added for new functionality
- [ ] Manual testing completed

## Checklist

- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] CHANGELOG.md updated
```

## Release Process

**(Note: This section is for project maintainers.)**

### Versioning

We follow [Semantic Versioning](https://semver.org/):

- **MAJOR**: Breaking changes
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes (backward compatible)

### Release Steps

1.  Update version in `src/pywebtransport/version.py`.
2.  Update `CHANGELOG.md`.
3.  Create a release pull request from the `dev` branch to `main` on our internal repository.
4.  After merge, the CI/CD pipeline will automatically tag the release and publish to PyPI.

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
