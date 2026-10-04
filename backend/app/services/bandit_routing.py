"""Bandit routing for new users on the tracking assignment routes.

``POST /api/v1/tracking/assign`` and ``POST /api/v1/tracking/assign/batch``
route a *new* user of a multi-armed bandit experiment by the experiment's
``BanditState.variant_weights``; sticky assignments always win, because
``AssignmentService.assign_user`` returns the stored row before it looks at
the override.

:func:`bandit_chooser` reads ``BanditState`` once and returns a function of
the user id that works on plain values only (variant ids, weights and the
experiment id as a string). The batch route calls it once per request, so a
batch of N users reads the bandit weights once, and nothing it holds is an ORM
object that a commit would expire and the next user would reload.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Callable, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.bandit_state import BanditState
from backend.app.models.experiment import Experiment

#: ``(variant id, weight)`` pairs, positive weights only, ordered by ``str(id)``.
WeightedVariants = List[Tuple[uuid.UUID, float]]

#: Given a user id, the variant a new user is routed to, or ``None`` for the
#: default traffic-allocation hashing.
Chooser = Callable[[str], Optional[uuid.UUID]]


def bandit_weight(raw: Any) -> float:
    """Extract a non-negative weight from a BanditState.variant_weights entry.

    The scheduler stores ``{"weight": float, "successes": ..., "pulls": ...}``
    per variant; plain numeric values are accepted as well.
    """
    if isinstance(raw, dict):
        raw = raw.get("weight", 0.0)
    try:
        weight = float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return weight if weight > 0.0 else 0.0


def _is_fixed(experiment: Optional[Experiment]) -> bool:
    return (getattr(experiment, "optimization_type", "fixed") or "fixed") == "fixed"


def weighted_variants(
    experiment: Optional[Experiment], bandit_state: Optional[BanditState]
) -> WeightedVariants:
    """The experiment's variants with a positive bandit weight, as plain values.

    Empty (meaning: use the default hashing) when the experiment is
    fixed-allocation, when there is no bandit state, or when every weight is
    zero or missing.
    """
    if experiment is None or _is_fixed(experiment):
        return []
    if bandit_state is None or not bandit_state.variant_weights:
        return []
    raw_weights = bandit_state.variant_weights
    if not isinstance(raw_weights, dict):
        return []
    # Stable ordering so the cumulative walk is reproducible across sessions.
    variants = sorted(experiment.variants or [], key=lambda v: str(v.id))
    weighted = [
        (variant.id, bandit_weight(raw_weights.get(str(variant.id))))
        for variant in variants
    ]
    return [(vid, w) for vid, w in weighted if w > 0.0]


def pick_variant(
    weighted: WeightedVariants, experiment_id: str, user_id: str
) -> Optional[uuid.UUID]:
    """Deterministic pick from *weighted* for ``(user_id, experiment_id)``.

    The user is hashed into a bucket in ``[0, 1)`` and the bucket is looked up
    in the cumulative distribution of the normalised weights, so repeated calls
    for the same user return the same variant before the sticky assignment row
    exists.
    """
    total = sum(w for _, w in weighted)
    if not weighted or total <= 0.0:
        return None
    digest = hashlib.md5(
        f"{user_id}:{experiment_id}:bandit".encode(), usedforsecurity=False
    ).hexdigest()
    bucket = int(digest, 16) % 10_000 / 10_000

    cumulative = 0.0
    for variant_id, weight in weighted:
        cumulative += weight / total
        if bucket < cumulative:
            return variant_id
    # Floating-point tail: bucket landed at/after the last threshold.
    return weighted[-1][0]


def select_bandit_variant(
    experiment: Optional[Experiment],
    bandit_state: Optional[BanditState],
    user_id: str,
) -> Optional[uuid.UUID]:
    """Pick a variant for a *new* user according to the bandit weights.

    Variants whose weight is missing or ``0`` receive no traffic. Returns
    ``None`` (meaning: use the default traffic-allocation hashing) when the
    experiment is fixed-allocation, when there is no bandit state, or when
    every weight is zero.
    """
    weighted = weighted_variants(experiment, bandit_state)
    if not weighted:
        return None
    return pick_variant(weighted, str(experiment.id), user_id)


def bandit_chooser(db: Session, experiment: Experiment) -> Chooser:
    """Read the bandit weights once; return the per-user choice over plain values.

    A fixed-allocation experiment reads nothing and always answers ``None``.
    """
    if _is_fixed(experiment):
        return lambda _user_id: None
    bandit_state = (
        db.query(BanditState).filter(BanditState.experiment_id == experiment.id).first()
    )
    weighted = weighted_variants(experiment, bandit_state)
    experiment_id = str(experiment.id)
    if not weighted:
        return lambda _user_id: None
    return lambda user_id: pick_variant(weighted, experiment_id, user_id)
