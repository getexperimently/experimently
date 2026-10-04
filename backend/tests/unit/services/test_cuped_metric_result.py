"""
``cuped_metric_result``: CUPED from per-arm sums, held to OLS (#217).

The estimate is the regression ``y ~ C(arm) + x``; these tests compare it
with statsmodels on simulated data whose answer is known.  Every random
number generator is seeded, and nothing here asserts a timing.

* S1: a planted correlation of 0.8 between a 0/1 covariate and a 0/1 outcome
  removes 60-68% of the effect's variance at 5,000 users per arm (the sampling
  sd of the reduction is about 1.3% there; at 1,000 per arm it is 3%, too wide
  for the band).
* S2: ``theta`` equals the ``x`` coefficient of OLS to 1e-9 with unequal arms.
  This is the only gate on ``theta``: an A/A run cannot tell a control-only
  slope from the pooled one.
* S3: the effect equals OLS's arm coefficient to 1e-9, and the standard error
  matches HC2 within 2e-3 at 3,000+ per arm.  At 20 per arm the two differ
  by about 5%, which is why the size is stated.  A ddof 0/1 swap (a ratio of
  about 1.00005) is out of reach at this size.
* S4: an A/A run at 0.05 gives between 76 and 126 false positives in 2,000,
  the binomial 99% band; both bounds are asserted.
* N2/N3: a covariate with no variation gives theta 0 and the unadjusted
  numbers; a treatment with no users is reported with n 0 and a reason.
"""

import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import statsmodels.formula.api as smf

from backend.app.services.sufficient_stats_analysis import (
    FEWER_THAN_2_UNITS,
    NO_RESIDUAL_VARIATION_REASON,
    NO_VARIATION_REASON,
    BinomialVariant,
    SufficientStatsNotComputed,
    SufficientStatsRefused,
    UnknownCorrectionMethodError,
    adjusted_p_values,
    cuped_metric_result,
    two_sided_z,
)

pytestmark = pytest.mark.unit

_METRIC = SimpleNamespace(id="m-1", name="Purchase")
CONTROL = BinomialVariant("c", "control", True)
T1 = BinomialVariant("t1", "t1", False)
T2 = BinomialVariant("t2", "t2", False)
T3 = BinomialVariant("t3", "t3", False)


def _sums(variant, y, x):
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    return (
        variant,
        int(len(y)),
        float(y.sum()),
        float(x.sum()),
        float((y * y).sum()),
        float((x * x).sum()),
        float((x * y).sum()),
    )


def _binary_pair(rng, n, p_y, p_x, rho):
    """``n`` draws of a correlated 0/1 pair with the given means and correlation."""
    p11 = rho * math.sqrt(p_y * (1 - p_y) * p_x * (1 - p_x)) + p_y * p_x
    p10 = p_y - p11
    p01 = p_x - p11
    p00 = 1 - p11 - p10 - p01
    cells = rng.choice(4, size=n, p=[p00, p01, p10, p11])
    y = (cells >= 2).astype(float)
    x = (cells % 2).astype(float)
    return y, x


def _ols(arms):
    """statsmodels' ``y ~ C(arm) + x`` on the raw rows, control as the base."""
    frames = [
        pd.DataFrame({"y": y, "x": x, "arm": name}) for name, (y, x) in arms.items()
    ]
    data = pd.concat(frames, ignore_index=True)
    return smf.ols("y ~ C(arm, Treatment('control')) + x", data=data)


def _arm_term(name):
    return f"C(arm, Treatment('control'))[T.{name}]"


# ---------------------------------------------------------------------------
# S1: planted recovery
# ---------------------------------------------------------------------------


def test_s1_planted_correlation_removes_60_to_68_percent():
    rng = np.random.default_rng(217)
    yc, xc = _binary_pair(rng, 5000, 0.5, 0.5, 0.8)
    yt, xt = _binary_pair(rng, 5000, 0.5, 0.5, 0.8)

    [row] = cuped_metric_result(
        [_sums(CONTROL, yc, xc), _sums(T1, yt, xt)], 0.95, "none", metric=_METRIC
    )

    reduction = row["variance_reduction_pct"] / 100.0
    assert 0.60 <= reduction <= 0.68, reduction
    # The identity it is computed from, recomputed here from the raw rows.
    theta = row["theta"]
    adjusted = np.var(yc - theta * xc, ddof=1) / len(yc) + np.var(
        yt - theta * xt, ddof=1
    ) / len(yt)
    raw = np.var(yc, ddof=1) / len(yc) + np.var(yt, ddof=1) / len(yt)
    assert reduction == pytest.approx(1 - adjusted / raw, abs=1e-12)


# ---------------------------------------------------------------------------
# S2/S3: theta, the effect and the SE against OLS
# ---------------------------------------------------------------------------


