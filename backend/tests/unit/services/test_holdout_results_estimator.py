"""The estimator behind ``GET /holdout/{id}/results`` (#445).

* A1: on a planted lift, ``p_value`` is Fisher's exact test and the interval
  is the closed-form Agresti-Caffo interval, both to 1e-12.
* A12: the confidence sequence is the observed difference plus or minus the
  normal-mixture half-width on the Agresti-Caffo variance, on a fixture
  where the holdout has no converters (the plug-in variance differs there).
* A4: 400 seeded A/A datasets at 100 against 1,000 users and a 1% rate give
  at most 36 significant results.  Fisher is conservative here (5-14 in the
  PE's runs); a Wald-z p-value gives 123-160.
* ``is_significant`` follows Fisher, and the interval is computed apart from
  it: one fixture where they disagree, with both values asserted.
* Which holdouts cannot be measured, and why.
"""

import math
from types import SimpleNamespace

import numpy as np
import pytest
from scipy import stats

from backend.app.models.global_holdout import LEGACY_HOLDOUT_SALT
from backend.app.services import holdout_results
from backend.app.services.holdout_results import (
    ACTIVATED_BEFORE_MEASUREMENT,
    NOT_ACTIVATED,
    always_valid_interval,
    compare,
    unmeasurable_reason,
)
from backend.app.services.sequential_testing_service import SequentialTestingService

pytestmark = pytest.mark.unit

Z_975 = 1.959963984540054


def _ac(n_h, x_h, n_r, x_r):
    """Agresti-Caffo, written out independently of the module."""
    ph = (x_h + 1) / (n_h + 2)
    pr = (x_r + 1) / (n_r + 2)
    var = ph * (1 - ph) / (n_h + 2) + pr * (1 - pr) / (n_r + 2)
    return pr - ph, var


def test_a1_planted_lift_is_fisher_and_agresti_caffo():
    n_h, x_h, n_r, x_r = 500, 50, 5000, 650  # 10% against 13%
    result = compare(n_h, x_h, n_r, x_r)

    _, fisher_p = stats.fisher_exact([[x_r, n_r - x_r], [x_h, n_h - x_h]])
    centre, var = _ac(n_h, x_h, n_r, x_r)

    assert result["p_value"] == pytest.approx(fisher_p, abs=1e-12)
    assert result["is_significant"] == bool(fisher_p < 0.05)
    assert result["ci_lower"] == pytest.approx(
        centre - Z_975 * math.sqrt(var), abs=1e-12
    )
    assert result["ci_upper"] == pytest.approx(
        centre + Z_975 * math.sqrt(var), abs=1e-12
    )
    assert result["absolute"] == pytest.approx(0.03, abs=1e-12)
    assert result["relative_pct"] == pytest.approx(30.0, abs=1e-9)


def test_a12_confidence_sequence_uses_the_agresti_caffo_variance():
    n_h, x_h, n_r, x_r = 100, 0, 1000, 20
    _, var = _ac(n_h, x_h, n_r, x_r)
    d = x_r / n_r - x_h / n_h
    half = SequentialTestingService.confidence_sequence_half_width(var, 0.001, 0.05)

    lower, upper = always_valid_interval(n_h, x_h, n_r, x_r)

    assert lower == pytest.approx(max(-1.0, d - half), abs=1e-12)
    assert upper == pytest.approx(min(1.0, d + half), abs=1e-12)
    result = compare(n_h, x_h, n_r, x_r)
    assert (result["always_valid_ci_lower"], result["always_valid_ci_upper"]) == (
        lower,
        upper,
    )


def test_the_relative_difference_is_null_when_the_holdout_rate_is_0():
    assert compare(100, 0, 1000, 20)["relative_pct"] is None


@pytest.mark.regression
def test_a4_a_a_false_positives_stay_at_or_below_36_of_400():
    """n_h = 100, n_r = 1000, p = 0.01, 400 datasets, seed 4454, upper bound only."""
    rng = np.random.default_rng(4454)
    x_h = rng.binomial(100, 0.01, size=400)
    x_r = rng.binomial(1000, 0.01, size=400)
    significant = sum(
        compare(100, int(h), 1000, int(r))["is_significant"]
        for h, r in zip(x_h, x_r)
        if h + r > 0
    )
    assert significant <= 36, significant


def test_is_significant_follows_fisher_where_the_interval_disagrees():
    """100 users with no converters against 31 of 1,000: Fisher p is about
    0.105 (not significant) while the interval excludes 0."""
    result = compare(100, 0, 1000, 31)

    assert result["p_value"] == pytest.approx(0.10475845782784073, abs=1e-9)
    assert result["is_significant"] is False
    assert result["ci_lower"] > 0
    assert result["ci_lower"] == pytest.approx(0.00012912826463586102, abs=1e-9)


# ---------------------------------------------------------------------------
# Which holdouts can be measured
# ---------------------------------------------------------------------------


def _holdout(**fields):
    base = {"hash_salt": "holdout:abc", "activated_at": None, "deactivated_at": None}
    base.update(fields)
    return SimpleNamespace(**base)


@pytest.mark.parametrize(
    "fields, reason",
    [
        # a legacy row, whatever activated_at says
        (
            {"hash_salt": LEGACY_HOLDOUT_SALT, "activated_at": "2026-10-01"},
            ACTIVATED_BEFORE_MEASUREMENT,
        ),
        ({"hash_salt": LEGACY_HOLDOUT_SALT}, ACTIVATED_BEFORE_MEASUREMENT),
        # the row the upgrade deactivated: active, nothing recorded
        ({"deactivated_at": "2026-10-01"}, ACTIVATED_BEFORE_MEASUREMENT),
        ({}, NOT_ACTIVATED),
        ({"activated_at": "2026-10-01"}, None),
        ({"activated_at": "2026-10-01", "deactivated_at": "2026-10-02"}, None),
    ],
)
def test_unmeasurable_reason(fields, reason):
    assert unmeasurable_reason(_holdout(**fields)) == reason


def test_the_minimum_is_100_users_per_group():
    assert holdout_results.MIN_USERS_PER_GROUP == 100
