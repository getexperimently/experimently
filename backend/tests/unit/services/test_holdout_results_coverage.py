"""Coverage of the holdout results intervals at the minimum group size (#445).

Drives the production functions in ``backend/app/services/holdout_results.py``
(no copy of the formulas here) on the case the minimum was chosen for: 100
users in the holdout against 1,000, a 1% rate, no true difference.  Seeded
and deterministic; nothing is timed.

* The 95% interval covers the true difference (0) in at least 95% of 20,000
  datasets.  Agresti-Caffo gives about 0.997; a Wald interval about 0.64.
* The confidence sequence covers it at every one of 20 looks (100 more
  holdout users and 1,000 more others per look) in at least 95% of 20,000
  runs.  On the Agresti-Caffo variance that is about 0.97; on the plug-in
  variance ``/sequential`` uses, about 0.75.
"""

import numpy as np
import pytest

from backend.app.services.holdout_results import (
    always_valid_interval,
    difference_interval,
)

pytestmark = pytest.mark.unit

SEED = 445
N_H, N_R, RATE = 100, 1000, 0.01
REPS = 20_000
LOOKS = 20


def test_the_95_percent_interval_covers_at_the_minimum():
    rng = np.random.default_rng(SEED)
    x_h = rng.binomial(N_H, RATE, size=REPS)
    x_r = rng.binomial(N_R, RATE, size=REPS)
    covered = 0
    for h, r in zip(x_h.tolist(), x_r.tolist()):
        lower, upper = difference_interval(N_H, h, N_R, r)
        covered += lower <= 0.0 <= upper
    assert covered / REPS >= 0.95, covered / REPS


def test_the_confidence_sequence_covers_at_every_look():
    rng = np.random.default_rng(SEED + 1)
    x_h = rng.binomial(N_H, RATE, size=(REPS, LOOKS)).cumsum(axis=1).tolist()
    x_r = rng.binomial(N_R, RATE, size=(REPS, LOOKS)).cumsum(axis=1).tolist()
    covered = 0
    for run_h, run_r in zip(x_h, x_r):
        for k in range(LOOKS):
            lower, upper = always_valid_interval(
                N_H * (k + 1), run_h[k], N_R * (k + 1), run_r[k]
            )
            if not lower <= 0.0 <= upper:
                break
        else:
            covered += 1
    assert covered / REPS >= 0.95, covered / REPS
