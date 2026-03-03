"""
Bayesian inference service for A/B experimentation (EP-035 Batch 1).

Provides pure-function implementations of:
- Beta-Binomial conjugate posterior updates
- Highest Density Interval (HDI) credible intervals via scipy
- Probability to Be Best (PtBB) via Monte Carlo sampling
- Expected Loss (Regret) via Monte Carlo sampling
- Bayes Factor via Savage-Dickey density ratio
- Bayesian stopping decision rules

All methods are stateless (no DB access) and thread-safe.
"""
import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy import stats as scipy_stats

from backend.app.schemas.bayesian import BayesianConfig, BayesianDecision

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public pure-function API
# ---------------------------------------------------------------------------


def compute_posterior(
    prior: Dict[str, float],
    observations: Dict[str, int],
) -> Dict[str, float]:
    """Compute Beta-Binomial conjugate posterior.

    Args:
        prior: Dict with keys 'alpha' and 'beta' (prior hyperparameters).
        observations: Dict with keys 'conversions' and 'total'.
            - conversions: Number of successes (>= 0).
            - total: Total number of trials (>= 0).

    Returns:
        Dict with keys 'alpha' and 'beta' representing posterior parameters.

    Raises:
        ValueError: If observations are invalid (negative conversions,
                    conversions > total, or negative total).
    """
    alpha_prior = float(prior["alpha"])
    beta_prior = float(prior["beta"])

    conversions = int(observations["conversions"])
    total = int(observations["total"])

    # Validate inputs
    if conversions < 0:
        raise ValueError(
            f"conversions must be >= 0, got {conversions}"
        )
    if total < 0:
        raise ValueError(
            f"total must be >= 0, got {total}"
        )
    if conversions > total:
        raise ValueError(
            f"conversions ({conversions}) must be <= total ({total})"
        )

    # Handle zero observations: return prior unchanged
    if total == 0:
        return {"alpha": alpha_prior, "beta": beta_prior}

    non_conversions = total - conversions

    # Conjugate Beta-Binomial update:
    #   alpha_posterior = alpha_prior + conversions
    #   beta_posterior  = beta_prior  + non_conversions
    alpha_posterior = alpha_prior + conversions
    beta_posterior = beta_prior + non_conversions

    return {"alpha": alpha_posterior, "beta": beta_posterior}


def compute_credible_interval(
    posterior: Dict[str, float],
    level: float = 0.95,
) -> Tuple[float, float]:
    """Compute a highest density interval (equal-tails) for a posterior.

    Supports Beta (keys: alpha, beta), Normal (keys: mu, sigma), and
    Gamma (keys: alpha, beta, family='gamma') posteriors.

    Args:
        posterior: Dict describing the posterior distribution.
            Must contain 'family' key ('beta', 'normal', or 'gamma')
            OR alpha/beta keys (Beta is assumed by default).
        level: Credible level in (0, 1), e.g. 0.95 for 95% CI.

    Returns:
        (lower, upper) credible interval bounds.

    Raises:
        ValueError: If level is not in (0, 1).
    """
    if not (0.0 < level < 1.0):
        raise ValueError(
            f"level must be in (0, 1), got {level}"
        )

    family = posterior.get("family", "beta")

    if family == "normal":
        mu = float(posterior["mu"])
        sigma = float(posterior["sigma"])
        dist = scipy_stats.norm(loc=mu, scale=sigma)
        lower, upper = dist.interval(level)
        return float(lower), float(upper)

    elif family == "gamma":
        # scipy's Gamma uses shape (a) and scale (1/rate)
        # Our 'beta' parameter is the rate, so scale = 1/beta
        alpha = float(posterior["alpha"])
        beta_rate = float(posterior["beta"])
        scale = 1.0 / beta_rate
        dist = scipy_stats.gamma(a=alpha, scale=scale)
        lower, upper = dist.interval(level)
        return float(lower), float(upper)

    else:
        # Default: Beta distribution
        alpha = float(posterior["alpha"])
        beta = float(posterior["beta"])
        dist = scipy_stats.beta(a=alpha, b=beta)
        lower, upper = dist.interval(level)
        return float(lower), float(upper)


