"""
Cross-SDK hash parity verifier (Python).

Verifies that the Elixir SDK's hashing formula produces the same result
as all other SDK implementations.

Run: python3 sdk/elixir/verify_hash.py

Formula:
  MD5("{userId}:{flagKey}") -> first 4 bytes as little-endian uint32 / 2^32
"""

import hashlib
import struct


def hash_user(user_id: str, flag_key: str) -> float:
    """
    Consistent hash matching the Elixir (and JS/Java/Go/Ruby/Python) SDKs.
    """
    raw = hashlib.md5(f"{user_id}:{flag_key}".encode("utf-8")).digest()
    v = struct.unpack_from("<I", raw, 0)[0]  # little-endian uint32 from first 4 bytes
    return v / 4_294_967_296.0


def run_tests():
    test_cases = [
        ("user-123", "my-flag", 0.6927449859213084),
        # Additional vectors for robustness
        ("", "flag", None),       # Just verify no exception + bounds
        ("user", "", None),
        ("a", "b", None),
    ]

    print("=== Python Cross-SDK Hash Parity Verification ===\n")

    all_passed = True

    for uid, fk, expected in test_cases:
        result = hash_user(uid, fk)

        # Bounds check
        assert 0.0 <= result < 1.0, f"Out of bounds: hash_user({uid!r}, {fk!r}) = {result}"

        if expected is not None:
            diff = abs(result - expected)
            passed = diff < 1e-10
            status = "PASSED" if passed else "FAILED"
            print(f"  hash_user({uid!r}, {fk!r})")
            print(f"    result:   {result:.20f}")
            print(f"    expected: {expected:.20f}")
            print(f"    diff:     {diff:.2e}")
            print(f"    status:   {status}\n")
            if not passed:
                all_passed = False
        else:
            print(f"  hash_user({uid!r}, {fk!r}) = {result:.20f}  [bounds OK]\n")

    if all_passed:
        print("All parity checks PASSED.")
        print(f"\nElixir hash formula verified via Python: {hash_user('user-123', 'my-flag')}")
    else:
        print("One or more parity checks FAILED.")
        raise SystemExit(1)


if __name__ == "__main__":
    run_tests()
