"""GD-3: ``/results`` finds a planted lift, names the right arm and measures it (#897).

500 simulated experiments with a control at 20% and a treatment at 26%
(a lift of 6 percentage points), 2,500 users per arm, each passed to
``binomial_metric_result`` the way ``AnalysisService.get_experiment_results``
calls it (see ``test_golden_aa_significance_rate.py``). Three gates:

* detection: the treatment is reported significant in at least 99% of the
  experiments (495 of 500);
* direction: every experiment in which it is significant names the treatment
  the winner, and nothing else;
* size: the lift the result reports, ``relative_improvement_pct`` times the
  control's ``mean`` (the absolute difference, in percentage points), is
  within 2 points of the planted 6 in the median experiment.

At this size Fisher's exact test has power close to 1 (the difference is
about five standard errors), and the standard error of the difference is
about 1.2 points, so its median absolute error is about 0.8. Measured at
this seed: significant in 499 of 500, the treatment named in all 499, a
median error of 0.84 points (499 or 500 detected and 0.76 to 0.88 points
at 10 other seeds). A lift computed with the arms the wrong way round
reports about -6 points: no winner in any of the 499, a median error of
11.96.

The draws come from one ``numpy`` Generator with a committed seed.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from types import SimpleNamespace
from typing import Optional, Tuple

import numpy as np
import pytest

from backend.app.services.sufficient_stats_analysis import (
    BinomialVariant,
    binomial_metric_result,
)

pytestmark = pytest.mark.unit

SIMS = 500
USERS_PER_ARM = 2_500
CONTROL_RATE = 0.20
TREATMENT_RATE = 0.26
PLANTED_LIFT_PP = 6.0
CONFIDENCE_LEVEL = 0.95
CORRECTION_METHOD = "benjamini_hochberg"
SEED = 897_003

#: 99% of ``SIMS``.
MIN_DETECTED = 495
MAX_MEDIAN_ERROR_PP = 2.0

CONTROL = BinomialVariant("00000000-0000-4000-8000-0000000000c0", "Control", True)
TREATMENT = BinomialVariant("00000000-0000-4000-8000-0000000000e1", "Treatment", False)
METRIC = SimpleNamespace(
    id="00000000-0000-4000-8000-0000000000a0",
    name="conversion",
    metric_type="conversion",
    is_primary=True,
)


@dataclass(frozen=True)
class Sim:
    """What ``/results`` reported for one simulated experiment."""

    significant: bool
    winner: Optional[str]
    #: ``relative_improvement_pct * control mean``: the absolute lift in points.
    lift_pp: Optional[float]


@lru_cache(maxsize=None)
def sims() -> Tuple[Sim, ...]:
    rng = np.random.default_rng(SEED)
    conversions = rng.binomial(
        USERS_PER_ARM, (CONTROL_RATE, TREATMENT_RATE), size=(SIMS, 2)
    )
    alpha = 1.0 - CONFIDENCE_LEVEL
    out = []
    for control, treatment in conversions:
        result = binomial_metric_result(
            [
                (CONTROL, USERS_PER_ARM, int(control)),
                (TREATMENT, USERS_PER_ARM, int(treatment)),
            ],
            alpha,
            CORRECTION_METHOD,
            metric=METRIC,
        )
        rows = {v["variant_id"]: v for v in result["variants"]}
        row = rows[TREATMENT.id]
        improvement = row["relative_improvement_pct"]
        out.append(
            Sim(
                significant=bool(row["is_significant"]),
                winner=result["winning_variant_id"],
                lift_pp=None
                if improvement is None
                else improvement * rows[CONTROL.id]["mean"],
            )
        )
    return tuple(out)


def test_the_planted_lift_is_detected():
    """GD-3: the treatment is significant in at least 495 of 500 experiments."""
    detected = sum(s.significant for s in sims())
    assert detected >= MIN_DETECTED, f"detected in {detected} of {SIMS}"


def test_the_treatment_is_named_the_winner():
    """GD-3: every experiment in which the treatment is significant names it."""
    winners = Counter(s.winner for s in sims() if s.significant)
    detected = sum(winners.values())
    assert winners == {TREATMENT.id: detected}, (
        f"winners named in the {detected} significant experiments: {dict(winners)}; "
        f"expected the treatment {TREATMENT.id} in all of them"
    )


def test_the_reported_lift_is_within_two_points_of_the_planted_lift():
    """GD-3: the median absolute error of the reported lift is at most 2 points."""
    errors = [
        float("inf") if s.lift_pp is None else abs(s.lift_pp - PLANTED_LIFT_PP)
        for s in sims()
    ]
    median_error = statistics.median(errors)
    assert median_error <= MAX_MEDIAN_ERROR_PP, (
        f"median absolute lift error {median_error:.3f} points, "
        f"bound {MAX_MEDIAN_ERROR_PP}"
    )
