"""
``/results`` intervals and significance use the requested confidence level (#454).

Before #454 the proportion path drew every variant's interval with a fixed
``z = 1.96`` and decided the legacy ``is_significant`` at a fixed
``p < 0.05``, whatever ``confidence_level`` the request asked for.  The
expected values here are computed in the test from ``scipy`` (the closed form
``p +/- norm.ppf(1 - (1 - level) / 2) * sqrt(p (1 - p) / n)``), never copied
from the code under test.
"""

import math

import pytest
from scipy.stats import fisher_exact, norm

from backend.app.services.sufficient_stats_analysis import (
    BinomialVariant,
    binomial_metric_result,
    binomial_variant_results,
    two_sided_z,
)
from backend.tests.unit.services.test_binomial_metric_result_characterisation import (
    _CONTROL,
    _PRIMARY_METRIC,
    _TREATMENT_A,
    _TREATMENT_B,
    results_output,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_C = BinomialVariant("c", "control", True)
_T = BinomialVariant("t", "treatment", False)
_METRIC = type(
    "M", (), {"id": "m", "name": "m", "metric_type": "conversion", "is_primary": True}
)()

_LEVELS = (0.90, 0.95, 0.99)


def _closed_form(p: float, n: int, level: float):
    """Normal-approximation interval for a proportion, in percent."""
    z = norm.ppf(1 - (1 - level) / 2)
    half = z * math.sqrt(p * (1 - p) / n)
    return (p - half) * 100, (p + half) * 100


@pytest.mark.parametrize("level", _LEVELS)
def test_variant_interval_is_at_the_requested_level(level):
    # p = 0.12, n = 1000: 90% [10.3097, 13.6903], 99% [9.3530, 14.6470].
    results = binomial_variant_results([(_C, 1000, 120), (_T, 1000, 150)], level)
    control = next(r for r in results if r["is_control"])
    lower, upper = _closed_form(0.12, 1000, level)
    assert control["confidence_interval"][0] == pytest.approx(lower, abs=1e-9)
    assert control["confidence_interval"][1] == pytest.approx(upper, abs=1e-9)


@pytest.mark.parametrize("level", _LEVELS)
def test_metric_result_interval_is_at_one_minus_alpha(level):
    result = binomial_metric_result(
        [(_C, 1000, 120), (_T, 1000, 150)], 1.0 - level, "none", metric=_METRIC
    )
    control = next(v for v in result["variants"] if v["is_control"])
    lower, upper = _closed_form(0.12, 1000, level)
    assert control["confidence_interval"][0] == pytest.approx(lower / 100, abs=1e-11)
    assert control["confidence_interval"][1] == pytest.approx(upper / 100, abs=1e-11)


def test_the_intervals_differ_between_levels():
    """A fixed multiplier gives the same interval at every level."""
    widths = []
    for level in _LEVELS:
        (control, _) = binomial_variant_results(
            [(_C, 1000, 120), (_T, 1000, 150)], level
        )
        lower, upper = control["confidence_interval"]
        widths.append(upper - lower)
    assert widths[0] < widths[1] < widths[2]


# 127/1000 against 100/1000: Fisher p is between 0.05 and 0.10.
_FLIP_COUNTS = [(_C, 1000, 100), (_T, 1000, 127)]


def test_the_flip_case_is_between_the_levels():
    p = fisher_exact([[127, 873], [100, 900]])[1]
    assert 0.05 < p < 0.10


@pytest.mark.parametrize("level, significant", [(0.90, True), (0.95, False)])
def test_legacy_significance_follows_the_level(level, significant):
    treatment = binomial_variant_results(_FLIP_COUNTS, level)[1]
    # The legacy dict carries scipy's numpy bool.
    assert bool(treatment["is_significant"]) is significant


@pytest.mark.parametrize("level, significant", [(0.90, True), (0.95, False)])
def test_metric_significance_follows_the_level(level, significant):
    result = binomial_metric_result(_FLIP_COUNTS, 1.0 - level, "none", metric=_METRIC)
    treatment = next(v for v in result["variants"] if not v["is_control"])
    assert treatment["is_significant"] is significant
    assert result["has_significant_result"] is significant


def test_results_threads_the_level_into_every_interval(monkeypatch):
    """``get_experiment_results`` at 0.90: legacy and schema-shaped intervals."""
    output = results_output("three_variants", 0.90, "none", monkeypatch)
    units = {_TREATMENT_A: 1000, _CONTROL: 1010, _TREATMENT_B: 980}
    purchases = {_TREATMENT_A: 149, _CONTROL: 118, _TREATMENT_B: 131}

    legacy = next(
        m for m in output["metrics_results"] if m["metric_id"] == _PRIMARY_METRIC
    )
    for v in legacy["variant_results"]:
        n = units[v["variant_id"]]
        lower, upper = _closed_form(purchases[v["variant_id"]] / n, n, 0.90)
        assert v["confidence_interval"][0] == pytest.approx(lower, abs=1e-9)
        assert v["confidence_interval"][1] == pytest.approx(upper, abs=1e-9)

    metric = next(m for m in output["metrics"] if m["metric_id"] == _PRIMARY_METRIC)
    for v in metric["variants"]:
        n = units[v["variant_id"]]
        lower, upper = _closed_form(purchases[v["variant_id"]] / n, n, 0.90)
        assert v["confidence_interval"][0] == pytest.approx(lower / 100, abs=1e-11)
        assert v["confidence_interval"][1] == pytest.approx(upper / 100, abs=1e-11)


@pytest.mark.parametrize(
    "level, z", [(0.90, 1.6448536270), (0.95, 1.9599639845), (0.99, 2.5758293035)]
)
def test_two_sided_z(level, z):
    assert two_sided_z(level) == pytest.approx(z, abs=1e-9)


@pytest.mark.parametrize("level", [0.0, 1.0, -0.5, 95.0])
def test_two_sided_z_refuses_a_level_outside_0_1(level):
    with pytest.raises(ValueError, match="confidence_level"):
        two_sided_z(level)
