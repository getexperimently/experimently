"""The one consistent hash. Every bucketing decision in the platform uses it.

There were four of these, and they disagreed (#81).

    openfeature.py          MD5("{user}:{key}"), first 4 bytes LE, / 2^32
    assignment_service.py   MD5("{user}:{experiment.id}"), FULL digest, % 100
    global_holdout / MEG    MD5("{user}:{salt}"), first 4 bytes LE, % 100
    lambda/shared           MurmurHash3-ish of the user, salted "{key}_variant"

The first is the contract: ``tests/sdk-contract/golden-vectors.json`` pins it
and all fourteen SDKs implement it, so it is the only one a client can
reproduce locally. The others were free to drift because nothing compared them.

They had drifted. For ``user-123`` / ``my-flag`` -- one input, one hash
function -- the contract puts the user in bucket **69** and
``assignment_service`` put them in bucket **79**, because reading the whole
128-bit digest modulo 100 is a different number from reading the first four
bytes little-endian. And the two were not even hashing the same string: the
contract uses the experiment's public ``key``, the assignment service used its
UUID primary key, which no client has.

The consequence is the one an experimentation platform cannot have: a user
counted in variant A by the API and variant B by an SDK evaluating locally,
silently, with no error anywhere -- and every metric computed from the join
between them quietly wrong.

THE ALGORITHM, as the golden vectors state it:

    1. concatenate "{user_id}:{key}"
    2. UTF-8 encode
    3. MD5 digest (16 bytes)
    4. read the FIRST FOUR BYTES as a little-endian unsigned 32-bit integer
    5. divide by 2^32

Step 4 is the one that is easy to get wrong and impossible to notice: every
other reading of the digest produces a valid-looking number in the right range.

MD5 is a bucketing function here, not a security primitive. It is fixed by the
contract: fourteen SDKs implement it, so changing it is a coordinated release,
not a refactor. ``usedforsecurity=False`` says so to the linters.
"""

from __future__ import annotations

import hashlib
import struct
from typing import Final

#: 2^32. The divisor the golden vectors specify.
HASH_DIVISOR: Final[int] = 4294967296

#: How many buckets a percentage-based allocation is drawn from.
BUCKET_COUNT: Final[int] = 100


def hash_user(user_id: str, key: str) -> float:
    """A stable float in [0.0, 1.0) for *user_id* under *key*.

    ``key`` is whatever namespaces the decision -- a flag key, an experiment
    key, a holdout salt. The same user under two different keys gets two
    unrelated positions, which is what stops every experiment bucketing the
    same users together.

    >>> round(hash_user("user-123", "my-flag"), 16)
    0.6927449859213084
    """
    digest = hashlib.md5(
        f"{user_id}:{key}".encode("utf-8"), usedforsecurity=False
    ).digest()
    (uint32,) = struct.unpack_from("<I", digest[:4])
    return uint32 / HASH_DIVISOR


def bucket_of(user_id: str, key: str) -> int:
    """The same position as an integer in [0, 100).

    For allocations expressed as percentages. Derived from :func:`hash_user`
    rather than computed separately, so the two can never disagree about which
    side of a boundary a user falls on.

    >>> bucket_of("user-123", "my-flag")
    69
    """
    return int(hash_user(user_id, key) * BUCKET_COUNT)
