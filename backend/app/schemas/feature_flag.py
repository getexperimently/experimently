# backend/app/schemas/feature_flag.py
"""
Feature flag schema models for validation and serialization.

The create/update contract (#94, D39 as narrowed by D40):

* A request names only fields the API reads. Anything else answers 422
  (``extra="forbid"``), instead of being dropped without a word.
* The fields every response carries but no request writes (``id``,
  ``owner_id``, ``created_at``, ``updated_at``, ``status``) are declared on the
  request models as read-only, so a GET body can be sent back unchanged. They
  are ignored -- removed by ``FeatureFlagService``, which is also where a sent
  ``status`` is compared with the stored one.
* A new flag is inactive unless ``is_active: true`` is sent.
* ``default_value`` is stored and type-checked; a boolean flag accepts only
  ``false`` for now (D40).
* There is one response representation, :class:`FeatureFlagRead`. It shares no
  base with the request models: ``extra="forbid"`` is inherited, and a response
  model must never refuse a stored row.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

#: The fields a flag response carries that no request writes.  A request may
#: send them back -- a GET body round-trips -- and they are ignored, except that
#: a ``status`` must equal the stored one (``FeatureFlagService``).
READ_ONLY_FIELDS = frozenset({"id", "owner_id", "created_at", "updated_at", "status"})

#: Fields stored in a NOT NULL column: an explicit null is refused, while
#: leaving one out of an update keeps the stored value.
NOT_NULL_FIELDS = ("key", "name", "is_active", "rollout_percentage", "default_value")

DEFAULT_VALUE_UNSUPPORTED = (
    "default_value can only be false for now; a flag that serves another value "
    "when it is off is not supported yet."
)

#: The answer to a ``status`` that differs from the stored one.
STATUS_READ_ONLY = "status is read-only. Use is_active to turn a flag on or off."

_READ_ONLY = {"readOnly": True}


class _FeatureFlagRequest(BaseModel):
    """What a create and an update have in common.  Never a response base."""

    model_config = ConfigDict(extra="forbid")

    # Read-only: accepted so a GET body can be sent back, and ignored.
    id: Any = Field(
        None, description="Read-only; ignored.", json_schema_extra=_READ_ONLY
    )
    owner_id: Any = Field(
        None, description="Read-only; ignored.", json_schema_extra=_READ_ONLY
    )
    created_at: Any = Field(
        None, description="Read-only; ignored.", json_schema_extra=_READ_ONLY
    )
    updated_at: Any = Field(
        None, description="Read-only; ignored.", json_schema_extra=_READ_ONLY
    )
    status: Any = Field(
        None,
        description=(
            "Read-only. Accepted when it equals the flag's status, in any case "
            "(on create: the status is_active gives it); any other value answers "
            "422. Turn a flag on or off with is_active."
        ),
        json_schema_extra=_READ_ONLY,
    )

    @field_validator(*NOT_NULL_FIELDS, mode="before", check_fields=False)
    @classmethod
    def refuse_null(cls, value: Any, info: ValidationInfo) -> Any:
        """Refuse an explicit null for a field stored in a NOT NULL column.

        A ``before`` validator does not run for a field left out: pydantic does
        not validate a default, so omission still means "not sent".
        """
        if value is None:
            raise PydanticCustomError(
                "null_not_allowed", f"{info.field_name} cannot be null"
            )
        return value

    @field_validator("key", check_fields=False)
    @classmethod
    def validate_key(cls, v: str) -> str:
        """Keys are lowercase letters, digits, hyphens and underscores, and
        start with a letter or a digit."""
        import re

        if not re.match(r"^[a-z0-9][a-z0-9_-]*$", v):
            raise ValueError(
                "Key must be lowercase alphanumeric characters, hyphens, or underscores only"
            )
        return v

    @field_validator("default_value", check_fields=False)
    @classmethod
    def only_false_for_now(cls, v: bool) -> bool:
        """A boolean flag's ``default_value`` may only be false (D40).

        A flag whose off-value is ``true`` would keep serving ``true`` when it
        is turned off.  The message names no submitted value.
        """
        if v is True:
            raise PydanticCustomError(
                "default_value_unsupported", DEFAULT_VALUE_UNSUPPORTED
            )
        return v


class FeatureFlagCreate(_FeatureFlagRequest):
    """The body of a flag create. A field not listed here answers 422."""

    key: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    is_active: bool = Field(
        False, description="Create the flag on. Left out, the flag starts off."
    )
    rollout_percentage: int = Field(0, ge=0, le=100)
    targeting_rules: Optional[Any] = None
    default_value: StrictBool = Field(
        False,
        description=(
            "What the flag serves when it is off. Only false is accepted for now."
        ),
    )
    tags: Optional[List[str]] = None


class FeatureFlagUpdate(_FeatureFlagRequest):
    """The body of a flag update.

    Every field is optional, and a field left out keeps its value. key, name,
    is_active, rollout_percentage and default_value refuse null; description,
    targeting_rules and tags accept null, which clears them. A field not
    listed here answers 422.
    """

    # The NOT_NULL_FIELDS default to None only to mean "not sent": pydantic
    # does not validate a default, while an explicit null reaches refuse_null.
    key: str = Field(None, min_length=1, max_length=100)
    name: str = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    is_active: bool = Field(None, description="Turn the flag on or off.")
    rollout_percentage: int = Field(None, ge=0, le=100)
    targeting_rules: Optional[Any] = None
    default_value: StrictBool = Field(
        None,
        description=(
            "What the flag serves when it is off. Only false is accepted for now."
        ),
    )
    tags: Optional[List[str]] = None


class FeatureFlagEvaluation(BaseModel):
    """Model for feature flag evaluation results."""

    key: str
    value: Any
    reason: str
    rule_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class FeatureFlagRead(BaseModel):
    """A feature flag, as every flag route returns it.

    Any of these bodies can be sent back with an update unchanged.
    """

    # Create, get, update, activate, deactivate and the list items all answer
    # with this, and nothing else.  It holds types only -- no key pattern, no
    # length limit -- because a response model that refuses a stored row turns
    # a read into a 500.  The two normalisers below are the only logic:
    # ``status`` is lower-cased and ``is_active`` is derived from it, so the
    # two never disagree and ``is_active`` is never null.
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: UUID
    key: str
    name: str
    description: Optional[str] = None
    status: Literal["active", "inactive", "archived"] = Field(
        ..., description="The flag's status, lower-cased."
    )
    is_active: bool = Field(..., description='True exactly when status is "active".')
    rollout_percentage: int
    targeting_rules: Optional[Any] = Field(
        None, description="The flag's targeting rules, as stored."
    )
    default_value: bool = Field(..., description="What the flag serves when it is off.")
    tags: Optional[List[str]] = None
    owner_id: Optional[UUID] = Field(
        None, description="The user who created the flag; null once that user is gone."
    )
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, data: Any) -> Any:
        """Read a stored row (or a mapping), lower-case ``status`` and derive
        ``is_active`` from it."""
        if isinstance(data, Mapping):
            values = dict(data)
        else:
            values = {
                name: getattr(data, name, None)
                for name in cls.model_fields
                if name != "is_active"
            }
        status = values.get("status")
        status = getattr(status, "value", status)
        if status is not None:
            status = str(status).lower()
        values["status"] = status
        values["is_active"] = status == "active"
        return values


def flag_to_read(flag: Any) -> FeatureFlagRead:
    """The one serializer from a stored flag to its response."""
    return FeatureFlagRead.model_validate(flag)


class FeatureFlagListResponse(BaseModel):
    """
    Paginated response model for feature flags.
    """

    items: List[FeatureFlagRead]
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
                        "status": "inactive",
                        "is_active": False,
                        "rollout_percentage": 0,
                        "targeting_rules": None,
                        "default_value": False,
                        "tags": None,
                        "owner_id": "5f0c8a52-1d7e-4c3b-9a6f-2b8e4d1c7a90",
                        "created_at": "2023-01-01T00:00:00Z",
                        "updated_at": "2023-01-01T00:00:00Z",
                    }
                ],
                "total": 1,
                "skip": 0,
                "limit": 100,
            }
        },
    )
