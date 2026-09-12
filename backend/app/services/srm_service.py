"""
Sample-ratio mismatch (SRM) detection.

An SRM is the single most common way an A/B test silently lies: the
randomiser was configured for, say, a 50/50 split but the observed
assignment counts are 60/40.  When that happens the groups are no longer
exchangeable and every downstream p-value is meaningless.

The check is a Pearson chi-square goodness-of-fit test of the observed
per-variant assignment counts against the counts expected from the
variants' configured ``traffic_allocation`` (stored as an integer
percentage 0-100 on ``Variant``; allocations that do not sum to 100 are
normalised).  ``warning`` is raised at p < 0.001 — the conventional SRM
threshold, deliberately strict because dashboards are polled many times.

The test only makes sense when the split it is testing against is the split
the randomiser actually used.  An adaptive (multi-armed-bandit) experiment
allocates traffic from ``BanditState.variant_weights``, which the scheduler
updates every few minutes and never writes back to ``traffic_allocation``, so
its assignment counts are *supposed* to drift away from the configured split.
``compute_srm_for_experiment`` therefore returns ``None`` for any experiment
whose ``optimization_type`` is not ``fixed`` (see
:data:`SRM_SUPPORTED_OPTIMIZATION_TYPE`) rather than crying wolf on every
bandit.

Known limitation: an experiment whose ``traffic_allocation`` was edited while
it was running has the same problem — the counts mix the old and the new split
— but nothing records when an allocation changed (``Variant.updated_at`` moves
for any edit, including a rename, so it cannot tell the two apart), so those
experiments are still tested against their current allocation.

``compute_srm`` is a pure function on counts and allocations;
``compute_srm_for_experiment`` reads the inputs from the database.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional
from uuid import UUID

from scipy.stats import chi2 as chi2_dist
from sqlalchemy import func
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

#: p-value below which the observed split is flagged as a mismatch.
SRM_P_VALUE_THRESHOLD: float = 0.001

#: The only ``Experiment.optimization_type`` the SRM test applies to.  Every
#: other value (``thompson_sampling``, ``ucb1``, ``epsilon_greedy``) is an
#: adaptive allocation driven by ``BanditState.variant_weights``, for which
#: ``traffic_allocation`` is not the expected split.
SRM_SUPPORTED_OPTIMIZATION_TYPE: str = "fixed"


@dataclass
class SRMResult:
    """Outcome of a sample-ratio-mismatch test.

    Attributes:
        chi2: Pearson chi-square statistic.
        p_value: Upper-tail probability with ``k - 1`` degrees of freedom.
        warning: ``True`` when ``p_value < threshold``.
        expected: Expected assignment count per variant id (fractional).
        observed: Observed assignment count per variant id.
    """

    chi2: float
    p_value: float
    warning: bool
    expected: Dict[str, float] = field(default_factory=dict)
    observed: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Plain-dict form used by the API schema and JSON snapshots."""
        return {
            "chi2": self.chi2,
            "p_value": self.p_value,
            "warning": self.warning,
            "expected": dict(self.expected),
            "observed": dict(self.observed),
        }


def compute_srm(
    observed: Mapping[str, int],
    allocations: Mapping[str, float],
    threshold: float = SRM_P_VALUE_THRESHOLD,
) -> Optional[SRMResult]:
    """Chi-square test of observed assignment counts against allocations.

    Args:
        observed: ``{variant_id: assignment_count}``.  Variants missing from
            the mapping count as 0.  Keys not present in ``allocations`` are
            ignored (they are not part of the randomised split).
        allocations: ``{variant_id: traffic_allocation}`` in any consistent
            unit (0-100 percentages or 0-1 fractions); they are normalised
            to sum to 1.  Variants with a zero or negative allocation are
            excluded from the test (no assignment is expected for them).
        threshold: p-value below which ``warning`` is set.

    Returns:
        ``SRMResult`` or ``None`` when the test is undefined: fewer than two
        variants with a positive allocation, or zero assignments in total.
    """
    keys = [str(k) for k, a in allocations.items() if a is not None and float(a) > 0.0]
    if len(keys) < 2:
        return None

    alloc = {str(k): float(a) for k, a in allocations.items() if str(k) in keys}
    alloc_total = sum(alloc.values())
    if alloc_total <= 0.0:
        return None

    obs = {k: int(observed.get(k, 0) or 0) for k in keys}
    total = sum(obs.values())
    if total <= 0:
        return None

    expected = {k: total * alloc[k] / alloc_total for k in keys}
    statistic = sum((obs[k] - expected[k]) ** 2 / expected[k] for k in keys)
    dof = len(keys) - 1
    p_value = float(chi2_dist.sf(statistic, dof))
    p_value = min(1.0, max(0.0, p_value))

    return SRMResult(
        chi2=float(statistic),
        p_value=p_value,
        warning=p_value < threshold,
        expected=expected,
        observed=obs,
    )


def _is_fixed_allocation(optimization_type: Any) -> bool:
    """True when an experiment splits traffic by ``traffic_allocation``.

    ``None`` (never set / legacy row) counts as fixed: those experiments are
    served the static split.  Anything else is a bandit.
    """
    if optimization_type is None:
        return True
    value = getattr(optimization_type, "value", optimization_type)
    return str(value).lower() == SRM_SUPPORTED_OPTIMIZATION_TYPE


def compute_srm_for_experiment(
    db: Session,
    experiment_id: UUID,
    threshold: float = SRM_P_VALUE_THRESHOLD,
) -> Optional[SRMResult]:
    """Run the SRM test on an experiment's variants and assignment rows.

    Reads ``Variant.traffic_allocation`` (0-100) and counts ``Assignment``
    rows per variant.

    Returns:
        ``None`` when the test is undefined (see :func:`compute_srm`) **or
        when the experiment does not use a fixed allocation**: a bandit
        (``optimization_type`` ``thompson_sampling`` / ``ucb1`` /
        ``epsilon_greedy``) reallocates traffic on purpose from
        ``BanditState.variant_weights``, which is never written back to
        ``traffic_allocation``, so a chi-square test against the configured
        split would flag every adaptive experiment as broken randomisation.
        An ``SRMResult`` otherwise.
    """
    from backend.app.models.assignment import Assignment
    from backend.app.models.experiment import Experiment, Variant

    variant_rows = (
        db.query(Variant.id, Variant.traffic_allocation)
        .filter(Variant.experiment_id == experiment_id)
        .all()
    )
    allocations = {
        str(variant_id): float(allocation if allocation is not None else 0)
        for variant_id, allocation in variant_rows
    }
    if len(allocations) < 2:
        return None

    # Adaptive allocation: the configured split is not the expected split.
    optimization_type = (
        db.query(Experiment.optimization_type)
        .filter(Experiment.id == experiment_id)
        .scalar()
    )
    if not _is_fixed_allocation(optimization_type):
        logger.debug(
            "SRM skipped for experiment %s: optimization_type=%s is adaptive",
            experiment_id,
            optimization_type,
        )
        return None

    count_rows = (
        db.query(Assignment.variant_id, func.count(Assignment.id))
        .filter(Assignment.experiment_id == experiment_id)
        .group_by(Assignment.variant_id)
        .all()
    )
    observed = {str(variant_id): int(count) for variant_id, count in count_rows}

    return compute_srm(observed, allocations, threshold=threshold)
