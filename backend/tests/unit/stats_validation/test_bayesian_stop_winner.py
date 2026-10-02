"""Statistical gates for the Bayesian ``STOP_WINNER`` rule (#242).

Before #242, ``STOP_WINNER`` meant "the best arm's expected loss is below
``loss_threshold``" (0.001 by default). At a 1% base rate two identical arms
cross that with a few thousand users each: it fired on every one of 2,000 A/A
simulations at 1% and 5,000 users per arm. The rule now also needs the
leading arm's probability to be best to reach ``PROB_BEST_THRESHOLD``.

The gates come in a pair, because a rule that never stops passes every A/A
gate:

* 242a, the A/A gate: 2,000 simulations of two identical arms in each of six
  cells (base rate 1%, 10%, 50% x 5,000 and 20,000 users per arm), one look
  each. At most ``MAX_FALSE_WINNERS`` may come back ``STOP_WINNER``.
* 242b, the power gate: 2,000 simulations of 1% against 1.25% at 40,000 users
  per arm. At least ``MIN_POWER_WINNERS`` must come back ``STOP_WINNER`` with
  the treatment leading.

Both run through ``BayesianService.analyze``, the function behind the results
API, with a fixed seed per simulation, so they are deterministic. They use
20,000 Monte Carlo samples per analysis, not the API's 100,000, to keep the
directory's wall time down; under an A/A test the leading arm's probability to
be best is close to uniform on [0.5, 1], so Monte Carlo noise on it moves
simulations across the threshold in both directions and leaves the count
where it was. The threshold-selection run used the API's 100,000 and seeds
disjoint from these (242_9xx); its counts are in the pull request for #242.

The bounds:

* ``MAX_FALSE_WINNERS = binom.ppf(0.999, 2000, 0.05) = 131``: a rule whose
  false-winner rate is 5% clears it under any seed with probability 0.999.
* ``MIN_POWER_WINNERS = binom.ppf(0.001, 2000, 0.9235) = 1,809``: 0.9235 is the
  power the selection run measured at the chosen threshold (1,847 of 2,000).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Tuple

import numpy as np
import pytest
from scipy.stats import binom

from backend.app.schemas.bayesian import BayesianConfig, BayesianDecision
from backend.app.services import bayesian_service
from backend.app.services.bayesian_service import BayesianService, should_stop

pytestmark = pytest.mark.unit

SIMS = 2_000
ALPHA = 0.05
MC_SAMPLES = 20_000

#: binom.ppf(.999, 2000, .05), checked in test_the_bounds_are_the_binomial_quantiles.
MAX_FALSE_WINNERS = 131

#: Power measured by the selection run at the chosen threshold.
SELECTION_POWER = 0.9235
#: binom.ppf(.001, 2000, SELECTION_POWER), checked below.
MIN_POWER_WINNERS = 1_809

#: (base rate, users per arm, seed). Seeds 242_1xx; the selection run used 242_9xx.
AA_CELLS = (
    (0.01, 5_000, 242_101),
    (0.01, 20_000, 242_102),
    (0.10, 5_000, 242_103),
    (0.10, 20_000, 242_104),
    (0.50, 5_000, 242_105),
    (0.50, 20_000, 242_106),
)

POWER_CONTROL, POWER_TREATMENT, POWER_N, POWER_SEED = 0.01, 0.0125, 40_000, 242_110


@dataclass(frozen=True)
class Sim:
    """One simulated experiment, as the results API analysed it."""

    posteriors: Tuple[dict, ...]
    decision: BayesianDecision
    ptbb: Tuple[float, ...]
    losses: Tuple[float, ...]


def _simulate(
    p_control: float, p_treatment: float, n: int, seed: int
) -> Tuple[Sim, ...]:
    rng = np.random.default_rng(seed)
    control = rng.binomial(n, p_control, SIMS)
    treatment = rng.binomial(n, p_treatment, SIMS)
    service = BayesianService()
    sims = []
    for i in range(SIMS):
        result = service.analyze(
            [
                {"conversions": int(control[i]), "total": n},
                {"conversions": int(treatment[i]), "total": n},
            ],
            n_samples=MC_SAMPLES,
            seed=seed * 10_000 + i,
        )
        sims.append(
            Sim(
                posteriors=tuple(result["posteriors"]),
                decision=result["decision"],
                ptbb=tuple(result["probability_to_be_best"]),
                losses=tuple(result["expected_loss"]),
            )
        )
    return tuple(sims)


@lru_cache(maxsize=None)
def aa_sims(p: float, n: int, seed: int) -> Tuple[Sim, ...]:
    return _simulate(p, p, n, seed)


@lru_cache(maxsize=None)
def power_sims() -> Tuple[Sim, ...]:
    return _simulate(POWER_CONTROL, POWER_TREATMENT, POWER_N, POWER_SEED)


def _winners(sims: Tuple[Sim, ...]) -> int:
    return sum(s.decision == BayesianDecision.STOP_WINNER for s in sims)


def _redecided_winners(sims: Tuple[Sim, ...]) -> int:
    """Re-decide the same simulations through ``should_stop``, at the current threshold.

    The probabilities and losses were computed once; passing them in means the
    rule is re-applied without drawing again.
    """
    config = BayesianConfig()
    return sum(
        should_stop(
            list(s.posteriors), config, losses=list(s.losses), ptbb=list(s.ptbb)
        )
        == BayesianDecision.STOP_WINNER
        for s in sims
    )


def _cell_id(cell) -> str:
    p, n, _ = cell
    return f"{p:.0%}-{n // 1000}k"


# ---------------------------------------------------------------------------
# The bounds themselves
# ---------------------------------------------------------------------------


def test_the_bounds_are_the_binomial_quantiles():
    assert binom.ppf(0.999, SIMS, ALPHA) == MAX_FALSE_WINNERS
    assert binom.ppf(0.001, SIMS, SELECTION_POWER) == MIN_POWER_WINNERS
    assert bayesian_service.PROB_BEST_THRESHOLD == 0.975


# ---------------------------------------------------------------------------
# 242a: A/A false winners at a single look
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize("cell", AA_CELLS, ids=_cell_id)
def test_aa_false_winners_within_bound(cell):
    """242a: two identical arms are called a winner at most 131 times in 2,000."""
    winners = _winners(aa_sims(*cell))
    assert winners <= MAX_FALSE_WINNERS, winners


@pytest.mark.parametrize("threshold", [0.0, 0.95], ids=["loss-only", "0.95"])
def test_aa_gate_rejects_the_weaker_rules(threshold, monkeypatch):
    """242a planted: the pre-#242 rule (loss only) and a 0.95 threshold both fail.

    The loss-only rule is ``PROB_BEST_THRESHOLD = 0``: the leader's probability
    always reaches it, so only the loss condition decides, as before #242. It
    fails in the 1% cells; 0.95 lets through about 10% and fails in every cell.
    """
    # Every simulation is analysed (and cached) at the real threshold first;
    # only the re-decision below sees the planted one.
    cells = {_cell_id(cell): aa_sims(*cell) for cell in AA_CELLS}
    monkeypatch.setattr(bayesian_service, "PROB_BEST_THRESHOLD", threshold)
    over = {name: _redecided_winners(sims) for name, sims in cells.items()}
    failing = {k for k, v in over.items() if v > MAX_FALSE_WINNERS}
    if threshold == 0.0:
        assert {"1%-5k", "1%-20k"} <= failing, over
    else:
        assert failing == {_cell_id(c) for c in AA_CELLS}, over


# ---------------------------------------------------------------------------
# 242b: power
# ---------------------------------------------------------------------------


def test_power_at_one_quarter_relative_lift():
    """242b: 1% vs 1.25% at 40,000 per arm calls the treatment the winner >= 1,809 times."""
    sims = power_sims()
    treatment_wins = sum(
        s.decision == BayesianDecision.STOP_WINNER and s.ptbb[1] > s.ptbb[0]
        for s in sims
    )
    assert treatment_wins >= MIN_POWER_WINNERS, treatment_wins
    # A winner on the control arm here would be a false winner too.
    assert _winners(sims) - treatment_wins <= MAX_FALSE_WINNERS


# ---------------------------------------------------------------------------
# The cases from the issue
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize(
    ("conversions", "total"), [(50, 5_000), (200, 20_000)], ids=["5k", "20k"]
)
def test_identical_arms_at_one_percent_continue(conversions, total):
    """#242: identical 1% arms answered STOP_WINNER at 5,000 and 20,000 per arm.

    Both expected losses are below the default 0.001, which is what made the
    pre-#242 rule fire; the probability to be best is about 0.5.
    """
    result = BayesianService().analyze(
        [
            {"conversions": conversions, "total": total},
            {"conversions": conversions, "total": total},
        ]
    )
    assert min(result["expected_loss"]) < BayesianConfig().loss_threshold
    assert result["decision"] == BayesianDecision.CONTINUE
