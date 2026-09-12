"""
Pydantic schemas for user-owned API keys (``/api/v1/api-keys``).

The plaintext key is returned exactly once, in the ``APIKeyCreated`` response
of ``POST /api/v1/api-keys``; only its SHA-256 hash is stored.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Length of the visible prefix (``eptk_`` + first 4 hex chars) shown in lists.
KEY_PREFIX_LENGTH = 9


class APIKeyCreate(BaseModel):
    """Body for ``POST /api/v1/api-keys``."""

    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    scopes: Optional[List[str]] = Field(
        None, description="Optional list of scope names (stored comma-separated)"
    )
    expires_at: Optional[datetime] = None

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("scopes", mode="before")
    @classmethod
    def _normalise_scopes(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v = list(v.split(","))
        cleaned = [str(s).strip() for s in v if str(s).strip()]
        for scope in cleaned:
            if "," in scope:
                raise ValueError("scope names may not contain commas")
        return cleaned


class APIKeyRead(BaseModel):
    """
    A key as shown in ``GET /api/v1/api-keys``.

    Only the SHA-256 hash of a key is stored, so neither the secret nor its
    prefix can be shown after creation; identify keys by ``id``/``name``.
    """

    id: UUID
    name: str
    description: Optional[str] = None
    scopes: List[str] = []
    is_active: bool
    user_id: UUID
    created_at: datetime
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class APIKeyCreated(BaseModel):
    """
    ``POST /api/v1/api-keys`` response.

    ``key`` is the plaintext secret and is shown only in this response.
    """

    id: UUID
    name: str
    key: str
    prefix: str
    created_at: datetime
    expires_at: Optional[datetime] = None
