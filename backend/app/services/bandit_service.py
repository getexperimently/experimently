"""
Multi-Armed Bandit Service implementing Thompson Sampling, UCB1, and Epsilon-Greedy
for dynamic traffic allocation to better-performing experiment variants.

Algorithms
----------
* ThompsonSampling  – Bayesian Beta-Bernoulli posterior; best for conversion metrics.
* UCB1              – Frequentist upper-confidence-bound; deterministic.
* EpsilonGreedy     – Simple explore-exploit; epsilon fraction goes to random arms.

All public ``compute_weights`` methods return a ``Dict[str, float]`` that maps
variant_id → allocation weight, where weights sum to 1.0.

Thompson sampling is the only stochastic algorithm.  Its draws come from
``numpy.random.default_rng(seed)``; the scheduler passes a seed derived from
``(experiment_id, tick day, n_samples)`` so a tick can be reproduced exactly.
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np

from backend.app.core.stats_engine import derive_seed, make_rng

#: Namespace for the fallback seed used when a caller passes ``seed=None``.
_FALLBACK_SEED_NAMESPACE = "bandit_service"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class VariantStats:
    """Accumulated statistics for a single variant arm."""

    variant_id: str
    successes: int = 0
    failures: int = 0
    pulls: int = 0
    total_reward: float = 0.0

    @property
    def mean_reward(self) -> float:
        """Average reward per pull (0.0 when no pulls recorded)."""
        return self.total_reward / self.pulls if self.pulls > 0 else 0.0

    @property
    def conversion_rate(self) -> float:
        """Empirical conversion rate = successes / pulls (0.0 when no pulls)."""
        return self.successes / self.pulls if self.pulls > 0 else 0.0


# ---------------------------------------------------------------------------
# Thompson Sampling
# ---------------------------------------------------------------------------


class ThompsonSampling:
    """
    Bayesian MAB using Beta distribution posteriors.

    Each variant is modelled as a Bernoulli arm.  The posterior after
    observing ``s`` successes and ``f`` failures starting from an
    uninformative Beta(1, 1) prior is Beta(1+s, 1+f).

    We estimate the *selection probability* for each arm by drawing
    ``n_samples`` samples from every posterior and counting which arm
    produces the largest draw on each trial.
    """

    PRIOR_ALPHA: float = 1.0  # uninformative prior
    PRIOR_BETA: float = 1.0
    N_SAMPLES: int = 10_000  # samples used to estimate selection probabilities

    @staticmethod
    def arm_fingerprint(
        alpha: Optional[Sequence[float]],
        beta: Optional[Sequence[float]],
    ) -> str:
        """Return a stable string identifying the arms' posterior parameters.

        ``%.17g`` round-trips a float exactly, so the same arms always give
        the same fingerprint and different arms (almost surely) do not.
        """
        if not alpha and not beta:
            return ""
        pairs = zip(alpha or [], beta or [])
        return ";".join(f"{float(a):.17g}:{float(b):.17g}" for a, b in pairs)

    @staticmethod
    def resolve_seed(
        seed: Optional[int],
        n_samples: int,
        alpha: Optional[Sequence[float]] = None,
        beta: Optional[Sequence[float]] = None,
    ) -> int:
        """Return ``seed``, or a fallback derived from the arms themselves.

        The scheduler passes a seed derived from ``(experiment_id, tick day,
        n_samples)``.  Without one the seed comes from ``(namespace, arm
        fingerprint, n_samples)``, so each set of arm statistics draws its own
        stream instead of every seedless caller on the platform sharing one
        fixed sequence (which would turn Monte Carlo error into a fixed bias);
        repeating a call on the same arms still reproduces it exactly.
        """
        if seed is not None:
            return int(seed)
        return derive_seed(
            _FALLBACK_SEED_NAMESPACE,
            ThompsonSampling.arm_fingerprint(alpha, beta),
            n_samples,
        )

    @staticmethod
    def sample(
        alpha: List[float],
        beta: List[float],
        n_samples: int = 10_000,
        seed: Optional[int] = None,
    ) -> List[float]:
        """
        Draw ``n_samples`` from each Beta posterior and estimate arm-selection
        probabilities.

        Parameters
        ----------
        alpha:
            Posterior alpha parameter for each variant (shape: n_variants).
        beta:
            Posterior beta parameter for each variant (shape: n_variants).
        n_samples:
            Number of Monte Carlo draws used to estimate probabilities.
        seed:
            RNG seed (see ``backend.app.core.stats_engine.derive_seed``);
            ``None`` derives one from ``alpha``/``beta`` (see
            :meth:`resolve_seed`).

        Returns
        -------
        List[float]
            Estimated selection probabilities, one per variant, summing to 1.0.
        """
        n_variants = len(alpha)

        if n_variants == 1:
            return [1.0]

        # Draw n_samples from each Beta posterior: shape (n_samples, n_variants)
        rng = make_rng(ThompsonSampling.resolve_seed(seed, n_samples, alpha, beta))
        draws = rng.beta(alpha, beta, size=(n_samples, n_variants))

        # For each sample pick the arm with the maximum draw
        winners = np.argmax(draws, axis=1)

        # Count wins per arm and normalise
        counts = np.bincount(winners, minlength=n_variants).astype(float)
        probabilities = (counts / n_samples).tolist()
        return probabilities

    @staticmethod
    def compute_weights(
        variant_stats: List[VariantStats],
        seed: Optional[int] = None,
    ) -> Dict[str, float]:
        """
        Compute allocation weights for all variants via Thompson Sampling.

        Parameters
        ----------
        variant_stats:
            Per-variant statistics list.
        seed:
            RNG seed for the ``N_SAMPLES`` Monte Carlo draws; ``None`` uses
            the deterministic module fallback.

        Returns
        -------
        Dict[str, float]
            {variant_id: weight} where weights sum to 1.0.
        """
        if len(variant_stats) == 1:
            return {variant_stats[0].variant_id: 1.0}

        alpha: List[float] = []
        beta_vals: List[float] = []

        for vs in variant_stats:
            # Posterior: Beta(prior_alpha + successes, prior_beta + failures)
            alpha.append(ThompsonSampling.PRIOR_ALPHA + vs.successes)
            beta_vals.append(ThompsonSampling.PRIOR_BETA + vs.failures)

        probs = ThompsonSampling.sample(
            alpha, beta_vals, ThompsonSampling.N_SAMPLES, seed=seed
        )
        return {vs.variant_id: p for vs, p in zip(variant_stats, probs)}


# ---------------------------------------------------------------------------
# UCB1
# ---------------------------------------------------------------------------


class UCB1:
    """
    Frequentist MAB using the UCB1 rule.

    Score for arm *i* after *n_i* pulls out of *N* total pulls::

        score_i = mean_reward_i + sqrt(2 * ln(N) / n_i)

    An arm that has never been pulled receives a score of +∞ so that it is
    tried at least once.
    """

    @staticmethod
    def compute_scores(
        counts: List[int],
        rewards: List[float],
        total_pulls: int,
    ) -> List[float]:
        """
        Compute raw UCB1 scores for each arm.

        Parameters
        ----------
        counts:
            Number of times each arm has been pulled.
        rewards:
            Cumulative reward for each arm.
        total_pulls:
            Total pulls across all arms (must equal ``sum(counts)``).

        Returns
        -------
        List[float]
            UCB1 score per arm.
        """
        scores: List[float] = []
        log_n = math.log(total_pulls) if total_pulls > 0 else 0.0

        for n_i, r_i in zip(counts, rewards):
            if n_i == 0:
                scores.append(math.inf)
            else:
                mean = r_i / n_i
                bonus = math.sqrt(2 * log_n / n_i)
                scores.append(mean + bonus)

        return scores

    @staticmethod
    def compute_weights(variant_stats: List[VariantStats]) -> Dict[str, float]:
        """
        Compute allocation weights by normalising UCB1 scores.

        Arms with score +∞ receive all the weight proportionally among
        themselves (to mimic the "try unplayed arms first" policy).

        Parameters
        ----------
        variant_stats:
            Per-variant statistics list.

        Returns
        -------
        Dict[str, float]
            {variant_id: weight} where weights sum to 1.0.
        """
        if len(variant_stats) == 1:
            return {variant_stats[0].variant_id: 1.0}

        counts = [vs.pulls for vs in variant_stats]
        rewards = [vs.total_reward for vs in variant_stats]
        total_pulls = sum(counts)

        # Edge case: nothing pulled yet — fall back to uniform
        if total_pulls == 0:
            n = len(variant_stats)
            return {vs.variant_id: 1.0 / n for vs in variant_stats}

        scores = UCB1.compute_scores(counts, rewards, total_pulls)

        # Separate infinite from finite scores
        inf_indices = [i for i, s in enumerate(scores) if math.isinf(s)]
        fin_scores = [s for s in scores if not math.isinf(s)]

        if inf_indices:
            # Distribute weight equally among unplayed arms
            inf_weight = 1.0 / len(inf_indices)
            weights = {}
            for i, vs in enumerate(variant_stats):
                if math.isinf(scores[i]):
                    weights[vs.variant_id] = inf_weight
                else:
                    weights[vs.variant_id] = 0.0
            return weights

        # All arms played: normalise finite scores
        total_score = sum(fin_scores)
        if total_score == 0.0:
            n = len(variant_stats)
            return {vs.variant_id: 1.0 / n for vs in variant_stats}

        return {
            vs.variant_id: scores[i] / total_score for i, vs in enumerate(variant_stats)
        }


# ---------------------------------------------------------------------------
# Epsilon-Greedy
# ---------------------------------------------------------------------------


class EpsilonGreedy:
    """
    Simple ε-greedy explore-exploit strategy.

    * Best arm (highest empirical mean):  weight = (1 - ε) + ε/n
    * All other arms:                     weight = ε / n

    Ties are broken by the first arm in the list.
    """

    DEFAULT_EPSILON: float = 0.1

    @staticmethod
    def compute_weights(
        variant_stats: List[VariantStats],
        epsilon: float = 0.1,
    ) -> Dict[str, float]:
        """
        Compute ε-greedy allocation weights.

        Parameters
        ----------
        variant_stats:
            Per-variant statistics list.
        epsilon:
            Exploration fraction in [0, 1].

        Returns
        -------
        Dict[str, float]
            {variant_id: weight} where weights sum to 1.0.
        """
        n = len(variant_stats)

        if n == 1:
            return {variant_stats[0].variant_id: 1.0}

        # Find the best arm by conversion_rate; ties go to the first arm
        best_idx = max(range(n), key=lambda i: variant_stats[i].conversion_rate)

        # Assign weights
        explore_weight = epsilon / n
        exploit_weight = (1 - epsilon) + epsilon / n

        weights = {}
        for i, vs in enumerate(variant_stats):
            weights[vs.variant_id] = exploit_weight if i == best_idx else explore_weight

        return weights


# ---------------------------------------------------------------------------
# BanditService — high-level dispatcher
# ---------------------------------------------------------------------------


class BanditService:
    """
    High-level dispatcher that routes to the correct MAB algorithm.

    Algorithms supported
    --------------------
    ``"thompson_sampling"``   ThompsonSampling (stochastic)
    ``"ucb1"``                UCB1 (deterministic)
    ``"epsilon_greedy"``      EpsilonGreedy (deterministic)
    ``"fixed"``               Equal weights — standard A/B traffic split

    Usage
    -----
    >>> variant_data = {
    ...     "ctrl": {"successes": 40, "failures": 60, "pulls": 100, "total_reward": 40.0},
    ...     "trtm": {"successes": 70, "failures": 30, "pulls": 100, "total_reward": 70.0},
    ... }
    >>> weights = BanditService.compute_weights("ucb1", variant_data)
    """

    ALGORITHMS = {
        "thompson_sampling": ThompsonSampling,
        "ucb1": UCB1,
        "epsilon_greedy": EpsilonGreedy,
    }

    @classmethod
    def _build_variant_stats(
        cls,
        variant_data: Dict[str, Dict],
    ) -> List[VariantStats]:
        """Convert the raw variant_data dict to a list of VariantStats."""
        stats: List[VariantStats] = []
        for variant_id, data in variant_data.items():
            stats.append(
                VariantStats(
                    variant_id=variant_id,
                    successes=int(data.get("successes", 0)),
                    failures=int(data.get("failures", 0)),
                    pulls=int(data.get("pulls", 0)),
                    total_reward=float(data.get("total_reward", 0.0)),
                )
            )
        return stats

    @classmethod
    def is_stochastic(cls, algorithm: str) -> bool:
        """True when ``algorithm`` draws Monte Carlo samples (needs a seed)."""
        return algorithm == "thompson_sampling"

    @classmethod
    def compute_weights(
        cls,
        algorithm: str,
        variant_data: Dict[str, Dict],
        epsilon: float = 0.1,
        seed: Optional[int] = None,
    ) -> Dict[str, float]:
        """
        Compute allocation weights for all variants.

        Parameters
        ----------
        algorithm:
            One of ``'thompson_sampling'``, ``'ucb1'``, ``'epsilon_greedy'``,
            ``'fixed'``.
        variant_data:
            ``{variant_id: {"successes": int, "failures": int,
                             "pulls": int, "total_reward": float}}``
        epsilon:
            Exploration fraction for epsilon-greedy (ignored by other algorithms).
        seed:
            RNG seed for Thompson sampling (ignored by deterministic algorithms).

        Returns
        -------
        Dict[str, float]
            ``{variant_id: weight}`` where ``sum(weights.values()) ≈ 1.0``.
        """
        variant_stats = cls._build_variant_stats(variant_data)
        n = len(variant_stats)

        if n == 0:
            return {}

        # Fixed / standard A/B: equal weights, no bandit logic
        if algorithm == "fixed" or algorithm not in cls.ALGORITHMS:
            equal_weight = 1.0 / n
            return {vs.variant_id: equal_weight for vs in variant_stats}

        algo_cls = cls.ALGORITHMS[algorithm]

        if algorithm == "epsilon_greedy":
            return algo_cls.compute_weights(variant_stats, epsilon=epsilon)

        if algorithm == "thompson_sampling":
            return algo_cls.compute_weights(variant_stats, seed=seed)

        return algo_cls.compute_weights(variant_stats)
