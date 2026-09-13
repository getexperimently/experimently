# Authentication and authorization
"""
Security utilities for authentication and authorization.

This module provides functions for password hashing, token generation,
and other security-related operations.

Security notes:
- Password hashing uses bcrypt directly (work factor 12, current best
  practice). The previous passlib wrapper was abandoned upstream and
  incompatible with bcrypt >= 4.1.
- Two token formats exist:
    * ``AUTH_PROVIDER=local`` (the default): HS256 JWTs signed
      with ``settings.SECRET_KEY`` and issued by ``create_local_access_token``.
      They are validated by ``decode_local_token`` on every request.
    * ``AUTH_PROVIDER=cognito``: opaque AWS Cognito access tokens validated
      remotely by ``CognitoAuthService``.  ``decode_token`` below is a stub
      that exists only so legacy tests can monkeypatch it; it MUST NOT be used
      for real validation.
"""

import hashlib
import hmac
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
import jwt
from fastapi.security import OAuth2PasswordBearer

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

# Bcrypt work factor; 12 rounds is the current best-practice default.
_BCRYPT_ROUNDS = 12

# Issuer claim stamped into every locally issued JWT.  ``decode_local_token``
# rejects tokens carrying any other issuer, so a Cognito token (or a JWT from
# some other service that happens to share the secret) can never be replayed
# against the local provider.
LOCAL_TOKEN_ISSUER = "experimently-local"
LOCAL_TOKEN_ALGORITHM = "HS256"

# OAuth2 password bearer scheme.  ``auto_error=False`` so that the absence of
# a token reaches ``deps.get_current_user``, which decides between the
# dev-admin bypass and a 401.  The tokenUrl keeps Swagger's "Authorize" button
# working with both providers (the /auth/token form accepts email+password
# when AUTH_PROVIDER=local).
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/token", auto_error=False
)


class InvalidTokenError(ValueError):
    """Raised when a local access token cannot be decoded or fails validation."""


def unwrap_secret(password: Any) -> str:
    """
    Return the plain-text value of *password*.

    Request schemas carry passwords as pydantic ``SecretStr`` (so they never
    leak into logs or ``repr``), while internal callers pass plain ``str``.
    ``get_password_hash``/``verify_password`` need the raw text, so every call
    site funnels through here rather than reaching for ``.get_secret_value()``
    on something that may already be a string.

    Args:
        password: A ``str`` or anything exposing ``get_secret_value()``.

    Returns:
        The plain-text password.
    """
    get_secret_value = getattr(password, "get_secret_value", None)
    if callable(get_secret_value):
        return get_secret_value()
    return password


def get_password_hash(password: str) -> str:
    """
    Hash a password using bcrypt.

    Args:
        password: Plain text password (see ``unwrap_secret`` for ``SecretStr``)

    Returns:
        Hashed password (bcrypt-format str)
    """
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against a bcrypt hash.

    Args:
        plain_password: Plain text password
        hashed_password: Bcrypt hash (as produced by get_password_hash)

    Returns:
        True if password matches hash, False otherwise
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        # Malformed hash — treat as a non-match rather than raising.
        return False


# ---------------------------------------------------------------------------
# Local provider JWTs
# ---------------------------------------------------------------------------


def role_name(role: Any) -> str:
    """Return the canonical upper-case role name (``ADMIN``, ``VIEWER`` ...)."""
    if role is None:
        return "VIEWER"
    name = getattr(role, "name", None)
    if isinstance(name, str):
        return name.upper()
    return str(role).upper()


def create_local_access_token(
    user: Any, *, expires_minutes: Optional[int] = None
) -> str:
    """
    Issue an HS256 JWT for *user* signed with ``settings.SECRET_KEY``.

    Claims: ``sub`` (user id as string UUID), ``email``, ``role``, ``iss``
    (``experimently-local``), ``iat``, ``exp`` and a random ``jti``.

    Args:
        user: A ``User`` model instance (anything with ``id``, ``email``, ``role``).
        expires_minutes: Override for ``LOCAL_AUTH_TOKEN_TTL_MINUTES``.

    Returns:
        The encoded token as a string.
    """
    ttl = (
        expires_minutes
        if expires_minutes is not None
        else settings.LOCAL_AUTH_TOKEN_TTL_MINUTES
    )
    now = datetime.now(timezone.utc)
    claims: Dict[str, Any] = {
        "sub": str(user.id),
        "email": user.email,
        "role": role_name(getattr(user, "role", None)),
        "iss": LOCAL_TOKEN_ISSUER,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=LOCAL_TOKEN_ALGORITHM)


def decode_local_token(token: str) -> Dict[str, Any]:
    """
    Decode and validate a locally issued access token.

    Verifies the signature (HS256, ``settings.SECRET_KEY``), the issuer, and
    the ``exp``/``iat`` claims; requires ``sub`` to be present.

    Raises:
        InvalidTokenError: for any malformed, expired, or foreign token.
    """
    if not token or not isinstance(token, str):
        raise InvalidTokenError("Token missing")
    try:
        return jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[LOCAL_TOKEN_ALGORITHM],
            issuer=LOCAL_TOKEN_ISSUER,
            options={"require": ["sub", "exp", "iat", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc


def decode_token(token: str) -> dict:
    """
    Decode a JWT token and return the claims.

    IMPORTANT: This is a stub implementation used exclusively for test mocking.
    In production the token is validated by AWS Cognito via CognitoAuthService
    (or by ``decode_local_token`` for the local provider).  This function MUST
    NOT be used for real token validation.

    Args:
        token: JWT token to decode

    Returns:
        Dict containing token claims (stub values only)
    """
    is_testing = os.getenv("TESTING", "").lower() in ("1", "true", "yes")
    if not is_testing:
        raise RuntimeError(
            "decode_token() is a test-only stub and must not be called outside "
            "a test context. Use decode_local_token() or CognitoAuthService."
        )
    return {
        "sub": "user_id",
        "username": "username",
        "exp": 0,
        "iat": 0,
        "email": "user@example.com",
    }


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------


def hash_api_key(api_key: str) -> str:
    """
    Hash an API key using SHA-256 for secure storage.

    Unlike passwords, API keys need fast lookup (not bcrypt) but must not
    be stored in plaintext. SHA-256 provides a one-way hash suitable for
    API key verification with constant-time comparison.

    Args:
        api_key: The plaintext API key to hash.

    Returns:
        Hex-encoded SHA-256 hash of the key.
    """
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def verify_api_key(plaintext_key: str, hashed_key: str) -> bool:
    """
    Verify an API key against its stored hash using constant-time comparison.

    Args:
        plaintext_key: The plaintext API key from the request.
        hashed_key: The stored SHA-256 hash to compare against.

    Returns:
        True if the key matches, False otherwise.
    """
    computed = hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest()
    return hmac.compare_digest(computed, hashed_key)