def compute_probability_to_be_best(
    posteriors: List[Dict[str, float]],
    n_samples: int = 100_000,
) -> List[float]:
    """Compute Probability to Be Best (PtBB) via Monte Carlo sampling.

    For each variant, draws n_samples from its Beta posterior and computes
    the fraction of samples in which that variant has the highest value.

    Args:
        posteriors: List of dicts, each with 'alpha' and 'beta' keys.
            Must have at least 2 elements.
        n_samples: Number of Monte Carlo samples (higher → more precision).

    Returns:
        List of probabilities (floats in [0, 1]) summing to 1.0.

    Raises:
        ValueError: If fewer than 2 posteriors are provided.
    """
    if len(posteriors) < 2:
        raise ValueError(
            f"At least 2 posteriors are required for PtBB, got {len(posteriors)}"
        )

    # Draw samples from each posterior (shape: [n_variants, n_samples])
    samples = np.array([
        np.random.beta(p["alpha"], p["beta"], n_samples)
        for p in posteriors
    ])

    # For each sample, find which variant is the winner
    winner = np.argmax(samples, axis=0)  # shape: [n_samples]

    return [float(np.mean(winner == i)) for i in range(len(posteriors))]


def compute_expected_loss(
    posteriors: List[Dict[str, float]],
    n_samples: int = 100_000,
) -> List[float]:
    """Compute Expected Loss (regret) for each variant via Monte Carlo.

    For variant i, the expected loss is E[max_j(theta_j) - theta_i],
    i.e., how much we expect to "lose" by choosing variant i instead of
    the best variant.

    Args:
        posteriors: List of dicts, each with 'alpha' and 'beta' keys.
            Must have at least 2 elements.
        n_samples: Number of Monte Carlo samples.

    Returns:
        List of expected loss values (floats >= 0), one per variant.

    Raises:
        ValueError: If fewer than 2 posteriors are provided.
    """
    if len(posteriors) < 2:
        raise ValueError(
            f"At least 2 posteriors are required for expected loss, got {len(posteriors)}"
        )

    # Draw samples from each posterior (shape: [n_variants, n_samples])
    samples = np.array([
        np.random.beta(p["alpha"], p["beta"], n_samples)
        for p in posteriors
    ])

    # The best possible outcome for each sample
    max_samples = np.max(samples, axis=0)  # shape: [n_samples]

    # Expected loss for variant i = E[max(theta) - theta_i]
    return [float(np.mean(max_samples - samples[i])) for i in range(len(posteriors))]


def compute_bayes_factor(
    prior: Dict[str, float],
    posterior: Dict[str, float],
    null_value: Optional[float] = None,
) -> float:
    """Compute the Bayes Factor using the Savage-Dickey density ratio.

    The Savage-Dickey density ratio for a point null H0: theta = theta_0 is:

        BF01 = p(theta=theta_0 | data) / p(theta=theta_0 | prior)

    BF01 > 1 means the data favor H0 (null hypothesis, no effect).

    We return BF10 = 1 / BF01, so:
        BF10 > 1 means the data favor H1 (alternative, there IS an effect).
        BF10 > 10 indicates strong evidence for a real difference.

    By convention, null_value defaults to the prior mean when not specified.
    This represents a hypothesis that the parameter equals its prior central value.

    Args:
        prior: Dict with 'alpha' and 'beta' (prior Beta distribution).
        posterior: Dict with 'alpha' and 'beta' (posterior Beta distribution).
        null_value: The null hypothesis theta value (default: prior mean).

    Returns:
        Bayes Factor BF10 (float > 0). BF10 > 10 = strong evidence for effect.
    """
    alpha_prior = float(prior["alpha"])
    beta_prior = float(prior["beta"])
    alpha_post = float(posterior["alpha"])
    beta_post = float(posterior["beta"])

    # Default null value is the prior mean
    if null_value is None:
        null_value = alpha_prior / (alpha_prior + beta_prior)

    # Clamp null_value to avoid numerical issues at the boundaries
    null_value = max(1e-10, min(1.0 - 1e-10, null_value))

    # Savage-Dickey density ratio:
    # BF01 = posterior_density / prior_density at null_value
    # BF10 = prior_density / posterior_density at null_value
    prior_density = scipy_stats.beta.pdf(null_value, alpha_prior, beta_prior)
    posterior_density = scipy_stats.beta.pdf(null_value, alpha_post, beta_post)

    # BF10: evidence for alternative hypothesis (effect exists)
    # When the data pull the posterior away from null, posterior_density at null
    # becomes low → prior_density / posterior_density becomes large → BF10 >> 1
    if posterior_density == 0.0:
        return float("inf")

    bf10 = prior_density / posterior_density
    return float(bf10)


