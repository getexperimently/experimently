"""
Unit tests for Bayesian schemas (EP-035 Batch 1).

Tests cover:
- BayesianConfig schema validation
- BayesianPosteriorResult schema
- BayesianDecision enum
- BayesianVariantResult schema
- BayesianResultsResponse schema
"""
import pytest
from pydantic import ValidationError

from backend.app.schemas.bayesian import (
    BayesianConfig,
    BayesianDecision,
    BayesianPosteriorResult,
    BayesianResultsResponse,
    BayesianVariantResult,
    PriorFamily,
)


# ---------------------------------------------------------------------------
# BayesianConfig tests
# ---------------------------------------------------------------------------


def test_bayesian_config_default_values():
    """BayesianConfig should have sensible defaults."""
    config = BayesianConfig()
    assert config.prior_family == PriorFamily.BETA
    assert config.alpha == 1.0
    assert config.beta == 1.0
    assert config.loss_threshold == 0.001
    assert config.credible_level == 0.95
    assert config.rope is None


def test_bayesian_config_prior_family_beta():
    """prior_family 'beta' should be valid."""
    config = BayesianConfig(prior_family="beta")
    assert config.prior_family == PriorFamily.BETA


def test_bayesian_config_prior_family_normal():
    """prior_family 'normal' should be valid."""
    config = BayesianConfig(prior_family="normal")
    assert config.prior_family == PriorFamily.NORMAL


def test_bayesian_config_prior_family_gamma():
    """prior_family 'gamma' should be valid."""
    config = BayesianConfig(prior_family="gamma")
    assert config.prior_family == PriorFamily.GAMMA


def test_bayesian_config_invalid_prior_family_raises():
    """Invalid prior_family should raise ValidationError."""
    with pytest.raises(ValidationError):
        BayesianConfig(prior_family="cauchy")


def test_bayesian_config_alpha_must_be_positive():
    """alpha <= 0 should raise ValidationError."""
    with pytest.raises(ValidationError):
        BayesianConfig(alpha=-1.0)
    with pytest.raises(ValidationError):
        BayesianConfig(alpha=0.0)


def test_bayesian_config_beta_must_be_positive():
    """beta <= 0 should raise ValidationError."""
    with pytest.raises(ValidationError):
        BayesianConfig(beta=-0.5)
    with pytest.raises(ValidationError):
        BayesianConfig(beta=0.0)


def test_bayesian_config_loss_threshold_must_be_positive():
    """loss_threshold <= 0 should raise ValidationError."""
    with pytest.raises(ValidationError):
        BayesianConfig(loss_threshold=0.0)
    with pytest.raises(ValidationError):
        BayesianConfig(loss_threshold=-0.001)


def test_bayesian_config_rope_valid():
    """Valid ROPE with two values where rope[0] < rope[1]."""
    config = BayesianConfig(rope=[-0.01, 0.01])
    assert config.rope == [-0.01, 0.01]


def test_bayesian_config_rope_invalid_length_raises():
    """ROPE with wrong number of values should raise ValidationError."""
    with pytest.raises(ValidationError):
        BayesianConfig(rope=[-0.01])
    with pytest.raises(ValidationError):
        BayesianConfig(rope=[-0.01, 0.0, 0.01])


def test_bayesian_config_rope_invalid_order_raises():
    """ROPE where rope[0] >= rope[1] should raise ValidationError."""
    with pytest.raises(ValidationError):
        BayesianConfig(rope=[0.01, -0.01])  # reversed
    with pytest.raises(ValidationError):
        BayesianConfig(rope=[0.0, 0.0])  # equal


# ---------------------------------------------------------------------------
# BayesianPosteriorResult tests
# ---------------------------------------------------------------------------


def test_bayesian_posterior_result_has_required_fields():
    """BayesianPosteriorResult should accept all required fields."""
    result = BayesianPosteriorResult(
        alpha=31.0,
        beta=971.0,
        mean=0.031,
        credible_interval_lower=0.021,
        credible_interval_upper=0.044,
    )
    assert result.alpha == 31.0
    assert result.beta == 971.0
    assert result.mean == pytest.approx(0.031)
    assert result.credible_interval_lower == pytest.approx(0.021)
    assert result.credible_interval_upper == pytest.approx(0.044)


