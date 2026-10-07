"""The oracles a journey's expectations may name.

An oracle computes, independently of the product, a number a screen or an API
answer must show: ``ORACLES[name](**args)``. The loader refuses a journey naming
one that is not here. ``expect.number`` and ``expect.cells`` compare what a
screen shows with one, at the precision the screen shows it (``checks.agrees``);
``expect.computed`` compares a number in an api step's answer with one, within a
relative tolerance the step gives.

Each oracle works from the counts a journey chose, with the numerics pinned in
``tests/acceptance/requirements.txt`` (the versions the API computes with), and
imports nothing from the product.
"""

from __future__ import annotations

from typing import Callable, Dict

from scipy import stats


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


ORACLES: Dict[str, Callable[..., float]] = {
    "fisher_exact_p": fisher_exact_p,
}
