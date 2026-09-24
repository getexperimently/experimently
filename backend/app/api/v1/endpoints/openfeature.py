"""
OpenFeature-compatible evaluation endpoints (EP-044).

Exposes two endpoints that OpenFeature providers use for local flag evaluation:

  GET  /api/v1/openfeature/flags
      Returns all feature flag definitions the API key can access.
      Providers fetch this once to warm their in-memory cache.

  POST /api/v1/openfeature/evaluate
      Server-side evaluation of a single flag for a given userId and attributes.
      Useful when the client cannot perform local evaluation (e.g., browsers
      that do not have Node's crypto module).

Authentication:
  Both endpoints require a valid API key in the X-API-Key header.
  The key is validated against the api_keys table; the associated user's
  feature flags are returned.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.core.consistent_hash import hash_user
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
    """Minimal flag definition used for local (client-side) evaluation."""

    key: str
    enabled: bool
    rollout_percentage: float
    variants: List[FlagVariantResponse] = []
    rules: List[TargetingRuleResponse] = []


class FlagsListResponse(BaseModel):
    flags: List[FeatureFlagDefinition]


class EvaluateRequest(BaseModel):
    flagKey: str
    userId: str = ""
    attributes: Dict[str, Any] = {}


class EvaluateResponse(BaseModel):
    value: Any
    variant: Optional[str] = None
    reason: str
    flagKey: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The hash lives in `backend.app.core.consistent_hash` -- one implementation for
# flags, experiment assignment and everything else that buckets a user. This
# module used to carry its own correct copy while `assignment_service` carried
# its own incorrect one, and nothing compared them (#81).


def _hash_user(user_id: str, flag_key: str) -> float:
    """Kept as a thin alias: this name appears in tests and in the SDK docs."""
    return hash_user(user_id, flag_key)


def _evaluate_flag(flag: FeatureFlag, user_id: str) -> EvaluateResponse:
    """
    Evaluate a feature flag for a user using the consistent hash algorithm.
    Returns an EvaluateResponse with value, variant, and reason.
    """
    if not flag.enabled:
        return EvaluateResponse(
            value=False, variant=None, reason="flag_disabled", flagKey=flag.key
        )

    h = _hash_user(user_id, flag.key)
    rollout_fraction = (flag.rollout_percentage or 0.0) / 100.0

    if h >= rollout_fraction:
        return EvaluateResponse(
            value=False, variant=None, reason="out_of_rollout", flagKey=flag.key
        )

    variants = flag.variants or []
    if variants:
        variant_hash = h / rollout_fraction if rollout_fraction > 0.0 else 0.0
        cumulative = 0.0
        for v in variants:
            weight = (
                v.get("weight", 0.0)
                if isinstance(v, dict)
                else getattr(v, "weight", 0.0)
            )
            cumulative += weight
            if variant_hash < cumulative:
                v_key = v.get("key") if isinstance(v, dict) else getattr(v, "key", None)
                v_val = (
                    v.get("value") if isinstance(v, dict) else getattr(v, "value", None)
                )
                return EvaluateResponse(
                    value=v_val if v_val is not None else v_key,
                    variant=v_key,
                    reason="variant_assigned",
                    flagKey=flag.key,
                )
        # Fallback to last variant.
        last = variants[-1]
        last_key = (
            last.get("key") if isinstance(last, dict) else getattr(last, "key", None)
        )
        last_val = (
            last.get("value")
            if isinstance(last, dict)
            else getattr(last, "value", None)
        )
        return EvaluateResponse(
            value=last_val if last_val is not None else last_key,
            variant=last_key,
            reason="variant_assigned",
            flagKey=flag.key,
        )

    return EvaluateResponse(
        value=True, variant=None, reason="in_rollout", flagKey=flag.key
    )


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
    summary="List all flags for OpenFeature local evaluation",
    description=(
        "Returns all feature flag definitions accessible to this API key. "
        "OpenFeature providers fetch this endpoint once on initialization to "
        "warm their local flag cache and perform client-side evaluation without "
        "a per-flag network round-trip."
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


@router.post(
    "/evaluate",
    response_model=EvaluateResponse,
    summary="Server-side flag evaluation (OpenFeature)",
    description=(
        "Evaluates a single feature flag server-side for the given userId "
        "and attributes. Use this endpoint when the client cannot perform local "
        "evaluation (e.g., in restricted browser environments)."
    ),
)
def evaluate_openfeature_flag(
    body: EvaluateRequest,
    db: Session = Depends(deps.get_db),
    api_key_user: User = Depends(deps.get_api_key),
) -> EvaluateResponse:
    """Evaluate a feature flag for a specific user server-side."""
    if api_key_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid API key required",
        )

    flag = db.query(FeatureFlag).filter(FeatureFlag.key == body.flagKey).first()

    if flag is None:
        return EvaluateResponse(
            value=None,
            variant=None,
            reason="FLAG_NOT_FOUND",
            flagKey=body.flagKey,
        )

    # Check ownership — only the owner or superusers can evaluate.
    if not api_key_user.is_superuser and flag.owner_id != api_key_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to evaluate this flag",
        )

    return _evaluate_flag(flag, body.userId)


@router.post(
    "/bulk-evaluate",
    response_model=List[EvaluateResponse],
    summary="Bulk server-side flag evaluation (OpenFeature)",
    description=(
        "Evaluates multiple feature flags in a single request, reducing round-trips "
        "for SDK clients that need to pre-load several flags."
    ),
)
def bulk_evaluate_openfeature_flags(
    bodies: List[EvaluateRequest],
    db: Session = Depends(deps.get_db),
    api_key_user: User = Depends(deps.get_api_key),
) -> List[EvaluateResponse]:
    """Bulk-evaluate multiple feature flags for a user."""
    if api_key_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid API key required",
        )

    results: List[EvaluateResponse] = []
    for body in bodies:
        flag = db.query(FeatureFlag).filter(FeatureFlag.key == body.flagKey).first()
        if flag is None:
            results.append(
                EvaluateResponse(
                    value=None,
                    variant=None,
                    reason="FLAG_NOT_FOUND",
                    flagKey=body.flagKey,
                )
            )
        elif not api_key_user.is_superuser and flag.owner_id != api_key_user.id:
            results.append(
                EvaluateResponse(
                    value=None,
                    variant=None,
                    reason="FORBIDDEN",
                    flagKey=body.flagKey,
                )
            )
        else:
            results.append(_evaluate_flag(flag, body.userId))

    return results
