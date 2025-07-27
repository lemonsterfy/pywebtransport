# Installation

Complete guide for installing PyWebTransport on different platforms and environments.

## Requirements

### Python Version

PyWebTransport requires **Python 3.8 or higher**:

```bash
python --version  # Should show 3.8+
```

### Supported Platforms

- **Linux** (Ubuntu 20.04+, CentOS 8+, Debian 11+)
- **macOS** (10.15+, including Apple Silicon)
- **Windows** (Windows 10+, Windows Server 2019+)

## Basic Installation

### Install from PyPI

Install the latest stable release:

```bash
pip install pywebtransport
```

Upgrade to the latest version:

```bash
pip install --upgrade pywebtransport
```

### Install with Development Tools

For development work:

```bash
pip install pywebtransport[dev]
```

This includes testing, linting, and formatting tools.

## Advanced Installation

### Install from Source

For the latest development features:

```bash
git clone https://github.com/lemonsterfy/pywebtransport.git
cd pywebtransport
pip install -e .
```

For development with all tools:

```bash
git clone https://github.com/lemonsterfy/pywebtransport.git
cd pywebtransport
pip install -e ".[dev]"
```

### Optional Dependencies

Available dependency groups:

```bash
pip install pywebtransport[dev]   # Development tools
pip install pywebtransport[docs]  # Documentation building
pip install pywebtransport[test]  # Testing utilities
```

## Virtual Environment Setup

### Using venv (Recommended)

```bash
# Create virtual environment
python -m venv pywebtransport-env

# Activate
source pywebtransport-env/bin/activate  # Linux/macOS
pywebtransport-env\Scripts\activate     # Windows

# Install
pip install pywebtransport
```

### Using conda

```bash
conda create -n pywebtransport python=3.11
conda activate pywebtransport
pip install pywebtransport
```

## Verify Installation

To verify that PyWebTransport is installed correctly, you can check its version and run a simple script to initialize the core components.

**1. Check the version:**

```bash
python -c "import pywebtransport; print(pywebtransport.__version__)"
```

**2. Test core component initialization:**

Save the following code as `verify.py` and run it. This script does not make any network requests but confirms that the client and server objects can be created.

```python
# verify.py
import asyncio

from pywebtransport import ClientConfig, ServerApp, ServerConfig, WebTransportClient


async def verify() -> None:
    print("Initializing core components...")
    try:
        # Initialize a client (without connecting)
        client = WebTransportClient(config=ClientConfig.create())

        # Initialize a server app (without starting)
        # A minimal config requires dummy cert files for initialization.
        ServerApp(config=ServerConfig.create(certfile="dummy.crt", keyfile="dummy.key"))

        await client.close()
        print("SUCCESS: Core components initialized successfully!")

    except Exception as e:
        print(f"FAILED: An error occurred during initialization: {e}")


if __name__ == "__main__":
    asyncio.run(verify())

```

Run the script from your terminal:
```bash
# Create dummy files for the script to run without errors
touch dummy.crt dummy.key
python verify.py
rm dummy.crt dummy.key
```

If the script prints "SUCCESS", your installation is working correctly.

## Dependencies

### Core Dependencies

PyWebTransport automatically installs its core dependencies with precise version constraints to ensure stability:

- **aioquic** (`>=1.2.0,<2.0.0`) - The underlying QUIC protocol implementation.
- **cryptography** (`>=45.0.4,<46.0.0`) - Handles all cryptographic operations.
- **typing-extensions** (`>=4.14.0,<5.0.0`) - Required for type hints on Python < 3.10.

### System Requirements

- **TLS 1.3 support** (included in Python 3.8+)
- **asyncio support** (standard library)
- **C compiler** (for building cryptography on some platforms)

## Platform-Specific Notes

### Linux

Install build dependencies if needed:

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install python3-pip python3-venv build-essential

# CentOS/RHEL/Fedora
sudo dnf install python3-pip gcc openssl-devel
```

### macOS

Install development tools if needed:

```bash
xcode-select --install
```

### Windows

Most installations work out of the box. If you encounter build errors:

1. Install [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
2. Restart your terminal
3. Retry installation

## Troubleshooting

### Permission Errors

Use virtual environment or user installation:

```bash
# User installation
pip install --user pywebtransport

# Virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # Linux/macOS
pip install pywebtransport
```

### Build Errors

Ensure development tools are installed:

```bash
# Ubuntu/Debian
sudo apt install build-essential python3-dev libssl-dev

# macOS
xcode-select --install

# Windows: Install Visual C++ Build Tools
```

### Outdated pip

```bash
pip install --upgrade pip
pip install pywebtransport
```

### Import Errors

Check Python version and virtual environment:

```bash
python --version
which python
pip list | grep pywebtransport
```

### Network Issues

Use alternative index if default fails:

```bash
pip install -i https://pypi.org/simple/ pywebtransport
```

## Container Installation

Basic Dockerfile:

```dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install PyWebTransport
RUN pip install pywebtransport

WORKDIR /app
COPY . .

CMD ["python", "app.py"]
```

## Upgrading

Check current version:

```python
import pywebtransport
print(pywebtransport.__version__)
```

Upgrade to latest:

```bash
pip install --upgrade pywebtransport
```

## Uninstallation

Remove PyWebTransport:

```bash
pip uninstall pywebtransport
```

Clean up virtual environment:

```bash
rm -rf pywebtransport-env  # Linux/macOS
rmdir /s pywebtransport-env  # Windows
```

## See Also

- **[Client API](client.md)** - WebTransport client implementation
- **[Server API](server.md)** - WebTransport server implementation
- **[Configuration API](config.md)** - Configuration options and builders
- **[Types API](types.md)** - Type definitions and constants
