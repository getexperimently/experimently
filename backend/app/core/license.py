"""
Offline licence verification for the enterprise edition.

The licence gate is the seam between Community Edition (CE) and Enterprise
Edition (EE).  It is deliberately *offline*: nothing in this module opens a
socket, resolves a hostname or reads a clock other than the local one.  A
licence is a self-contained, Ed25519-signed token that the running instance
can check on its own.

Key format
----------
A licence key is two base64url (unpadded) segments joined by a dot::

    base64url(claims_json) "." base64url(signature)

The signature is an Ed25519 signature over the **ASCII bytes of the first
segment** (the base64url text, not the decoded JSON).  Signing the encoded
form means a verifier never has to reproduce the signer's exact JSON spelling.

Claims
------
``claims_json`` is a JSON object::

    {
      "customer":   "Acme GmbH",      # display name, never exposed by the API
      "plan":       "enterprise",     # informational label
      "features":   ["hipaa", "sso"], # feature names; "*" grants everything
      "iat":        1757548800,       # issued at   (unix seconds)
      "nbf":        1757548800,       # not before  (unix seconds)
      "exp":        1789084800,       # expires at  (unix seconds)
      "kid":        "2026-09",        # which public key signed this
      "grace_days": 14,               # optional, default 14
      "max_seats":  50                # optional, informational
    }

``kid`` selects the verifying key from an embedded ``{kid: pem}`` map, so a
signing key can be rotated by adding an entry to :data:`EMBEDDED_PUBLIC_KEYS`
-- the verifier itself never changes.

Status machine
--------------
=============  ============================================================
``none``       no ``EXPERIMENTLY_LICENSE_KEY`` set -- this is CE
``active``     ``nbf <= now < exp``
``grace``      ``exp <= now < exp + grace_days`` (default 14 days)
``expired``    ``now >= exp + grace_days``
``invalid``    malformed, unknown ``kid``, bad signature, revoked, or
               ``now < nbf``
=============  ============================================================

``expired`` has two sub-windows, both reported as ``expired``:

* **read-only window** -- the first :data:`READ_ONLY_DAYS` (30) days after
  grace ends.  Enterprise reads still succeed; writes are refused.
* **after that** -- reads and writes are both refused.

No licence state ever deletes or hides data.  Only enterprise *writes*, and
then enterprise *reads*, are refused; every row stays in the database and
every CE feature keeps working.

Every observed change of licence state is written to the audit trail as a
``license.*`` event (see :func:`audit_license_state`).  A write that fails is
retried once a minute; if a *different* transition is recorded first, its row
carries the last *recorded* state as ``old_value`` -- never one whose write
failed or is still in flight -- and the failed one is retried when it is next
observed, not back-filled.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Dict, Mapping, Optional, Tuple, Union

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from backend.app.core.config import settings

if TYPE_CHECKING:  # imports the API/ORM layer, which `core` must not need at runtime
    from fastapi import HTTPException
    from sqlalchemy.orm import Session

    from backend.app.models.audit_log import ActionType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Policy constants
# ---------------------------------------------------------------------------

#: Days after ``exp`` during which the licence still works exactly as if it
#: were active.  Overridable per licence via the ``grace_days`` claim.
DEFAULT_GRACE_DAYS = 14

#: Days after the grace window during which enterprise *reads* still work but
#: enterprise *writes* are refused.  After this, both are refused.
READ_ONLY_DAYS = 30

#: ``kid`` reserved for developer licences minted by
#: ``scripts/make_dev_license.py``.  Trusted only in the environments listed
#: in :data:`DEV_KEY_ENVIRONMENTS`.
DEV_KID = "dev"

#: A dev-signed licence is never trusted outside these environments, no matter
#: what ``EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY`` contains -- and the environment
#: has to be *declared* in the process environment, not merely defaulted to
#: (see :func:`_dev_key_permitted`).
DEV_KEY_ENVIRONMENTS: Tuple[str, ...] = ("development", "test")

#: The exact spellings a deployment may declare to be granted the dev key: the
#: two environments above plus the legacy ``dev`` alias config.py accepts for
#: development.  Deliberately *not* config.py's whole alias table, which also
#: maps ``demo`` to development -- the internet-facing demo stack declares
#: ``APP_ENV=demo`` and must not honour a developer-signed licence.
DEV_KEY_DECLARATIONS: frozenset = frozenset({"development", "dev", "test"})

#: Production signing keys, keyed by ``kid``.  Rotating a key means adding an
#: entry here and shipping a release; old keys stay until every licence signed
#: with them has expired.  Empty in the open-source tree: the real public keys
#: are added by the release that first issues licences against them.
EMBEDDED_PUBLIC_KEYS: Dict[str, str] = {}

#: Signing keys whose licences must no longer be honoured.  Revoking a ``kid``
#: revokes *every* licence it signed, so this is the blunt instrument: use it
#: when a signing key is compromised, not to cut off one customer.
REVOKED_KIDS: frozenset = frozenset()

#: Individual licences revoked by their ``jti`` (per-licence serial).  This is
#: the granular revocation path: one entry stops one licence, leaving every
#: other licence signed by the same key working.  A licence issued without a
#: ``jti`` cannot be revoked this way, which is why the signer always sets one.
REVOKED_JTIS: frozenset = frozenset()

#: Feature name that grants every feature (used by developer licences).
WILDCARD_FEATURE = "*"

#: The feature names a licence may grant -- one per Enterprise group in
#: ``ee-manifest.txt``, in the same order.  This tuple is the contract between
#: three places that have no other way to agree:
#:
#: * the ``features`` claim a signed licence carries,
#: * :func:`require_feature`, which names one per gated route,
#: * ``frontend/src/services/edition.ts``'s ``FEATURES``, which the dashboard
#:   passes to ``useFeature()`` to decide what chrome to render.
#:
#: A typo in any of them is silent -- the feature is simply never granted, and
#: the dashboard hides a tab the licence paid for.  ``require_feature`` rejects
#: an unknown name at import time, and
#: ``backend/tests/unit/core/test_feature_names.py`` pins the dashboard's copy
#: against this one.
KNOWN_FEATURES: Tuple[str, ...] = (
    "workspaces",
    "hipaa",
    "compliance",
    "sso",
    "rbac",
    "warehouse",
    "integrations",
    "counters",
    "etl",
    "split_url",
)

#: Widest instant a claim may name.  ``datetime.fromtimestamp`` raises
#: ``OSError``/``OverflowError``/``ValueError`` outside the platform's range,
#: and ``expires_at + timedelta(days=grace_days)`` overflows well before it, so
#: an authentic-but-absurd ``exp`` would turn every request into a 500 rather
#: than a licence decision.  Bound the claims instead.
MIN_TIMESTAMP = 0  # 1970-01-01T00:00:00Z
MAX_TIMESTAMP = 253402300799  # 9999-12-31T23:59:59Z

#: Upper bound on the ``grace_days`` claim (ten years).  Out-of-range values
#: fall back to :data:`DEFAULT_GRACE_DAYS`, exactly as a negative one does.
MAX_GRACE_DAYS = 3650

_DATETIME_MAX_UTC = datetime.max.replace(tzinfo=timezone.utc)
_DATETIME_MIN_UTC = datetime.min.replace(tzinfo=timezone.utc)


def _from_timestamp(seconds: int) -> datetime:
    """``datetime.fromtimestamp`` that saturates instead of raising.

    :func:`_verify_signature` already refuses claims outside
    ``MIN_TIMESTAMP..MAX_TIMESTAMP``; this covers a :class:`LicenseClaims`
    built directly (tests, ``scripts/make_dev_license.py``) and the platforms
    whose C library gives up earlier than ours does.
    """
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return _DATETIME_MAX_UTC if seconds > 0 else _DATETIME_MIN_UTC


def _add_days(moment: datetime, days: int) -> datetime:
    """``moment + days`` that saturates at :data:`datetime.max` instead of raising."""
    try:
        return moment + timedelta(days=days)
    except OverflowError:
        return _DATETIME_MAX_UTC


_REQUIRED_CLAIMS = ("customer", "plan", "features", "iat", "nbf", "exp", "kid")


class LicenseStatus(str, Enum):
    """Resolved licence state.  Serialises as its lowercase value."""

    NONE = "none"
    ACTIVE = "active"
    GRACE = "grace"
    EXPIRED = "expired"
    INVALID = "invalid"


# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------


def b64url_encode(raw: bytes) -> str:
    """base64url-encode ``raw`` without padding."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64url_decode(segment: str) -> bytes:
    """base64url-decode ``segment``, restoring stripped padding."""
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LicenseClaims:
    """The verified contents of a licence key."""

    customer: str
    plan: str
    features: Tuple[str, ...]
    iat: int
    nbf: int
    exp: int
    kid: str
    #: Per-licence serial, so a single licence can be revoked without
    #: revoking every licence the same key signed.  Optional for licences
    #: issued before it existed; the signer sets one on every new licence.
    jti: Optional[str] = None
    grace_days: int = DEFAULT_GRACE_DAYS
    max_seats: Optional[int] = None

    @property
    def expires_at(self) -> datetime:
        return _from_timestamp(self.exp)

    @property
    def not_before(self) -> datetime:
        return _from_timestamp(self.nbf)

    @property
    def grace_ends_at(self) -> datetime:
        return _add_days(self.expires_at, self.grace_days)

    @property
    def read_only_ends_at(self) -> datetime:
        return _add_days(self.grace_ends_at, READ_ONLY_DAYS)


