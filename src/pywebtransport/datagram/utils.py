"""Shared utility functions for datagram-related operations."""

from __future__ import annotations

import hashlib

__all__: list[str] = ["calculate_checksum"]


def calculate_checksum(*, data: bytes, algorithm: str = "sha256") -> str:
    """Calculate the checksum of data using a specified secure hash algorithm."""
    if algorithm not in hashlib.algorithms_guaranteed:
        raise ValueError(f"Unsupported or insecure hash algorithm: {algorithm}")
    hash_obj = hashlib.new(algorithm)
    hash_obj.update(data)
    return hash_obj.hexdigest()
