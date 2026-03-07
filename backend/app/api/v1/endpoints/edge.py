"""
Edge Bootstrap API endpoint (EP-047).

Provides a fast, lightweight endpoint optimized for edge SDK initialization:

  GET /api/v1/edge/bootstrap
    Returns all feature flags and experiments for the API key in a single
    response. Designed to be cached at CDN level with a 60-second TTL.

Response format:
  {
    "flags": [
      {
        "key": str,
        "enabled": bool,
        "rolloutPercentage": float,
        "variants": [...],
        "rules": [...]
      }
    ],
    "experiments": [
      {
        "key": str,
        "enabled": bool,
        "variants": [{"key": str, "name": str, "weight": float}]
      }
    ],
    "ttl_seconds": 60,
    "version": "<sha256 of payload for cache invalidation>"
  }

Authentication: X-API-Key header (validated against the api_keys table).
Response is deterministic for the same set of flags (stable version hash).
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.experiment import Experiment, ExperimentStatus, Variant
from backend.app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Edge"],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid API key"},
    },
)

# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class EdgeTargetingRule(BaseModel):
    """Targeting rule used for local evaluation in edge environments."""
    attribute: str
    operator: str
    value: Any
    rolloutPercentage: Optional[float] = None


class EdgeFlagVariant(BaseModel):
    """Feature flag variant for local evaluation."""
    key: str
    weight: float
    value: Optional[Any] = None


class EdgeFeatureFlag(BaseModel):
    """
    Minimal feature flag definition for edge SDK local evaluation.
    Uses camelCase keys to match the TypeScript SDK conventions.
    """
    key: str
    enabled: bool
    rolloutPercentage: float
    variants: List[EdgeFlagVariant] = []
    rules: List[EdgeTargetingRule] = []


class EdgeExperimentVariant(BaseModel):
    """Experiment variant for assignment / bucketing."""
    key: str
    name: str
    weight: float


class EdgeExperiment(BaseModel):
    """Minimal experiment definition for edge SDK assignment."""
    key: str
    enabled: bool
    variants: List[EdgeExperimentVariant] = []


class EdgeBootstrapResponse(BaseModel):
    """
    Full edge bootstrap payload.

    Designed to be:
      - Cached at CDN level (use Cache-Control: public, max-age=60)
      - Verified via the `version` hash (SHA-256 of the sorted JSON payload)
      - Consumed by the Edge SDK's `refreshFlags()` method
    """
    flags: List[EdgeFeatureFlag]
    experiments: List[EdgeExperiment]
    ttl_seconds: int = 60
    version: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _flag_to_edge(flag: FeatureFlag) -> EdgeFeatureFlag:
    """Convert a SQLAlchemy FeatureFlag to an EdgeFeatureFlag schema."""
    # Parse variants
    variants_raw = flag.variants if isinstance(flag.variants, list) else []
    variants: List[EdgeFlagVariant] = []
    for v in variants_raw:
        if isinstance(v, dict):
            variants.append(EdgeFlagVariant(
                key=v.get("key", ""),
                weight=float(v.get("weight", 0.0)),
                value=v.get("value"),
            ))

    # Parse targeting rules
    rules_raw = flag.targeting_rules if isinstance(flag.targeting_rules, list) else []
    rules: List[EdgeTargetingRule] = []
    for r in rules_raw:
        if isinstance(r, dict):
            rollout = r.get("rollout_percentage") or r.get("rolloutPercentage")
            rules.append(EdgeTargetingRule(
                attribute=r.get("attribute", ""),
                operator=r.get("operator", "eq"),
                value=r.get("value"),
                rolloutPercentage=float(rollout) if rollout is not None else None,
            ))

    # Resolve enabled state
    enabled: bool
    if hasattr(flag, "enabled"):
        enabled = bool(flag.enabled)
    else:
        enabled = flag.status == FeatureFlagStatus.ACTIVE

    return EdgeFeatureFlag(
        key=flag.key,
        enabled=enabled,
        rolloutPercentage=float(flag.rollout_percentage or 0.0),
        variants=variants,
        rules=rules,
    )


def _experiment_to_edge(experiment: Experiment, db_variants: List[Variant]) -> EdgeExperiment:
    """Convert a SQLAlchemy Experiment to an EdgeExperiment schema."""
    edge_variants: List[EdgeExperimentVariant] = []
    total_allocation = sum(v.traffic_allocation or 0 for v in db_variants) or 100
    for v in db_variants:
        allocation = v.traffic_allocation or 0
        edge_variants.append(EdgeExperimentVariant(
            key=v.name.lower().replace(" ", "-"),
            name=v.name,
            weight=allocation / total_allocation,  # normalize to [0, 1]
        ))

    enabled = experiment.status == ExperimentStatus.ACTIVE

    return EdgeExperiment(
        key=experiment.name.lower().replace(" ", "-"),
        enabled=enabled,
        variants=edge_variants,
    )


def _compute_version(flags: List[EdgeFeatureFlag], experiments: List[EdgeExperiment]) -> str:
    """
    Compute a stable SHA-256 version hash of the payload.

    The hash is computed over a canonically serialized JSON string (keys sorted,
    flags sorted by key). This ensures the same flag set always produces the same
    version string, allowing edge clients to skip re-applying a cached payload.
    """
    payload = {
        "flags": sorted(
            [f.model_dump() for f in flags],
            key=lambda x: x["key"],
        ),
        "experiments": sorted(
            [e.model_dump() for e in experiments],
            key=lambda x: x["key"],
        ),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/bootstrap",
    response_model=EdgeBootstrapResponse,
    summary="Edge SDK bootstrap — all flags and experiments in one call",
    description=(
        "Returns all feature flags and experiments accessible to this API key "
        "in a single response. Optimized for edge SDK initialization. "
        "The response includes a stable SHA-256 `version` hash for cache "
        "invalidation. Designed to be cached at CDN level with a 60-second TTL. "
        "\n\n"
        "**Authentication**: Pass a valid API key in the `X-API-Key` header."
    ),
)
def get_edge_bootstrap(
    db: Session = Depends(deps.get_db),
    api_key_user: User = Depends(deps.get_api_key),
) -> EdgeBootstrapResponse:
    """
    Return all flags and experiments for the API key in one lightweight payload.

    This endpoint is the primary entry point for edge SDK initialization.
    Edge functions call this once at startup (or on cache miss) to warm their
    in-memory flag store.
    """
    if api_key_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid API key required",
        )

    # Fetch all feature flags for this user
    db_flags: List[FeatureFlag] = (
        db.query(FeatureFlag)
        .filter(FeatureFlag.owner_id == api_key_user.id)
        .all()
    )

    # Fetch all experiments for this user
    db_experiments: List[Experiment] = (
        db.query(Experiment)
        .filter(Experiment.owner_id == api_key_user.id)
        .all()
    )

    # Convert to edge schema
    edge_flags = [_flag_to_edge(flag) for flag in db_flags]

    edge_experiments: List[EdgeExperiment] = []
    for experiment in db_experiments:
        db_variants = (
            db.query(Variant)
            .filter(Variant.experiment_id == experiment.id)
            .order_by(Variant.id)
            .all()
        )
        edge_experiments.append(_experiment_to_edge(experiment, db_variants))

    # Compute stable version hash
    version = _compute_version(edge_flags, edge_experiments)

    logger.info(
        "Edge bootstrap served",
        extra={
            "user_id": str(api_key_user.id),
            "flag_count": len(edge_flags),
            "experiment_count": len(edge_experiments),
            "version": version[:8],
        },
    )

    return EdgeBootstrapResponse(
        flags=edge_flags,
        experiments=edge_experiments,
        ttl_seconds=60,
        version=version,
    )