def test_s2_theta_equals_the_ols_coefficient_with_unequal_arms():
    rng = np.random.default_rng(2172)
    yc, xc = _binary_pair(rng, 3000, 0.10, 0.20, 0.5)
    yt, xt = _binary_pair(rng, 7000, 0.15, 0.20, 0.5)

    [row] = cuped_metric_result(
        [_sums(CONTROL, yc, xc), _sums(T1, yt, xt)], 0.95, "none", metric=_METRIC
    )

    fit = _ols({"control": (yc, xc), "t1": (yt, xt)}).fit()
    assert row["theta"] == pytest.approx(fit.params["x"], rel=1e-9)


def test_s2_theta_pools_every_arm_with_different_slopes():
    """Three arms of 3,000/9,000/800 with different slopes: still one OLS fit."""
    rng = np.random.default_rng(5)
    yc, xc = _binary_pair(rng, 3000, 0.10, 0.30, 0.45)
    y1, x1 = _binary_pair(rng, 9000, 0.12, 0.30, 0.3)
    y2, x2 = _binary_pair(rng, 800, 0.20, 0.30, 0.1)

    rows = cuped_metric_result(
        [_sums(CONTROL, yc, xc), _sums(T1, y1, x1), _sums(T2, y2, x2)],
        0.95,
        "none",
        metric=_METRIC,
    )

    fit = _ols({"control": (yc, xc), "t1": (y1, x1), "t2": (y2, x2)}).fit()
    for row, name in zip(rows, ("t1", "t2")):
        assert row["theta"] == pytest.approx(fit.params["x"], rel=1e-9)
        assert row["adjusted_effect"] == pytest.approx(
            fit.params[_arm_term(name)], rel=1e-9
        )


def test_s3_effect_equals_ols_and_se_matches_hc2():
    rng = np.random.default_rng(2173)
    yc, xc = _binary_pair(rng, 3000, 0.10, 0.25, 0.5)
    yt, xt = _binary_pair(rng, 4000, 0.13, 0.25, 0.5)

    [row] = cuped_metric_result(
        [_sums(CONTROL, yc, xc), _sums(T1, yt, xt)], 0.90, "none", metric=_METRIC
    )

    model = _ols({"control": (yc, xc), "t1": (yt, xt)})
    ols = model.fit()
    hc2 = model.fit(cov_type="HC2")
    assert row["adjusted_effect"] == pytest.approx(
        ols.params[_arm_term("t1")], rel=1e-9
    )
    assert row["adjusted_se"] == pytest.approx(hc2.bse[_arm_term("t1")], rel=2e-3)
    half = two_sided_z(0.90) * row["adjusted_se"]
    assert row["adjusted_ci_lower"] == row["adjusted_effect"] - half
    assert row["adjusted_ci_upper"] == row["adjusted_effect"] + half


# ---------------------------------------------------------------------------
# S4: A/A false-positive rate
# ---------------------------------------------------------------------------


def test_s4_aa_false_positives_are_inside_the_binomial_band():
    rng = np.random.default_rng(4242)
    false_positives = 0
    for _ in range(2000):
        yc, xc = _binary_pair(rng, 1000, 0.5, 0.5, 0.8)
        yt, xt = _binary_pair(rng, 1000, 0.5, 0.5, 0.8)
        [row] = cuped_metric_result(
            [_sums(CONTROL, yc, xc), _sums(T1, yt, xt)],
            0.95,
            "none",
            metric=_METRIC,
        )
        false_positives += row["is_significant"]
    assert 76 <= false_positives <= 126, false_positives


# ---------------------------------------------------------------------------
# Settings: the level and the correction
# ---------------------------------------------------------------------------


def test_correction_applies_across_the_metrics_treatments():
    rng = np.random.default_rng(31)
    arms = [_sums(CONTROL, *_binary_pair(rng, 2000, 0.10, 0.3, 0.5))]
    for variant, p_y in ((T1, 0.11), (T2, 0.12), (T3, 0.13)):
        arms.append(_sums(variant, *_binary_pair(rng, 2000, p_y, 0.3, 0.5)))

    rows = cuped_metric_result(arms, 0.95, "benjamini_hochberg", metric=_METRIC)

    raw = [row["adjusted_p_value"] for row in rows]
    expected = adjusted_p_values(raw, "benjamini_hochberg")
    assert [row["corrected_p_value"] for row in rows] == expected
    assert expected != raw
    for row in rows:
        assert row["is_significant"] == (row["corrected_p_value"] < 0.05)


def test_an_unknown_correction_method_is_refused():
    arms = [_sums(CONTROL, [0, 1, 1], [0, 1, 0]), _sums(T1, [1, 1, 0], [1, 0, 0])]
    with pytest.raises(UnknownCorrectionMethodError):
        cuped_metric_result(arms, 0.95, "holm", metric=_METRIC)


# ---------------------------------------------------------------------------
# N2/N3 and the edges
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("x_value", [0.0, 1.0])
def test_no_covariate_variation_gives_theta_zero_and_the_unadjusted_numbers(x_value):
    """Coverage of exactly 0% or 100%: theta 0, no NaN, not an error."""
    yc = [1, 0, 0, 0, 1, 0, 0, 0, 0, 0]
    yt = [1, 1, 0, 0, 1, 0, 0, 1, 0, 0]
    rows = cuped_metric_result(
        [
            _sums(CONTROL, yc, [x_value] * len(yc)),
            _sums(T1, yt, [x_value] * len(yt)),
        ],
        0.95,
        "none",
        metric=_METRIC,
    )
    [row] = rows
    assert row["theta"] == 0.0
    assert row["variance_reduction_pct"] == 0.0
    assert row["adjusted_effect"] == row["unadjusted_effect"]
    assert row["adjusted_se"] == row["unadjusted_se"]
    assert all(not (isinstance(v, float) and math.isnan(v)) for v in row.values()), row


