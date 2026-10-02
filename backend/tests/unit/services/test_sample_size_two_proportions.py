"""The two-proportion sample size and its inverse, the power (#666).

``sample_size_two_proportions`` (power_calculator_service.py) is what the
results Sample Size tab, the guided setup and ``/utils`` plan with, and
``compute_power`` is its exact inverse, so the
tab's "planned sample reached" and its achieved power never disagree.

* Row 1a: every case against the formula written out here from
  ``scipy.stats.norm.ppf`` (pooled under H0, unpooled under H1), with ``==``,
  plus literal answers so the reference is not only a copy of the code.
* Row 1b: an independent library, statsmodels ``NormalIndPower`` on Cohen's h,
  within 0.5% over a fixed small-effect grid. Cohen's h is a different
  approximation, so equality would be wrong; outside small effects the two
  drift apart by more than 0.5%, which is why the grid stops at baseline 0.6
  and a 10% relative effect.
* ``compute_power`` is at least the target at the planned size and below it
  one user earlier; never asserted equal to it.
"""

import itertools
import math

import pytest
from scipy.stats import norm
from statsmodels.stats.power import NormalIndPower
from statsmodels.stats.proportion import proportion_effectsize

from backend.app.services.power_calculator_service import (
    compute_power,
    sample_size_two_proportions,
)

pytestmark = [pytest.mark.unit]


def size(p1, p2, alpha, power, two_tailed=True):
    return sample_size_two_proportions(p1, p2, alpha, power, two_tailed)


def power_at(n, p1, p2, alpha, two_tailed=True):
    return compute_power(n, p1, p2, alpha, two_tailed)


def _reference(p1: float, mde: float, alpha: float, power: float) -> int:
    """Fleiss, two-sided, written out independently of the service."""
    p2 = p1 * (1 + mde)
    z_a = norm.ppf(1 - alpha / 2)
    z_b = norm.ppf(power)
    p_bar = (p1 + p2) / 2
    n = (
        z_a * math.sqrt(2 * p_bar * (1 - p_bar))
        + z_b * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    ) ** 2 / (p2 - p1) ** 2
    return math.ceil(n)


# (id, baseline, relative mde, alpha per comparison, power, literal answer)
CASES = [
    ("default-12pct", 0.12, 0.05, 0.05, 0.80, 47036),
    ("old-default-10pct", 0.10, 0.05, 0.05, 0.80, 57763),
    ("small-baseline", 0.01, 0.10, 0.05, 0.80, 163095),
    ("large-baseline", 0.60, 0.05, 0.05, 0.80, 4129),
    ("alpha-0.10", 0.12, 0.05, 0.10, 0.80, None),
    ("alpha-0.01-power-0.9", 0.12, 0.05, 0.01, 0.90, 89168),
    ("power-0.5", 0.12, 0.05, 0.05, 0.50, None),
    ("power-0.95", 0.05, 0.10, 0.01, 0.95, 70888),
    ("large-effect", 0.30, 0.20, 0.05, 0.90, 1289),
    # Three and four variants with a correction: alpha / (k - 1) per comparison.
    ("k3-corrected", 0.12, 0.05, 0.05 / 2, 0.80, None),
    ("k4-corrected", 0.12, 0.05, 0.05 / 3, 0.80, None),
]


@pytest.mark.parametrize(
    "p1,mde,alpha,power,literal", [c[1:] for c in CASES], ids=[c[0] for c in CASES]
)
def test_sample_size_matches_the_written_out_formula(p1, mde, alpha, power, literal):
    got = size(p1, p1 * (1 + mde), alpha, power, two_tailed=True)
    assert got == _reference(p1, mde, alpha, power)
    if literal is not None:
        assert got == literal


def test_corrections_need_more_users_than_none():
    plain = size(0.12, 0.126, 0.05, 0.80)
    k3 = size(0.12, 0.126, 0.025, 0.80)
    k4 = size(0.12, 0.126, 0.05 / 3, 0.80)
    assert plain < k3 < k4


# --- row 1b: statsmodels --------------------------------------------------------

BASELINES = [0.01, 0.05, 0.10, 0.20, 0.30, 0.45, 0.60]
RELATIVE_EFFECTS = [0.02, 0.05, 0.10]
ALPHAS = [0.01, 0.05, 0.10]
POWERS = [0.5, 0.8, 0.9, 0.95]
TOLERANCE = 0.005


def _statsmodels(p1: float, mde: float, alpha: float, power: float) -> int:
    h = proportion_effectsize(p1 * (1 + mde), p1)
    n = NormalIndPower().solve_power(
        effect_size=h, alpha=alpha, power=power, ratio=1.0, alternative="two-sided"
    )
    return math.ceil(n)


def test_sample_size_agrees_with_statsmodels_on_small_effects():
    worst = (0.0, None)
    failures = []
    for p1, mde, alpha, power in itertools.product(
        BASELINES, RELATIVE_EFFECTS, ALPHAS, POWERS
    ):
        ours = size(p1, p1 * (1 + mde), alpha, power)
        theirs = _statsmodels(p1, mde, alpha, power)
        gap = abs(ours - theirs) / theirs
        if gap > worst[0]:
            worst = (gap, (p1, mde, alpha, power, ours, theirs))
        if gap > TOLERANCE:
            failures.append((p1, mde, alpha, power, ours, theirs, f"{gap:.4%}"))
    print(f"max gap vs statsmodels: {worst[0]:.4%} at {worst[1]}")
    assert not failures, failures
    assert len(BASELINES) * len(RELATIVE_EFFECTS) * len(ALPHAS) * len(POWERS) == 252


# --- compute_power --------------------------------------------------------------

POWER_GRID = list(
    itertools.product(
        [0.01, 0.05, 0.12, 0.30, 0.60],
        [0.02, 0.05, 0.10, 0.30],
        [0.10, 0.05, 0.025, 0.05 / 3, 0.01],
        [0.5, 0.8, 0.9, 0.95, 0.99],
    )
)


@pytest.mark.parametrize("p1,mde,alpha,target", POWER_GRID)
def test_power_reaches_the_target_exactly_at_the_planned_size(p1, mde, alpha, target):
    p2 = p1 * (1 + mde)
    required = size(p1, p2, alpha, target)
    assert power_at(required, p1, p2, alpha) >= target
    assert power_at(required - 1, p1, p2, alpha) < target
    # "Reached" is the integer comparison, and it agrees with the power one.
    for current in (required - 1, required, required + 1):
        assert (current >= required) == (power_at(current, p1, p2, alpha) >= target)


@pytest.mark.regression
def test_power_at_the_default_case_is_not_below_the_target():
    """The old inline formula gave 0.79999 here while calling it adequate."""
    p1, p2 = 0.12, 0.12 * 1.05
    assert size(p1, p2, 0.05, 0.80) == 47036
    assert power_at(47036, p1, p2, 0.05) >= 0.80
    assert power_at(47035, p1, p2, 0.05) < 0.80


@pytest.mark.parametrize("n", [0, -1])
def test_power_with_no_users_is_zero(n):
    assert power_at(n, 0.12, 0.126, 0.05) == 0.0


def test_power_grows_with_users():
    values = [power_at(n, 0.12, 0.126, 0.05) for n in (1, 1000, 10000, 47036, 200000)]
    assert values == sorted(values)
    assert values[-1] > 0.99
