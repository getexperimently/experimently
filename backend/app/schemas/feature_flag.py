# backend/app/schemas/feature_flag.py
"""
Feature flag schema models for validation and serialization.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FeatureFlagBase(BaseModel):
    """Base model for feature flag data."""

    key: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    is_active: bool = True
    rollout_percentage: Optional[int] = Field(None, ge=0, le=100)
    targeting_rules: Optional[Any] = None
    default_value: Any = False
    tags: Optional[List[str]] = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        """Validate feature flag key format.

        Keys must be lowercase alphanumeric with hyphens or underscores,
        matching the pattern ^[a-z0-9][a-z0-9_-]*[a-z0-9]$|^[a-z0-9]$.
        """
        import re

        if not re.match(r"^[a-z0-9][a-z0-9_-]*$", v):
            raise ValueError(
                "Key must be lowercase alphanumeric characters, hyphens, or underscores only"
            )
        return v


class FeatureFlagCreate(FeatureFlagBase):
    """Model for creating a new feature flag."""


class FeatureFlagUpdate(FeatureFlagBase):
    """Model for updating a feature flag."""

    key: Optional[str] = None
    name: Optional[str] = None
    is_active: Optional[bool] = None
    default_value: Optional[Any] = None


class FeatureFlagInDBBase(FeatureFlagBase):
    """Base model for feature flags in DB."""

    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FeatureFlag(FeatureFlagInDBBase):
    """Feature flag model for responses."""


class FeatureFlagInDB(FeatureFlagInDBBase):
    """Feature flag model with additional DB fields."""


class FeatureFlagEvaluation(BaseModel):
    """Model for feature flag evaluation results."""

    key: str
    value: Any
    reason: str
    rule_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class FeatureFlagReadExtended(FeatureFlagInDBBase):
    """
    Extended feature flag read model with additional information.
    Used for detailed feature flag reads (``GET /feature-flags/`` items).

    The ORM model only carries ``status`` (``FeatureFlagStatus``); this schema
    exposes it lower-cased (``"active"`` / ``"inactive"`` / ``"archived"``),
    the same casing ``GET /feature-flags/{flag_id}`` uses, and derives
    ``is_active`` from it so the two never disagree.
    """

    status: Optional[str] = Field(
        None, description='Lower-cased flag status: "active", "inactive" or "archived"'
    )
    owner_id: Optional[UUID] = None
    metrics: Optional[List[Dict[str, Any]]] = None
    variants: Optional[List[Dict[str, Any]]] = None
    last_evaluated: Optional[datetime] = None

    @field_validator("status", mode="before")
    @classmethod
    def normalise_status(cls, v: Any) -> Optional[str]:
        """Accept the ``FeatureFlagStatus`` enum or a string in any casing."""
        if v is None:
            return None
        value = getattr(v, "value", v)
        return str(value).lower()

    @model_validator(mode="after")
    def derive_is_active(self) -> "FeatureFlagReadExtended":
        """``is_active`` mirrors ``status`` whenever a status is known."""
        if self.status is not None:
            self.is_active = self.status == "active"
        return self


class FeatureFlagListResponse(BaseModel):
    """
    Paginated response model for feature flags.
    """

    items: List[FeatureFlagReadExtended]
    total: int
    skip: int
    limit: int

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "id": "123e4567-e89b-12d3-a456-426614174000",
                        "key": "new_feature",
                        "name": "New Feature Flag",
                        "description": "Controls access to new feature",
                        "status": "active",
                        "is_active": True,
                        "created_at": "2023-01-01T00:00:00Z",
                        "updated_at": "2023-01-01T00:00:00Z",
                    }
                ],
                "total": 1,
                "skip": 0,
                "limit": 100,
            }
        },
        from_attributes=True,
    )
