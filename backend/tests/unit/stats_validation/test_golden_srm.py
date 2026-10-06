"""GD-5: the sample-ratio check flags a broken split and spares a sound one (#897).

``compute_srm`` is the pure chi-square test behind ``/results``' ``srm``
block: ``compute_srm_for_experiment`` counts assignments per variant, reads
each variant's ``traffic_allocation`` (an integer percentage) and passes both
here at the default threshold, ``SRM_P_VALUE_THRESHOLD`` (0.001). This
battery calls it the same way, for a 50/50 experiment with 25,000 assigned
users, the control's count drawn as Binomial(25,000, share) and the
treatment given the rest:

* detection: with a 52/48 split, at least 99% of 2,000 experiments (1,980)
  are flagged. The expected chi-square statistic is about 40 against a
  critical value of about 10.8, so a correct check misses a handful at most.
  (At 10,000 users the same split is flagged in only 1,552 of 2,000, which
  is why the battery uses 25,000.)
* the null: with a true 50/50 split, at most 8 of 2,000 experiments are
  flagged. 8 is ``binom.ppf(0.999, 2000, 0.001)``: a check whose false-flag
  rate is the threshold stays at or under it with probability 0.999.
* one fixed case, 5,200 against 4,800: the statistic is exactly 16 and the
  p-value is ``scipy.stats.chisquare``'s, to a relative 1e-9.

Measured at this seed: 1,997 of the 52/48 experiments flagged and 2 of the
50/50 ones (1,996 to 2,000 and 0 to 7 at 10 other seeds). A threshold of
1e-30 flags none of the 52/48 experiments; a threshold of 0.01 flags 19 of
the 50/50 ones (13 to 26 at the other seeds).

The draws come from one ``numpy`` Generator with a committed seed.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Tuple

import numpy as np
import pytest
from scipy.stats import binom, chisquare

from backend.app.services import srm_service
from backend.app.services.srm_service import compute_srm

pytestmark = pytest.mark.unit

SIMS = 2_000
USERS = 25_000
SKEWED_SHARE = 0.52
SEED = 897_005

#: 99% of ``SIMS``.
MIN_DETECTED = 1_980
#: ``binom.ppf(0.999, SIMS, 0.001)``, checked below.
MAX_NULL_FLAGGED = 8

CONTROL = "00000000-0000-4000-8000-0000000000c0"
TREATMENT = "00000000-0000-4000-8000-0000000000e1"
#: ``traffic_allocation`` 50/50, as ``compute_srm_for_experiment`` passes it.
ALLOCATIONS = {CONTROL: 50.0, TREATMENT: 50.0}


@lru_cache(maxsize=None)
def control_counts() -> Tuple[Tuple[int, ...], Tuple[int, ...]]:
    """The control's assignment count per experiment: (52/48, 50/50)."""
    rng = np.random.default_rng(SEED)
    skewed = rng.binomial(USERS, SKEWED_SHARE, SIMS)
    null = rng.binomial(USERS, 0.5, SIMS)
    return tuple(int(c) for c in skewed), tuple(int(c) for c in null)


def _flagged(counts: Tuple[int, ...]) -> int:
    flagged = 0
    for control in counts:
        result = compute_srm(
            {CONTROL: control, TREATMENT: USERS - control}, ALLOCATIONS
        )
        assert result is not None
        flagged += result.warning
    return flagged


def test_the_null_bound_is_the_binomial_quantile_at_the_threshold():
    assert srm_service.SRM_P_VALUE_THRESHOLD == 0.001
    assert binom.ppf(0.999, SIMS, 0.001) == MAX_NULL_FLAGGED


def test_a_52_48_split_is_flagged():
    """GD-5: at least 1,980 of 2,000 experiments split 52/48 are flagged."""
    skewed, _ = control_counts()
    flagged = _flagged(skewed)
    assert flagged >= MIN_DETECTED, f"flagged {flagged} of {SIMS} 52/48 experiments"


def test_a_50_50_split_is_flagged_at_most_8_times_in_2000():
    """GD-5: at most 8 of 2,000 experiments split 50/50 are flagged."""
    _, null = control_counts()
    flagged = _flagged(null)
    assert flagged <= MAX_NULL_FLAGGED, (
        f"flagged {flagged} of {SIMS} 50/50 experiments; bound {MAX_NULL_FLAGGED}"
    )


def test_fixed_counts_give_the_exact_chi_square_p_value():
    """GD-5: 5,200 against 4,800 is chi-square 16, p as scipy computes it."""
    result = compute_srm({CONTROL: 5_200, TREATMENT: 4_800}, ALLOCATIONS)
    assert result is not None
    expected = chisquare([5_200, 4_800])
    assert result.chi2 == 16.0 == expected.statistic
    assert result.p_value == pytest.approx(expected.pvalue, rel=1e-9, abs=0)
    assert result.warning is True
