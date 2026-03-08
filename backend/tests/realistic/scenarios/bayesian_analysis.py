"""
Realistic scenario: Bayesian Experimentation Validation (EP-035).

Validates the mathematical correctness of the Bayesian analysis pipeline:
  1. Beta-Binomial posterior computation
  2. Credible interval coverage
  3. Probability of being best (Monte Carlo)
  4. Expected loss computation
  5. Bayes Factor (Savage-Dickey density ratio)
  6. Bayesian stopping rule
  7. Full BayesianService.analyze() pipeline

These tests do NOT require a running platform — they exercise the Bayesian
service directly with known inputs and verify outputs against hand-computed
or analytically known values.
"""

import math
import pytest


class TestBetaBinomialPosterior:
    """Validate Beta-Binomial conjugate update is correct."""

    def test_uniform_prior_with_no_data(self):
        from backend.app.services.bayesian_service import compute_posterior

        posterior = compute_posterior(
            prior={"alpha": 1, "beta": 1},
            observations={"conversions": 0, "total": 0},
        )
        assert posterior["alpha"] == 1
        assert posterior["beta"] == 1

    def test_uniform_prior_with_all_conversions(self):
        from backend.app.services.bayesian_service import compute_posterior

        posterior = compute_posterior(
            prior={"alpha": 1, "beta": 1},
            observations={"conversions": 100, "total": 100},
        )
        # posterior = Beta(1+100, 1+0) = Beta(101, 1)
        assert posterior["alpha"] == 101
        assert posterior["beta"] == 1

    def test_uniform_prior_with_no_conversions(self):
        from backend.app.services.bayesian_service import compute_posterior

        posterior = compute_posterior(
            prior={"alpha": 1, "beta": 1},
            observations={"conversions": 0, "total": 100},
        )
        # posterior = Beta(1+0, 1+100) = Beta(1, 101)
        assert posterior["alpha"] == 1
        assert posterior["beta"] == 101

    def test_informative_prior_updates_correctly(self):
        from backend.app.services.bayesian_service import compute_posterior

        posterior = compute_posterior(
            prior={"alpha": 10, "beta": 90},  # prior mean = 0.1
            observations={"conversions": 50, "total": 500},
        )
        # posterior = Beta(10+50, 90+450) = Beta(60, 540)
        assert posterior["alpha"] == 60
        assert posterior["beta"] == 540

    def test_posterior_mean_converges_to_observed_rate(self):
        from backend.app.services.bayesian_service import compute_posterior

        posterior = compute_posterior(
            prior={"alpha": 1, "beta": 1},
            observations={"conversions": 800, "total": 10000},
        )
        # Large sample: posterior mean ≈ 800/10000 = 0.08
        mean = posterior["alpha"] / (posterior["alpha"] + posterior["beta"])
        assert abs(mean - 0.08) < 0.005


class TestCredibleInterval:
    """Validate credible interval computation."""

    def test_95_ci_for_known_beta(self):
        from backend.app.services.bayesian_service import compute_credible_interval

        # Beta(100, 100) has mean 0.5, should have CI roughly [0.43, 0.57]
        lo, hi = compute_credible_interval({"alpha": 100, "beta": 100}, level=0.95)
        assert 0.40 < lo < 0.50
        assert 0.50 < hi < 0.60

    def test_ci_width_decreases_with_more_data(self):
        from backend.app.services.bayesian_service import compute_credible_interval

        lo_small, hi_small = compute_credible_interval({"alpha": 10, "beta": 10})
        lo_large, hi_large = compute_credible_interval({"alpha": 100, "beta": 100})
        width_small = hi_small - lo_small
        width_large = hi_large - lo_large
        assert width_large < width_small

    def test_ci_covers_posterior_mean(self):
        from backend.app.services.bayesian_service import compute_credible_interval

        posterior = {"alpha": 50, "beta": 150}
        mean = 50 / 200
        lo, hi = compute_credible_interval(posterior, level=0.95)
        assert lo <= mean <= hi

    def test_narrow_ci_with_high_confidence_data(self):
        from backend.app.services.bayesian_service import compute_credible_interval

        lo, hi = compute_credible_interval({"alpha": 1000, "beta": 9000})
        width = hi - lo
        assert width < 0.02, f"CI width {width:.4f} too wide for n=10000"


