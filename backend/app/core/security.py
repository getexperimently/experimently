# Authentication and authorization
"""
Security utilities for authentication and authorization.

This module provides functions for password hashing, token generation,
and other security-related operations.

Security notes:
- Password hashing uses bcrypt via passlib.  The default bcrypt work factor
  (12 rounds) is used, which meets current best practices.
- JWT validation in production is delegated entirely to AWS Cognito via
  CognitoAuthService.  The decode_token() function below is a stub used
  only in test mocking scenarios.  It MUST NOT be used for real token
  validation in production code.
"""

import logging
from passlib.context import CryptContext
from fastapi.security import OAuth2PasswordBearer
from backend.app.core.config import settings

logger = logging.getLogger(__name__)

# Create password context for hashing — bcrypt with automatic deprecation handling
# The effective work factor is 12 rounds (passlib default), which is appropriate.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 password bearer scheme for token authentication
import os as _os
# auto_error=False when Cognito isn't configured, so dev mode works without tokens
_cognito_configured = bool(_os.environ.get("COGNITO_USER_POOL_ID") and _os.environ.get("COGNITO_CLIENT_ID"))
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/token", auto_error=_cognito_configured)

def get_password_hash(password: str) -> str:
    """
    Hash a password using bcrypt.

    Args:
        password: Plain text password

    Returns:
        Hashed password
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against a hash.

    Args:
        plain_password: Plain text password
        hashed_password: Hashed password

    Returns:
        True if password matches hash, False otherwise
    """
    return pwd_context.verify(plain_password, hashed_password)

def decode_token(token: str) -> dict:
    """
    Decode a JWT token and return the claims.

    IMPORTANT: This is a stub implementation used exclusively for test mocking.
    In production the token is validated by AWS Cognito via CognitoAuthService.
    This function MUST NOT be used for real token validation.

    Args:
        token: JWT token to decode

    Returns:
        Dict containing token claims (stub values only)
    """
    import os
    is_testing = os.getenv("TESTING", "").lower() in ("1", "true", "yes")
    if not is_testing:
        raise RuntimeError(
            "decode_token() is a test-only stub and must not be called outside "
            "a test context. Production authentication must use CognitoAuthService."
        )
    return {
        "sub": "user_id",
        "username": "username",
        "exp": 0,
        "iat": 0,
        "email": "user@example.com"
    }


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
    import hashlib
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
    import hashlib
    import hmac
    computed = hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest()
    return hmac.compare_digest(computed, hashed_key)
