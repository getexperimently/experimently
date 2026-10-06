"""GD-1: how often ``/results`` calls two identical arms significant (#897).

Two arms with the same conversion rate should be reported significant about
as often as the significance level says, and no more often. This battery
simulates 2,000 A/A experiments (5,000 users per arm, a 10% conversion rate)
and passes each one's counts to ``binomial_metric_result``, the function that
turns per-variant counts into ``/results``' ``metrics``, the way
``AnalysisService.get_experiment_results`` calls it: ``alpha = 1 - 0.95``
from the stored confidence level, the stored default correction
(Benjamini-Hochberg, which leaves a single treatment's p-value as it is) and
the control listed first. ``test_binomial_metric_result_characterisation.py``
pins that this function's output is what ``/results`` returns.

The gate counts the experiments whose treatment is reported significant
(Fisher's exact test, two-sided, p < 0.05), not the ones with a winner. A
winner also needs a positive lift, so about half of the significant A/A
experiments name one (43 of the 93 at this seed), and a gate on winners
would hold half the error rate to the whole band.

The band is 3.4% to 6.6% of 2,000 (68 to 132): the nominal 5% plus or minus
1.6 percentage points, about the central 99.9% of Binomial(2,000, 0.05).
Fisher's exact test is conservative at this size, so a correct
implementation sits a little under 5%. Measured: 93 at this seed (4.65%),
and 79 to 106 at 25 other seeds. A p-value compared with 0.10 instead of
0.05 (a doubled significance level, or a one-sided p-value, which is half
the two-sided one) counts 200 at this seed and 166 to 209 at the 25 others.

The draws come from one ``numpy`` Generator with a committed seed, so the
count is the same on every run.
"""

from __future__ import annotations

from functools import lru_cache
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.stats import binom

from backend.app.services.sufficient_stats_analysis import (
    BinomialVariant,
    binomial_metric_result,
)

pytestmark = pytest.mark.unit

SIMS = 2_000
USERS_PER_ARM = 5_000
RATE = 0.10
#: The experiment's stored level; ``/results`` uses ``1 - level`` as alpha.
CONFIDENCE_LEVEL = 0.95
#: The correction an experiment stores unless its creator picks another.
CORRECTION_METHOD = "benjamini_hochberg"
SEED = 897_001

#: 3.4% and 6.6% of ``SIMS``.
MIN_SIGNIFICANT = 68
MAX_SIGNIFICANT = 132

CONTROL = BinomialVariant("00000000-0000-4000-8000-0000000000c0", "Control", True)
TREATMENT = BinomialVariant("00000000-0000-4000-8000-0000000000e1", "Treatment", False)
METRIC = SimpleNamespace(
    id="00000000-0000-4000-8000-0000000000a0",
    name="conversion",
    metric_type="conversion",
    is_primary=True,
)


@lru_cache(maxsize=None)
def significant_experiments() -> int:
    """How many of the ``SIMS`` A/A experiments report the treatment significant."""
    rng = np.random.default_rng(SEED)
    conversions = rng.binomial(USERS_PER_ARM, RATE, size=(SIMS, 2))
    alpha = 1.0 - CONFIDENCE_LEVEL
    significant = 0
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
        row = next(v for v in result["variants"] if v["variant_id"] == TREATMENT.id)
        significant += bool(row["is_significant"])
    return significant


def test_the_band_is_the_nominal_rate_plus_or_minus_one_point_six():
    """The band in counts, within one of the central 99.9% of Binomial(2,000, 0.05)."""
    assert MIN_SIGNIFICANT == round(0.034 * SIMS)
    assert MAX_SIGNIFICANT == round(0.066 * SIMS)
    assert abs(binom.ppf(0.0005, SIMS, 0.05) - MIN_SIGNIFICANT) <= 1
    assert abs(binom.ppf(0.9995, SIMS, 0.05) - MAX_SIGNIFICANT) <= 1


def test_aa_significance_rate_is_within_the_band():
    """GD-1: 68 to 132 of 2,000 A/A experiments are reported significant."""
    significant = significant_experiments()
    assert MIN_SIGNIFICANT <= significant <= MAX_SIGNIFICANT, (
        f"{significant} of {SIMS} A/A experiments significant "
        f"({significant / SIMS:.2%}); the band is {MIN_SIGNIFICANT} to "
        f"{MAX_SIGNIFICANT}"
    )