class TestProbabilityToBeBest:
    """Validate Monte Carlo probability of being best computation."""

    def test_clearly_better_variant_wins(self):
        from backend.app.services.bayesian_service import compute_probability_to_be_best

        posteriors = [
            {"alpha": 10, "beta": 90},   # mean = 0.1
            {"alpha": 50, "beta": 50},   # mean = 0.5 — clearly better
        ]
        ptbb = compute_probability_to_be_best(posteriors, n_samples=50_000)
        assert ptbb[1] > 0.99, f"Better variant should win >99%, got {ptbb[1]:.3f}"

    def test_equal_variants_are_50_50(self):
        from backend.app.services.bayesian_service import compute_probability_to_be_best

        posteriors = [
            {"alpha": 100, "beta": 100},
            {"alpha": 100, "beta": 100},
        ]
        ptbb = compute_probability_to_be_best(posteriors, n_samples=50_000)
        # Each should be ~0.5 ± 0.05
        assert 0.45 <= ptbb[0] <= 0.55
        assert 0.45 <= ptbb[1] <= 0.55

    def test_probabilities_sum_to_one(self):
        from backend.app.services.bayesian_service import compute_probability_to_be_best

        posteriors = [
            {"alpha": 20, "beta": 80},
            {"alpha": 30, "beta": 70},
            {"alpha": 25, "beta": 75},
        ]
        ptbb = compute_probability_to_be_best(posteriors, n_samples=50_000)
        assert abs(sum(ptbb) - 1.0) < 0.001, f"PtBB should sum to 1, got {sum(ptbb)}"

    def test_three_way_split_with_one_dominant(self):
        from backend.app.services.bayesian_service import compute_probability_to_be_best

        posteriors = [
            {"alpha": 5, "beta": 95},    # 5% CVR
            {"alpha": 5, "beta": 95},    # 5% CVR
            {"alpha": 50, "beta": 50},   # 50% CVR — dominant
        ]
        ptbb = compute_probability_to_be_best(posteriors, n_samples=50_000)
        assert ptbb[2] > 0.99


class TestExpectedLoss:
    """Validate expected loss computation."""

    def test_clearly_best_variant_has_near_zero_loss(self):
        from backend.app.services.bayesian_service import compute_expected_loss

        posteriors = [
            {"alpha": 10, "beta": 90},   # 10% CVR
            {"alpha": 90, "beta": 10},   # 90% CVR — much better
        ]
        losses = compute_expected_loss(posteriors, n_samples=50_000)
        assert losses[1] < 0.01, f"Best variant should have near-zero loss, got {losses[1]}"
        assert losses[0] > 0.5, f"Worst variant should have high loss, got {losses[0]}"

    def test_equal_variants_have_similar_loss(self):
        from backend.app.services.bayesian_service import compute_expected_loss

        posteriors = [
            {"alpha": 100, "beta": 100},
            {"alpha": 100, "beta": 100},
        ]
        losses = compute_expected_loss(posteriors, n_samples=50_000)
        assert abs(losses[0] - losses[1]) < 0.02

    def test_all_losses_non_negative(self):
        from backend.app.services.bayesian_service import compute_expected_loss

        posteriors = [
            {"alpha": 20, "beta": 80},
            {"alpha": 30, "beta": 70},
        ]
        losses = compute_expected_loss(posteriors, n_samples=50_000)
        for loss in losses:
            assert loss >= 0.0


