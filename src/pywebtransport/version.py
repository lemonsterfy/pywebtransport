"""
PyWebTransport Version Information.
"""

__all__ = [
    "MAJOR",
    "MINOR",
    "PATCH",
    "__author__",
    "__description__",
    "__email__",
    "__license__",
    "__url__",
    "__version__",
    "__version_info__",
    "get_version",
    "get_version_info__",
    "is_development",
    "is_stable",
]

__version__ = "0.1.2"
__version_info__ = (0, 1, 2)
__author__ = "lemonsterfy"
__email__ = "lemonsterfy@gmail.com"
__license__ = "MIT"
__description__ = "A high-performance, async-native WebTransport implementation for Python."
__url__ = "https://github.com/lemonsterfy/pywebtransport"

MAJOR = __version_info__[0]
MINOR = __version_info__[1]
PATCH = __version_info__[2]


def get_version() -> str:
    """Get the version string."""
    return __version__


def get_version_info__() -> tuple:
    """Get the version info tuple."""
    return __version_info__


def is_stable() -> bool:
    """Check if this is a stable release."""
    return MAJOR >= 1


def is_development() -> bool:
    """Check if this is a development version."""
    return PATCH == 0 and MINOR == 0 and MAJOR == 0
