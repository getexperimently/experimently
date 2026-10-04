"""
The interaction test's statistics (#219): ``services/interaction_analysis.py``.

The fit is the binomial maximum-likelihood estimate of the additive model
(``p0j = bj``, ``p1j = bj + d``); the statistic is Pearson's X^2 against it.
These gates were written before the fit:

* **S1-hard.** The tables on which a plain IRLS fails or stops short of the
  maximum (strong interactions, a cell with no converter, a cell where everyone
  converts) are checked against two references that maximise the likelihood
  directly and share nothing with the implementation: a profile likelihood by
  bounded Brent searches on its value, and SLSQP on the joint likelihood with
  its box constraints.  One table's X^2 is frozen as a literal, 855.7295, the
  value both references give.
* **S1 (mild).** statsmodels ``GLM(Binomial(link=Identity()))`` on mild tables
  only, at ``tol=1e-10``, and only where it reports ``converged``.
* **No-raise sweep.** At least 2,000 floor-passing tables with strong
  interactions (lifts from -90% to +200%, J = 2 and 3, allocations up to 99/1)
  give a finite X^2 and never raise.  The sweep is shown to be hard: the IRLS
  that plan v2 specified raises on a share of it.
* **U6.** The floor's boundaries, exactly.
"""

import warnings

import numpy as np
import pytest
from scipy import optimize

from backend.app.services import interaction_analysis as ia

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# References, independent of the implementation
# ---------------------------------------------------------------------------

_EDGE = 1e-12


def _pearson(n, x, fitted):
    with np.errstate(all="ignore"):
        term = (x - n * fitted) ** 2 / (n * fitted * (1 - fitted))
    exact = ((x == 0) & (fitted <= 1e-9)) | ((x == n) & (fitted >= 1 - 1e-9))
    return float(np.where(exact, 0.0, term).sum())


def _column_max(x0, n0, x1, n1, d):
    """max over b of one column's log-likelihood at difference d (Brent)."""
    lo, hi = max(0.0, -d) + _EDGE, min(1.0, 1.0 - d) - _EDGE

    def negative(b):
        total = 0.0
        if x0:
            total += x0 * np.log(b)
        if n0 - x0:
            total += (n0 - x0) * np.log1p(-b)
        if x1:
            total += x1 * np.log(b + d)
        if n1 - x1:
            total += (n1 - x1) * np.log1p(-(b + d))
        return -total

    found = optimize.minimize_scalar(
        negative,
        bounds=(lo, hi),
        method="bounded",
        options={"xatol": 1e-15, "maxiter": 1000},
    )
    return found.x, -found.fun


def profile_reference(n, x) -> float:
    """X^2 at the MLE, by a bounded Brent search on the profile likelihood."""
    n, x = np.asarray(n, float), np.asarray(x, float)
    columns = range(n.shape[1])

    def negative_profile(d):
        return -sum(
            _column_max(x[0, j], n[0, j], x[1, j], n[1, j], d)[1] for j in columns
        )

    found = optimize.minimize_scalar(
        negative_profile,
        bounds=(-1 + 1e-9, 1 - 1e-9),
        method="bounded",
        options={"xatol": 1e-14, "maxiter": 1000},
    )
    d = found.x
    b = np.array(
        [_column_max(x[0, j], n[0, j], x[1, j], n[1, j], d)[0] for j in columns]
    )
    return _pearson(n, x, np.vstack([b, b + d]))


