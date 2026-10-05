"""Statistical gates for the sequential confidence sequence (#231).

The confidence sequence on ``GET /results/{id}/sequential`` is the inversion of
the same normal-mixture mSPRT that decides ``can_stop`` (Johari et al. 2017;
Howard et al. 2021):

    delta_hat +/- sqrt( V (V + tau^2) / tau^2 * (2 ln(1/alpha) + ln((V + tau^2) / V)) )

Before #231 the half-width was ``sqrt(V + tau^2) * sqrt(2 ln(1/alpha))``, which
never falls below ``sqrt(tau^2 * 2 ln 20) = 0.0774`` and so stopped narrowing,
and which disagreed with ``can_stop`` on 79 of 40,000 looks.

Since #854, V is the Agresti-Caffo variance of the difference: one success and
one failure are added to each arm, ``p~ = (x + 1) / (n + 2)``, and
``V = p~_c (1 - p~_c) / (n_c + 2) + p~_t (1 - p~_t) / (n_t + 2)``.  The
expected half-widths below are literals: each was computed once outside the
service, with exact fractions for V and 50-digit ``decimal`` arithmetic for the
logarithms and the square root, and the exact V is given beside it so the
number can be re-derived by hand.  They are not recomputed from a formula
typed into this file, so a test cannot agree with the service by sharing its
mistake.  ``test_sequential_unequal_arms.py`` holds the coverage gates at
unequal splits.

The gates come in pairs, because an infinitely wide interval passes every
coverage and false-positive gate: 231a/231b pin the width (closed form, and
that it narrows), 231c pins the agreement with the stop decision, and 231d/231e
are the null-rate and coverage gates the width gates keep honest.

Every simulation uses a fixed seed, so it is deterministic. The bounds are the
binomial 0.999 quantiles at the nominal level, so a correct method clears them
under any seed: ``binom.ppf(.999, 2000, .05) == 131`` false rejections, and
coverage ``>= 2000 - binom.ppf(.999, 2000, .05) == 1869``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import List, Tuple

import numpy as np
import pytest
from scipy.stats import binom

from backend.app.services.sequential_testing_service import SequentialTestingService

pytestmark = pytest.mark.unit

ALPHA = 0.05
TAU_SQUARED = 0.001
PATHS = 2_000
LOOKS = 20

#: binom.ppf(.999, 2000, .05), checked in test_the_bounds_are_the_binomial_quantiles.
MAX_FALSE_REJECTIONS = 131
MIN_COVERED_PATHS = 1_869

#: Absolute effect of the A/B paths (treatment minus control).
DELTA = 0.01

# Base rates, arm-size ratios (treatment / control) and look spacings the
# paths draw from. Unequal arms are included on purpose: the duality has to
# hold for any V, not only for balanced designs.
_BASE_RATES = (0.02, 0.05, 0.10, 0.30, 0.50)
_RATIOS = (0.25, 0.5, 1.0, 2.0, 3.0)
_STEPS = (100, 400, 1_000)


def closed_form_half_width(variance: float, tau_squared: float, alpha: float) -> float:
    """The normal-mixture half-width, computed here independently of the service."""
    return math.sqrt(
        variance
        * (variance + tau_squared)
        / tau_squared
        * (2.0 * math.log(1.0 / alpha) + math.log((variance + tau_squared) / variance))
    )


@dataclass(frozen=True)
class Look:
    can_stop: bool
    lower: float
    upper: float
    true_delta: float


def _simulate(seed: int, effect: float) -> List[List[Look]]:
    """``PATHS`` paths of ``LOOKS`` cumulative looks each, through the service."""
    service = SequentialTestingService()
    rng = np.random.default_rng(seed)
    paths: List[List[Look]] = []
    for _ in range(PATHS):
        p_c = float(rng.choice(_BASE_RATES))
        p_t = p_c + effect
        ratio = float(rng.choice(_RATIOS))
        step_c = int(rng.choice(_STEPS))
        step_t = max(1, int(round(step_c * ratio)))
        conv_c = np.cumsum(rng.binomial(step_c, p_c, size=LOOKS))
        conv_t = np.cumsum(rng.binomial(step_t, p_t, size=LOOKS))
        looks: List[Look] = []
        for k in range(LOOKS):
            n_c, n_t = step_c * (k + 1), step_t * (k + 1)
            s_c, s_t = int(conv_c[k]), int(conv_t[k])
            msprt = service.compute_msprt(
                s_c, n_c, s_t, n_t, tau_squared=TAU_SQUARED, alpha=ALPHA
            )
            cs = service.compute_always_valid_ci(
                s_c, n_c, s_t, n_t, alpha=ALPHA, tau_squared=TAU_SQUARED
            )
            looks.append(Look(msprt.can_stop, cs.lower, cs.upper, effect))
        paths.append(looks)
    return paths


@lru_cache(maxsize=None)
def aa_paths() -> Tuple[Tuple[Look, ...], ...]:
    return tuple(tuple(p) for p in _simulate(seed=231_001, effect=0.0))


@lru_cache(maxsize=None)
def ab_paths() -> Tuple[Tuple[Look, ...], ...]:
    return tuple(tuple(p) for p in _simulate(seed=231_002, effect=DELTA))


def _half_width_at(n_per_arm: int, rate: float = 0.1) -> float:
    successes = int(round(rate * n_per_arm))
    cs = SequentialTestingService().compute_always_valid_ci(
        successes,
        n_per_arm,
        successes,
        n_per_arm,
        alpha=ALPHA,
        tau_squared=TAU_SQUARED,
    )
    return cs.width / 2.0


# ---------------------------------------------------------------------------
# The bounds themselves
# ---------------------------------------------------------------------------


def test_the_bounds_are_the_binomial_quantiles():
    assert binom.ppf(0.999, PATHS, ALPHA) == MAX_FALSE_REJECTIONS
    assert PATHS - binom.ppf(0.999, PATHS, ALPHA) == MIN_COVERED_PATHS


# ---------------------------------------------------------------------------
# 231a / 231b: the width gates
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_cs_half_width_closed_form():
    """231a: at 10k per arm, p = 0.1, the half-width is the mixture closed form.

    1,000 of 10,000 in each arm: p~ = 1001/10002, so
    V = 2 p~ (1 - p~) / 10002 = 9010001/500300060004 (about 1.8009e-5), and the
    half-width is 0.013557851680358.  The pre-#231 formula gave 0.0781 here,
    and the plug-in V = 2 (0.1)(0.9) / 10000 of #231 to #854 gave 0.0135547.
    """
    assert _half_width_at(10_000) == pytest.approx(0.013557851680358, rel=1e-9)


@pytest.mark.parametrize(
    ("n_per_arm", "rate", "expected"),
    [
        # x = 100 per arm:     V = 91001/503006004
        (1_000, 0.1, 0.040998093600704),
        # x = 60 per arm:      V = 179401/13527018004
        (3_000, 0.02, 0.011780646825829),
        # x = 25,000 per arm:  V = 1/100004 (p~ = 1/2 exactly)
        (50_000, 0.5, 0.010350003952168),
        # x = 1,000,000:       V = 9000010000001/500000300000060000004
        (10_000_000, 0.1, 0.000551819546292),
    ],
)
def test_cs_half_width_closed_form_across_sizes(n_per_arm, rate, expected):
    """231a, at other sizes and base rates (literals; see the module docstring)."""
    assert _half_width_at(n_per_arm, rate) == pytest.approx(expected, rel=1e-9)


def test_cs_narrows_below_a_tenth_of_a_point_at_ten_million():
    """231b: the interval keeps narrowing; the pre-#231 one stalled at 0.0774."""
    assert _half_width_at(10_000_000) < 0.001