@dataclass(frozen=True)
class LicenseState:
    """A licence resolved against a point in time.

    ``reason`` carries a short machine-readable explanation for
    :attr:`LicenseStatus.INVALID` (``bad_signature``, ``unknown_kid``,
    ``not_yet_valid``, ...).  It is diagnostic only and is never returned by
    the public ``/edition`` endpoint.
    """

    status: LicenseStatus
    features: Tuple[str, ...] = ()
    plan: Optional[str] = None
    customer: Optional[str] = None
    kid: Optional[str] = None
    expires_at: Optional[datetime] = None
    max_seats: Optional[int] = None
    reason: Optional[str] = None
    #: True while enterprise reads are still permitted in the ``expired``
    #: read-only window.  Meaningless for the other states.
    reads_allowed: bool = False
    evaluated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc), compare=False
    )

    # -- predicates --------------------------------------------------------

    @property
    def is_enterprise(self) -> bool:
        """True when the instance is running against a real licence.

        ``expired`` counts: the dashboard still shows enterprise chrome (with
        a lapsed banner) so the operator can see what they have lost.
        """
        return self.status in (
            LicenseStatus.ACTIVE,
            LicenseStatus.GRACE,
            LicenseStatus.EXPIRED,
        )

    @property
    def edition(self) -> str:
        return "enterprise" if self.is_enterprise else "ce"

    def grants(self, feature: str) -> bool:
        """True when the licence *names* ``feature`` (ignoring expiry)."""
        return WILDCARD_FEATURE in self.features or feature in self.features

    def allows(self, feature: str, *, write: bool = True) -> bool:
        """True when ``feature`` may be used right now.

        ``none``/``invalid``  -> never.
        ``active``/``grace``  -> whenever the licence names the feature.
        ``expired``           -> reads only, and only inside the 30-day
                                 read-only window.
        """
        if not self.grants(feature):
            return False
        if self.status in (LicenseStatus.ACTIVE, LicenseStatus.GRACE):
            return True
        if self.status is LicenseStatus.EXPIRED:
            return (not write) and self.reads_allowed
        return False


