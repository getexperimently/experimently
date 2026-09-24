"""One hash, checked against the file every SDK is checked against.

#81: four bucketing implementations, none compared to any other.

    openfeature.py          MD5("{user}:{key}"), first 4 bytes LE, / 2^32
    assignment_service.py   MD5("{user}:{experiment.id}"), FULL digest, % 100
    global_holdout / MEG    MD5("{user}:{salt}"), first 4 bytes LE, % 100
    lambda/shared           MurmurHash3-ish, salted "{key}_variant"

They had drifted, and the drift is invisible: every one of them returns a
plausible number in the right range. For `user-123`/`my-flag` the contract puts
the user in bucket 69 and `assignment_service` put them in bucket 79.

For an experimentation platform that is the worst class of bug there is. A user
counted in variant A by the API and variant B by an SDK evaluating locally
produces no error, no log line and no failed request -- just a quietly wrong
number in every metric computed from the join.

These read `tests/sdk-contract/golden-vectors.json`, the same file the
cross-SDK suite reads, so the backend cannot drift from the fourteen SDKs
without failing here first.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

from backend.app.core.consistent_hash import HASH_DIVISOR, bucket_of, hash_user

REPO_ROOT = Path(__file__).resolve().parents[4]
VECTORS = REPO_ROOT / "tests" / "sdk-contract" / "golden-vectors.json"

pytestmark = pytest.mark.skipif(
    not VECTORS.is_file(), reason="this tree has no sdk-contract vectors"
)


def _vectors() -> dict:
    return json.loads(VECTORS.read_text(encoding="utf-8"))


@pytest.mark.regression
def test_the_vector_file_is_readable_and_not_empty():
    """Vacuity guard: an empty list would make every case below pass."""
    data = _vectors()
    assert data.get("hash_vectors"), f"no hash_vectors in {VECTORS}"


@pytest.mark.regression
def test_every_golden_vector_matches():
    """The contract, verbatim, for all fourteen SDKs and the backend."""
    mismatches = []
    for vector in _vectors()["hash_vectors"]:
        actual = hash_user(vector["user_id"], vector["flag_key"])
        if abs(actual - vector["expected_hash"]) > 1e-12:
            mismatches.append(
                f"{vector['user_id']}/{vector['flag_key']}: "
                f"expected {vector['expected_hash']}, got {actual}"
            )
    assert not mismatches, "the backend disagrees with the SDK contract:\n" + "\n".join(
        mismatches
    )


@pytest.mark.regression
def test_the_md5_digest_in_the_vectors_is_the_one_we_compute():
    """Pins the input string, not just the output number.

    A different separator or ordering could still land on the right float for
    one vector by luck; the digest cannot.
    """
    for vector in _vectors()["hash_vectors"]:
        expected = vector.get("md5_hex")
        if not expected:
            continue
        actual = hashlib.md5(
            f"{vector['user_id']}:{vector['flag_key']}".encode(),
            usedforsecurity=False,
        ).hexdigest()
        assert actual == expected, (
            f"{vector['user_id']}/{vector['flag_key']}: the input string is not "
            f"'{{user_id}}:{{flag_key}}' -- digest {actual} != {expected}"
        )


@pytest.mark.regression
def test_the_first_four_bytes_are_read_little_endian():
    """The step that is easy to get wrong and impossible to notice.

    Big-endian, or the whole digest, both yield a valid-looking number in
    [0, 1). This asserts the one reading the contract specifies.
    """
    digest = hashlib.md5(b"user-123:my-flag", usedforsecurity=False).digest()
    little = struct.unpack_from("<I", digest[:4])[0] / HASH_DIVISOR
    big = struct.unpack_from(">I", digest[:4])[0] / HASH_DIVISOR
    whole = int.from_bytes(digest, "big") / (1 << 128)

    assert hash_user("user-123", "my-flag") == little
    assert little != big, "the vector cannot distinguish endianness"
    assert little != whole, "the vector cannot distinguish digest width"


@pytest.mark.regression
def test_bucket_is_derived_from_the_same_float():
    """So the two can never disagree about a boundary."""
    for user in ("user-123", "u-2", "", "unicode-Ä-user"):
        for key in ("my-flag", "exp-checkout", "another"):
            assert bucket_of(user, key) == int(hash_user(user, key) * 100)
            assert 0 <= bucket_of(user, key) < 100


@pytest.mark.regression
def test_the_whole_digest_modulo_100_is_a_different_answer():
    """The exact defect #81 describes, pinned so it cannot return.

    This is what `assignment_service` used to do.
    """
    old = (
        int(hashlib.md5(b"user-123:my-flag", usedforsecurity=False).hexdigest(), 16)
        % 100
    )
    assert bucket_of("user-123", "my-flag") == 69
    assert old == 79
    assert old != bucket_of("user-123", "my-flag"), (
        "the two readings now agree, so this test proves nothing -- check the "
        "vector rather than deleting it"
    )


@pytest.mark.regression
def test_the_key_namespaces_the_decision():
    """The same user must not land in the same place in every experiment."""
    positions = {hash_user("user-123", f"exp-{i}") for i in range(25)}
    assert len(positions) > 20, (
        f"25 keys produced only {len(positions)} distinct positions; the key is "
        "not reaching the hash"
    )
