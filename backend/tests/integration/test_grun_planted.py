# SPDX-FileCopyrightText: 2026 Experimently contributors
# SPDX-License-Identifier: Apache-2.0
"""G-a: a planted failure that hashes to shard 2 of 4. Scratch branch only."""


def test_planted_failure_1() -> None:
    assert False, "G-a planted failure (shard 2)"