# ---------------------------------------------------------------------------
# 231c: the interval agrees with the stop decision on every look
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_cs_matches_can_stop():
    """231c: ``can_stop == (0 not in CS)`` on every one of 80,000 looks.

    By duality this is an identity, not a rate, so the bound is zero. The
    pre-#231 interval disagreed on 79 of 40,000 A/A looks. The data are
    random binomial draws, never a constructed boundary case, where floating
    point can put Lambda at 19.999999999999975 against a boundary of 20.
    """
    disagreements = []
    stops = 0
    looks = 0
    for kind, paths in (("A/A", aa_paths()), ("A/B", ab_paths())):
        for i, path in enumerate(paths):
            for k, look in enumerate(path):
                looks += 1
                stops += look.can_stop
                excludes_zero = not (look.lower <= 0.0 <= look.upper)
                if look.can_stop != excludes_zero:
                    disagreements.append((kind, i, k, look))
    assert looks == 2 * PATHS * LOOKS
    # Not vacuous: both decisions occur many times.
    assert stops > 1_000 and looks - stops > 1_000, stops
    assert disagreements == [], (
        f"{len(disagreements)} looks where can_stop and the interval disagree; "
        f"first: {disagreements[:3]}"
    )


# ---------------------------------------------------------------------------
# 231d: type I error under continuous peeking
# ---------------------------------------------------------------------------


