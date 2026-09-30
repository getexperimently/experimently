"""
User schema models for validation and serialization.

This module defines Pydantic models for user-related data structures.
These models are used for request/response validation and documentation.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
)

from backend.app.schemas.auth import RoleName

#: bcrypt reads at most 72 bytes of a password; the hashing library refuses a
#: longer one outright, so the rule refuses it first, with a readable message.
PASSWORD_MAX_BYTES = 72
PASSWORD_MIN_LENGTH = 8

#: A password that is not valid text (a lone UTF-16 surrogate, which JSON can
#: carry as ``"\ud800"``) cannot be encoded to bytes, hashed or compared.
#: The message is fixed and never includes the value.
PASSWORD_NOT_TEXT_MESSAGE = "Password must be valid text"


def check_password_strength(password: str) -> str:
    """Return ``password`` if it meets the password rules; raise ``ValueError`` if not.

    The one rule for every password a client sets -- a new account, a change
    of your own password, an administrator's reset of someone else's:

    * valid text (encodable as UTF-8);
    * at least 8 characters;
    * at most 72 bytes once encoded as UTF-8 (bcrypt's limit);
    * at least one upper-case letter, one lower-case letter and one digit.

    The length check is here as well as in ``Field(min_length=8)`` on the
    models that declare one, because a field validator runs even where the
    field has no such constraint (``UserUpdate.password``). No message
    includes the submitted value.
    """
    try:
        encoded = password.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(PASSWORD_NOT_TEXT_MESSAGE) from None
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(
            f"Password must be at least {PASSWORD_MIN_LENGTH} characters long"
        )
    if len(encoded) > PASSWORD_MAX_BYTES:
        raise ValueError(
            f"Password must be at most {PASSWORD_MAX_BYTES} bytes long "
            "(UTF-8); most characters outside English take two or more bytes"
        )
    if not any(c.isupper() for c in password):
        raise ValueError("Password must contain at least one uppercase letter")
    if not any(c.islower() for c in password):
        raise ValueError("Password must contain at least one lowercase letter")
    if not any(c.isdigit() for c in password):
        raise ValueError("Password must contain at least one digit")
    return password


class UserBase(BaseModel):
    """Base user model."""

    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    full_name: Optional[str] = None
    is_active: bool = True
    is_superuser: bool = False

    model_config = ConfigDict(from_attributes=True)


class UserCreate(UserBase):
    """User creation model."""

    password: SecretStr = Field(..., min_length=8)
    role: Optional[RoleName] = Field(
        None,
        description=(
            "RBAC role name (ADMIN, DEVELOPER, ANALYST or VIEWER; case-insensitive). "
            "Defaults to VIEWER."
        ),
    )

    @field_validator("role", mode="before")
    @classmethod
    def normalise_role(cls, v: Any) -> Any:
        """Accept ``UserRole`` members and lower-/upper-case names alike."""
        if v is None:
            return None
        name = getattr(v, "name", None)
        if isinstance(name, str):
            return name.upper()
        return v.upper() if isinstance(v, str) else v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: SecretStr) -> SecretStr:
        """Validate password strength."""
        check_password_strength(v.get_secret_value())
        return v


class UserUpdate(UserBase):
    """User update model."""

    # ``password`` sets ANOTHER account's password (a superuser's reset). Your
    # own password is changed with ``POST /api/v1/users/me/password``, which
    # asks for the current one; sending your own ``password`` here is refused
    # (``apply_password_change`` in the users endpoints). The docstring above
    # is published in the stable contract, so this note is a comment.
    password: Optional[SecretStr] = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: Optional[SecretStr]) -> Optional[SecretStr]:
        """The same rule as ``UserCreate``; ``None`` (no change) passes."""
        if v is not None:
            check_password_strength(v.get_secret_value())
        return v


class UserInDBBase(UserBase):
    """Base model for users in DB."""

    id: str

    model_config = ConfigDict(from_attributes=True)


class User(UserInDBBase):
    """User model for responses."""


class UserInDB(UserInDBBase):
    """User model with hashed password."""

    hashed_password: str

    model_config = ConfigDict(from_attributes=True)


class PasswordChange(BaseModel):
    """The body of ``POST /api/v1/users/me/password``."""

    current_password: Optional[SecretStr] = Field(
        None,
        description=(
            "Your current password. Required: a request without it, or with "
            "an empty one, is refused with 403."
        ),
    )
    new_password: SecretStr = Field(
        ...,
        min_length=8,
        description=(
            "At least 8 characters and at most 72 bytes (UTF-8), with an "
            "upper-case letter, a lower-case letter and a digit."
        ),
    )

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: SecretStr) -> SecretStr:
        """Validate new password strength."""
        check_password_strength(v.get_secret_value())
        return v

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    """Token model."""

    access_token: str
    token_type: str

    model_config = ConfigDict(from_attributes=True)


class TokenPayload(BaseModel):
    """Token payload model."""

    sub: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class UserResponse(BaseModel):
    """Model for user response data."""

    id: Any  # Accept any type for id to handle both string and UUID
    username: str
    email: str  # Using str instead of EmailStr for test compatibility
    full_name: Optional[str] = None
    is_active: bool
    is_superuser: bool
    # The RBAC role. Optional because a few legacy rows predate the column;
    # the dashboard needs it to render the role chip and decide what to offer.
    role: Optional[RoleName] = None
    created_at: datetime
    updated_at: datetime
    # Make all optional fields truly optional
    last_login: Optional[datetime] = None
    preferences: Optional[Dict[str, Any]] = None

    @field_validator("role", mode="before")
    @classmethod
    def _role_name(cls, v: Any) -> Any:
        """Accept the ``UserRole`` enum, its value or its name."""
        if v is None or isinstance(v, str):
            return v.upper() if isinstance(v, str) else v
        name = getattr(v, "name", None)
        return name or str(v)

    model_config = ConfigDict(
        from_attributes=True,
        arbitrary_types_allowed=True,
        extra="ignore",  # Ignore extra fields to prevent validation errors
    )


class UserListResponse(BaseModel):
    """Model for paginated user list response."""

    # ``UserResponse``, not ``Dict``: the endpoints hand this ORM objects, which
    # a dict annotation rejects (every call to GET /api/v1/admin/users was a 500).
    items: List[UserResponse]
    total: int
    skip: int = 0
    limit: int = 100

    model_config = ConfigDict(
        schema_extra={
            "example": {
                "items": [
                    {
                        "id": "123e4567-e89b-12d3-a456-426614174000",
                        "username": "johndoe",
                        "email": "john.doe@example.com",
                        "full_name": "John Doe",
                        "is_active": True,
                        "is_superuser": False,
                        "created_at": "2023-01-01T00:00:00Z",
                        "updated_at": "2023-01-01T00:00:00Z",
                    }
                ],
                "total": 1,
                "skip": 0,
                "limit": 100,
            }
        }
    )
