"""The mean-metric fixtures and their exact reference (plan SPEC 5 and errata 1).

* **F-MEAN-1** -- ``rng = default_rng(20260927)``; control
  ``1e4 + rng.normal(0.0, 1.0, 200_000)``, then treatment
  ``1e4 + rng.normal(0.005, 1.0, 200_000)``, float64.
* **F-MEAN-1 +1e9** -- the same arrays plus 1e9, in float64.
* **F-MEAN-REV** -- zero-inflated revenue with full-mantissa values: 95%
  zeros, ``lognormal(3, 1)`` rounded to cents, capped at 500; control
  ``seed 1, lift 0``, treatment ``seed 2, lift 0.01``; 200,000 per arm.

Tolerances are per fixture.  F-MEAN-1's 1e-12 discriminates the centred
design from the naive ``SUM(y)``/``SUM(y*y)`` form (measured 4.0e-6) and from
feeding reconstructed means onward.  F-MEAN-REV's values are not exact after
centring, and its tolerance, 1e-10, is the measured worst (8.0e-12 across
summation orders and DuckDB threads=1/threads=8) with headroom.

The reference is exact: sums of the stored float64 values as integers over a
common power-of-two denominator, so no rounding enters it.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Callable

import numpy as np

N_PER_ARM = 200_000


@dataclass(frozen=True)
class MeanFixture:
    name: str
    control: np.ndarray
    treatment: np.ndarray
    tolerance: float


def f_mean_1() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(20260927)
    control = 1e4 + rng.normal(0.0, 1.0, N_PER_ARM)
    treatment = 1e4 + rng.normal(0.005, 1.0, N_PER_ARM)
    return control, treatment


def f_mean_1_plus_1e9() -> tuple[np.ndarray, np.ndarray]:
    control, treatment = f_mean_1()
    return control + 1e9, treatment + 1e9


def _revenue(seed: int, lift: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    converted = rng.random(N_PER_ARM) < 0.05 * (1 + lift)
    amount = np.round(np.exp(rng.normal(3.0, 1.0, N_PER_ARM)), 2)
    return np.minimum(np.where(converted, amount, 0.0), 500.0)


def f_mean_rev() -> tuple[np.ndarray, np.ndarray]:
    return _revenue(1, 0.0), _revenue(2, 0.01)


FIXTURES: dict[str, tuple[Callable[[], tuple[np.ndarray, np.ndarray]], float]] = {
    "f_mean_1": (f_mean_1, 1e-12),
    "f_mean_1_plus_1e9": (f_mean_1_plus_1e9, 2e-12),
    "f_mean_rev": (f_mean_rev, 1e-10),
}


def load(name: str) -> MeanFixture:
    make, tolerance = FIXTURES[name]
    control, treatment = make()
    return MeanFixture(name, control, treatment, tolerance)


@dataclass(frozen=True)
class ExactArm:
    n: int
    mean: Fraction
    variance: Fraction


def exact_arm(values: np.ndarray) -> ExactArm:
    """Mean and sample variance of the stored float64 values, exactly."""
    ratios = [v.as_integer_ratio() for v in values.tolist()]
    denominator = max(d for _, d in ratios)
    s1 = 0
    s2 = 0
    for numerator, d in ratios:
        scaled = numerator * (denominator // d)
        s1 += scaled
        s2 += scaled * scaled
    n = len(ratios)
    mean = Fraction(s1, n * denominator)
    variance = Fraction(s2 * n - s1 * s1, n * (n - 1) * denominator * denominator)
    return ExactArm(n, mean, variance)


def relative_error(value: float, reference: Fraction) -> float:
    if reference == 0:
        return abs(value)
    return float(abs(Fraction(value) - reference) / abs(reference))