def test_aa_false_rejections_under_peeking():
    """231d: on 2,000 A/A paths read 20 times each, at most 131 ever stop."""
    rejected = sum(any(look.can_stop for look in path) for path in aa_paths())
    assert rejected <= MAX_FALSE_REJECTIONS, rejected


# ---------------------------------------------------------------------------
# 231e: anytime coverage
# ---------------------------------------------------------------------------


def test_cs_anytime_coverage():
    """231e: the interval holds the true effect at every look on >= 1,869 of 2,000 paths."""
    covered = sum(
        all(look.lower <= look.true_delta <= look.upper for look in path)
        for path in ab_paths()
    )
    assert covered >= MIN_COVERED_PATHS, covered


# ---------------------------------------------------------------------------
# Degenerate inputs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "counts",
    [
        (0, 0, 0, 0),  # no data
        (0, 0, 5, 100),  # empty control arm
        (5, 100, 0, 0),  # empty treatment arm
    ],
)
def test_no_finite_interval_without_data(counts):
    """n = 0 in an arm: the interval is [-1, 1] and the mSPRT cannot stop."""
    service = SequentialTestingService()
    cs = service.compute_always_valid_ci(*counts, alpha=ALPHA, tau_squared=TAU_SQUARED)
    msprt = service.compute_msprt(*counts, tau_squared=TAU_SQUARED, alpha=ALPHA)
    assert (cs.lower, cs.upper, cs.width) == (-1.0, 1.0, 2.0)
    assert cs.sample_size == counts[1] + counts[3]
    assert msprt.lambda_ratio == 1.0
    assert msprt.can_stop is False


#: 0 or 500 of 500 in an arm: p~ = 1/502 or 501/502, so each arm contributes
#: (501/502^2) / 502 and V = 501/63253004 (about 7.9206e-6) in all three
#: cases below.  Half-width 0.009301626884454 (literal; module docstring).
_ALL_OR_NOTHING_HALF_WIDTH = 0.009301626884454


@pytest.mark.regression
@pytest.mark.parametrize(
    ("counts", "lower", "upper", "can_stop"),
    [
        # Nobody converts in either arm: a narrow interval around 0, no stop.
        (
            (0, 500, 0, 500),
            -_ALL_OR_NOTHING_HALF_WIDTH,
            _ALL_OR_NOTHING_HALF_WIDTH,
            False,
        ),
        # Everybody converts in both arms: the same.
        (
            (500, 500, 500, 500),
            -_ALL_OR_NOTHING_HALF_WIDTH,
            _ALL_OR_NOTHING_HALF_WIDTH,
            False,
        ),
        # 0 of 500 against 500 of 500: the largest possible difference, which
        # can now stop.  The upper end is clipped to 1.
        ((0, 500, 500, 500), 1.0 - _ALL_OR_NOTHING_HALF_WIDTH, 1.0, True),
    ],
)
def test_all_or_nothing_arms_get_a_finite_interval(counts, lower, upper, can_stop):
    """#854: with no variation inside either arm the interval is finite.

    The plug-in variance used before #854 is 0 here, so the interval was
    [-1, 1] and the mSPRT could never stop, even at 0/500 against 500/500.
    The Agresti-Caffo variance is positive for any counts.
    """
    service = SequentialTestingService()
    cs = service.compute_always_valid_ci(*counts, alpha=ALPHA, tau_squared=TAU_SQUARED)
    msprt = service.compute_msprt(*counts, tau_squared=TAU_SQUARED, alpha=ALPHA)
    assert cs.lower == pytest.approx(lower, rel=1e-9)
    assert cs.upper == pytest.approx(upper, rel=1e-9)
    assert cs.sample_size == 1_000
    assert msprt.can_stop is can_stop
    assert msprt.can_stop == (not (cs.lower <= 0.0 <= cs.upper))


