"""
Pydantic v2 schemas for Global Holdout (EP-022).

Defines request/response models for creating, updating, and querying
global holdout configurations that reserve a percentage of users from
all experiments.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GlobalHoldoutCreate(BaseModel):
    """Schema for creating a new global holdout."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Unique name for the global holdout.",
    )
    description: Optional[str] = Field(
        None,
        max_length=2000,
        description="Description of the holdout's purpose.",
    )
    holdout_percentage: int = Field(
        default=10,
        ge=1,
        le=20,
        description=(
            "Percentage of users to hold out, 1-20. Recommended: 1-5%, up to 10% "
            "when traffic is low; run for 1-3 months. Cannot change once the "
            "holdout has been active."
        ),
    )
    is_active: bool = Field(
        default=False,
        description=(
            "Whether the holdout is active. True makes it the active holdout "
            "and deactivates the one that was active."
        ),
    )

    @field_validator("holdout_percentage", mode="before")
    @classmethod
    def validate_holdout_percentage(cls, v: int) -> int:
        if not (1 <= v <= 20):
            raise ValueError("holdout_percentage must be between 1 and 20")
        return v


class GlobalHoldoutUpdate(BaseModel):
    """Schema for updating a global holdout."""

    name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=200,
        description="Updated name.",
    )
    description: Optional[str] = Field(
        None,
        max_length=2000,
        description="Updated description.",
    )
    holdout_percentage: Optional[int] = Field(
        None,
        ge=1,
        le=20,
        description=(
            "Percentage of users to hold out, 1-20. Recommended: 1-5%, up to 10% "
            "when traffic is low; run for 1-3 months. Cannot change once the "
            "holdout has been active."
        ),
    )
    is_active: Optional[bool] = Field(
        None,
        description=(
            "Updated active status. True deactivates the active holdout; a "
            "holdout that has ended cannot restart."
        ),
    )

    @field_validator("holdout_percentage", mode="before")
    @classmethod
    def validate_holdout_percentage(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 20):
            raise ValueError("holdout_percentage must be between 1 and 20")
        return v


class GlobalHoldoutResponse(BaseModel):
    """Response schema for a global holdout."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: Optional[str] = None
    holdout_percentage: int
    is_active: bool
    owner_id: Optional[UUID] = None
    activated_at: Optional[datetime] = Field(
        None,
        description=(
            "When the holdout was activated (UTC). Null for a holdout never "
            "activated, and for one active since before holdout membership "
            "was recorded."
        ),
    )
    deactivated_at: Optional[datetime] = Field(
        None,
        description="When the holdout was deactivated (UTC); it cannot restart.",
    )
    created_at: datetime
    updated_at: datetime


class GlobalHoldoutListResponse(BaseModel):
    """List of global holdouts."""

    items: List[GlobalHoldoutResponse]
    total: int


class HoldoutCheckResponse(BaseModel):
    """Result of checking if a user is in the global holdout."""

    user_id: str = Field(..., description="User identifier.")
    is_in_holdout: bool = Field(
        ..., description="True if the user is in the global holdout."
    )
    holdout_percentage: int = Field(..., description="Current holdout percentage.")
    bucket: int = Field(
        ...,
        ge=0,
        le=99,
        description="User's holdout bucket (0-99).",
    )
