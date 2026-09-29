"""
The sufficient-statistics estimators' output, pinned per ``ENGINE_VERSION``
and per function.

``backend/app/services/sufficient_stats_analysis.py`` computes metric results
from per-variant counts or sums, for ``/results`` and for callers with no
Experimently database rows (warehouse analysis, #312).  This test runs fixed
counts through each estimator, hashes the outputs and compares the hash with
the one pinned for the current ``ENGINE_VERSION`` **and that function**.

It is separate from ``ENGINE_FINGERPRINTS`` in ``test_engine_fingerprint.py``,
which is not edited for these functions.  The rules:

* never edit the hash of a (version, function) pair that has shipped in a
  release;
* a new estimator adds its own key under the current version; it does not
  touch another function's entry;
* when an estimator's output changes after its version shipped, bump
  ``ENGINE_VERSION`` (see ``test_engine_fingerprint.py``) and add the new
  version's entries, keeping the old ones.
"""

import hashlib
import json
from types import SimpleNamespace
from typing import Any, Callable, Dict

import pytest

from backend.app.core.stats_engine import ENGINE_VERSION
from backend.app.services.sufficient_stats_analysis import (
    BinomialVariant,
    binomial_metric_result,
)
from backend.tests.unit.services.test_binomial_metric_result_characterisation import (
    _FIXTURES,
    _canonical,
    _experiment,
    results_output,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]

#: sha256 of the canonical outputs below, per engine version, per function.
SUFFICIENT_STATS_FINGERPRINTS: Dict[str, Dict[str, str]] = {
    "1.1.0": {
        "binomial_metric_result": "cd5de7d0dd07d9e53e847cd8bb56a2b7e1c1164b590e2370c50f35aee74e0411",
    },
}

_CONTROL = "ffffffff-0000-4000-8000-000000000002"
_TREATMENT_1 = "00000000-0000-4000-8000-000000000001"
_TREATMENT_2 = "77777777-0000-4000-8000-000000000003"

_METRIC = SimpleNamespace(
    id="33333333-0000-4000-8000-000000000003",
    name="Converted",
    metric_type="conversion",
    is_primary=True,
)


def _binomial_outputs() -> Dict[str, Any]:
    """Fixed counts through ``binomial_metric_result``."""
    control = BinomialVariant(_CONTROL, "control", True)
    t1 = BinomialVariant(_TREATMENT_1, "t1", False)
    t2 = BinomialVariant(_TREATMENT_2, "t2", False)
    count_sets = {
        # Treatment first: the control is found by flag, not position.
        "three": [(t1, 1000, 150), (control, 1000, 120), (t2, 1000, 131)],
        "unbalanced": [(control, 2000, 40), (t1, 150, 9), (t2, 30000, 690)],
        "edges": [(t1, 0, 0), (control, 500, 0), (t2, 400, 12)],
    }
    outputs: Dict[str, Any] = {}
    for name, counts in count_sets.items():
        for alpha in (0.05, 0.10):
            for correction in ("none", "bonferroni", "benjamini_hochberg"):
                outputs[f"{name}/{alpha}/{correction}"] = binomial_metric_result(
                    counts, alpha, correction, metric=_METRIC
                )
    return outputs


#: Every function this file pins, by the key it is pinned under.
_ESTIMATORS: Dict[str, Callable[[], Dict[str, Any]]] = {
    "binomial_metric_result": _binomial_outputs,
}


def _fingerprint(outputs: Dict[str, Any]) -> str:
    payload = json.dumps(_canonical(outputs), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("function", sorted(_ESTIMATORS))
def test_sufficient_stats_fingerprint(function):
    pinned = SUFFICIENT_STATS_FINGERPRINTS.get(ENGINE_VERSION, {})
    actual = _fingerprint(_ESTIMATORS[function]())
    assert function in pinned, (
        f"{function} has no pinned fingerprint for ENGINE_VERSION "
        f"{ENGINE_VERSION}; add {actual!r} (see this module's docstring)."
    )
    assert actual == pinned[function], (
        f"{function}'s output changed under ENGINE_VERSION {ENGINE_VERSION} "
        f"(fingerprint {actual}). See this module's docstring."
    )


def test_every_pinned_function_is_exercised():
    """A pinned key with no estimator behind it would pass by being skipped."""
    assert set(SUFFICIENT_STATS_FINGERPRINTS[ENGINE_VERSION]) == set(_ESTIMATORS)


@pytest.mark.parametrize("fixture_name", sorted(_FIXTURES))
@pytest.mark.parametrize(
    "confidence, correction",
    [(0.95, "none"), (0.95, "bonferroni"), (0.90, "benjamini_hochberg")],
)
def test_binomial_metric_result_is_what_results_returns(
    fixture_name, confidence, correction, monkeypatch
):
    """Same counts in, the same objects out: ``==``, not a rounded hash."""
    fixture = _FIXTURES[fixture_name]
    experiment = _experiment()
    output = results_output(fixture_name, confidence, correction, monkeypatch)
    for metric, from_results in zip(
        sorted(experiment.metric_definitions, key=lambda m: not m.is_primary),
        output["metrics"],
    ):
        assert from_results["metric_id"] == metric.id
        counts = [
            (
                v,
                fixture.units[v.id],
                fixture.converted[(metric.event_name, v.id)],
            )
            for v in experiment.variants
        ]
        assert (
            binomial_metric_result(counts, 1.0 - confidence, correction, metric=metric)
            == from_results
        )


def test_binomial_metric_result_needs_a_control():
    with pytest.raises(ValueError, match="control"):
        binomial_metric_result(
            [(BinomialVariant(_TREATMENT_1, "t1", False), 10, 1)],
            0.05,
            "none",
            metric=_METRIC,
        )
