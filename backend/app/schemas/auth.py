"""
Pydantic schemas for authentication.

This module defines the request and response schemas for authentication operations.
"""

from typing import Any, Dict, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# ---------------------------------------------------------------------------
# Local provider (the default) — /auth/login, /auth/me, /auth/logout
# ---------------------------------------------------------------------------


RoleName = Literal["ADMIN", "DEVELOPER", "ANALYST", "VIEWER"]


class LoginRequest(BaseModel):
    """Body for ``POST /api/v1/auth/login`` (local provider)."""

    # Plain ``str`` (not EmailStr): a malformed address is simply an unknown
    # user (401), and local accounts such as ``admin@localhost`` stay usable.
    email: str = Field(..., min_length=1, max_length=320)
    password: str = Field(..., min_length=1, max_length=256)

    @field_validator("email", mode="before")
    @classmethod
    def _strip_email(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v


class UserMe(BaseModel):
    """
    The authenticated user's own profile, as returned by ``GET /auth/me`` and
    embedded in the login response.  ``role`` is the upper-case name of the
    ``UserRole`` enum (matches the frontend ``UserRole`` type).
    """

    id: UUID
    email: str
    username: str
    full_name: Optional[str] = None
    role: RoleName
    is_superuser: bool
    is_active: bool
    auth_provider: Literal["local", "cognito"]

    model_config = ConfigDict(from_attributes=True)

    @field_validator("role", mode="before")
    @classmethod
    def _role_to_name(cls, v: Any) -> Any:
        """Accept a ``UserRole`` enum member, its name, or its lower-case value."""
        if v is None:
            return "VIEWER"
        name = getattr(v, "name", None)
        if isinstance(name, str):
            return name.upper()
        if isinstance(v, str):
            return v.upper()
        return v


class LoginResponse(BaseModel):
    """Token response for the local provider."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(..., description="Seconds until the token expires")
    user: UserMe


class SignUpRequest(BaseModel):
    """Schema for user registration request."""

    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=100)
    email: EmailStr
    given_name: str = Field(..., min_length=1, max_length=50)
    family_name: str = Field(..., min_length=1, max_length=50)

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Enforce password strength: must contain uppercase, lowercase, and digit."""
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class SignUpResponse(BaseModel):
    """Schema for user registration response."""

    user_id: str
    confirmed: bool
    message: str


class ConfirmSignUpRequest(BaseModel):
    """Schema for confirming user registration."""

    username: str
    confirmation_code: str


class ConfirmSignUpResponse(BaseModel):
    """Schema for confirmation response."""

    message: str
    confirmed: bool


class TokenResponse(BaseModel):
    """Schema for authentication token response."""

    access_token: str
    id_token: str
    refresh_token: Optional[str] = None
    expires_in: int
    token_type: str


class ForgotPasswordRequest(BaseModel):
    """Schema for forgot password request."""

    username: str


class ForgotPasswordResponse(BaseModel):
    """Schema for forgot password response."""

    message: str


class ConfirmForgotPasswordRequest(BaseModel):
    """Schema for confirming forgot password."""

    username: str
    confirmation_code: str
    new_password: str = Field(..., min_length=8, max_length=100)

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Enforce password strength: must contain uppercase, lowercase, and digit."""
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class ConfirmForgotPasswordResponse(BaseModel):
    """Schema for confirm forgot password response."""

    message: str


class RefreshTokenRequest(BaseModel):
    """Schema for refresh token request."""

    refresh_token: str


class UserInfoResponse(BaseModel):
    """Schema for user information response."""

    username: str
    attributes: Dict[str, Any]
