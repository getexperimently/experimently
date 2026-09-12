"""
Unit tests for the offline licence gate (``backend/app/core/license.py``).

Covers the eight states the open-core plan names -- no key, valid, expired
within grace, expired inside the read-only window, expired past it, tampered
claims, unknown ``kid``, not-yet-valid -- plus the feature/wildcard rules, key
rotation, revocation, the ``require_feature`` 403 body and the ``license.*``
audit trail.

Nothing here touches the network: verification is a local Ed25519 check.
"""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from backend.app.core import license as lic
from backend.app.core.license import (
    DEFAULT_GRACE_DAYS,
    DEV_KID,
    READ_ONLY_DAYS,
    LicenseStatus,
    require_feature,
    reset_license_cache,
    verify_license_key,
)
from backend.app.models.audit_log import ActionType, EntityType

NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Minting helpers (a local signer; the real one lives in
# scripts/make_dev_license.py and produces byte-identical keys)
# ---------------------------------------------------------------------------


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _public_pem(private_key: Ed25519PrivateKey) -> str:
    return (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )


def _claims(
    *,
    kid: str = DEV_KID,
    features: Any = ("hipaa", "sso"),
    exp: datetime,
    nbf: Optional[datetime] = None,
    grace_days: int = DEFAULT_GRACE_DAYS,
    customer: str = "Acme GmbH",
    plan: str = "enterprise",
    max_seats: int = 25,
    jti: Optional[str] = None,
) -> Dict[str, Any]:
    nbf = nbf or (NOW - timedelta(days=1))
    claims = {
        "customer": customer,
        "plan": plan,
        "features": list(features),
        "iat": int((NOW - timedelta(days=1)).timestamp()),
        "nbf": int(nbf.timestamp()),
        "exp": int(exp.timestamp()),
        "kid": kid,
        "grace_days": grace_days,
        "max_seats": max_seats,
    }
    if jti is not None:
        claims["jti"] = jti
    return claims


def _sign(private_key: Ed25519PrivateKey, claims: Dict[str, Any]) -> str:
    segment = _b64url(
        json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return f"{segment}.{_b64url(private_key.sign(segment.encode('ascii')))}"


@pytest.fixture(autouse=True)
def clean_license_cache():
    """The module memoises verification and the last audited state."""
    reset_license_cache()
    yield
    reset_license_cache()


@pytest.fixture
def signer():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def keymap(signer):
    return {DEV_KID: _public_pem(signer)}


# ---------------------------------------------------------------------------
# The eight states
# ---------------------------------------------------------------------------


class TestLicenseStates:
    def test_no_key_is_community_edition(self, keymap):
        for empty in (None, "", "   "):
            state = verify_license_key(empty, now=NOW, public_keys=keymap)
            assert state.status is LicenseStatus.NONE
            assert state.edition == "ce"
            assert state.features == ()
            assert state.expires_at is None
            assert not state.allows("hipaa", write=True)
            assert not state.allows("hipaa", write=False)

    def test_valid_key_is_active_and_allows_reads_and_writes(self, signer, keymap):
        key = _sign(signer, _claims(exp=NOW + timedelta(days=30)))
        state = verify_license_key(key, now=NOW, public_keys=keymap)

        assert state.status is LicenseStatus.ACTIVE
        assert state.edition == "enterprise"
        assert state.features == ("hipaa", "sso")
        assert state.customer == "Acme GmbH"
        assert state.plan == "enterprise"
        assert state.max_seats == 25
        assert state.expires_at == NOW + timedelta(days=30)
        assert state.allows("hipaa", write=True)
        assert state.allows("hipaa", write=False)

    def test_expired_within_grace_still_works_completely(self, signer, keymap):
        # Expired 3 days ago, 14-day grace.
        key = _sign(signer, _claims(exp=NOW - timedelta(days=3)))
        state = verify_license_key(key, now=NOW, public_keys=keymap)

        assert state.status is LicenseStatus.GRACE
        assert state.edition == "enterprise"
        assert state.allows("hipaa", write=True), "grace must not refuse writes"
        assert state.allows("hipaa", write=False)

    def test_past_grace_inside_read_only_window_refuses_writes_only(
        self, signer, keymap
    ):
        # 20 days past exp = 6 days past the 14-day grace, well inside the
        # 30-day read-only window.
        key = _sign(signer, _claims(exp=NOW - timedelta(days=20)))
        state = verify_license_key(key, now=NOW, public_keys=keymap)

        assert state.status is LicenseStatus.EXPIRED
        assert state.reads_allowed is True
        assert state.allows("hipaa", write=False), "reads stay open in read-only"
        assert not state.allows("hipaa", write=True)
        # Data is never hidden: the licence still names its features.
        assert state.features == ("hipaa", "sso")

    def test_past_read_only_window_refuses_everything(self, signer, keymap):
        # 14 + 30 = 44 days of runway; 60 days past exp is beyond it.
        key = _sign(signer, _claims(exp=NOW - timedelta(days=60)))
        state = verify_license_key(key, now=NOW, public_keys=keymap)

        assert state.status is LicenseStatus.EXPIRED
        assert state.reads_allowed is False
        assert not state.allows("hipaa", write=False)
        assert not state.allows("hipaa", write=True)

    def test_tampered_claims_are_invalid(self, signer, keymap):
        key = _sign(signer, _claims(exp=NOW + timedelta(days=30)))
        segment, signature = key.split(".")
        forged = json.loads(
            base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
        )
        forged["features"] = ["hipaa", "sso", "warehouse"]
        tampered_segment = _b64url(
            json.dumps(forged, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )

        state = verify_license_key(
            f"{tampered_segment}.{signature}", now=NOW, public_keys=keymap
        )
        assert state.status is LicenseStatus.INVALID
        assert state.reason == "bad_signature"
        assert state.edition == "ce"
        assert state.features == ()
        assert not state.allows("warehouse", write=False)

    def test_unknown_kid_is_invalid(self, signer, keymap):
        key = _sign(
            signer, _claims(kid="not-a-key-we-know", exp=NOW + timedelta(days=30))
        )
        state = verify_license_key(key, now=NOW, public_keys=keymap)

        assert state.status is LicenseStatus.INVALID
        assert state.reason == "unknown_kid"
        assert not state.allows("hipaa", write=False)

    def test_not_yet_valid_is_invalid(self, signer, keymap):
        key = _sign(
            signer,
            _claims(exp=NOW + timedelta(days=365), nbf=NOW + timedelta(days=7)),
        )
        state = verify_license_key(key, now=NOW, public_keys=keymap)

        assert state.status is LicenseStatus.INVALID
        assert state.reason == "not_yet_valid"
        assert not state.allows("hipaa", write=False)

        # ...and the very same key verifies once nbf has passed: nbf must not
        # be baked into the cached verification result.
        later = verify_license_key(key, now=NOW + timedelta(days=8), public_keys=keymap)
        assert later.status is LicenseStatus.ACTIVE


# ---------------------------------------------------------------------------
# Boundaries, features and key handling
# ---------------------------------------------------------------------------


class TestBoundaries:
    @pytest.mark.parametrize(
        ("offset_days", "expected"),
        [
            (-1, LicenseStatus.ACTIVE),
            (0, LicenseStatus.GRACE),  # exp is exclusive
            (DEFAULT_GRACE_DAYS - 1, LicenseStatus.GRACE),
            (DEFAULT_GRACE_DAYS, LicenseStatus.EXPIRED),
        ],
    )
    def test_status_boundaries(self, signer, keymap, offset_days, expected):
        exp = NOW - timedelta(days=offset_days)
        key = _sign(signer, _claims(exp=exp))
        assert verify_license_key(key, now=NOW, public_keys=keymap).status is expected

    def test_read_only_window_boundary(self, signer, keymap):
        exp = NOW - timedelta(days=DEFAULT_GRACE_DAYS + READ_ONLY_DAYS)
        key = _sign(signer, _claims(exp=exp))
        just_out = verify_license_key(key, now=NOW, public_keys=keymap)
        assert just_out.reads_allowed is False

        just_in = verify_license_key(
            key, now=NOW - timedelta(minutes=1), public_keys=keymap
        )
        assert just_in.reads_allowed is True

    def test_custom_grace_days_claim_is_honoured(self, signer, keymap):
        key = _sign(signer, _claims(exp=NOW - timedelta(days=5), grace_days=1))
        assert (
            verify_license_key(key, now=NOW, public_keys=keymap).status
            is LicenseStatus.EXPIRED
        )

    def test_grace_days_defaults_when_claim_absent(self, signer, keymap):
        claims = _claims(exp=NOW - timedelta(days=5))
        del claims["grace_days"]
        key = _sign(signer, claims)
        assert (
            verify_license_key(key, now=NOW, public_keys=keymap).status
            is LicenseStatus.GRACE
        )


class TestFeatureScoping:
    def test_feature_outside_the_licence_is_refused_even_when_active(
        self, signer, keymap
    ):
        key = _sign(signer, _claims(features=["hipaa"], exp=NOW + timedelta(days=30)))
        state = verify_license_key(key, now=NOW, public_keys=keymap)
        assert state.status is LicenseStatus.ACTIVE
        assert state.allows("hipaa")
        assert not state.allows("warehouse")
        assert not state.allows("warehouse", write=False)

    def test_wildcard_grants_every_feature(self, signer, keymap):
        key = _sign(signer, _claims(features=["*"], exp=NOW + timedelta(days=30)))
        state = verify_license_key(key, now=NOW, public_keys=keymap)
        assert state.allows("anything-at-all")
        assert state.allows("hipaa", write=False)


class TestKeyHandling:
    @pytest.mark.parametrize(
        "bad",
        [
            "not-a-license",
            "only-one-segment.",
            ".only-the-signature",
            "a.b.c",
            "!!!!.!!!!",
        ],
    )
    def test_malformed_keys_are_invalid_not_crashes(self, keymap, bad):
        state = verify_license_key(bad, now=NOW, public_keys=keymap)
        assert state.status is LicenseStatus.INVALID

    def test_claims_that_are_not_a_json_object_are_invalid(self, signer, keymap):
        segment = _b64url(b'["not", "an", "object"]')
        key = f"{segment}.{_b64url(signer.sign(segment.encode('ascii')))}"
        state = verify_license_key(key, now=NOW, public_keys=keymap)
        assert state.status is LicenseStatus.INVALID
        assert state.reason == "malformed_claims"

    @pytest.mark.parametrize("missing", ["customer", "plan", "features", "exp", "kid"])
    def test_missing_required_claim_is_invalid(self, signer, keymap, missing):
        claims = _claims(exp=NOW + timedelta(days=30))
        del claims[missing]
        state = verify_license_key(_sign(signer, claims), now=NOW, public_keys=keymap)
        assert state.status is LicenseStatus.INVALID
        assert state.reason in (f"missing_claim:{missing}", "unknown_kid")

    def test_key_rotation_needs_no_verifier_change(self):
        """Two signing keys, two kids, one map -- both licences verify."""
        old, new = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
        keymap = {"2025-01": _public_pem(old), "2026-09": _public_pem(new)}

        for kid, signer in (("2025-01", old), ("2026-09", new)):
            key = _sign(signer, _claims(kid=kid, exp=NOW + timedelta(days=30)))
            state = verify_license_key(key, now=NOW, public_keys=keymap)
            assert state.status is LicenseStatus.ACTIVE
            assert state.kid == kid

        # A licence signed by the old key but claiming the new kid fails.
        crossed = _sign(old, _claims(kid="2026-09", exp=NOW + timedelta(days=30)))
        assert (
            verify_license_key(crossed, now=NOW, public_keys=keymap).reason
            == "bad_signature"
        )

    @pytest.mark.regression
    def test_revoked_kid_is_invalid(self, signer, keymap, monkeypatch):
        key = _sign(signer, _claims(exp=NOW + timedelta(days=30)))
        # Verified first, so the signature is in the memo: revocation has to
        # take effect against a warm cache, without reset_license_cache().
        assert verify_license_key(key, now=NOW, public_keys=keymap).status is (
            LicenseStatus.ACTIVE
        )
        monkeypatch.setattr(lic, "REVOKED_KIDS", frozenset({DEV_KID}))
        state = verify_license_key(key, now=NOW, public_keys=keymap)
        assert state.status is LicenseStatus.INVALID
        assert state.reason == "revoked"
        assert state.kid == DEV_KID

    @pytest.mark.regression
    def test_revoked_jti_is_invalid_without_touching_its_siblings(
        self, signer, keymap, monkeypatch
    ):
        """One serial off, every other licence the same key signed still works."""
        doomed = _sign(signer, _claims(jti="lic-1", exp=NOW + timedelta(days=30)))
        sibling = _sign(signer, _claims(jti="lic-2", exp=NOW + timedelta(days=30)))
        for key in (doomed, sibling):
            assert verify_license_key(key, now=NOW, public_keys=keymap).status is (
                LicenseStatus.ACTIVE
            )

        monkeypatch.setattr(lic, "REVOKED_JTIS", frozenset({"lic-1"}))
        assert verify_license_key(doomed, now=NOW, public_keys=keymap).reason == (
            "revoked"
        )
        assert verify_license_key(sibling, now=NOW, public_keys=keymap).status is (
            LicenseStatus.ACTIVE
        )

    @pytest.mark.regression
    def test_the_verification_cache_is_bounded(self, signer, keymap):
        """`verify_license_key` takes an arbitrary key, so the memo cannot grow
        without limit just because a caller checks untrusted input."""
        reset_license_cache()
        for n in range(lic._VERIFY_CACHE_MAX * 2):
            verify_license_key(f"not.alicence{n}", now=NOW, public_keys=keymap)
        assert len(lic._verify_cache) == lic._VERIFY_CACHE_MAX

    @pytest.mark.parametrize(
        "field,value",
        [
            ("exp", 1 << 62),
            ("nbf", 1 << 62),
            ("iat", 1 << 62),
            ("exp", -(1 << 62)),
        ],
    )
    @pytest.mark.regression
    def test_an_absurd_timestamp_is_refused_not_raised(
        self, signer, keymap, field, value
    ):
        """An authentic licence naming year 146 billion must not 500 the API.

        `datetime.fromtimestamp` raises OSError/OverflowError/ValueError there,
        and the claims are only read after the signature checks out -- so this
        is reachable by anyone who can sign, including a leaked dev key.
        """
        claims = _claims(exp=NOW + timedelta(days=30))
        claims[field] = value
        state = verify_license_key(_sign(signer, claims), now=NOW, public_keys=keymap)
        assert state.status is LicenseStatus.INVALID
        assert state.reason == "malformed_claims"

    @pytest.mark.regression
    def test_an_absurd_grace_falls_back_to_the_default(self, signer, keymap):
        """`exp + timedelta(days=grace_days)` overflows long before exp does."""
        claims = _claims(exp=NOW - timedelta(days=1))
        claims["grace_days"] = 1 << 40
        state = verify_license_key(_sign(signer, claims), now=NOW, public_keys=keymap)
        # Default 14-day grace, so a licence that expired yesterday is in grace.
        assert state.status is LicenseStatus.GRACE

    def test_the_widest_permitted_timestamp_still_resolves(self, signer, keymap):
        claims = _claims(exp=NOW + timedelta(days=30))
        claims["exp"] = lic.MAX_TIMESTAMP
        state = verify_license_key(_sign(signer, claims), now=NOW, public_keys=keymap)
        assert state.status is LicenseStatus.ACTIVE
        # grace_ends_at saturates rather than raising OverflowError.
        assert state.expires_at.year == 9999

    @pytest.mark.regression
    def test_a_newline_escaped_pem_is_accepted(self, signer):
        """`make_dev_license.py --env-file` writes the PEM on one line with
        `\\n` escapes, and a shell `export` leaves them literal; the verifier
        used to answer `unknown_kid` for it, which names nothing."""
        escaped = _public_pem(signer).strip().replace("\n", "\\n")
        assert "\n" not in escaped
        key = _sign(signer, _claims(exp=NOW + timedelta(days=30)))
        state = verify_license_key(key, now=NOW, public_keys={DEV_KID: escaped})
        assert state.status is LicenseStatus.ACTIVE

    def test_unparseable_public_key_in_the_map_does_not_crash(self, signer):
        key = _sign(signer, _claims(exp=NOW + timedelta(days=30)))
        state = verify_license_key(
            key, now=NOW, public_keys={DEV_KID: "-----BEGIN PUBLIC KEY-----\nnope\n"}
        )
        assert state.status is LicenseStatus.INVALID
        assert state.reason == "unknown_kid"

    def test_verification_is_offline(self, signer, keymap):
        """No socket is opened anywhere in the verification path."""
        import socket

        key = _sign(signer, _claims(exp=NOW + timedelta(days=30)))
        with patch.object(
            socket.socket, "connect", side_effect=AssertionError("phoned home")
        ):
            assert (
                verify_license_key(key, now=NOW, public_keys=keymap).status
                is LicenseStatus.ACTIVE
            )


class TestSettingsResolution:
    """``current_license_state`` reads settings, incl. the dev-key rules."""

    def test_dev_key_is_trusted_in_test_environment(self, signer, monkeypatch):
        monkeypatch.setattr(
            lic.settings, "EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY", _public_pem(signer)
        )
        monkeypatch.setattr(lic.settings, "ENVIRONMENT", "test")
        monkeypatch.setattr(
            lic.settings,
            "EXPERIMENTLY_LICENSE_KEY",
            _sign(signer, _claims(exp=NOW + timedelta(days=30))),
        )
        assert lic.current_license_state(now=NOW).status is LicenseStatus.ACTIVE

    def test_dev_key_is_refused_in_production(self, signer, monkeypatch):
        monkeypatch.setattr(
            lic.settings, "EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY", _public_pem(signer)
        )
        monkeypatch.setattr(lic.settings, "ENVIRONMENT", "production")
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setattr(
            lic.settings,
            "EXPERIMENTLY_LICENSE_KEY",
            _sign(signer, _claims(exp=NOW + timedelta(days=30))),
        )
        state = lic.current_license_state(now=NOW)
        assert state.status is LicenseStatus.INVALID
        assert state.reason == "unknown_kid"

    @pytest.mark.regression
    def test_dev_key_is_refused_when_the_environment_is_not_declared(
        self, signer, monkeypatch
    ):
        """`ENVIRONMENT` defaults to development, so silence must not unlock EE.

        A deployment that never sets the variable -- a plain `docker run`, a
        chart or task definition that forgot it -- would otherwise accept a
        self-minted developer licence.

        The trap this reproduces: config.py mirrors the *defaulted* environment
        back into `APP_ENV` at import for legacy readers, so by the time the
        verifier runs, `os.environ` on an undeclared process says `APP_ENV=dev`
        -- exactly what a declared development one says. The first version of
        this test `delenv`'d `APP_ENV` and so never saw that; the guard has to
        use the flag config.py captured *before* the mirror.
        """
        from backend.app.core import config

        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.setenv("APP_ENV", "dev")  # what config.py's mirror leaves behind
        monkeypatch.setattr(config, "ENVIRONMENT_DECLARED", False)
        monkeypatch.setattr(
            lic.settings, "EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY", _public_pem(signer)
        )
        # The settings object still says "development" -- its default.
        monkeypatch.setattr(lic.settings, "ENVIRONMENT", "development")
        monkeypatch.setattr(
            lic.settings,
            "EXPERIMENTLY_LICENSE_KEY",
            _sign(signer, _claims(exp=NOW + timedelta(days=30))),
        )
        lic.reset_license_cache()
        state = lic.current_license_state(now=NOW)
        assert state.status is LicenseStatus.INVALID
        assert state.reason == "unknown_kid"
        assert state.edition == "ce"

    @pytest.mark.regression
    @pytest.mark.parametrize("declared", ["demo", "staging", "production", "prod"])
    def test_dev_key_is_refused_for_every_other_declared_environment(
        self, signer, monkeypatch, declared
    ):
        """`demo` in particular: config.py's alias table maps it to development,
        and the internet-facing demo stack declares APP_ENV=demo. Going through
        that table granted the dev key there; the verifier keeps its own,
        narrower, list of spellings."""
        from backend.app.core import config

        monkeypatch.setattr(config, "ENVIRONMENT_DECLARED", True)
        monkeypatch.setenv("ENVIRONMENT", declared)
        monkeypatch.setattr(
            lic.settings, "EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY", _public_pem(signer)
        )
        monkeypatch.setattr(
            lic.settings,
            "EXPERIMENTLY_LICENSE_KEY",
            _sign(signer, _claims(exp=NOW + timedelta(days=30))),
        )
        lic.reset_license_cache()
        assert lic._dev_key_permitted() is False
        assert lic.current_license_state(now=NOW).reason == "unknown_kid"

    def test_an_ignored_dev_key_is_explained_once(self, signer, monkeypatch):
        """Nothing else says why: /edition carries no reason and the 403 names
        only the feature, so an operator who forgot to declare the environment
        saw "invalid" with no way to learn why."""
        from backend.app.core import config

        monkeypatch.setattr(config, "ENVIRONMENT_DECLARED", False)
        monkeypatch.setattr(
            lic.settings, "EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY", _public_pem(signer)
        )
        lic.reset_license_cache()
        with patch.object(lic, "logger") as log:
            lic.public_key_map()
            lic.public_key_map()
        assert log.warning.call_count == 1
        assert "process environment" in str(log.warning.call_args)

    @pytest.mark.parametrize("declared", ["development", "dev", "test"])
    def test_dev_key_works_when_the_environment_says_so(
        self, signer, monkeypatch, declared
    ):
        from backend.app.core import config

        monkeypatch.setattr(config, "ENVIRONMENT_DECLARED", True)
        monkeypatch.setenv("ENVIRONMENT", declared)
        monkeypatch.setattr(
            lic.settings, "EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY", _public_pem(signer)
        )
        monkeypatch.setattr(
            lic.settings,
            "EXPERIMENTLY_LICENSE_KEY",
            _sign(signer, _claims(exp=NOW + timedelta(days=30))),
        )
        lic.reset_license_cache()
        assert lic.current_license_state(now=NOW).status is LicenseStatus.ACTIVE

    def test_embedded_map_wins_over_the_dev_key(self, signer, monkeypatch):
        """A dev key can never shadow an embedded production kid."""
        production = Ed25519PrivateKey.generate()
        monkeypatch.setitem(lic.EMBEDDED_PUBLIC_KEYS, DEV_KID, _public_pem(production))
        monkeypatch.setattr(
            lic.settings, "EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY", _public_pem(signer)
        )
        monkeypatch.setattr(lic.settings, "ENVIRONMENT", "development")
        assert lic.public_key_map()[DEV_KID] == _public_pem(production)

    def test_no_key_in_settings_is_community_edition(self, monkeypatch):
        monkeypatch.setattr(lic.settings, "EXPERIMENTLY_LICENSE_KEY", "")
        assert lic.current_license_state(now=NOW).status is LicenseStatus.NONE


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


class TestLicenseAudit:
    @pytest.mark.asyncio
    async def test_state_change_writes_a_license_audit_event(self, signer, keymap):
        db = MagicMock()
        state = verify_license_key(
            _sign(signer, _claims(exp=NOW + timedelta(days=30))),
            now=NOW,
            public_keys=keymap,
        )

        with patch(
            "backend.app.services.audit_service.AuditService.log_action",
            new_callable=AsyncMock,
        ) as log_action:
            emitted = await lic.audit_license_state(db, state)

        assert emitted is True
        kwargs = log_action.await_args.kwargs
        assert kwargs["action_type"] is ActionType.LICENSE_ACTIVE
        assert kwargs["action_type"].value == "license.active"
        assert kwargs["action_type"].value.startswith("license.")
        assert kwargs["entity_type"] is EntityType.LICENSE
        assert kwargs["new_value"] == "active"
        assert kwargs["old_value"] is None
        assert kwargs["user_id"] is None
        assert kwargs["entity_id"] == lic.license_entity_id(state.kid)

    @pytest.mark.asyncio
    async def test_unchanged_state_is_not_re_audited(self, signer, keymap):
        db = MagicMock()
        state = verify_license_key(
            _sign(signer, _claims(exp=NOW + timedelta(days=30))),
            now=NOW,
            public_keys=keymap,
        )
        with patch(
            "backend.app.services.audit_service.AuditService.log_action",
            new_callable=AsyncMock,
        ) as log_action:
            assert await lic.audit_license_state(db, state) is True
            assert await lic.audit_license_state(db, state) is False
        assert log_action.await_count == 1

    @pytest.mark.asyncio
    async def test_every_transition_is_audited_with_the_previous_state(
        self, signer, keymap
    ):
        db = MagicMock()
        key = _sign(signer, _claims(exp=NOW + timedelta(days=30)))
        instants = [
            (NOW, "active"),
            (NOW + timedelta(days=31), "grace"),
            (NOW + timedelta(days=60), "expired"),
        ]
        with patch(
            "backend.app.services.audit_service.AuditService.log_action",
            new_callable=AsyncMock,
        ) as log_action:
            for instant, _expected in instants:
                state = verify_license_key(key, now=instant, public_keys=keymap)
                await lic.audit_license_state(db, state)

        transitions = [
            (call.kwargs["old_value"], call.kwargs["new_value"])
            for call in log_action.await_args_list
        ]
        assert transitions == [
            (None, "active"),
            ("active", "grace"),
            ("grace", "expired:read_only"),
        ]

    @pytest.mark.asyncio
    @pytest.mark.regression
    async def test_a_failed_write_does_not_block_a_different_transition(
        self, signer, keymap
    ):
        """The back-off used to be global, so a failed write for state A held
        up a different transition B arriving inside the window."""
        db = MagicMock()
        key = _sign(signer, _claims(exp=NOW + timedelta(days=30)))
        active = verify_license_key(key, now=NOW, public_keys=keymap)
        grace = verify_license_key(
            key, now=NOW + timedelta(days=31), public_keys=keymap
        )
        with patch(
            "backend.app.services.audit_service.AuditService.log_action",
            new_callable=AsyncMock,
            side_effect=[RuntimeError("down"), uuid.uuid4()],
        ) as log_action:
            assert await lic.audit_license_state(db, active) is False
            # `active` is in back-off; `grace` is a different fingerprint and
            # must be written straight away.
            assert lic.audit_pending(active) is False
            assert lic.audit_pending(grace) is True
            assert await lic.audit_license_state(db, grace) is True
        assert log_action.await_count == 2
        # Honest about what was recorded: the failed `active` row is not
        # back-filled, so grace's old_value is the last *recorded* state.
        assert log_action.await_args.kwargs["old_value"] is None
        assert log_action.await_args.kwargs["new_value"] == "grace"

    @pytest.mark.asyncio
    @pytest.mark.regression
    async def test_a_swallowed_insert_failure_counts_as_a_failure(self, signer, keymap):
        """AuditService.log_action catches every exception and returns None,
        so a failed INSERT never reached the except-branch: the transition was
        marked audited, nothing rolled back, nothing retried. A None return
        has to be treated as the failure it is."""
        db = MagicMock()
        state = verify_license_key(
            _sign(signer, _claims(exp=NOW + timedelta(days=30))),
            now=NOW,
            public_keys=keymap,
        )
        with patch(
            "backend.app.services.audit_service.AuditService.log_action",
            new_callable=AsyncMock,
            return_value=None,  # what log_action answers when the INSERT failed
        ):
            assert await lic.audit_license_state(db, state) is False
        db.rollback.assert_called_once()
        later = datetime.now(timezone.utc) + timedelta(
            seconds=lic.AUDIT_RETRY_SECONDS + 1
        )
        assert lic.audit_pending(state, now=later) is True

    @pytest.mark.regression
    @pytest.mark.asyncio
    async def test_the_end_of_the_read_only_window_is_audited(self, signer, keymap):
        """Both halves of `expired` report status "expired"; the day enterprise
        reads stop is still a transition the trail has to show."""
        db = MagicMock()
        key = _sign(signer, _claims(exp=NOW + timedelta(days=30)))
        # exp + 30d, grace 14d, read-only 30d -> reads stop at day 74.
        read_only = NOW + timedelta(days=60)
        after = NOW + timedelta(days=80)
        with patch(
            "backend.app.services.audit_service.AuditService.log_action",
            new_callable=AsyncMock,
        ) as log_action:
            for instant in (read_only, after):
                state = verify_license_key(key, now=instant, public_keys=keymap)
                assert state.status is LicenseStatus.EXPIRED
                await lic.audit_license_state(db, state)

        assert [
            (call.kwargs["old_value"], call.kwargs["new_value"])
            for call in log_action.await_args_list
        ] == [(None, "expired:read_only"), ("expired:read_only", "expired:no_reads")]

    @pytest.mark.regression
    @pytest.mark.asyncio
    async def test_the_customer_name_is_not_written_to_the_audit_trail(
        self, signer, keymap
    ):
        """Audit rows are readable by ANALYST and VIEWER; the licensee is not."""
        db = MagicMock()
        state = verify_license_key(
            _sign(signer, _claims(customer="Acme GmbH", exp=NOW + timedelta(days=30))),
            now=NOW,
            public_keys=keymap,
        )
        assert state.customer == "Acme GmbH"
        with patch(
            "backend.app.services.audit_service.AuditService.log_action",
            new_callable=AsyncMock,
        ) as log_action:
            await lic.audit_license_state(db, state)
        kwargs = log_action.await_args.kwargs
        assert "Acme" not in json.dumps({k: str(v) for k, v in kwargs.items()})
        assert kwargs["entity_name"] == f"license:{state.kid}"

    @pytest.mark.asyncio
    async def test_audit_failure_never_breaks_the_gate(self, signer, keymap):
        db = MagicMock()
        state = verify_license_key(
            _sign(signer, _claims(exp=NOW + timedelta(days=30))),
            now=NOW,
            public_keys=keymap,
        )
        with patch(
            "backend.app.services.audit_service.AuditService.log_action",
            new_callable=AsyncMock,
            side_effect=RuntimeError("database is on fire"),
        ):
            # No exception, and an honest answer: nothing was recorded.
            assert await lic.audit_license_state(db, state) is False
        db.rollback.assert_called_once()

    @pytest.mark.regression
    @pytest.mark.asyncio
    async def test_a_failed_audit_is_retried_after_a_backoff_not_lost(
        self, signer, keymap
    ):
        """The fingerprint used to be marked audited *before* the INSERT and
        never restored, so a transition whose first write failed -- Postgres
        still coming up after a restart, say -- was lost for the life of the
        process while the caller was told True."""
        db = MagicMock()
        state = verify_license_key(
            _sign(signer, _claims(exp=NOW + timedelta(days=30))),
            now=NOW,
            public_keys=keymap,
        )
        with patch(
            "backend.app.services.audit_service.AuditService.log_action",
            new_callable=AsyncMock,
            side_effect=[RuntimeError("database is on fire"), uuid.uuid4()],
        ) as log_action:
            assert await lic.audit_license_state(db, state) is False
            # Straight away: still inside the backoff, no second attempt.
            assert await lic.audit_license_state(db, state) is False
            assert log_action.await_count == 1
            assert lic.audit_pending(state) is False
            # ...but the transition is still owed.
            later = datetime.now(timezone.utc) + timedelta(
                seconds=lic.AUDIT_RETRY_SECONDS + 1
            )
            assert lic.audit_pending(state, now=later) is True
            with patch.object(lic, "_audit_retry_after", {}):
                assert await lic.audit_license_state(db, state) is True
            assert log_action.await_count == 2
            # Recorded now: the previous state was None, the new one active.
            assert log_action.await_args.kwargs["old_value"] is None
            assert log_action.await_args.kwargs["new_value"] == "active"
        # And once recorded it stays recorded.
        assert lic.audit_pending(state) is False


# ---------------------------------------------------------------------------
# require_feature
# ---------------------------------------------------------------------------


def _gated_app() -> FastAPI:
    """A minimal app exercising both the router-level and endpoint-level forms."""
    app = FastAPI()

    @app.get("/write", dependencies=[Depends(require_feature("hipaa", write=True))])
    def write_endpoint():
        return {"ok": True}

    # The router-level form: `write` follows the method.
    by_method = APIRouter(dependencies=[Depends(require_feature("hipaa"))])

    @by_method.get("/by-method")
    def by_method_get():
        return {"ok": True}

    @by_method.post("/by-method")
    def by_method_post():
        return {"ok": True}

    app.include_router(by_method)

    @app.get("/read", dependencies=[Depends(require_feature("hipaa", write=False))])
    def read_endpoint():
        return {"ok": True}

    @app.get("/other", dependencies=[Depends(require_feature("warehouse"))])
    def other_endpoint():
        return {"ok": True}

    return app


@pytest.fixture
def gated_client():
    app = _gated_app()
    # The gate opens its own session for the audit write; it never asks the
    # request for one, so there is no get_db override here.
    with patch("backend.app.db.session.SessionLocal", return_value=MagicMock()):
        with patch(
            "backend.app.services.audit_service.AuditService.log_action",
            new_callable=AsyncMock,
        ):
            yield TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def license_in_settings(monkeypatch, signer):
    """Install a dev-signed key in settings; returns a setter taking claims."""
    monkeypatch.setattr(
        lic.settings, "EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY", _public_pem(signer)
    )
    monkeypatch.setattr(lic.settings, "ENVIRONMENT", "test")
    monkeypatch.setenv("ENVIRONMENT", "test")

    def install(**claim_kwargs):
        monkeypatch.setattr(
            lic.settings,
            "EXPERIMENTLY_LICENSE_KEY",
            _sign(signer, _claims(**claim_kwargs)),
        )

    return install


class TestRequireFeature:
    def test_no_licence_refuses_reads_and_writes_with_the_403_body(
        self, gated_client, monkeypatch
    ):
        monkeypatch.setattr(lic.settings, "EXPERIMENTLY_LICENSE_KEY", "")
        for path in ("/write", "/read"):
            response = gated_client.get(path)
            assert response.status_code == 403
            assert response.json() == {
                "detail": {
                    "code": "feature_not_licensed",
                    "feature": "hipaa",
                    "status": "none",
                }
            }

    def test_active_licence_permits_reads_and_writes(
        self, gated_client, license_in_settings
    ):
        license_in_settings(exp=datetime.now(timezone.utc) + timedelta(days=30))
        assert gated_client.get("/write").status_code == 200
        assert gated_client.get("/read").status_code == 200

    def test_grace_permits_everything(self, gated_client, license_in_settings):
        license_in_settings(exp=datetime.now(timezone.utc) - timedelta(days=3))
        assert gated_client.get("/write").status_code == 200
        assert gated_client.get("/read").status_code == 200

    def test_read_only_window_refuses_writes_and_passes_reads(
        self, gated_client, license_in_settings
    ):
        license_in_settings(exp=datetime.now(timezone.utc) - timedelta(days=20))
        write = gated_client.get("/write")
        assert write.status_code == 403
        assert write.json()["detail"] == {
            "code": "feature_not_licensed",
            "feature": "hipaa",
            "status": "expired",
        }
        assert gated_client.get("/read").status_code == 200
        # Router-level gate, no explicit `write`: the method decides.
        assert gated_client.get("/by-method").status_code == 200
        assert gated_client.post("/by-method").status_code == 403

    def test_past_read_only_window_refuses_both(
        self, gated_client, license_in_settings
    ):
        license_in_settings(exp=datetime.now(timezone.utc) - timedelta(days=90))
        assert gated_client.get("/write").status_code == 403
        read = gated_client.get("/read")
        assert read.status_code == 403
        assert read.json()["detail"]["status"] == "expired"

    def test_unlicensed_feature_is_refused_while_a_licensed_one_passes(
        self, gated_client, license_in_settings
    ):
        license_in_settings(
            features=["hipaa"], exp=datetime.now(timezone.utc) + timedelta(days=30)
        )
        assert gated_client.get("/write").status_code == 200
        refused = gated_client.get("/other")
        assert refused.status_code == 403
        assert refused.json()["detail"] == {
            "code": "feature_not_licensed",
            "feature": "warehouse",
            "status": "active",
        }

    def test_invalid_licence_refuses_with_status_invalid(
        self, gated_client, monkeypatch, signer
    ):
        monkeypatch.setattr(
            lic.settings, "EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY", _public_pem(signer)
        )
        monkeypatch.setattr(lic.settings, "ENVIRONMENT", "test")
        monkeypatch.setattr(
            lic.settings,
            "EXPERIMENTLY_LICENSE_KEY",
            _sign(
                Ed25519PrivateKey.generate(),  # signed by a key nobody trusts
                _claims(exp=datetime.now(timezone.utc) + timedelta(days=30)),
            ),
        )
        response = gated_client.get("/read")
        assert response.status_code == 403
        assert response.json()["detail"]["status"] == "invalid"

    def test_403_body_never_carries_the_customer_or_the_key(
        self, gated_client, license_in_settings
    ):
        license_in_settings(
            features=["sso"],
            customer="Acme GmbH",
            exp=datetime.now(timezone.utc) + timedelta(days=30),
        )
        response = gated_client.get("/write")
        assert response.status_code == 403
        assert "Acme" not in response.text
        assert lic.settings.EXPERIMENTLY_LICENSE_KEY[:24] not in response.text

    @pytest.mark.regression
    def test_the_gate_never_touches_the_request_session(
        self, license_in_settings, monkeypatch
    ):
        """AuditService.log_action commits.

        If the gate borrowed the request's session, resolving the dependency
        would commit whatever else that request had pending, and a failed
        INSERT would leave the session needing a rollback -- every later query
        on it raising PendingRollbackError.  It opens its own instead.
        """
        from backend.app.api import deps

        license_in_settings(
            features=["hipaa"], exp=datetime.now(timezone.utc) + timedelta(days=30)
        )
        request_session = MagicMock(name="request_session")
        audit_session = MagicMock(name="audit_session")

        app = _gated_app()
        app.dependency_overrides[deps.get_db] = lambda: request_session
        with patch(
            "backend.app.db.session.SessionLocal", return_value=audit_session
        ) as session_local:
            with patch(
                "backend.app.services.audit_service.AuditService.log_action",
                new_callable=AsyncMock,
            ) as log_action:
                with TestClient(app, raise_server_exceptions=False) as client:
                    assert client.get("/write").status_code == 200
                    # The audit runs as a background task on the app's loop.
                    client.portal.call(lic.drain_audits)

        session_local.assert_called_once()
        assert log_action.await_args.kwargs["db"] is audit_session
        audit_session.close.assert_called_once()
        request_session.commit.assert_not_called()
        request_session.rollback.assert_not_called()

    def test_a_broken_audit_session_does_not_break_the_request(
        self, license_in_settings
    ):
        license_in_settings(
            features=["hipaa"], exp=datetime.now(timezone.utc) + timedelta(days=30)
        )
        with patch(
            "backend.app.db.session.SessionLocal",
            side_effect=RuntimeError("no connections left"),
        ):
            client = TestClient(_gated_app(), raise_server_exceptions=False)
            assert client.get("/write").status_code == 200

    @pytest.mark.regression
    def test_an_already_audited_state_opens_no_session(self, license_in_settings):
        """Once per transition, not once per request: after the first request
        has written the row, the gate must answer from memory."""
        license_in_settings(
            features=["hipaa"], exp=datetime.now(timezone.utc) + timedelta(days=30)
        )
        with patch(
            "backend.app.db.session.SessionLocal", return_value=MagicMock()
        ) as session_local:
            with patch(
                "backend.app.services.audit_service.AuditService.log_action",
                new_callable=AsyncMock,
            ):
                with TestClient(_gated_app(), raise_server_exceptions=False) as client:
                    for _ in range(5):
                        assert client.get("/write").status_code == 200
                        client.portal.call(lic.drain_audits)
        session_local.assert_called_once()


class TestAuditIsOffTheRequestPath:
    @pytest.mark.regression
    def test_a_slow_audit_write_does_not_delay_the_gate(self, license_in_settings):
        """The decision does not depend on the write, so the write must not sit
        in front of it: awaiting it inline made the first request after a
        restart wait out a database connect timeout before its 401/403/200.
        (AuditService runs the INSERT in an executor, so the slow part is an
        await, which is what this simulates.)"""
        import time

        license_in_settings(
            features=["hipaa"], exp=datetime.now(timezone.utc) + timedelta(days=30)
        )
        release = asyncio.Event()

        async def slow_log_action(**kwargs):
            await asyncio.wait_for(release.wait(), timeout=5)
            return uuid.uuid4()

        with patch.object(lic, "audit_session_factory", MagicMock):
            with patch(
                "backend.app.services.audit_service.AuditService.log_action",
                side_effect=slow_log_action,
            ):
                with TestClient(_gated_app(), raise_server_exceptions=False) as client:
                    started = time.monotonic()
                    assert client.get("/write").status_code == 200
                    elapsed = time.monotonic() - started
                    client.portal.call(release.set)
                    client.portal.call(lic.drain_audits)
        assert elapsed < 2.0, f"the gate waited {elapsed:.1f}s for the audit write"

    @pytest.mark.asyncio
    @pytest.mark.regression
    async def test_a_cancelled_write_releases_the_in_flight_slot(self, signer, keymap):
        """The write is a background task; a task cancelled with the loop that
        left the slot held would make the transition unrecordable for the
        rest of the process."""
        state = verify_license_key(
            _sign(signer, _claims(exp=NOW + timedelta(days=30))),
            now=NOW,
            public_keys=keymap,
        )
        started = asyncio.Event()

        async def hang(**kwargs):
            started.set()
            await asyncio.sleep(30)

        with patch(
            "backend.app.services.audit_service.AuditService.log_action",
            side_effect=hang,
        ):
            task = asyncio.create_task(lic.audit_license_state(MagicMock(), state))
            await started.wait()
            assert lic.audit_pending(state) is False  # in flight
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert lic.audit_pending(state) is True  # released, will be retried

    @pytest.mark.asyncio
    @pytest.mark.regression
    async def test_overlapping_transitions_cite_only_recorded_states(
        self, signer, keymap
    ):
        """Two requests straddle a licence boundary: A observes active, B
        observes grace, and A's write fails after B's succeeded. B's row
        must name the last *recorded* state (none), not A's, and A must
        remain retryable."""
        key = _sign(signer, _claims(exp=NOW + timedelta(days=30)))
        active = verify_license_key(key, now=NOW, public_keys=keymap)
        grace = verify_license_key(
            key, now=NOW + timedelta(days=31), public_keys=keymap
        )
        gate_a = asyncio.Event()
        calls = []

        async def log_action(**kwargs):
            calls.append((kwargs["old_value"], kwargs["new_value"]))
            if kwargs["new_value"] == "active":
                await gate_a.wait()
                raise RuntimeError("A's INSERT failed")
            return uuid.uuid4()

        with patch(
            "backend.app.services.audit_service.AuditService.log_action",
            side_effect=log_action,
        ):
            task_a = asyncio.create_task(lic.audit_license_state(MagicMock(), active))
            await asyncio.sleep(0)  # A is now in flight
            assert await lic.audit_license_state(MagicMock(), grace) is True
            gate_a.set()
            assert await task_a is False

        assert calls == [(None, "active"), (None, "grace")]
        assert (
            lic.audit_pending(
                active,
                now=datetime.now(timezone.utc)
                + timedelta(seconds=lic.AUDIT_RETRY_SECONDS + 1),
            )
            is True
        )

    @pytest.mark.asyncio
    @pytest.mark.regression
    async def test_out_of_order_completion_does_not_reinstate_an_older_state(
        self, signer, keymap
    ):
        """A slow write of `active` still in flight when `grace` is observed and
        written: `active` finishing last must not become the recorded state, or
        the next `grace` request would write a third, stale-old_value row."""
        key = _sign(signer, _claims(exp=NOW + timedelta(days=30)))
        active = verify_license_key(key, now=NOW, public_keys=keymap)
        grace = verify_license_key(
            key, now=NOW + timedelta(days=31), public_keys=keymap
        )
        release_active = asyncio.Event()
        rows = []

        async def log_action(**kwargs):
            rows.append((kwargs["old_value"], kwargs["new_value"]))
            if kwargs["new_value"] == "active":
                await release_active.wait()
            return uuid.uuid4()

        with patch(
            "backend.app.services.audit_service.AuditService.log_action",
            side_effect=log_action,
        ):
            slow = asyncio.create_task(lic.audit_license_state(MagicMock(), active))
            await asyncio.sleep(0)
            assert await lic.audit_license_state(MagicMock(), grace) is True
            release_active.set()
            assert await slow is True
            # `grace` is the current state and stays recorded: nothing to write.
            assert lic.audit_pending(grace) is False
            assert await lic.audit_license_state(MagicMock(), grace) is False
        assert rows == [(None, "active"), (None, "grace")]


class TestCheckFeature:
    """The synchronous twin of require_feature, for capability wrappers."""

    def test_refuses_with_the_same_403(self, license_in_settings):
        from fastapi import HTTPException

        license_in_settings(
            features=["sso"], exp=datetime.now(timezone.utc) + timedelta(days=30)
        )
        with pytest.raises(HTTPException) as excinfo:
            lic.check_feature("hipaa")
        assert excinfo.value.status_code == 403
        assert excinfo.value.detail == {
            "code": "feature_not_licensed",
            "feature": "hipaa",
            "status": "active",
        }

    def test_returns_the_state_when_allowed(self, license_in_settings):
        license_in_settings(
            features=["hipaa"], exp=datetime.now(timezone.utc) + timedelta(days=30)
        )
        assert lic.check_feature("hipaa").status is LicenseStatus.ACTIVE

    @pytest.mark.asyncio
    @pytest.mark.regression
    async def test_a_capability_observation_reaches_the_audit_trail(
        self, license_in_settings
    ):
        """A headless deployment that only ever calls a capability route (the
        compliance export, split-URL creation) observed transitions that no
        require_feature gate or /edition probe would record."""
        license_in_settings(
            features=["hipaa"], exp=datetime.now(timezone.utc) + timedelta(days=30)
        )
        with patch.object(lic, "audit_session_factory", MagicMock):
            with patch(
                "backend.app.services.audit_service.AuditService.log_action",
                new_callable=AsyncMock,
                return_value=uuid.uuid4(),
            ) as log_action:
                lic.check_feature("hipaa")
                await lic.drain_audits()
        assert log_action.await_count == 1
        assert log_action.await_args.kwargs["new_value"] == "active"

    @pytest.mark.regression
    def test_reads_survive_the_read_only_window_writes_do_not(
        self, license_in_settings
    ):
        from fastapi import HTTPException

        # Expired 20 days ago: past the 14-day grace, inside the 30-day read-only.
        license_in_settings(
            features=["hipaa"], exp=datetime.now(timezone.utc) - timedelta(days=20)
        )
        assert lic.check_feature("hipaa", write=False).status is LicenseStatus.EXPIRED
        with pytest.raises(HTTPException):
            lic.check_feature("hipaa", write=True)

    def test_unknown_feature_is_a_programming_error(self):
        with pytest.raises(ValueError):
            lic.check_feature("hippa")