# ---------------------------------------------------------------------------
# Public-key resolution
# ---------------------------------------------------------------------------


def public_key_map() -> Dict[str, str]:
    """Return ``{kid: pem}`` for every key this process will verify against.

    The embedded production map, plus the developer key from
    ``EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY`` when the process environment
    explicitly names one of :data:`DEV_KEY_ENVIRONMENTS`.  The dev key can
    never shadow an embedded one: embedded entries win.
    """
    keys: Dict[str, str] = {}
    dev_pem = (
        getattr(settings, "EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY", "") or ""
    ).strip()
    if dev_pem:
        if _dev_key_permitted():
            keys[DEV_KID] = dev_pem
        else:
            _warn_dev_key_ignored_once()
    keys.update(EMBEDDED_PUBLIC_KEYS)
    return keys


_dev_key_warned = False


def _warn_dev_key_ignored_once() -> None:
    """Say why a configured developer key is being ignored -- once.

    Nothing else does: ``/api/v1/edition`` deliberately carries no reason and
    the 403 body names only the feature and the status, so an operator who
    followed the dev-licence instructions and forgot to declare the
    environment saw "invalid" with no way to learn why.
    """
    global _dev_key_warned
    if _dev_key_warned:
        return
    _dev_key_warned = True
    logger.warning(
        "EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY is set but ignored: a developer-signed "
        "licence is honoured only when the *process environment* declares "
        "ENVIRONMENT=development or ENVIRONMENT=test (a value in an env file "
        "read by settings does not count). Any dev-signed licence will resolve "
        "to invalid/unknown_kid until it does."
    )


