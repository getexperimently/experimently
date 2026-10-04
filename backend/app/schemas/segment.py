"""
Segment schemas for Pydantic validation and serialization.

This module defines Pydantic models for audience segmentation data structures
used in the P3-C: Audience Segmentation API.
"""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.core.targeting_adapter import (
    TargetingRulesError,
    validate_segment_rules,
)

#: The description of a segment's ``rules`` in the OpenAPI document.
SEGMENT_RULES_DESCRIPTION = (
    "Targeting rules in the format flag and experiment targeting use: "
    '{"logical_operator": "AND"|"OR"|"NOT" (optional), "groups": '
    '[{"logical_operator"?, "conditions": [{"attribute", "operator", "value"}]}]}, '
    "with operators such as equals, in, regex and semver_gte. At least one group, "
    "each with at least one condition; at most 20 groups, 50 conditions, 10 regex "
    "conditions and 1,000 list values. Any other shape is refused with 422."
)


def _checked_segment_rules(value: Any) -> Any:
    """Refuse segment rules membership would not evaluate as written (#440).

    The value is returned as given, never rewritten. The message is fixed
    text naming a place and a reason, never the submitted rules (see
    ``validate_segment_rules``).
    """
    try:
        validate_segment_rules(value)
    except TargetingRulesError as err:
        raise ValueError(str(err)) from None
    return value


class SegmentStatus(str, Enum):
    """Segment lifecycle status."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class SegmentCreate(BaseModel):
    """Schema for creating a new audience segment."""

    name: str = Field(..., min_length=2, max_length=128)
    description: Optional[str] = Field(None, max_length=512)
    rules: dict = Field(..., description=SEGMENT_RULES_DESCRIPTION)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "US Premium Users",
                "description": "Premium subscribers in the United States",
                "rules": {
                    "logical_operator": "AND",
                    "groups": [
                        {
                            "logical_operator": "AND",
                            "conditions": [
                                {
                                    "attribute": "country",
                                    "operator": "equals",
                                    "value": "US",
                                },
                                {
                                    "attribute": "plan",
                                    "operator": "equals",
                                    "value": "premium",
                                },
                            ],
                        }
                    ],
                },
            }
        }
    )

    @field_validator("rules", mode="before")
    @classmethod
    def checked_rules(cls, value: Any) -> Any:
        return _checked_segment_rules(value)


class SegmentUpdate(BaseModel):
    """Schema for updating an existing audience segment.  All fields are optional."""

    name: Optional[str] = Field(None, min_length=2, max_length=128)
    description: Optional[str] = None
    rules: Optional[dict] = Field(
        None,
        description=SEGMENT_RULES_DESCRIPTION
        + " Leave it out to keep the stored rules.",
    )
    status: Optional[SegmentStatus] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Updated Segment Name",
                "status": "inactive",
            }
        }
    )

    @field_validator("rules", mode="before")
    @classmethod
    def checked_rules(cls, value: Any) -> Any:
        if value is None:
            return None
        return _checked_segment_rules(value)


class SegmentResponse(BaseModel):
    """Schema for returning a segment in API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str] = None
    rules: dict
    status: SegmentStatus
    created_at: str
    updated_at: str
    member_count: Optional[int] = None  # populated on demand


class SegmentMembershipRequest(BaseModel):
    """Check if a user context matches a segment."""

    user_context: dict = Field(
        ...,
        description="User attributes to evaluate against segment rules. "
        'e.g. {"user_id": "123", "country": "US", "plan": "pro", "age": 25}',
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_context": {
                    "user_id": "123",
                    "country": "US",
                    "plan": "pro",
                    "age": 25,
                }
            }
        }
    )


class SegmentMembershipResponse(BaseModel):
    """Result of evaluating a user context against a segment."""

    segment_id: str
    segment_name: str
    is_member: bool
    matched_rules: list[str] = Field(
        default=[],
        description="Each condition, in any group, that the context satisfies "
        'on its own, as "<attribute> <operator> <value>". Empty when the user '
        "is not a member.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "segment_id": "abc123",
                "segment_name": "US Premium Users",
                "is_member": True,
                "matched_rules": ["country equals US", "plan equals premium"],
            }
        }
    )


class BulkSegmentMembershipRequest(BaseModel):
    """Check membership for one user across multiple segments."""

    user_context: dict
    segment_ids: list[str] = Field(..., min_length=1, max_length=50)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_context": {"country": "US", "plan": "pro"},
                "segment_ids": ["seg-1", "seg-2"],
            }
        }
    )

    @field_validator("segment_ids")
    @classmethod
    def validate_segment_ids(cls, v: list[str]) -> list[str]:
        if len(v) < 1:
            raise ValueError("segment_ids must contain at least 1 element")
        if len(v) > 50:
            raise ValueError("segment_ids cannot contain more than 50 elements")
        return v


class BulkSegmentMembershipResponse(BaseModel):
    """Result of evaluating one user against multiple segments."""

    user_context: dict
    memberships: dict[str, bool]  # {segment_id: is_member}
    evaluation_time_ms: float

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_context": {"country": "US", "plan": "pro"},
                "memberships": {"seg-1": True, "seg-2": False},
                "evaluation_time_ms": 3.42,
            }
        }
    )


class ExperimentSegmentLink(BaseModel):
    """Link an experiment to a required audience segment."""

    experiment_id: str
    segment_id: str
    is_required: bool = True  # if True, only segment members can be assigned


class SegmentExperimentResponse(BaseModel):
    """Which experiments and feature flags use this segment."""

    segment_id: str
    experiments: list[dict]  # [{id, name, status}]
    feature_flags: list[dict]  # [{id, name}]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "segment_id": "abc123",
                "experiments": [
                    {"id": "exp-1", "name": "Homepage Test", "status": "active"}
                ],
                "feature_flags": [{"id": "ff-1", "name": "dark-mode"}],
            }
        }
    )


class AudiencePreviewResponse(BaseModel):
    """Estimated audience size from preview evaluation."""

    estimated_percentage: float
    sample_size: int
    matched: int

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "estimated_percentage": 35.5,
                "sample_size": 1000,
                "matched": 355,
            }
        }
    )
