"""
Seeded simulations of the interaction test (#219): false positives and power.

* **S8.** A skewed null: 2 x 3, both experiments split 95/5, base rate 3%,
  1,000,000 users, main effects but no interaction.  200,000 tables (at
  100,000 plan v1's excess at alpha .20 is only about 4 standard errors, too
  close to the band to be a dependable plant; it measured +2.8 on this seed).  At
  alpha .20, .10, .05 and .01 the share flagged is within 3.5 standard errors
  of alpha.  The plant is plan v1's rule (a Wald test on observed rates, with
  at least 10 observed converters per cell) on the same tables: it must be
  outside the band, above, at every level.
* **S4-S6.** Null bands at 1,000 users per cell: an A/A table, main effects
  with no interaction, and a 2 x 3 table (df = J - 1).
* **S2.** Power: balanced, base 5%, A's lift +1 point in B's control and -1
  point in B's treatment, 5,000 users in the smallest cell: 0.902 measured
  for plan v2 (``arch219-sims-v2/power.out``); the band is 3.5 standard
  errors.

All tables go through the batched fit at once.
"""

import time

import numpy as np
import pytest
from scipy import stats

from backend.app.services import interaction_analysis as ia

pytestmark = pytest.mark.unit

ALPHAS = (0.20, 0.10, 0.05, 0.01)
BAND_SE = 3.5


def _p_values(n, x):
    fitted = ia.fit_additive_batch(n, x)
    statistic = ia.pearson_statistic_batch(n, x, fitted)
    return stats.chi2.sf(statistic, n.shape[2] - 1)


def _passes_floor(n, x):
    pooled = x.sum((1, 2)) / n.sum((1, 2))
    expected = n * pooled[:, None, None]
    return (
        (n >= ia.MIN_USERS_PER_CELL)
        & (expected >= ia.MIN_EXPECTED_PER_CELL)
        & (n - expected >= ia.MIN_EXPECTED_PER_CELL)
    ).all((1, 2))


def _v1_wald(n, x):
    """Plan v1: Cochran's Q with observed-rate variances; c >= 10 observed."""
    rates = x / n
    variance = rates * (1 - rates) / n
    diff = rates[:, 1] - rates[:, 0]
    weight = 1 / (variance[:, 1] + variance[:, 0])
    pooled = (weight * diff).sum(1) / weight.sum(1)
    q = (weight * (diff - pooled[:, None]) ** 2).sum(1)
    tested = ((n >= 100) & (x >= 10) & (n - x >= 10)).all((1, 2))
    return stats.chi2.sf(q, n.shape[2] - 1), tested


def _within_band(p_values, alpha):
    share = float((p_values < alpha).mean())
    se = (alpha * (1 - alpha) / len(p_values)) ** 0.5
    return share, (share - alpha) / se


def _s8_tables():
    rng = np.random.default_rng(8080219)
    reps = 200_000
    split_a = np.array([0.95, 0.05])
    split_b = np.array([0.95, 0.025, 0.025])
    rates = 0.03 * (
        1 + np.array([0.0, 0.2])[:, None] + np.array([0.0, 0.3, 0.15])[None]
    )
    n = rng.multinomial(1_000_000, np.outer(split_a, split_b).ravel(), size=reps)
    n = n.reshape(reps, 2, 3).astype(float)
    x = rng.binomial(n.astype(np.int64), rates[None]).astype(float)
    return n, x


#: S8 takes about 45 s on a laptop, so it is marked slow; the unit job runs
#: slow tests too.
S8 = pytest.mark.slow


@pytest.fixture(scope="module")
def s8():
    n, x = _s8_tables()
    started = time.perf_counter()
    tested = _passes_floor(n, x)
    p_values = _p_values(n[tested], x[tested])
    seconds = time.perf_counter() - started
    print(
        f"S8: {tested.sum()} of {len(n)} tables tested; fit wall time {seconds:.1f} s"
    )
    return n, x, tested, p_values


@S8
def test_s8_every_table_passes_the_floor(s8):
    _, _, tested, _ = s8
    assert tested.all()


@S8
@pytest.mark.parametrize("alpha", ALPHAS)
def test_s8_the_skewed_null_is_calibrated(s8, alpha):
    *_, p_values = s8
    share, z = _within_band(p_values, alpha)
    assert abs(z) <= BAND_SE, f"alpha {alpha}: {share:.4f} (z {z:+.1f})"


@S8
@pytest.mark.parametrize("alpha", ALPHAS)
def test_s8_plan_v1s_rule_fails_the_band(s8, alpha):
    """The plant: the same tables under plan v1's test are above the band."""
    n, x, _, _ = s8
    with np.errstate(all="ignore"):
        p_values, tested = _v1_wald(n, x)
    share, z = _within_band(p_values[tested], alpha)
    assert z > BAND_SE, f"alpha {alpha}: {share:.4f} (z {z:+.1f})"


def _fixed_cells(rates, per_cell, reps, seed):
    rng = np.random.default_rng(seed)
    rates = np.asarray(rates)
    n = np.full((reps,) + rates.shape, float(per_cell))
    x = rng.binomial(per_cell, np.broadcast_to(rates, n.shape)).astype(float)
    return n, x


@pytest.mark.parametrize(
    "name,rates",
    [
        ("S4 A/A", [[0.10, 0.10], [0.10, 0.10]]),
        ("S5 main effects", [[0.10, 0.12], [0.12, 0.14]]),
        ("S6 2x3", [[0.10, 0.12, 0.14], [0.12, 0.14, 0.16]]),
    ],
)
def test_null_bands(name, rates):
    n, x = _fixed_cells(rates, 1000, 2000, seed=219)
    assert _passes_floor(n, x).all()
    flagged = int((_p_values(n, x) < 0.05).sum())
    assert 76 <= flagged <= 126, f"{name}: {flagged} of 2000"


def test_s2_power_for_a_planted_interaction():
    rng = np.random.default_rng(2192026)
    reps, smallest = 4000, 5000
    rates = np.array([[0.05, 0.05], [0.06, 0.04]])
    n = rng.multinomial(4 * smallest, np.full(4, 0.25), size=reps).reshape(reps, 2, 2)
    n = n.astype(float)
    x = rng.binomial(n.astype(np.int64), rates[None]).astype(float)
    tested = _passes_floor(n, x)
    power = float(((_p_values(n, x) < 0.05) & tested).mean())
    se = (0.902 * 0.098 / reps) ** 0.5
    assert abs(power - 0.902) <= BAND_SE * se, f"power {power:.3f}"
