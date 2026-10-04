"""Benjamini-Hochberg and Bonferroni, held to a reference (#580).

Every experiment now stores a correction method, Benjamini-Hochberg unless its
creator chose otherwise, so ``adjusted_p_values`` decides the verdict of every
experiment with more than one treatment. It is compared here with
``statsmodels.stats.multitest.multipletests`` (``fdr_bh`` and ``bonferroni``),
and, for two cases, with values worked by hand, so the test does not rest on
statsmodels alone.

An unknown spelling used to mean "no correction", silently
(``adjusted_p_values([0.03], "benjamini-hochberg") == [None]``). It now raises
``UnknownCorrectionMethodError``, which is deliberately not a ``ValueError``:
the results route answers a ``ValueError`` with 404 and the export reads one as
"no results".
"""

from __future__ import annotations

from typing import List, Optional

import pytest
from statsmodels.stats.multitest import multipletests

from backend.app.services.sufficient_stats_analysis import (
    CORRECTION_METHODS,
    UnknownCorrectionMethodError,
    adjusted_p_values,
)

pytestmark = [pytest.mark.unit]

#: The fifteen p-values of Benjamini and Hochberg (1995), section 4.
BH_1995 = [
    0.0001,
    0.0004,
    0.0019,
    0.0095,
    0.0201,
    0.0278,
    0.0298,
    0.0344,
    0.0459,
    0.3240,
    0.4262,
    0.5719,
    0.6528,
    0.7590,
    1.0000,
]

CASES = {
    "bh_1995": BH_1995,
    "ties": [0.02, 0.02, 0.04],
    "unsorted": [0.04, 0.01, 0.03],
    "with_a_null": [0.01, None, 0.04, 0.03],
    "one": [0.035],
}

STATSMODELS = {"benjamini_hochberg": "fdr_bh", "bonferroni": "bonferroni"}


def _reference(p_values: List[Optional[float]], method: str) -> List[Optional[float]]:
    """statsmodels over the non-null values, None kept where it was."""
    valid = [p for p in p_values if p is not None]
    _, corrected, _, _ = multipletests(valid, method=STATSMODELS[method])
    it = iter(corrected)
    return [None if p is None else float(next(it)) for p in p_values]


@pytest.mark.parametrize("method", sorted(STATSMODELS))
@pytest.mark.parametrize("case", sorted(CASES))
def test_adjusted_p_values_match_statsmodels(case, method):
    p_values = CASES[case]
    actual = adjusted_p_values(p_values, method)
    expected = _reference(p_values, method)
    assert [a is None for a in actual] == [e is None for e in expected]
    # Ties differ from statsmodels by a few ULPs (3.5e-18).
    assert [a for a in actual if a is not None] == pytest.approx(
        [e for e in expected if e is not None], abs=1e-12
    )


@pytest.mark.parametrize(
    "p_values, expected",
    [
        # Ranked 0.01, 0.03, 0.04 of k=3: 0.03, 0.045, 0.04, then the step-up
        # minimum from the top gives 0.03, 0.04, 0.04.
        ([0.04, 0.01, 0.03], [0.04, 0.03, 0.04]),
        # 0.02 * 3/2 = 0.03 for both ties; 0.04 * 3/3 = 0.04.
        ([0.02, 0.02, 0.04], [0.03, 0.03, 0.04]),
    ],
    ids=["unsorted", "ties"],
)
def test_benjamini_hochberg_by_hand(p_values, expected):
    assert adjusted_p_values(p_values, "benjamini_hochberg") == pytest.approx(
        expected, abs=1e-12
    )


def test_no_correction_adjusts_nothing():
    assert adjusted_p_values([0.01, None, 0.04], "none") == [None, None, None]


@pytest.mark.regression
@pytest.mark.parametrize(
    "method", ["benjamini-hochberg", "BH", "holm", "", "Bonferroni", None]
)
def test_an_unknown_method_is_refused_not_read_as_no_correction(method):
    with pytest.raises(UnknownCorrectionMethodError) as caught:
        adjusted_p_values([0.01, 0.03], method)
    assert caught.value.method == method
    # Raised before the p-values are looked at, so an empty list is no escape.
    with pytest.raises(UnknownCorrectionMethodError):
        adjusted_p_values([], method)


def test_the_refusal_is_not_a_value_error():
    """The route's ``except ValueError`` is a 404; this must reach the 500."""
    assert not issubclass(UnknownCorrectionMethodError, ValueError)


def test_the_known_methods_are_the_three_the_api_accepts():
    assert CORRECTION_METHODS == ("none", "bonferroni", "benjamini_hochberg")
