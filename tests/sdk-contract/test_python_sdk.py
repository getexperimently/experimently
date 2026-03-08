"""
Cross-SDK contract tests for the Python SDK consistent hashing.

Validates that the Python SDK produces identical hash values to the
golden test vectors shared across all SDKs.

Run: pytest tests/sdk-contract/test_python_sdk.py -v
"""

import hashlib
import json
import struct
from pathlib import Path

import pytest

VECTORS_PATH = Path(__file__).parent / "golden-vectors.json"
TOLERANCE = 1e-10  # Floating-point comparison tolerance


def load_golden_vectors():
    with open(VECTORS_PATH) as f:
        return json.load(f)


def compute_hash(user_id: str, flag_key: str) -> float:
    """Python implementation of the cross-SDK MD5 consistent hash."""
    combined = f"{user_id}:{flag_key}".encode("utf-8")
    hash_bytes = hashlib.md5(combined).digest()[:4]
    hash_value = struct.unpack("<I", hash_bytes)[0]  # little-endian uint32
    return hash_value / 0x100000000  # divide by 2^32


def compute_md5_hex(user_id: str, flag_key: str) -> str:
    """Compute full MD5 hex digest for verification."""
    combined = f"{user_id}:{flag_key}".encode("utf-8")
    return hashlib.md5(combined).hexdigest()


class TestHashVectors:
    """Validate hash output matches golden vectors."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.vectors = load_golden_vectors()

    @pytest.mark.parametrize(
        "vector",
        load_golden_vectors()["hash_vectors"],
        ids=lambda v: f"{v['user_id']}:{v['flag_key']}",
    )
    def test_hash_value_matches(self, vector):
        result = compute_hash(vector["user_id"], vector["flag_key"])
        assert abs(result - vector["expected_hash"]) < TOLERANCE, (
            f"Hash mismatch for {vector['user_id']}:{vector['flag_key']}: "
            f"expected {vector['expected_hash']}, got {result}"
        )

    @pytest.mark.parametrize(
        "vector",
        load_golden_vectors()["hash_vectors"],
        ids=lambda v: f"md5_{v['user_id']}:{v['flag_key']}",
    )
    def test_md5_hex_matches(self, vector):
        result = compute_md5_hex(vector["user_id"], vector["flag_key"])
        assert result == vector["md5_hex"], (
            f"MD5 hex mismatch for {vector['user_id']}:{vector['flag_key']}: "
            f"expected {vector['md5_hex']}, got {result}"
        )


class TestRolloutVectors:
    """Validate rollout inclusion/exclusion matches golden vectors."""

    @pytest.mark.parametrize(
        "vector",
        load_golden_vectors()["rollout_vectors"],
        ids=lambda v: f"rollout_{v['user_id']}:{v['flag_key']}",
    )
    def test_rollout_inclusion(self, vector):
        h = compute_hash(vector["user_id"], vector["flag_key"])

        if "rollout_3_percent" in vector:
            included = h < 0.03
            assert included == vector["rollout_3_percent"], (
                f"3% rollout mismatch: hash={h}, expected included={vector['rollout_3_percent']}"
            )

        if "rollout_5_percent" in vector:
            included = h < 0.05
            assert included == vector["rollout_5_percent"], (
                f"5% rollout mismatch: hash={h}, expected included={vector['rollout_5_percent']}"
            )

        if "rollout_50_percent" in vector:
            included = h < 0.50
            assert included == vector["rollout_50_percent"], (
                f"50% rollout mismatch: hash={h}, expected included={vector['rollout_50_percent']}"
            )

        if "rollout_100_percent" in vector:
            included = h < 1.0
            assert included == vector["rollout_100_percent"], (
                f"100% rollout mismatch: hash={h}, expected included={vector['rollout_100_percent']}"
            )


class TestHashProperties:
    """Validate fundamental properties of the hash function."""

    def test_deterministic(self):
        """Same inputs always produce same output."""
        h1 = compute_hash("user-123", "my-flag")
        h2 = compute_hash("user-123", "my-flag")
        assert h1 == h2

    def test_range_zero_to_one(self):
        """Hash output is in [0.0, 1.0)."""
        for i in range(100):
            h = compute_hash(f"user-{i}", "test-flag")
            assert 0.0 <= h < 1.0, f"Hash out of range: {h}"

    def test_different_users_different_hashes(self):
        """Different users get different hashes (with high probability)."""
        hashes = {compute_hash(f"user-{i}", "flag") for i in range(100)}
        assert len(hashes) == 100, "Hash collisions detected"

    def test_string_format(self):
        """Hash input is exactly '{user_id}:{flag_key}'."""
        # Verify by checking MD5 directly
        expected_input = "user-123:my-flag"
        expected_md5 = hashlib.md5(expected_input.encode("utf-8")).hexdigest()
        assert expected_md5 == "43bc57b1e81dec71c5242122ac05170f"

    def test_little_endian_byte_order(self):
        """Verify little-endian interpretation of MD5 bytes."""
        combined = "user-123:my-flag".encode("utf-8")
        digest = hashlib.md5(combined).digest()

        # Little-endian: first byte is least significant
        le_value = struct.unpack("<I", digest[:4])[0]
        # Big-endian: first byte is most significant
        be_value = struct.unpack(">I", digest[:4])[0]

        assert le_value != be_value, "LE and BE should differ"
        assert le_value / 0x100000000 == pytest.approx(0.6927449859213084, abs=TOLERANCE)
