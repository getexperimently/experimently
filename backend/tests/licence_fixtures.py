"""Development licences for the test suite.

The Enterprise routers are mounted behind ``require_feature`` (see
``backend/app/ee_transitional.py``), so a suite that exercises them has to run
under a licence.  This module mints one: an Ed25519 key pair generated for the
process, a licence signed with it, and ``kid="dev"`` -- which
``core/license.py`` honours only because the process environment names
``test``.  Nothing here is persisted; every pytest session gets a fresh key.

Two entry points:

* :func:`install_session_license` -- called once from ``conftest.py`` at
  import: a wildcard licence, valid for a year, so every existing Enterprise
  test runs licensed without knowing it.
* :func:`sign_license` / the ``licensed`` fixture -- for tests that need a
  *particular* licence: a subset of features, an expired one, one in grace.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.app.core import license as lic
from backend.app.core.config import settings

#: The signing key for this process.  Generated once at import, never written.
SESSION_PRIVATE_KEY: Ed25519PrivateKey = Ed25519PrivateKey.generate()

SESSION_PUBLIC_PEM: str = (
    SESSION_PRIVATE_KEY.public_key()
    .public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode("ascii")
)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def sign_license(
    *,
    features: Iterable[str] = ("*",),
    days: int = 365,
    not_before_days: int = -1,
    grace_days: int = lic.DEFAULT_GRACE_DAYS,
    customer: str = "Test Suite",
    plan: str = "enterprise",
    jti: Optional[str] = None,
    private_key: Optional[Ed25519PrivateKey] = None,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    """A licence key signed by the session key (or *private_key*).

    ``days`` may be negative to mint an already-expired licence; the grace and
    read-only windows are then measured from that past ``exp``.
    """
    now = datetime.now(timezone.utc)
    claims: Dict[str, Any] = {
        "customer": customer,
        "plan": plan,
        "features": list(features),
        "iat": int(now.timestamp()),
        "nbf": int((now + timedelta(days=not_before_days)).timestamp()),
        "exp": int((now + timedelta(days=days)).timestamp()),
        "kid": lic.DEV_KID,
        "jti": jti or f"test-{os.getpid()}-{int(now.timestamp())}",
        "grace_days": grace_days,
    }
    if extra_claims:
        claims.update(extra_claims)
    segment = _b64url(
        json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signer = private_key or SESSION_PRIVATE_KEY
    return f"{segment}.{_b64url(signer.sign(segment.encode('ascii')))}"


def install_session_license() -> None:
    """Point settings at the session key and a wildcard licence.

    The verifier honours ``kid="dev"`` only when the *process environment*
    names a development or test environment -- deliberately, so a deployment
    that forgot to set ``ENVIRONMENT`` cannot be unlocked with a self-minted
    key.  The suite therefore has to be started with ``APP_ENV=test`` (every
    CI job does; ``CLAUDE.md`` says so for local runs).  This function does
    not set it: writing ``ENVIRONMENT`` into ``os.environ`` here would leak
    into every ``Settings()`` a test builds -- pydantic-settings reads the
    environment over a class default -- and silently turn a
    ``ProdSettings()`` under test into a test-environment one.
    """
    settings.EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY = SESSION_PUBLIC_PEM
    settings.EXPERIMENTLY_LICENSE_KEY = sign_license()
    lic.reset_license_cache()
    state = lic.current_license_state()
    if state.status is not lic.LicenseStatus.ACTIVE:
        declared = os.environ.get("ENVIRONMENT") or os.environ.get("APP_ENV")
        raise RuntimeError(
            "The test suite runs under a development licence, which the verifier "
            "honours only in a declared development/test environment. "
            f"ENVIRONMENT/APP_ENV is {declared!r}; the licence resolved to "
            f"{state.status.value} ({state.reason}). Start pytest with "
            "`export APP_ENV=test TESTING=true` (see CLAUDE.md)."
        )


@pytest.fixture
def licensed(monkeypatch):
    """Install a specific licence for one test; returns the installer.

    ``licensed(features=["sso"])`` -- only SSO;
    ``licensed(days=-20)`` -- expired, inside the read-only window;
    ``licensed(None)`` -- no licence at all (Community).
    """

    def install(*args: Any, **kwargs: Any) -> lic.LicenseState:
        if args and args[0] is None:
            monkeypatch.setattr(settings, "EXPERIMENTLY_LICENSE_KEY", "")
        else:
            monkeypatch.setattr(
                settings, "EXPERIMENTLY_LICENSE_KEY", sign_license(**kwargs)
            )
        monkeypatch.setattr(
            settings, "EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY", SESSION_PUBLIC_PEM
        )
        # No ENVIRONMENT here: conftest declared APP_ENV=test at start-up and
        # deliberately pops ENVIRONMENT, and a Settings() built inside a test
        # must not see a value the suite planted.
        lic.reset_license_cache()
        return lic.current_license_state()

    yield install
    # Back to the session-wide wildcard licence for whoever runs next.
    lic.reset_license_cache()
