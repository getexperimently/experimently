"""
OpenFeature flag listing (EP-044). Deprecated.

  GET  /api/v1/openfeature/flags
      Returns the feature flag definitions the API key's user can list.

This route is deprecated and kept with its behaviour unchanged. Neither
OpenFeature provider calls it: both evaluate through
``GET /api/v1/feature-flags/evaluate/{key}`` (see docs/sdk/openfeature.md).
Server-side local evaluation downloads ``GET /api/v1/sdk/ruleset`` instead (#226).

``POST /api/v1/openfeature/evaluate`` and ``POST /api/v1/openfeature/bulk-evaluate``
were removed (#241): they could not evaluate an existing flag (they read a
``FeatureFlag.enabled`` attribute the model does not have), and neither provider
called them.
``backend/tests/smoke/test_openfeature_routes.py`` pins the exact route set.

Authentication:
  A valid API key in the X-API-Key header.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["OpenFeature"],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid API key"},
    },
)

# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class FlagVariantResponse(BaseModel):
    key: str
    weight: float
    value: Optional[Any] = None


class TargetingRuleResponse(BaseModel):
    attribute: str
    operator: str
    value: Any


class FeatureFlagDefinition(BaseModel):
    """A feature flag as the deprecated /openfeature/flags listing returns it."""

    key: str
    enabled: bool
    rollout_percentage: float
    variants: List[FlagVariantResponse] = []
    rules: List[TargetingRuleResponse] = []


class FlagsListResponse(BaseModel):
    flags: List[FeatureFlagDefinition]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _flag_to_definition(flag: FeatureFlag) -> FeatureFlagDefinition:
    """Convert a SQLAlchemy FeatureFlag to an OpenFeature FeatureFlagDefinition."""
    variants_raw = flag.variants or []
    variants = []
    for v in variants_raw:
        if isinstance(v, dict):
            variants.append(
                FlagVariantResponse(
                    key=v.get("key", ""),
                    weight=float(v.get("weight", 0.0)),
                    value=v.get("value"),
                )
            )

    rules_raw = flag.targeting_rules or []
    rules = []
    for r in rules_raw:
        if isinstance(r, dict):
            rules.append(
                TargetingRuleResponse(
                    attribute=r.get("attribute", ""),
                    operator=r.get("operator", "eq"),
                    value=r.get("value"),
                )
            )

    return FeatureFlagDefinition(
        key=flag.key,
        enabled=flag.enabled
        if hasattr(flag, "enabled")
        else (flag.status == FeatureFlagStatus.ACTIVE),
        rollout_percentage=float(flag.rollout_percentage or 0.0),
        variants=variants,
        rules=rules,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/flags",
    response_model=FlagsListResponse,
    summary="Flag definitions for the API key's user (deprecated)",
    deprecated=True,
    description=(
        "**Deprecated.** Neither OpenFeature provider calls this route: both "
        "evaluate through `GET /api/v1/feature-flags/evaluate/{flag_key}`. For "
        "server-side local evaluation use `GET /api/v1/sdk/ruleset`, with an "
        "API key that carries the `sdk:ruleset` scope. This route still answers "
        "as before and may be removed in a later release.\n\n"
        "Returns the feature flags owned by the user who created the API key; "
        "a key created by a superuser gets every flag. A flag's `rules` carry "
        "only rules stored in the legacy list shape; rules written in the "
        "dashboard's shape are left out, so a flag that has them is returned "
        "with `rules: []`. A flag's `enabled` is true when its status is active."
    ),
)
def get_openfeature_flags(
    db: Session = Depends(deps.get_db),
    api_key_user: User = Depends(deps.get_api_key),
) -> FlagsListResponse:
    """Return all feature flags available to the API key's user."""
    if api_key_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid API key required",
        )

    # Superusers and admins can see all flags; regular users see only their own.
    if api_key_user.is_superuser:
        flags = db.query(FeatureFlag).all()
    else:
        flags = (
            db.query(FeatureFlag).filter(FeatureFlag.owner_id == api_key_user.id).all()
        )

    definitions = [_flag_to_definition(f) for f in flags]
    return FlagsListResponse(flags=definitions)
