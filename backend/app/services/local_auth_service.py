"""
Local (email + password) authentication -- the default provider.

``AUTH_PROVIDER=local`` authenticates against ``users.email`` /
``users.hashed_password`` (bcrypt, see ``core.security``) and issues HS256
JWTs.  No AWS dependency.

Brute-force protection
----------------------
Failed logins are counted per e-mail address.  After
``LOCAL_AUTH_MAX_FAILED_ATTEMPTS`` failures inside a rolling window of
``LOCAL_AUTH_LOCKOUT_MINUTES`` the address is locked for the remainder of
that window and ``/auth/login`` answers ``423 Locked``.  A successful login
clears the counter.

The counter is an **in-process** dictionary.  That is deliberate: it
needs no extra infrastructure and is correct for the default single-worker
container (``WEB_CONCURRENCY=1``).  Deployments running several uvicorn
workers or replicas get an independent counter per worker, so the effective
threshold is ``LOCAL_AUTH_MAX_FAILED_ATTEMPTS x workers``.  Either accept
that (the per-IP rate limit on ``/api/v1/auth/login`` still applies) or run
a single worker.  Unknown e-mail addresses are counted too, so an attacker
cannot use the 423 as a user-enumeration oracle, and a bcrypt verification
runs against a dummy hash for unknown addresses so response time does not
reveal whether the address exists either.

The tracker sweeps expired windows periodically and caps the number of
tracked addresses, so unauthenticated traffic cannot grow it without bound.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.security import get_password_hash, verify_password
from backend.app.models.user import User

# Upper bound on distinct addresses kept in memory.  When exceeded (after a
# sweep) the entries with the oldest most-recent failure are evicted; an
# attacker spraying random addresses can therefore only evict their own noise.
MAX_TRACKED_ADDRESSES = 10_000

# How often (seconds) record_failure sweeps expired windows for every key.
SWEEP_INTERVAL_SECONDS = 60.0


class AccountLockedError(Exception):
    """Raised when the address has exceeded the failed-login threshold."""

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, int(retry_after_seconds))
        super().__init__(
            f"Too many failed login attempts; retry in {self.retry_after_seconds}s"
        )


class InvalidCredentialsError(Exception):
    """Raised for unknown e-mail, wrong password, or an inactive account."""


def _normalise_email(email: str) -> str:
    return (email or "").strip().lower()


@dataclass
class LockoutStatus:
    locked: bool
    failures: int
    retry_after_seconds: int


class LoginAttemptTracker:
    """
    Thread-safe rolling-window failure counter keyed by e-mail.

    ``max_attempts`` failures within ``window_seconds`` lock the key until the
    oldest failure ages out of the window.
    """

    def __init__(
        self,
        max_attempts: int,
        window_seconds: int,
        max_tracked: int = MAX_TRACKED_ADDRESSES,
        sweep_interval: float = SWEEP_INTERVAL_SECONDS,
    ) -> None:
        self.max_attempts = max(1, int(max_attempts))
        self.window_seconds = max(1, int(window_seconds))
        self.max_tracked = max(1, int(max_tracked))
        self.sweep_interval = max(0.0, float(sweep_interval))
        self._lock = threading.Lock()
        self._failures: Dict[str, Deque[float]] = {}
        # Clock of the last sweep, in whatever time base the caller uses
        # (time.monotonic() by default, synthetic values in tests).
        self._last_sweep: Optional[float] = None

    def __len__(self) -> int:
        with self._lock:
            return len(self._failures)

    def _sweep(self, now: float) -> None:
        """Drop every expired window, then enforce the size cap.  Caller holds the lock."""
        cutoff = now - self.window_seconds
        for key in [k for k, w in self._failures.items() if not w or w[-1] <= cutoff]:
            self._failures.pop(key, None)
        self._last_sweep = now
        overflow = len(self._failures) - self.max_tracked
        if overflow > 0:
            oldest = sorted(self._failures.items(), key=lambda item: item[1][-1])[
                :overflow
            ]
            for key, _ in oldest:
                self._failures.pop(key, None)

    def _prune(self, key: str, now: float) -> Deque[float]:
        window = self._failures.get(key)
        if window is None:
            window = deque()
            self._failures[key] = window
        cutoff = now - self.window_seconds
        while window and window[0] <= cutoff:
            window.popleft()
        if not window:
            # Drop empty keys so the dict does not grow without bound.
            self._failures.pop(key, None)
        return window

    def status(self, email: str, now: Optional[float] = None) -> LockoutStatus:
        key = _normalise_email(email)
        now = time.monotonic() if now is None else now
        with self._lock:
            window = self._prune(key, now)
            failures = len(window)
            if failures >= self.max_attempts:
                retry_after = int(window[0] + self.window_seconds - now) + 1
                return LockoutStatus(True, failures, retry_after)
            return LockoutStatus(False, failures, 0)

    def record_failure(self, email: str, now: Optional[float] = None) -> LockoutStatus:
        key = _normalise_email(email)
        now = time.monotonic() if now is None else now
        with self._lock:
            if (
                self._last_sweep is None
                or now - self._last_sweep >= self.sweep_interval
                or len(self._failures) >= self.max_tracked
            ):
                self._sweep(now)
            window = self._prune(key, now)
            window.append(now)
            self._failures[key] = window
            failures = len(window)
            if failures >= self.max_attempts:
                retry_after = int(window[0] + self.window_seconds - now) + 1
                return LockoutStatus(True, failures, retry_after)
            return LockoutStatus(False, failures, 0)

    def reset(self, email: str) -> None:
        key = _normalise_email(email)
        with self._lock:
            self._failures.pop(key, None)

    def clear(self) -> None:
        """Forget every counter (tests)."""
        with self._lock:
            self._failures.clear()


# A real bcrypt hash of a random secret: verifying against it costs the same
# as verifying a real user's password, which keeps the response time of an
# unknown address indistinguishable from a wrong password.
_DUMMY_PASSWORD_HASH = get_password_hash(secrets.token_urlsafe(24))


class LocalAuthService:
    """Email/password authentication with per-address lockout."""

    def __init__(self, tracker: Optional[LoginAttemptTracker] = None) -> None:
        # ``is not None``: an empty tracker is falsy (``__len__``).
        self.tracker = (
            tracker
            if tracker is not None
            else LoginAttemptTracker(
                max_attempts=settings.LOCAL_AUTH_MAX_FAILED_ATTEMPTS,
                window_seconds=settings.LOCAL_AUTH_LOCKOUT_MINUTES * 60,
            )
        )

    def authenticate(self, db: Session, email: str, password: str) -> User:
        """
        Return the active ``User`` matching *email*/*password*.

        Raises:
            AccountLockedError: the address is currently locked out.
            InvalidCredentialsError: unknown address, wrong password or the
                account is inactive.  The caller must not distinguish these.
        """
        email_key = _normalise_email(email)
        status = self.tracker.status(email_key)
        if status.locked:
            raise AccountLockedError(status.retry_after_seconds)

        user = (
            db.query(User).filter(User.email == email_key).first()
            if email_key
            else None
        )
        if user is None and email and email != email_key:
            # Legacy rows may have been stored with the original casing.
            user = db.query(User).filter(User.email == email.strip()).first()

        if user is not None and user.hashed_password:
            password_ok = verify_password(password or "", user.hashed_password)
        else:
            # Constant-cost path for unknown addresses / passwordless rows
            # (SSO-only accounts): burn a bcrypt verification anyway.
            verify_password(password or "", _DUMMY_PASSWORD_HASH)
            password_ok = False
        ok = password_ok and user is not None and bool(user.is_active)
        if not ok:
            # The failure that reaches the threshold is still answered with
            # 401; every attempt after it (correct password or not) gets 423
            # until the oldest failure ages out of the window.
            self.tracker.record_failure(email_key)
            raise InvalidCredentialsError("Invalid email or password")

        self.tracker.reset(email_key)
        return user


# Process-wide tracker shared by /auth/login and /auth/token (local provider).
login_attempt_tracker = LoginAttemptTracker(
    max_attempts=settings.LOCAL_AUTH_MAX_FAILED_ATTEMPTS,
    window_seconds=settings.LOCAL_AUTH_LOCKOUT_MINUTES * 60,
)
local_auth_service = LocalAuthService(tracker=login_attempt_tracker)