def test_adjust_false_is_the_method_none():
    rng = np.random.default_rng(9)
    yc, xc = _binary_pair(rng, 500, 0.2, 0.3, 0.7)
    yt, xt = _binary_pair(rng, 500, 0.25, 0.3, 0.7)
    [row] = cuped_metric_result(
        [_sums(CONTROL, yc, xc), _sums(T1, yt, xt)],
        0.95,
        "none",
        metric=_METRIC,
        adjust=False,
    )
    assert row["theta"] == 0.0
    assert row["variance_reduction_pct"] == 0.0
    assert row["adjusted_effect"] == row["unadjusted_effect"]


def test_a_treatment_with_no_users_is_n_zero_with_a_reason():
    rng = np.random.default_rng(10)
    yc, xc = _binary_pair(rng, 400, 0.2, 0.3, 0.5)
    yt, xt = _binary_pair(rng, 400, 0.3, 0.3, 0.5)
    rows = cuped_metric_result(
        [_sums(CONTROL, yc, xc), _sums(T1, [], []), _sums(T2, yt, xt)],
        0.95,
        "benjamini_hochberg",
        metric=_METRIC,
    )
    empty, full = rows
    assert empty["treatment_sample_size"] == 0
    assert empty["unavailable_reason"] == FEWER_THAN_2_UNITS
    assert empty["adjusted_effect"] is None
    assert full["unavailable_reason"] is None
    # The empty arm is not a comparison: the correction family is one test.
    assert full["corrected_p_value"] == full["adjusted_p_value"]


def test_a_control_with_fewer_than_2_units_is_not_computed():
    with pytest.raises(SufficientStatsNotComputed) as raised:
        cuped_metric_result(
            [_sums(CONTROL, [1], [0]), _sums(T1, [0, 1], [1, 0])],
            0.95,
            "none",
            metric=_METRIC,
        )
    assert raised.value.code == FEWER_THAN_2_UNITS


def test_no_variation_in_either_arm_is_a_reason():
    [row] = cuped_metric_result(
        [_sums(CONTROL, [0, 0, 0], [0, 1, 0]), _sums(T1, [0, 0], [1, 1])],
        0.95,
        "none",
        metric=_METRIC,
    )
    assert row["unavailable_reason"] == NO_VARIATION_REASON
    assert row["adjusted_effect"] is None


@pytest.mark.regression
def test_an_exact_fit_has_no_numbers_never_a_zero_se_p_value():
    """Two 2-user arms where y = x within each arm: the pooled slope explains
    every outcome, the adjusted variance is 0 while the unadjusted is not.
    Reporting SE 0 and p 0 would claim certainty two users per arm cannot give."""
    [row] = cuped_metric_result(
        [_sums(CONTROL, [0, 1], [0, 1]), _sums(T1, [0, 1], [0, 1])],
        0.95,
        "none",
        metric=_METRIC,
    )
    assert row["unavailable_reason"] == NO_RESIDUAL_VARIATION_REASON
    assert row["adjusted_se"] is None
    assert row["adjusted_p_value"] is None
    assert row["is_significant"] is False


@pytest.mark.regression
def test_an_exact_fit_with_an_effect_has_no_numbers_either():
    """y = x + const per arm with a shifted treatment: an effect, still SE 0."""
    [row] = cuped_metric_result(
        [_sums(CONTROL, [0, 1], [0, 1]), _sums(T1, [0, 1], [-1, 0])],
        0.95,
        "none",
        metric=_METRIC,
    )
    assert row["unavailable_reason"] == NO_RESIDUAL_VARIATION_REASON
    assert row["adjusted_p_value"] is None
    assert row["is_significant"] is False


@pytest.mark.parametrize(
    "bad",
    [
        (CONTROL, 3, float("nan"), 1.0, 1.0, 1.0, 1.0),
        (CONTROL, -1, 0.0, 0.0, 0.0, 0.0, 0.0),
        (CONTROL, 3, 3.0, 0.0, 1.0, 0.0, 0.0),  # sum_y2 < sum_y^2 / n
        (CONTROL, 0, 1.0, 0.0, 1.0, 0.0, 0.0),
    ],
)
def test_sums_no_sample_could_produce_are_refused(bad):
    with pytest.raises(SufficientStatsRefused):
        cuped_metric_result(
            [bad, _sums(T1, [0, 1], [1, 0])], 0.95, "none", metric=_METRIC
        )


def test_no_control_is_a_value_error():
    with pytest.raises(ValueError, match="control"):
        cuped_metric_result([_sums(T1, [0, 1], [1, 0])], 0.95, "none", metric=_METRIC)