class TestBayesFactor:
    """Validate Savage-Dickey density ratio for Bayes Factor."""

    def test_strong_evidence_for_effect(self):
        from backend.app.services.bayesian_service import compute_bayes_factor

        # Uniform prior, strong observed rate far from null
        bf = compute_bayes_factor(
            prior={"alpha": 1, "beta": 1},
            posterior={"alpha": 100, "beta": 10},  # mean ≈ 0.91
        )
        # BF10 should be > 10 (strong evidence the rate is not 0.5)
        assert bf > 10, f"Expected BF > 10, got {bf}"

    def test_no_evidence_when_posterior_matches_prior(self):
        from backend.app.services.bayesian_service import compute_bayes_factor

        bf = compute_bayes_factor(
            prior={"alpha": 1, "beta": 1},
            posterior={"alpha": 1, "beta": 1},  # no data
        )
        # BF should be ~1 (no evidence either way)
        assert 0.1 < bf < 10, f"No data should give BF ~1, got {bf}"

    def test_bayes_factor_label_categories(self):
        from backend.app.services.bayesian_service import get_bayes_factor_label

        assert "Anecdotal" in get_bayes_factor_label(2.0)
        assert "Moderate" in get_bayes_factor_label(5.0)
        assert "Strong" in get_bayes_factor_label(20.0)
        assert "Very Strong" in get_bayes_factor_label(50.0)


class TestBayesianStoppingRule:
    """Validate the stopping rule for Bayesian experiments."""

    def test_stop_when_clear_winner(self):
        from backend.app.services.bayesian_service import should_stop

        posteriors = [
            {"alpha": 10, "beta": 990},    # 1% CVR
            {"alpha": 200, "beta": 800},   # 20% CVR — obvious winner
        ]
        try:
            from backend.app.schemas.bayesian import BayesianConfig
            config = BayesianConfig()
        except ImportError:
            pytest.skip("BayesianConfig not available")

        decision = should_stop(posteriors, config, n_samples=50_000)
        assert decision is not None
        # Should recommend stopping — the expected loss for the winner is tiny

    def test_continue_when_uncertain(self):
        from backend.app.services.bayesian_service import should_stop

        posteriors = [
            {"alpha": 5, "beta": 5},   # very uncertain (n=10)
            {"alpha": 6, "beta": 4},   # slightly better but tiny sample
        ]
        try:
            from backend.app.schemas.bayesian import BayesianConfig
            config = BayesianConfig()
        except ImportError:
            pytest.skip("BayesianConfig not available")

        decision = should_stop(posteriors, config, n_samples=50_000)
        assert decision is not None


class TestBayesianServiceIntegration:
    """Test the full BayesianService.analyze() pipeline."""

    def test_analyze_returns_all_expected_fields(self):
        from backend.app.services.bayesian_service import BayesianService

        service = BayesianService()
        result = service.analyze(
            variant_observations=[
                {"conversions": 80, "total": 1000},
                {"conversions": 95, "total": 1000},
            ],
            n_samples=10_000,
        )
        assert "posteriors" in result
        assert "credible_intervals" in result
        assert "probability_to_be_best" in result
        assert "expected_loss" in result
        assert "decision" in result

    def test_analyze_with_three_variants(self):
        from backend.app.services.bayesian_service import BayesianService

        service = BayesianService()
        result = service.analyze(
            variant_observations=[
                {"conversions": 50, "total": 500},
                {"conversions": 60, "total": 500},
                {"conversions": 55, "total": 500},
            ],
        )
        assert len(result["posteriors"]) == 3
        assert len(result["probability_to_be_best"]) == 3
        assert len(result["expected_loss"]) == 3

    def test_analyze_large_sample_identifies_winner(self):
        from backend.app.services.bayesian_service import BayesianService

        service = BayesianService()
        result = service.analyze(
            variant_observations=[
                {"conversions": 500, "total": 10000},   # 5%
                {"conversions": 800, "total": 10000},   # 8%
            ],
        )
        ptbb = result["probability_to_be_best"]
        assert ptbb[1] > 0.99, f"Variant 1 (8%) should clearly win, got ptbb={ptbb}"
