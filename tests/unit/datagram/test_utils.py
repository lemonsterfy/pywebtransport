"""Unit tests for the pywebtransport.datagram.utils module."""

import hashlib

import pytest

from pywebtransport.datagram.utils import calculate_checksum


class TestChecksumUtils:
    def test_calculate_checksum(self) -> None:
        data = b"pywebtransport"
        expected_sha256 = hashlib.sha256(data).hexdigest()

        checksum = calculate_checksum(data=data, algorithm="sha256")

        assert checksum == expected_sha256

    def test_calculate_checksum_unsupported_algorithm(self) -> None:
        with pytest.raises(ValueError, match="Unsupported or insecure hash algorithm: nonexistent-algorithm"):
            calculate_checksum(data=b"data", algorithm="nonexistent-algorithm")
