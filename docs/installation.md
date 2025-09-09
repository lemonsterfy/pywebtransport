# Installation

Complete guide for installing PyWebTransport on different platforms and environments.

## Requirements

### Python Version

PyWebTransport requires **Python 3.11 or higher**:

```bash
python --version  # Should show 3.11+
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

## Advanced Installation

### Install from Source

For the latest development features or to contribute to the project, you can install from a local clone. See our [Contributing Guide](../CONTRIBUTING.md) for the full developer setup.

```bash
git clone https://github.com/lemonsterfy/pywebtransport.git
cd pywebtransport
pip install -e .
```

### Optional Dependencies

You can install optional dependency groups for specific features.

```bash
# For high-performance structured data serialization
pip install pywebtransport[msgpack]
pip install pywebtransport[protobuf]

# For building documentation
pip install pywebtransport[docs]

# For running tests against the installed package
pip install pywebtransport[test]
```

## Virtual Environment Setup

### Using venv (Recommended)

```bash
# Create virtual environment
python -m venv .venv

# Activate
source .venv/bin/activate  # Linux/macOS
.venv\Scripts\activate     # Windows

# Install
pip install pywebtransport
```

### Using conda

```bash
conda create -n pywebtransport python=3.12
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

Save the following code as `verify.py` and run it. This script does not make any network requests but confirms that the client and server objects can be created. It temporarily creates empty dummy.crt and dummy.key files to satisfy the minimum ServerConfig requirements without needing real certificates.

```python
# verify.py
import asyncio
import os

from pywebtransport import ClientConfig, ServerApp, ServerConfig, WebTransportClient


async def verify() -> None:
    print("Initializing core components...")
    try:
        async with WebTransportClient(config=ClientConfig.create()):
            pass

        ServerApp(config=ServerConfig.create(certfile="dummy.crt", keyfile="dummy.key"))

        print("SUCCESS: Core components initialized successfully!")

    except Exception as e:
        print(f"FAILED: An error occurred during initialization: {e}")


if __name__ == "__main__":
    with open("dummy.crt", "w") as f:
        f.write("")
    with open("dummy.key", "w") as f:
        f.write("")

    try:
        asyncio.run(verify())
    finally:
        os.remove("dummy.crt")
        os.remove("dummy.key")

```

Run the script from your terminal:

```bash
python verify.py
```

If the script prints "SUCCESS", your installation is working correctly.

## Dependencies

### Core Dependencies

PyWebTransport automatically installs its core dependencies:

- **aioquic** (`>=1.2.0,<2.0.0`) - The underlying QUIC protocol implementation.
- **cryptography** (`>=45.0.4,<46.0.0`) - Handles all cryptographic operations.

### System Requirements

- **TLS 1.3 support** (included in Python 3.11+)
- **asyncio support** (standard library)

## Platform-Specific Notes

### Linux

A C compiler and development headers are required to build the cryptography dependency.

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install python3-pip python3-venv build-essential

# CentOS/RHEL/Fedora
sudo dnf install python3-pip gcc openssl-devel
```

### macOS

Install the Xcode command-line tools if needed:

```bash
xcode-select --install
```

### Windows

Most installations work out of the box. If you encounter build errors, you may need the C++ build tools.

1. Install [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
2. Restart your terminal
3. Retry installation

## Troubleshooting

### Permission Errors

Use a virtual environment (recommended) or user installation:

```bash
# User installation
pip install --user pywebtransport
```

### Build Errors

Ensure development tools and headers are installed as described in the "Platform-Specific Notes" section.

### Outdated pip

```bash
pip install --upgrade pip
pip install pywebtransport
```

### Import Errors

Check Python version and virtual environment:

```bash
python --version
which python  # On Linux/macOS
pip list | grep pywebtransport
```

### Network Issues

Use an alternative index if the default fails:

```bash
pip install -i https://pypi.org/simple/ pywebtransport
```

## Container Installation

Basic Dockerfile:

```dockerfile
FROM python:3.12-slim

# Install system dependencies needed for building cryptography
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

Clean up a virtual environment:

```bash
rm -rf .venv  # Linux/macOS
rmdir /s .venv  # Windows
```

## See Also

- **[Home](index.md)**: Project homepage and overview
- **[Quick Start](quickstart.md)**: A 5-minute tutorial
- **[API Reference](api-reference/index.md)**: Complete API documentation
- **[Contributing Guide](../CONTRIBUTING.md)**: Learn how to contribute