def slsqp_reference(n, x):
    """X^2 at the MLE by SLSQP on the joint likelihood; None if SLSQP fails."""
    n, x = np.asarray(n, float), np.asarray(x, float)
    J = n.shape[1]

    def clipped(t):
        return np.clip(np.vstack([t[:J], t[:J] + t[J]]), 1e-300, 1 - 1e-16)

    def negative(t):
        p = clipped(t)
        return -(x * np.log(p) + (n - x) * np.log1p(-p)).sum()

    def gradient(t):
        p = clipped(t)
        score = x / p - (n - x) / (1 - p)
        return -np.r_[score[0] + score[1], score[1].sum()]

    rows, bounds = [], []
    for j in range(J):
        for treated in (0, 1):
            for sign, offset in ((1, 0.0), (-1, -1.0)):
                row = np.zeros(J + 1)
                row[j], row[J] = sign, sign * treated
                rows.append(row)
                bounds.append(offset)
    A, lb = np.array(rows), np.array(bounds)
    start = np.r_[np.clip(x.sum(0) / n.sum(0), 0.02, 0.98), 0.0]
    found = optimize.minimize(
        negative,
        start,
        jac=gradient,
        constraints=[{"type": "ineq", "fun": lambda t: A @ t - lb, "jac": lambda t: A}],
        method="SLSQP",
        options={"ftol": 1e-15, "maxiter": 5000},
    )
    if not found.success:
        return None
    t = found.x
    return _pearson(n, x, np.clip(np.vstack([t[:J], t[:J] + t[J]]), 0, 1))


# ---------------------------------------------------------------------------
# S1-hard: where a plain IRLS fails
# ---------------------------------------------------------------------------

#: The PE's four tables (``reviews/v2-principal-engineer.md``, F-A), and three
#: more strong ones.  Rows: control, treatment; columns: the other's arms.
HARD_TABLES = {
    "treatment removes the effect in B2": (
        [[5000, 5000], [5000, 5000]],
        [[100, 2000], [100, 100]],
    ),
    "the same, skewed (IRLS oscillates)": (
        [[50000, 2000], [2000, 2000]],
        [[1000, 800], [40, 40]],
    ),
    "a cell with no converter": ([[2000, 2000], [2000, 2000]], [[20, 600], [0, 900]]),
    "a cell where everyone converts": (
        [[2000, 2000], [2000, 2000]],
        [[1960, 1000], [2000, 1900]],
    ),
    "J=3, treatment removes the effect in B3": (
        [[3000, 3000, 3000], [3000, 3000, 3000]],
        [[60, 300, 900], [60, 300, 30]],
    ),
    "opposite, strong": ([[4000, 4000], [4000, 4000]], [[40, 1600], [400, 400]]),
    "constant relative lift (docs)": (
        [[2000, 2000], [2000, 2000]],
        [[200, 400], [300, 600]],
    ),
}

#: X^2 of the oscillating table, from the profile and SLSQP references (they
#: agree to 1e-8); measured independently by the principal engineer.
OSCILLATING_X2 = 855.7295


@pytest.mark.parametrize("name", sorted(HARD_TABLES))
def test_s1_hard_matches_the_profile_likelihood(name):
    n, x = HARD_TABLES[name]
    assert ia.floor_reason(n, x) is None
    result = ia.interaction_test(n, x)
    reference = profile_reference(n, x)
    assert result.statistic == pytest.approx(reference, rel=1e-6)
    assert result.degrees_of_freedom == len(n[0]) - 1


@pytest.mark.parametrize("name", sorted(HARD_TABLES))
def test_s1_hard_matches_slsqp_where_slsqp_succeeds(name):
    n, x = HARD_TABLES[name]
    reference = slsqp_reference(n, x)
    if reference is None:
        pytest.skip("SLSQP stops short on this boundary table; the profile covers it")
    assert ia.interaction_test(n, x).statistic == pytest.approx(reference, rel=1e-6)


def test_s1_hard_the_oscillating_table_is_frozen():
    n, x = HARD_TABLES["the same, skewed (IRLS oscillates)"]
    assert ia.interaction_test(n, x).statistic == pytest.approx(
        OSCILLATING_X2, rel=1e-6
    )


def test_the_two_references_agree_on_the_frozen_literal():
    """The literal is checked against both references, so it is not one method's."""
    n, x = HARD_TABLES["the same, skewed (IRLS oscillates)"]
    assert profile_reference(n, x) == pytest.approx(OSCILLATING_X2, rel=1e-6)
    assert slsqp_reference(n, x) == pytest.approx(OSCILLATING_X2, rel=1e-6)


# ---------------------------------------------------------------------------
# S1 (mild): statsmodels, only where it converges
# ---------------------------------------------------------------------------


