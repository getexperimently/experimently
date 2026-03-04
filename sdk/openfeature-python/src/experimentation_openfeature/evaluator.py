"""
Local flag evaluator using the same consistent MD5 hash algorithm
as the Go, Java, and TypeScript SDKs.

Hash algorithm (byte-for-byte compatible):
  1. Concatenate userId + ":" + flagKey as UTF-8.
  2. Compute MD5 digest.
  3. Read first 4 bytes as a little-endian unsigned 32-bit integer.
  4. Divide by 2^32 = 4294967296 to normalize to [0.0, 1.0).

Cross-SDK test vector:
  hash_user("user-123", "my-flag")
  MD5("user-123:my-flag") hex = 59e69a9b6823fae4e285e6c5ccdb11ee
  First 4 bytes LE: 0x9b, 0x9a, 0xe6, 0x59 → uint32 = 0x59e69a9b = 1508165275
  1508165275 / 4294967296 ≈ 0.35108...
"""
from __future__ import annotations

import hashlib
import struct
from typing import Any, Optional, Tuple

from .types import FeatureFlagDefinition, FlagVariant, LocalEvalResult

# 2^32 — MUST match the Go SDK's hashDivisor and the Java SDK's HASH_DIVISOR.
_HASH_DIVISOR: int = 4294967296


def hash_user(user_id: str, flag_key: str) -> float:
    """
    Compute a float in [0.0, 1.0) for the (user_id, flag_key) pair using MD5.

    This is byte-for-byte compatible with the Go, Java, and TypeScript SDKs.
    """
    input_str = f"{user_id}:{flag_key}"
    digest = hashlib.md5(input_str.encode("utf-8")).digest()  # noqa: S324
    # Interpret first 4 bytes as a little-endian unsigned 32-bit integer.
    (uint32,) = struct.unpack_from("<I", digest[:4])
    return uint32 / _HASH_DIVISOR


class LocalEvaluator:
    """
    Performs local (client-side) feature flag evaluation using the
    consistent hash algorithm that is shared across all platform SDKs.
    """

    def evaluate(self, flag: FeatureFlagDefinition, user_id: str) -> LocalEvalResult:
        """
        Evaluate a feature flag for a user without a network call.

        Logic:
          1. Flag disabled → value=False, variant=None.
          2. hash(userId, flagKey) ≥ rolloutFraction → out of rollout → value=False.
          3. Variants defined → assign one proportionally by weight.
          4. No variants → boolean flag → value=True.
        """
        if not flag.enabled:
            return LocalEvalResult(value=False, variant=None, enabled=False)

        h = hash_user(user_id, flag.key)
        rollout_fraction = flag.rollout_percentage / 100.0

        if h >= rollout_fraction:
            return LocalEvalResult(value=False, variant=None, enabled=False)

        if flag.variants:
            variant_key, variant_value = self._assign_variant(
                flag.variants, h, rollout_fraction
            )
            return LocalEvalResult(
                value=variant_value if variant_value is not None else variant_key,
                variant=variant_key,
                enabled=True,
            )

        return LocalEvalResult(value=True, variant=None, enabled=True)

    def _assign_variant(
        self,
        variants: list[FlagVariant],
        hash_val: float,
        rollout_fraction: float,
    ) -> Tuple[str, Any]:
        """
        Pick a variant for a user who is within the rollout band.

        Re-scales hash from [0, rolloutFraction) → [0.0, 1.0) and then
        selects proportionally by cumulative weight (matches Go/Java SDKs).
        """
        variant_hash = hash_val / rollout_fraction if rollout_fraction > 0.0 else 0.0
        cumulative = 0.0
        for v in variants:
            cumulative += v.weight
            if variant_hash < cumulative:
                return v.key, v.value
        # Fallback to last variant (floating-point rounding edge cases).
        last = variants[-1]
        return last.key, last.value