# ---------------------------------------------------------------------------
# BayesianDecision enum tests
# ---------------------------------------------------------------------------


def test_bayesian_decision_enum_values():
    """BayesianDecision enum should have all required values."""
    assert BayesianDecision.CONTINUE == "CONTINUE"
    assert BayesianDecision.STOP_WINNER == "STOP_WINNER"
    assert BayesianDecision.STOP_EQUIVALENT == "STOP_EQUIVALENT"
    assert BayesianDecision.STOP_FUTILE == "STOP_FUTILE"


def test_bayesian_decision_enum_members():
    """BayesianDecision should have exactly the required members."""
    members = {d.value for d in BayesianDecision}
    assert "CONTINUE" in members
    assert "STOP_WINNER" in members
    assert "STOP_EQUIVALENT" in members
    assert "STOP_FUTILE" in members


# ---------------------------------------------------------------------------
# BayesianVariantResult tests
# ---------------------------------------------------------------------------


def test_bayesian_variant_result_required_fields():
    """BayesianVariantResult should accept all required fields."""
    posterior = BayesianPosteriorResult(
        alpha=31.0,
        beta=971.0,
        mean=0.031,
        credible_interval_lower=0.021,
        credible_interval_upper=0.044,
    )
    result = BayesianVariantResult(
        variant_key="control",
        posterior=posterior,
        probability_to_be_best=0.45,
        expected_loss=0.005,
    )
    assert result.variant_key == "control"
    assert result.probability_to_be_best == pytest.approx(0.45)
    assert result.expected_loss == pytest.approx(0.005)
    assert result.bayes_factor is None  # optional, defaults to None


def test_bayesian_variant_result_with_bayes_factor():
    """BayesianVariantResult should accept optional bayes_factor."""
    posterior = BayesianPosteriorResult(
        alpha=31.0,
        beta=971.0,
        mean=0.031,
        credible_interval_lower=0.021,
        credible_interval_upper=0.044,
    )
    result = BayesianVariantResult(
        variant_key="treatment",
        posterior=posterior,
        probability_to_be_best=0.55,
        expected_loss=0.002,
        bayes_factor=12.5,
    )
    assert result.bayes_factor == pytest.approx(12.5)


# ---------------------------------------------------------------------------
# BayesianResultsResponse tests
# ---------------------------------------------------------------------------


def test_bayesian_results_response_is_enabled_required():
    """BayesianResultsResponse should have is_enabled field."""
    response = BayesianResultsResponse(is_enabled=True)
    assert response.is_enabled is True
    assert response.variant_results == []
    assert response.decision is None


def test_bayesian_results_response_with_decision():
    """BayesianResultsResponse should accept a BayesianDecision."""
    response = BayesianResultsResponse(
        is_enabled=True,
        decision=BayesianDecision.STOP_WINNER,
    )
    assert response.decision == BayesianDecision.STOP_WINNER


def test_bayesian_results_response_with_variants():
    """BayesianResultsResponse should accept a list of BayesianVariantResult."""
    posterior = BayesianPosteriorResult(
        alpha=31.0,
        beta=971.0,
        mean=0.031,
        credible_interval_lower=0.021,
        credible_interval_upper=0.044,
    )
    variant = BayesianVariantResult(
        variant_key="treatment",
        posterior=posterior,
        probability_to_be_best=0.6,
        expected_loss=0.001,
    )
    response = BayesianResultsResponse(
        is_enabled=True,
        decision=BayesianDecision.STOP_WINNER,
        variant_results=[variant],
    )
    assert len(response.variant_results) == 1
    assert response.variant_results[0].variant_key == "treatment"


def test_prior_family_enum_has_all_values():
    """PriorFamily should have beta, normal, gamma."""
    assert PriorFamily.BETA == "beta"
    assert PriorFamily.NORMAL == "normal"
    assert PriorFamily.GAMMA == "gamma"
