# SPDX-FileCopyrightText: 2026 Experimently contributors
# SPDX-License-Identifier: Apache-2.0
"""The OIDC state store must be bounded (#94).

`GET /api/v1/auth/sso/oidc/{provider}/login` is on the PUBLIC router and every
call minted an entry. Expiry was consulted only on `pop`, so a token nobody
redeemed was removed by nothing -- an anonymous caller could grow the process's
memory one HTTP request at a time.

These pin the bound. They do NOT pin that the flow survives abuse: a flood
still displaces pending logins, because nothing here can tell an attacker's
token from a user's. Only the redesign in #94 fixes that, by holding no server
state at all.
"""

from __future__ import annotations

import time

import pytest

sso_service = pytest.importorskip(
    "modules.backend.app.services.sso_service", reason="modules profile only"
)


@pytest.fixture(autouse=True)
def _empty_store():
    sso_service._state_store.clear()
    yield
    sso_service._state_store.clear()


@pytest.mark.unit
@pytest.mark.regression
def test_the_store_cannot_grow_without_limit():
    """The vulnerability, directly: mint far past the cap and measure."""
    cap = sso_service._STATE_STORE_MAX
    for _ in range(cap + (cap // 5)):
        sso_service.generate_state_token()
    assert len(sso_service._state_store) <= cap, (
        f"{len(sso_service._state_store)} live tokens with a cap of {cap}; an "
        "unauthenticated route can still exhaust memory"
    )


@pytest.mark.unit
def test_expired_tokens_are_dropped_rather_than_live_ones():
    """Eviction prefers the dead. A cap that shed live tokens first would
    break legitimate logins while the expired ones sat there."""
    cap = sso_service._STATE_STORE_MAX
    past = time.time() - 1
    for i in range(cap):
        sso_service._state_store[f"expired-{i}"] = past

    fresh = sso_service.generate_state_token()

    assert fresh in sso_service._state_store, "the new token was evicted"
    assert not any(k.startswith("expired-") for k in sso_service._state_store), (
        "expired tokens survived while the store was at its cap"
    )


@pytest.mark.unit
def test_a_token_still_round_trips():
    """The bound must not break the thing the store is for."""
    token = sso_service.generate_state_token()
    assert sso_service.verify_state_token(token) is True


@pytest.mark.unit
def test_a_token_is_single_use():
    from fastapi import HTTPException

    token = sso_service.generate_state_token()
    assert sso_service.verify_state_token(token) is True
    with pytest.raises(HTTPException):
        sso_service.verify_state_token(token)


@pytest.mark.unit
def test_an_expired_token_is_refused():
    from fastapi import HTTPException

    token = sso_service.generate_state_token()
    sso_service._state_store[token] = time.time() - 1
    with pytest.raises(HTTPException) as exc:
        sso_service.verify_state_token(token)
    assert exc.value.status_code == 400


@pytest.mark.unit
def test_eviction_is_not_quadratic():
    """Shedding one token per insert is O(n) per call at exactly the moment
    the process is already under load. Asserted as a bounded operation count,
    not a wall-clock time -- three flaky gates in this repository came from
    timing assertions."""
    cap = sso_service._STATE_STORE_MAX
    now = time.time() + sso_service._STATE_TTL_SECONDS
    for i in range(cap):
        sso_service._state_store[f"live-{i}"] = now

    before = len(sso_service._state_store)
    sso_service.generate_state_token()
    after = len(sso_service._state_store)

    # One insert shed a BATCH, so the store dropped by more than one.
    assert after < before, "the store did not shrink when it hit the cap"
    assert before - after > 1, (
        "one token was shed per insert, which is the quadratic shape"
    )
