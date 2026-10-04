"""
Does one experiment's treatment effect differ across another experiment's arms (#219)?

Pure statistics, no database access.  For one treatment of experiment E and
the arms of experiment O that share users with E, the counts form a 2 x J
table: row 0 is E's control, row 1 the treatment, one column per arm of O.

The test asks whether the treatment's lift **in percentage points** is the
same in every column.  Under that hypothesis -- the additive model -- the
conversion rates are ``p0j = bj`` and ``p1j = bj + d``: one baseline per arm
of O and one common difference ``d``.  The model is fitted by binomial maximum
likelihood, and the statistic is Pearson's X^2 of the counts against the
fitted rates, on J - 1 degrees of freedom.

A table is tested only when every cell has at least ``MIN_USERS_PER_CELL``
users and at least ``MIN_EXPECTED_PER_CELL`` expected converters and
non-converters at the table's pooled rate (``floor_reason``).  Below that
floor the chi-squared approximation is not calibrated on skewed allocations.
"""

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
from scipy import stats

#: Fewer users than this in any cell of the 2 x J table: not tested.
MIN_USERS_PER_CELL = 100

#: Fewer expected converters (or non-converters) than this in any cell, at
#: the table's pooled rate: not tested.
MIN_EXPECTED_PER_CELL = 25

#: Every ``unavailable_reason`` of the pair analysis, in the order they are
#: checked: the first that applies wins.  The first five apply to a whole
#: experiment, the last two to one treatment.
MUTUAL_EXCLUSION_GROUP = "mutual_exclusion_group"
NO_SHARED_USERS = "no_shared_users"
NO_METRIC = "no_metric"
NOT_A_PROPORTION_METRIC = "not_a_proportion_metric"
NO_CONTROL_VARIANT = "no_control_variant"
TOO_FEW_SHARED_USERS = "too_few_shared_users"
TOO_FEW_CONVERSIONS = "too_few_conversions"

UNAVAILABLE_REASONS = (
    MUTUAL_EXCLUSION_GROUP,
    NO_SHARED_USERS,
    NO_METRIC,
    NOT_A_PROPORTION_METRIC,
    NO_CONTROL_VARIANT,
    TOO_FEW_SHARED_USERS,
    TOO_FEW_CONVERSIONS,
)


class InteractionFitError(Exception):
    """The fit did not reach the maximum-likelihood estimate.

    Never caught: it reaches the route's ``unexpected_failure`` (a 500).  The
    fit below cannot produce it on a table that passes the floor; it is an
    assertion, kept so that a defect is a 500 and never a wrong answer.
    """


@dataclass(frozen=True)
class InteractionTest:
    """The result of ``interaction_test``."""

    statistic: float
    degrees_of_freedom: int
    p_value: float


def _as_tables(n: Sequence, x: Sequence):
    n_arr = np.asarray(n, dtype=float)
    x_arr = np.asarray(x, dtype=float)
    if n_arr.shape != x_arr.shape or n_arr.ndim != 2 or n_arr.shape[0] != 2:
        raise ValueError("n and x must both have shape (2, J)")
    return n_arr, x_arr


def floor_reason(n: Sequence, x: Sequence) -> Optional[str]:
    """Why this 2 x J table is not tested, or None when it is.

    ``too_few_shared_users``: fewer than two columns, or a cell with fewer
    than ``MIN_USERS_PER_CELL`` users.  ``too_few_conversions``: a cell whose
    expected converters ``n * pbar`` or non-converters ``n * (1 - pbar)`` is
    below ``MIN_EXPECTED_PER_CELL``, where ``pbar`` is the table's pooled rate.
    The first is checked first.
    """
    n_arr, x_arr = _as_tables(n, x)
    if n_arr.shape[1] < 2 or (n_arr < MIN_USERS_PER_CELL).any():
        return TOO_FEW_SHARED_USERS
    pooled = x_arr.sum() / n_arr.sum()
    if (n_arr * pooled < MIN_EXPECTED_PER_CELL).any() or (
        n_arr * (1.0 - pooled) < MIN_EXPECTED_PER_CELL
    ).any():
        return TOO_FEW_CONVERSIONS
    return None


def fit_additive_batch(n: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Maximum-likelihood rates of the additive model for each table.

    ``n`` and ``x`` have shape ``(B, 2, J)``; the result has the same shape.
    """
    raise NotImplementedError("the fit is written after its tests (#219)")


def pearson_statistic_batch(
    n: np.ndarray, x: np.ndarray, fitted: np.ndarray
) -> np.ndarray:
    """Pearson's X^2 of each table against its fitted rates.

    A cell whose fitted rate is on the boundary of [0, 1] where its count is
    too (no converter at a fitted 0, every user converting at a fitted 1)
    contributes 0: the model fits it exactly.
    """
    raise NotImplementedError("the fit is written after its tests (#219)")


def interaction_test(n: Sequence, x: Sequence) -> InteractionTest:
    """Pearson's X^2 test of the additive model on one 2 x J table.

    Call it only on a table ``floor_reason`` accepts.

    Raises:
        InteractionFitError: the fit failed (a defect; never caught).
    """
    n_arr, x_arr = _as_tables(n, x)
    fitted = fit_additive_batch(n_arr[None], x_arr[None])
    statistic = float(pearson_statistic_batch(n_arr[None], x_arr[None], fitted)[0])
    if not np.isfinite(statistic):
        raise InteractionFitError("the Pearson statistic is not finite")
    df = n_arr.shape[1] - 1
    return InteractionTest(
        statistic=statistic,
        degrees_of_freedom=df,
        p_value=float(stats.chi2.sf(statistic, df)),
    )