def _mild_tables():
    rng = np.random.default_rng(2190415)
    tables = []
    for J in (2, 3, 4):
        for split in (0.5, 0.95, 0.99):
            for base in (0.01, 0.05, 0.3):
                share = np.r_[split, [(1 - split) / (J - 1)] * (J - 1)]
                n = np.round(np.outer([0.5, 0.5], share) * 400000).astype(int)
                rates = base * np.vstack(
                    [1 + 0.1 * np.arange(J), 1.05 + 0.1 * np.arange(J)]
                )
                x = rng.binomial(n, rates)
                if ia.floor_reason(n, x) is None:
                    tables.append((n.tolist(), x.tolist()))
    return tables


MILD_TABLES = _mild_tables()


def _statsmodels(n, x):
    import statsmodels.api as sm

    n, x = np.asarray(n, float), np.asarray(x, float)
    J = n.shape[1]
    design, outcome = [], []
    for treated in (0, 1):
        for j in range(J):
            design.append(
                [1.0] + [float(j == k) for k in range(1, J)] + [float(treated)]
            )
            outcome.append([x[treated, j], n[treated, j] - x[treated, j]])
    family = sm.families.Binomial(link=sm.families.links.Identity())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fitted = sm.GLM(np.array(outcome), np.array(design), family=family).fit(
            tol=1e-10
        )
    return fitted


def test_s1_mild_tables_cover_the_allocations():
    assert len(MILD_TABLES) >= 20


@pytest.mark.parametrize("table", MILD_TABLES, ids=lambda t: f"J{len(t[0][0])}")
def test_s1_matches_statsmodels_on_mild_tables(table):
    n, x = table
    fitted = _statsmodels(n, x)
    assert fitted.converged is True
    assert ia.interaction_test(n, x).statistic == pytest.approx(
        fitted.pearson_chi2, rel=1e-6
    )


# ---------------------------------------------------------------------------
# The no-raise sweep
# ---------------------------------------------------------------------------

SWEEP_SEED = 2190404
SWEEP_MINIMUM = 2000


def _skewed(k, first):
    return np.r_[first, [(1 - first) / (k - 1)] * (k - 1)]


def sweep_tables():
    """Floor-passing, strongly interacting tables on the PE's grid, by J."""
    rng = np.random.default_rng(SWEEP_SEED)
    lifts = np.array([-0.9, -0.5, 0.0, 0.5, 1.0, 2.0])
    by_j = {2: ([], []), 3: ([], [])}
    found = 0
    while found < SWEEP_MINIMUM + 200:
        J = int(rng.choice([2, 3]))
        a = rng.choice(["bal", "90/10", "95/5", "99/1"])
        b = rng.choice(["bal", "90/10", "95/5"])
        pa = np.full(2, 0.5) if a == "bal" else _skewed(2, float(a[:2]) / 100)
        pb = np.full(J, 1 / J) if b == "bal" else _skewed(J, float(b[:2]) / 100)
        base = rng.choice([0.01, 0.03, 0.1, 0.3, 0.5])
        total = int(rng.choice([2000, 10000, 40000, 200000, 1000000]))
        control = base * (1 + rng.choice([0, 0.3, -0.3, 1.0], size=J))
        lift = rng.choice(lifts, size=J)
        if len(set(lift)) == 1:
            continue
        rates = np.clip(np.vstack([control, control * (1 + lift)]), 0, 0.999)
        n = rng.multinomial(total, np.outer(pa, pb).ravel()).reshape(2, J)
        if (n == 0).any():
            continue
        x = rng.binomial(n, rates)
        if ia.floor_reason(n, x) is not None:
            continue
        by_j[J][0].append(n)
        by_j[J][1].append(x)
        found += 1
    return {
        J: (np.array(ns, float), np.array(xs, float)) for J, (ns, xs) in by_j.items()
    }


SWEEP = sweep_tables()


def test_the_sweep_has_enough_tables():
    assert sum(len(n) for n, _ in SWEEP.values()) >= SWEEP_MINIMUM