def _dev_key_permitted() -> bool:
    """Whether a developer-signed licence may be honoured here.

    ``settings.ENVIRONMENT`` is not enough on its own: it *defaults* to
    ``development``, so a deployment that simply never sets it -- a plain
    ``docker run`` of the image, a chart or task definition missing the
    variable -- would accept a self-minted developer licence and unlock every
    enterprise feature.  The environment therefore has to be named
    **explicitly** in the process environment, and name a development one.
    Anything else, including saying nothing at all, is treated as production.

    "Named explicitly" is ``config.ENVIRONMENT_DECLARED``, captured when the
    settings module loaded, *before* it mirrored the resolved default back
    into ``APP_ENV`` for legacy readers -- reading ``os.environ`` here after
    that mirror ran would see ``APP_ENV=dev`` on an undeclared process and
    open the gate, which is exactly the hole this function closes.
    """
    from backend.app.core import config as _config

    if not _config.ENVIRONMENT_DECLARED:
        return False
    declared = (
        (os.environ.get("ENVIRONMENT") or os.environ.get("APP_ENV") or "")
        .strip()
        .lower()
    )
    return declared in DEV_KEY_DECLARATIONS


def _load_public_key(pem: str) -> Optional[Ed25519PublicKey]:
    # A PEM that travelled through an environment file or a shell export often
    # arrives with its newlines as the two characters `\n`; accept that form,
    # since the alternative is an `unknown_kid` that names nothing.
    if "\\n" in pem and "\n" not in pem.strip():
        pem = pem.replace("\\n", "\n")
    try:
        loaded = load_pem_public_key(pem.encode("utf-8"))
    except Exception:  # malformed PEM in the map / in the env var
        logger.warning("Licence public key could not be parsed; ignoring it")
        return None
    if not isinstance(loaded, Ed25519PublicKey):
        logger.warning("Licence public key is not Ed25519; ignoring it")
        return None
    return loaded


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Verification:
    """Result of the time-independent half of verification (cacheable)."""

    claims: Optional[LicenseClaims] = None
    error: Optional[str] = None


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _verify_signature(raw_key: str, keys: Mapping[str, str]) -> _Verification:
    """Structure, ``kid`` lookup, signature and claim types.

    Deliberately contains **no** time comparison, so the result can be cached
    for the lifetime of the key: ``nbf``/``exp`` are applied afterwards.
    """
    parts = raw_key.split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return _Verification(error="malformed")
    claims_segment, signature_segment = parts

    try:
        claims_bytes = b64url_decode(claims_segment)
        signature = b64url_decode(signature_segment)
    except (binascii.Error, ValueError):
        return _Verification(error="malformed")

    try:
        payload = json.loads(claims_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _Verification(error="malformed_claims")
    if not isinstance(payload, dict):
        return _Verification(error="malformed_claims")

    missing = [name for name in _REQUIRED_CLAIMS if name not in payload]
    if missing:
        return _Verification(error=f"missing_claim:{missing[0]}")

    kid = payload["kid"]
    if not isinstance(kid, str) or not kid:
        return _Verification(error="unknown_kid")
    pem = keys.get(kid)
    if pem is None:
        return _Verification(error="unknown_kid")
    public_key = _load_public_key(pem)
    if public_key is None:
        return _Verification(error="unknown_kid")

    try:
        public_key.verify(signature, claims_segment.encode("ascii"))
    except (InvalidSignature, UnicodeEncodeError):
        return _Verification(error="bad_signature")

    # --- claim types (only reachable for authentic claims) ---
    features = payload["features"]
    if not isinstance(features, list) or not all(isinstance(f, str) for f in features):
        return _Verification(error="malformed_claims")
    iat, nbf, exp = (_coerce_int(payload[name]) for name in ("iat", "nbf", "exp"))
    if iat is None or nbf is None or exp is None:
        return _Verification(error="malformed_claims")
    customer, plan = payload["customer"], payload["plan"]
    if not isinstance(customer, str) or not isinstance(plan, str):
        return _Verification(error="malformed_claims")

    if not all(MIN_TIMESTAMP <= value <= MAX_TIMESTAMP for value in (iat, nbf, exp)):
        return _Verification(error="malformed_claims")

    jti = payload.get("jti")
    if jti is not None and not isinstance(jti, str):
        return _Verification(error="malformed_claims")

    grace_days = _coerce_int(payload.get("grace_days", DEFAULT_GRACE_DAYS))
    if grace_days is None or not (0 <= grace_days <= MAX_GRACE_DAYS):
        grace_days = DEFAULT_GRACE_DAYS
    max_seats = _coerce_int(payload.get("max_seats"))

    return _Verification(
        claims=LicenseClaims(
            customer=customer,
            plan=plan,
            features=tuple(features),
            iat=iat,
            nbf=nbf,
            exp=exp,
            kid=kid,
            jti=jti,
            grace_days=grace_days,
            max_seats=max_seats,
        )
    )


# Verification is pure and moderately expensive (a PEM parse plus an Ed25519
# verify), so the time-independent half is memoised per (key, key-map).
#
# The cache is bounded and LRU.  In a normal process it holds exactly one
# entry -- the configured licence -- but `verify_license_key` is public and
# takes an arbitrary key, so an unbounded dict would let a caller that checks
# attacker-supplied keys grow it without limit.
_VERIFY_CACHE_MAX = 64
_verify_lock = threading.Lock()
_verify_cache: "OrderedDict[Tuple[str, Tuple[Tuple[str, str], ...]], _Verification]" = (
    OrderedDict()
)


def _verify_cached(raw_key: str, keys: Mapping[str, str]) -> _Verification:
    cache_key = (raw_key, tuple(sorted(keys.items())))
    with _verify_lock:
        cached = _verify_cache.get(cache_key)
        if cached is not None:
            _verify_cache.move_to_end(cache_key)
    if cached is not None:
        return cached
    result = _verify_signature(raw_key, keys)
    with _verify_lock:
        _verify_cache[cache_key] = result
        _verify_cache.move_to_end(cache_key)
        while len(_verify_cache) > _VERIFY_CACHE_MAX:
            _verify_cache.popitem(last=False)
    return result


def revocation_reason(claims: LicenseClaims) -> Optional[str]:
    """``"revoked"`` when this licence is on either revocation list.

    Deliberately **outside** :func:`_verify_cached`: the cached half is the
    signature check, which can never change for a given key, while the
    revocation lists can (a release ships a new one, a test patches one).
    Caching a revocation decision would keep honouring a licence revoked
    after it was first seen -- or, with a stale cache, keep refusing one.
    """
    if claims.kid in REVOKED_KIDS:
        return "revoked"
    if claims.jti is not None and claims.jti in REVOKED_JTIS:
        return "revoked"
    return None


def _state_from_claims(claims: LicenseClaims, now: datetime) -> LicenseState:
    if now < claims.not_before:
        return LicenseState(
            status=LicenseStatus.INVALID,
            kid=claims.kid,
            reason="not_yet_valid",
            evaluated_at=now,
        )

    if now < claims.expires_at:
        status = LicenseStatus.ACTIVE
    elif now < claims.grace_ends_at:
        status = LicenseStatus.GRACE
    else:
        status = LicenseStatus.EXPIRED

    return LicenseState(
        status=status,
        features=claims.features,
        plan=claims.plan,
        customer=claims.customer,
        kid=claims.kid,
        expires_at=claims.expires_at,
        max_seats=claims.max_seats,
        reads_allowed=now < claims.read_only_ends_at,
        evaluated_at=now,
    )


def verify_license_key(
    raw_key: Optional[str],
    *,
    now: Optional[datetime] = None,
    public_keys: Optional[Mapping[str, str]] = None,
) -> LicenseState:
    """Resolve ``raw_key`` to a :class:`LicenseState`.  Pure; never raises.

    Args:
        raw_key: the ``base64url(claims).base64url(sig)`` token, or ``None``.
        now: evaluation instant (defaults to ``datetime.now(timezone.utc)``).
        public_keys: ``{kid: pem}`` override; defaults to
            :func:`public_key_map`.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    candidate = (raw_key or "").strip()
    if not candidate:
        return LicenseState(status=LicenseStatus.NONE, evaluated_at=now)

    keys = public_key_map() if public_keys is None else dict(public_keys)
    verified = _verify_cached(candidate, keys)
    if verified.claims is None:
        return LicenseState(
            status=LicenseStatus.INVALID,
            reason=verified.error or "invalid",
            evaluated_at=now,
        )
    revoked = revocation_reason(verified.claims)
    if revoked is not None:
        return LicenseState(
            status=LicenseStatus.INVALID,
            kid=verified.claims.kid,
            reason=revoked,
            evaluated_at=now,
        )
    return _state_from_claims(verified.claims, now)


def current_license_state(*, now: Optional[datetime] = None) -> LicenseState:
    """Resolve ``settings.EXPERIMENTLY_LICENSE_KEY`` against the clock."""
    return verify_license_key(
        getattr(settings, "EXPERIMENTLY_LICENSE_KEY", "") or "", now=now
    )


def reset_license_cache() -> None:
    """Drop the verification cache and the audited-state marker.

    Used by tests and by anything that reloads settings at runtime.
    """
    global _dev_key_warned
    with _verify_lock:
        _verify_cache.clear()
    with _audit_lock:
        global _last_recorded, _in_flight, _write_seq, _recorded_seq
        _last_recorded = None
        _in_flight = None
        _write_seq = 0
        _recorded_seq = 0
        _audit_retry_after.clear()
    _dev_key_warned = False


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

# Namespace for the synthetic entity id an audit row needs (``entity_id`` is
# NOT NULL).  Derived from the ``kid`` so every licence signed by one key maps
# to one stable id, the way SafetyService uses a fixed default config id.
_LICENSE_ENTITY_NAMESPACE = uuid.NAMESPACE_URL

_Fingerprint = Tuple[str, Optional[str], Optional[str]]

_audit_lock = threading.Lock()
#: The last transition whose row is *in the database* -- only ever set after a
#: successful write, so the next row's ``old_value`` is always a recorded state.
_last_recorded: Optional[_Fingerprint] = None
#: The transition whose write is in progress, so overlapping requests that
#: observe the same state do not each open a session and write a row.
_in_flight: Optional[_Fingerprint] = None
#: Monotonic id of the most recently *started* write, and the id of the write
#: that last set ``_last_recorded``.  Two overlapping writes for different
#: transitions can finish out of order; only the newer one may own the
#: recorded state, or the older transition would be re-audited with a stale
#: ``old_value`` on the next request.
_write_seq = 0
_recorded_seq = 0

#: After a failed audit write the transition is retried, but not on every
#: request: while the database is down, one attempt per this many seconds.
AUDIT_RETRY_SECONDS = 60
#: Per fingerprint, so a failed write for one transition does not hold up a
#: *different* transition that arrives inside the window.
_audit_retry_after: Dict[Tuple[str, Optional[str], Optional[str]], datetime] = {}


def audit_fingerprint(state: LicenseState) -> Tuple[str, Optional[str], Optional[str]]:
    """What makes two licence states the *same* for audit purposes.

    The audited label, not the bare status: `reads_allowed` is part of the
    identity of the state, not a detail of it.  The day an `expired` licence
    stops serving enterprise reads is a real transition an operator has to
    see, and both sides of it report `status == "expired"`, so a fingerprint
    taken from the status alone made that day silent.
    """
    return (_audit_new_value(state), state.kid, state.reason)


def audit_pending(state: LicenseState, *, now: Optional[datetime] = None) -> bool:
    """True when *state* is a transition the trail has not recorded yet.

    Cheap and lock-only: the gate calls this on every request and opens a
    database session only when it answers True, which is once per transition
    in the life of a process (plus one retry a minute after a failed write).
    """
    now = now or datetime.now(timezone.utc)
    fingerprint = audit_fingerprint(state)
    with _audit_lock:
        if fingerprint in (_last_recorded, _in_flight):
            return False
        retry_after = _audit_retry_after.get(fingerprint)
        return retry_after is None or now >= retry_after


def license_entity_id(kid: Optional[str]) -> uuid.UUID:
    """Stable synthetic ``entity_id`` for the licence audit rows."""
    return uuid.uuid5(
        _LICENSE_ENTITY_NAMESPACE, f"experimently:license:{kid or 'none'}"
    )


def _action_type_for(status: LicenseStatus) -> "ActionType":
    from backend.app.models.audit_log import ActionType

    return {
        LicenseStatus.NONE: ActionType.LICENSE_NONE,
        LicenseStatus.ACTIVE: ActionType.LICENSE_ACTIVE,
        LicenseStatus.GRACE: ActionType.LICENSE_GRACE,
        LicenseStatus.EXPIRED: ActionType.LICENSE_EXPIRED,
        LicenseStatus.INVALID: ActionType.LICENSE_INVALID,
    }[status]


async def audit_license_state(db: "Session", state: LicenseState) -> bool:
    """Write a ``license.*`` audit event when the licence state has changed.

    Returns True when an event was emitted.  Best-effort in both directions:
    a failed write is logged and swallowed (the licence gate must never break
    a request), and the state is marked as audited either way so a database
    problem cannot turn every request into a failed INSERT.
    """
    global _last_recorded, _in_flight, _write_seq, _recorded_seq

    label = _audit_new_value(state)
    fingerprint = audit_fingerprint(state)
    now = datetime.now(timezone.utc)
    with _audit_lock:
        if fingerprint in (_last_recorded, _in_flight):
            return False
        retry_after = _audit_retry_after.get(fingerprint)
        if retry_after is not None and now < retry_after:
            return False
        # `old_value` is the last *recorded* state, never one whose write is
        # still in flight or failed: two overlapping requests that straddle a
        # licence boundary must not produce a row citing a state that was
        # never written.
        previous = _last_recorded
        _in_flight = fingerprint
        _audit_retry_after.pop(fingerprint, None)
        _write_seq += 1
        my_seq = _write_seq

    recorded = False
    try:
        from backend.app.models.audit_log import EntityType
        from backend.app.services.audit_service import AuditService

        audit_id = await AuditService.log_action(
            db=db,
            user_id=None,  # system event, no actor
            user_email="system",
            action_type=_action_type_for(state.status),
            entity_type=EntityType.LICENSE,
            entity_id=license_entity_id(state.kid),
            # Not the customer name.  Audit rows are readable by ANALYST and
            # VIEWER, and the licensee is commercial information that those
            # roles have no reason to see; the `kid` identifies the licence
            # just as well for anyone reading the trail.
            entity_name=f"license:{state.kid or 'none'}"[:255],
            old_value=previous[0] if previous else None,
            new_value=label,
            reason=state.reason or state.plan,
        )
        # log_action swallows every exception and answers None, so a failed
        # INSERT arrives here as a return value, not as an exception.  Treat it
        # as one: without this the retry path below was unreachable.
        if audit_id is None:
            raise RuntimeError("AuditService.log_action returned None")
        recorded = True
    except Exception as exc:
        logger.warning("Failed to audit licence state %s: %s", state.status.value, exc)
        # log_action commits, and a failed INSERT leaves the session needing a
        # rollback; without one, every later query on it raises.
        try:
            db.rollback()
        except Exception:  # pragma: no cover - the session may already be gone
            logger.debug("Licence audit rollback failed", exc_info=True)
        # The transition is not recorded, so do not pretend it was: the next
        # request retries -- but not every request, or an outage turns the
        # gate into a failed INSERT per call.  One attempt a minute until it
        # lands.
        with _audit_lock:
            _audit_retry_after[fingerprint] = datetime.now(timezone.utc) + timedelta(
                seconds=AUDIT_RETRY_SECONDS
            )
    finally:
        # Release the in-flight slot on *every* exit -- success, failure, and
        # cancellation.  The write runs as a background task, and a task
        # cancelled with the event loop (server shutdown, a test client's loop
        # closing) that left the slot held would make this transition
        # unrecordable for the rest of the process.
        with _audit_lock:
            if recorded and my_seq > _recorded_seq:
                _last_recorded = fingerprint
                _recorded_seq = my_seq
            if _in_flight == fingerprint:
                _in_flight = None
    return recorded


def _audit_new_value(state: LicenseState) -> str:
    """The audited state, distinguishing the two halves of ``expired``."""
    if state.status is LicenseStatus.EXPIRED and not state.reads_allowed:
        return "expired:no_reads"
    if state.status is LicenseStatus.EXPIRED:
        return "expired:read_only"
    return str(state.status.value)


def _default_audit_session() -> "Session":
    """A session on the application engine (``backend.app.db.session``)."""
    from backend.app.db.session import SessionLocal

    return SessionLocal()


#: How the gate opens the session for its audit write.  A module attribute so
#: the test suite can point it at the per-process test database (the
#: application engine targets a database the suite never creates), and so a
#: deployment with a separate audit database could do the same.
audit_session_factory: Callable[[], "Session"] = _default_audit_session


async def audit_on_a_dedicated_session(state: LicenseState) -> bool:
    """Audit *state* on a short-lived session of the licence gate's own.

    The gate must not touch the request's session.  ``AuditService.log_action``
    **commits**, so borrowing it would commit whatever else the request had
    pending at that moment, and a failed INSERT would leave the request's
    session in a state where every later query raises.  Opening one session,
    writing one row and closing it keeps the two transactions apart.

    Never raises: a licence audit failing is not a reason to fail a request.
    """
    if not audit_pending(state):
        return False  # the common case: nothing to write, no session opened

    db = None
    try:
        db = audit_session_factory()
        return await audit_license_state(db, state)
    except Exception as exc:
        # Including the pool being exhausted, which is exactly when a request
        # most needs the gate to answer rather than raise.
        logger.warning("Licence audit session failed: %s", exc)
        return False
    finally:
        if db is not None:
            db.close()


#: Audit writes in progress, held so the event loop does not garbage-collect
#: a task nothing else references.  Tests drain it with :func:`drain_audits`.
_audit_tasks: "set[asyncio.Task[bool]]" = set()


def schedule_audit(state: LicenseState) -> Optional["asyncio.Task[bool]"]:
    """Record *state*'s transition in the background, if it is one.

    The gate's decision does not depend on the audit, so the write must not
    sit in front of it: awaiting it inline meant the first request after a
    restart with the database still coming up waited out a connect timeout
    (and paid it again at every retry) before receiving a 401, 403 or 200.
    The fast path -- nothing to record -- costs a lock and returns None.
    """
    if not audit_pending(state):
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # no loop: a sync caller; nothing to schedule onto
        return None
    task = loop.create_task(audit_on_a_dedicated_session(state))
    _audit_tasks.add(task)
    task.add_done_callback(_audit_tasks.discard)
    return task


async def drain_audits() -> None:
    """Wait for every audit write scheduled on *this* loop to finish (tests).

    A task left behind by a loop that has since closed (a test client's
    per-request loop, say) can never be awaited from another loop -- gathering
    it raises "future belongs to a different loop" -- so those are dropped.
    """
    loop = asyncio.get_running_loop()
    mine = []
    for task in list(_audit_tasks):
        if task.get_loop() is loop:
            mine.append(task)
        else:
            _audit_tasks.discard(task)
    if mine:
        await asyncio.gather(*mine, return_exceptions=True)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def _refusal(state: LicenseState, name: str) -> "HTTPException":
    """The 403 every unlicensed use of *name* gets, in one shape."""
    from fastapi import HTTPException
    from fastapi import status as http_status

    return HTTPException(
        status_code=http_status.HTTP_403_FORBIDDEN,
        detail={
            "code": "feature_not_licensed",
            "feature": name,
            "status": state.status.value,
        },
    )


def check_feature(name: str, write: bool = True) -> LicenseState:
    """Synchronous licence check for code that is not a FastAPI dependency.

    Raises the same 403 as :func:`require_feature`.  Used by the Enterprise
    registration to wrap a capability whose *route* is Community (the URL
    exists in every edition) but whose *body* is licensed.  Audits the
    transition like the router gate does, when an event loop is running.
    """
    if name not in KNOWN_FEATURES:
        raise ValueError(
            f"unknown feature {name!r}; known: {', '.join(KNOWN_FEATURES)}"
        )
    state = current_license_state()
    # A transition observed only through a capability (a headless deployment
    # that calls nothing but the compliance export, say) still has to reach
    # the trail; schedule_audit is a no-op without a running loop.
    schedule_audit(state)
    if not state.allows(name, write=write):
        raise _refusal(state, name)
    return state


#: HTTP methods the gate treats as reads when ``write`` is left to the method.
READ_METHODS: frozenset = frozenset({"GET", "HEAD", "OPTIONS"})


WritePredicate = Callable[[Any], bool]


def require_feature(
    name: str, write: Union[bool, WritePredicate, None] = None
) -> Callable:
    """Build a dependency that refuses unlicensed use of ``name``.

    Usable on a single endpoint or on a whole router::

        router = APIRouter(dependencies=[Depends(require_feature("hipaa"))])

        @router.get("/x", dependencies=[Depends(require_feature("hipaa", write=False))])

    ``write`` decides what the ``expired`` read-only window allows.  Left as
    ``None`` -- the router-level form -- it follows the request method:
    ``GET``/``HEAD``/``OPTIONS`` are reads, everything else is a write.  Pass
    a bool to override (``write=False`` on an SSO login router whose ``POST``
    is not a data write in the licence sense), or a callable taking the
    request for routers where the verb is not the whole story -- a ``POST``
    that runs a read-only warehouse query is a read.

    Refusal is ``403`` with::

        {"detail": {"code": "feature_not_licensed",
                    "feature": name,
                    "status": "<none|active|grace|expired|invalid>"}}

    The audit write runs on a session of its own (see
    :func:`audit_on_a_dedicated_session`), never the request's.
    """
    if name not in KNOWN_FEATURES:
        # Raised while the router is being built, so a typo is a start-up
        # failure rather than a route that silently refuses everyone.
        raise ValueError(
            f"unknown feature {name!r}; add it to KNOWN_FEATURES (and to "
            f"frontend/src/services/edition.ts) first. Known: "
            f"{', '.join(KNOWN_FEATURES)}"
        )

    # Imported lazily so that verifying a licence never needs the API layer:
    # ``verify_license_key`` is pure and ``core`` stays importable on its own.
    from fastapi import Request

    async def _require_feature(request) -> LicenseState:  # type: ignore[no-untyped-def]
        state = current_license_state()
        schedule_audit(state)
        if write is None:
            is_write = request.method.upper() not in READ_METHODS
        elif callable(write):
            is_write = bool(write(request))
        else:
            is_write = write
        if not state.allows(name, write=is_write):
            raise _refusal(state, name)
        return state

    # The annotation is set as an object, not written inline: this module uses
    # `from __future__ import annotations`, so an inline `request: Request`
    # would be the *string* "Request", which FastAPI resolves against the
    # function's globals -- where the lazily imported name does not exist --
    # and then treats the parameter as a required query string.
    _require_feature.__annotations__ = {"request": Request, "return": LicenseState}
    _require_feature.__name__ = f"require_feature_{name}"
    return _require_feature