def get_bayes_factor_label(bf: float) -> str:
    """Return a human-readable interpretation label for a Bayes Factor.

    Uses the Jeffreys / Kass-Raftery scale:
        1  –  3  : Anecdotal
        3  – 10  : Moderate
        10 – 30  : Strong
        >  30    : Very Strong

    Args:
        bf: Bayes Factor value (BF10, should be >= 0).

    Returns:
        String label from the scale above.
    """
    if bf < 3.0:
        return "Anecdotal"
    elif bf < 10.0:
        return "Moderate"
    elif bf < 30.0:
        return "Strong"
    else:
        return "Very Strong"


def should_stop(
    posteriors: List[Dict[str, float]],
    config: BayesianConfig,
    n_samples: int = 100_000,
) -> BayesianDecision:
    """Apply Bayesian stopping rules to determine whether to stop the experiment.

    Stopping rules (evaluated in order):
    1. STOP_WINNER: min(expected_loss) < config.loss_threshold, meaning one
       variant is clearly better than all others.
    2. STOP_EQUIVALENT (ROPE): If config.rope is set and the posterior
       probability that the difference between the best and worst variant
       falls within ROPE is > 0.95, stop as equivalent.
    3. CONTINUE: Otherwise, keep running.

    Args:
        posteriors: List of posterior dicts (alpha, beta per variant).
        config: BayesianConfig with thresholds.
        n_samples: Monte Carlo samples for loss calculation.

    Returns:
        BayesianDecision enum value.
    """
    losses = compute_expected_loss(posteriors, n_samples=n_samples)
    min_loss = min(losses)

    # Rule 1: STOP_WINNER when expected loss of the best arm is below threshold
    if min_loss < config.loss_threshold:
        return BayesianDecision.STOP_WINNER

    # Rule 2: STOP_EQUIVALENT via ROPE
    if config.rope is not None:
        rope_lower, rope_upper = config.rope
        # Sample from all posteriors and check if differences fall within ROPE
        samples = np.array([
            np.random.beta(p["alpha"], p["beta"], n_samples)
            for p in posteriors
        ])
        # Compare each non-best variant to the best
        best_idx = losses.index(min_loss)
        best_samples = samples[best_idx]
        all_in_rope = True
        for i, _ in enumerate(posteriors):
            if i == best_idx:
                continue
            diff = best_samples - samples[i]
            prob_in_rope = float(np.mean((diff >= rope_lower) & (diff <= rope_upper)))
            if prob_in_rope <= 0.95:
                all_in_rope = False
                break
        if all_in_rope:
            return BayesianDecision.STOP_EQUIVALENT

    return BayesianDecision.CONTINUE


# ---------------------------------------------------------------------------
# BayesianService class (wraps pure functions with optional config)
# ---------------------------------------------------------------------------


class BayesianService:
    """High-level service for Bayesian A/B test analysis.

    Wraps the pure-function API with a configurable BayesianConfig and
    provides convenience methods for end-to-end analysis.
    """

    def __init__(self, config: Optional[BayesianConfig] = None) -> None:
        """Initialise with an optional BayesianConfig (defaults used if None)."""
        self.config = config or BayesianConfig()

    def update_posterior(
        self,
        observations: Dict[str, int],
    ) -> Dict[str, float]:
        """Update the prior with new observations and return the posterior."""
        prior = {"alpha": self.config.alpha, "beta": self.config.beta}
        return compute_posterior(prior, observations)

    def analyze(
        self,
        variant_observations: List[Dict[str, int]],
        n_samples: int = 100_000,
    ) -> Dict:
        """Run full Bayesian analysis for all variants.

        Args:
            variant_observations: List of dicts with 'conversions' and 'total'
                per variant.
            n_samples: Monte Carlo samples.

        Returns:
            Dict with posteriors, PtBBs, losses, and decision.
        """
        prior = {"alpha": self.config.alpha, "beta": self.config.beta}

        # Update posteriors
        posteriors = [
            compute_posterior(prior, obs) for obs in variant_observations
        ]

        # Compute credible intervals
        credible_intervals = [
            compute_credible_interval(p, level=self.config.credible_level)
            for p in posteriors
        ]

        # PtBB and expected loss
        ptbb = compute_probability_to_be_best(posteriors, n_samples=n_samples)
        losses = compute_expected_loss(posteriors, n_samples=n_samples)

        # Stopping decision
        decision = should_stop(posteriors, self.config, n_samples=n_samples)

        return {
            "posteriors": posteriors,
            "credible_intervals": credible_intervals,
            "probability_to_be_best": ptbb,
            "expected_loss": losses,
            "decision": decision,
        }