@pytest.mark.regression
@pytest.mark.parametrize(
    "counts",
    [
        # 1% against 99% at 100 per arm.
        (1, 100, 99, 100),
        # A large, real experiment: 10% against 11% at ten million per arm,
        # |Z| about 72.
        (1_000_000, 10_000_000, 1_100_000, 10_000_000),
    ],
)
def test_overwhelming_difference_stays_finite_and_stops(counts):
    """#854: the evidence ratio stays a finite float however strong the evidence.

    ``exp(tau^2 Z^2 / (2 (V + tau^2)))`` does not fit in a double once the
    exponent passes about 709.78 (|Z| above about 38 when V is much smaller
    than tau^2).  The ratio is computed in log space and capped at the largest
    finite double, which is still far above 1/alpha, so the test stops and the
    interval excludes 0.
    """
    service = SequentialTestingService()
    msprt = service.compute_msprt(*counts, tau_squared=TAU_SQUARED, alpha=ALPHA)
    cs = service.compute_always_valid_ci(*counts, alpha=ALPHA, tau_squared=TAU_SQUARED)
    assert math.isfinite(msprt.lambda_ratio)
    assert msprt.lambda_ratio == pytest.approx(1.7976931348622732e308, rel=1e-12)
    assert msprt.can_stop is True
    assert 0.0 < msprt.always_valid_p_value < ALPHA
    assert msprt.can_stop == (not (cs.lower <= 0.0 <= cs.upper))


# ---------------------------------------------------------------------------
# The interval stays inside [-1, 1]
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_small_sample_interval_is_clipped_to_the_proportion_range():
    """At p = 0.5 with 10 per arm the half-width is about 3.27: the interval is [-1, 1].

    A difference of proportions cannot leave [-1, 1]. Before the clip this
    look was reported as roughly [-3.92, 3.92] (plug-in variance), which the
    dashboard drew raw.  The clipped interval must still be the whole range (a
    wide interval must not look narrow) and must still contain 0, as
    ``can_stop`` is false.  Agresti-Caffo: p~ = 6/12 in each arm, V = 1/24.
    """
    service = SequentialTestingService()
    raw_half_width = closed_form_half_width(1 / 24, TAU_SQUARED, ALPHA)
    assert raw_half_width > 3.2  # not vacuous: the unclipped interval leaves [-1, 1]
    cs = service.compute_always_valid_ci(
        5, 10, 5, 10, alpha=ALPHA, tau_squared=TAU_SQUARED
    )
    msprt = service.compute_msprt(5, 10, 5, 10, tau_squared=TAU_SQUARED, alpha=ALPHA)
    assert (cs.lower, cs.upper, cs.width) == (-1.0, 1.0, 2.0)
    assert cs.lower <= 0.0 <= cs.upper
    assert msprt.can_stop is False


@pytest.mark.regression
def test_clip_is_one_sided_when_only_one_end_leaves_the_range():
    """2/20 against 18/20: the upper end is clipped to 1, the lower end is not.

    p~_c = 3/22, p~_t = 19/22, V = 57/5324, half-width 0.872983362597160
    (literal; module docstring), so the raw interval is 0.8 -/+ that:
    [-0.072983362597160, 1.672983362597160].
    """
    service = SequentialTestingService()
    half_width = 0.872983362597160
    cs = service.compute_always_valid_ci(
        2, 20, 18, 20, alpha=ALPHA, tau_squared=TAU_SQUARED
    )
    assert 0.8 + half_width > 1.0 > 0.8 - half_width > -1.0  # not vacuous
    assert cs.upper == 1.0
    assert cs.lower == pytest.approx(-0.072983362597160, rel=1e-9)
    assert cs.width == pytest.approx(cs.upper - cs.lower, rel=1e-12)
