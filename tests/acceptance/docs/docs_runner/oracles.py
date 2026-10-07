"""The oracles a journey's expectations may name.

An oracle computes, independently of the product, a number a screen or an API
answer must show: ``ORACLES[name](**args)``. The loader refuses a journey naming
one that is not here. ``expect.number`` and ``expect.cells`` compare what a
screen shows with one, at the precision the screen shows it (``checks.agrees``);
``expect.computed`` compares a number in an api step's answer with one, within a
relative tolerance the step gives.

Each oracle works from the counts or the inputs a journey chose, with the
numerics pinned in ``tests/acceptance/requirements.txt`` (the versions the API
computes with), and imports nothing from the product.
"""

from __future__ import annotations

import math
from typing import Callable, Dict

from scipy import stats
from statsmodels.stats.power import NormalIndPower
from statsmodels.stats.proportion import samplesize_proportions_2indep_onetail


def fisher_exact_p(
    control_users: int,
    control_converted: int,
    treatment_users: int,
    treatment_converted: int,
) -> float:
    """The two-sided p-value of Fisher's exact test on a 2x2 table of users.

    Rows are the two variants, columns the users who converted and those who
    did not. This is the test ``GET /api/v1/results/{experiment_id}`` reports
    for a conversion metric (``statistical_test_used: fisher_exact``), on
    converting users, not events: a user who converted twice counts once.
    """
    table = [
        [treatment_converted, treatment_users - treatment_converted],
        [control_converted, control_users - control_converted],
    ]
    if min(min(row) for row in table) < 0:
        raise ValueError("more users converted than were assigned")
    return float(stats.fisher_exact(table, alternative="two-sided")[1])


def _per_comparison_alpha(alpha: float, n_variants: int) -> float:
    """Bonferroni over the ``n_variants - 1`` comparisons with the control."""
    if n_variants < 2:
        raise ValueError("an experiment has at least two variants")
    return alpha / (n_variants - 1)


def sample_size_proportions(
    baseline_rate: float,
    minimum_detectable_effect: float,
    alpha: float,
    power: float,
    n_variants: int = 2,
) -> float:
    """Users per variant for a conversion rate, by the formula the guide states.

    ``statistics/power-analysis.md`` ("The Formula") gives the two-proportions
    z-test sample size of Fleiss (2003): the null's variance pooled at
    ``p_bar``, the alternative's unpooled, two-sided, with
    ``p2 = baseline + baseline * MDE`` and, for more than two variants, alpha
    divided by the number of comparisons with the control (Bonferroni).
    statsmodels' ``samplesize_proportions_2indep_onetail`` computes exactly
    that (``alternative="two-sided"`` halves alpha), independently of the
    product. A plan needs whole users, at least as many as the formula says,
    so the oracle rounds up.
    """
    corrected = _per_comparison_alpha(alpha, n_variants)
    p1 = baseline_rate
    p2 = baseline_rate + baseline_rate * minimum_detectable_effect
    if not 0 < p1 < p2 < 1:
        raise ValueError("the rates must satisfy 0 < baseline < treatment < 1")
    n = samplesize_proportions_2indep_onetail(
        diff=p2 - p1,
        prop2=p1,
        power=power,
        ratio=1,
        alpha=corrected,
        alternative="two-sided",
    )
    return float(math.ceil(float(n)))


def sample_size_means(
    baseline_rate: float,
    minimum_detectable_effect: float,
    baseline_std: float,
    alpha: float,
    power: float,
    n_variants: int = 2,
) -> float:
    """Users per variant for a mean (``metric_type: mean``), rounded up.

    The guide states no formula for a mean. This is the z-test on two means
    with a known standard deviation, two-sided by its near tail only, as the
    conversion formula is: statsmodels' ``NormalIndPower`` solved for the
    sample size with the standardised effect ``baseline_rate *
    minimum_detectable_effect / baseline_std``, one-sided (``larger``) at half
    the alpha. That is ``2 * (z_alpha + z_power)^2 / effect^2`` to within the
    solver's tolerance; a solve with both tails adds the far tail's sliver of
    power (392.443 users against 392.444 at an effect of 0.2). Below about two
    users per variant the solver finds nothing, and the oracle says so.
    """
    corrected = _per_comparison_alpha(alpha, n_variants)
    effect = baseline_rate * minimum_detectable_effect / baseline_std
    n = float(
        NormalIndPower().solve_power(
            effect_size=effect,
            nobs1=None,
            alpha=corrected / 2,
            power=power,
            ratio=1.0,
            alternative="larger",
        )
    )
    if not math.isfinite(n):
        raise ValueError("the solver found no sample size for these inputs")
    return float(math.ceil(n))


def absolute_effect(
    baseline_rate: float, minimum_detectable_effect: float, points: bool = False
) -> float:
    """The absolute effect a relative MDE means on a baseline.

    The guide: "An MDE of 10% on a 5% baseline means you want to detect a lift
    from 5% to 5.5% (absolute change = 0.5 percentage points)". With
    ``points`` it is in percentage points, as the dashboard shows it.
    """
    effect = baseline_rate * minimum_detectable_effect
    return effect * 100 if points else effect


ORACLES: Dict[str, Callable[..., float]] = {
    "fisher_exact_p": fisher_exact_p,
    "sample_size_proportions": sample_size_proportions,
    "sample_size_means": sample_size_means,
    "absolute_effect": absolute_effect,
}