def test_no_raise_sweep_every_table_gives_a_finite_statistic():
    for n, x in SWEEP.values():
        fitted = ia.fit_additive_batch(n, x)
        assert ((fitted >= 0) & (fitted <= 1)).all()
        statistic = ia.pearson_statistic_batch(n, x, fitted)
        assert np.isfinite(statistic).all()
        assert (statistic >= 0).all()


def test_no_raise_sweep_one_table_at_a_time():
    """The route's path, ``interaction_test``, on the first 40 tables of each J."""
    for n, x in SWEEP.values():
        for k in range(40):
            result = ia.interaction_test(n[k], x[k])
            assert np.isfinite(result.statistic)
            assert 0.0 <= result.p_value <= 1.0


class _SpecFitError(Exception):
    pass


def _v2_spec_irls(n, x):
    """Plan v2's fit as written: IRLS, clamp 1e-9, absolute 1e-12, cap 100, raise."""
    J = n.shape[1]
    design = np.zeros((2 * J, J + 1))
    for j in range(J):
        design[j, j] = design[J + j, j] = design[J + j, J] = 1
    observed, users = (x / n).ravel(), n.ravel()
    fitted = ((x + 0.5) / (n + 1.0)).ravel()
    for _ in range(100):
        weights = users / (fitted * (1 - fitted))
        weighted = design * weights[:, None]
        coefficients = np.linalg.solve(design.T @ weighted, weighted.T @ observed)
        new = np.clip(design @ coefficients, 1e-9, 1 - 1e-9)
        change = np.max(np.abs(new - fitted))
        fitted = new
        if change < 1e-12:
            return
    raise _SpecFitError


def test_the_sweep_is_hard_the_v2_irls_raises_on_part_of_it():
    """The plant: plan v2's IRLS raises on at least 2% of the sweep.

    Measured on this seed: see the PR (the principal engineer measured 5-12%
    on his own seeds).
    """
    raised = total = 0
    with np.errstate(all="ignore"):
        for n, x in SWEEP.values():
            for k in range(len(n)):
                total += 1
                try:
                    _v2_spec_irls(n[k], x[k])
                except (_SpecFitError, np.linalg.LinAlgError):
                    raised += 1
    assert raised / total >= 0.02, f"{raised}/{total}"


# ---------------------------------------------------------------------------
# U6: the floor, at its boundaries
# ---------------------------------------------------------------------------


def test_u6_ninety_nine_users_is_too_few_and_one_hundred_is_enough():
    x = [[50, 50], [50, 50]]
    assert ia.floor_reason([[99, 100], [100, 100]], x) == ia.TOO_FEW_SHARED_USERS
    assert ia.floor_reason([[100, 100], [100, 100]], x) is None


def test_u6_one_column_is_too_few():
    assert ia.floor_reason([[1000], [1000]], [[100], [100]]) == ia.TOO_FEW_SHARED_USERS


def test_u6_expected_converters_at_exactly_25_is_enough():
    # pooled rate 100 / 6400 = 1/64 exactly: 1600 / 64 = 25.0, 1599 / 64 < 25
    x = [[25, 25], [25, 25]]
    assert ia.floor_reason([[1600, 1600], [1600, 1600]], x) is None
    assert ia.floor_reason([[1599, 1601], [1600, 1600]], x) == ia.TOO_FEW_CONVERSIONS


def test_u6_expected_non_converters_at_exactly_25_is_enough():
    x = [[1575, 1575], [1575, 1575]]
    assert ia.floor_reason([[1600, 1600], [1600, 1600]], x) is None
    assert ia.floor_reason([[1599, 1601], [1600, 1600]], x) == ia.TOO_FEW_CONVERSIONS


def test_u6_too_few_users_is_checked_before_too_few_conversions():
    assert ia.floor_reason([[40, 40], [40, 40]], [[0, 0], [0, 0]]) == (
        ia.TOO_FEW_SHARED_USERS
    )


def test_a_table_of_the_wrong_shape_is_refused():
    with pytest.raises(ValueError):
        ia.floor_reason([[100, 100]], [[1, 1]])
