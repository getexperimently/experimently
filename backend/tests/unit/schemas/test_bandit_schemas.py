"""
Test cases for Bandit schemas.

Validates:
- OptimizationType enum values
- BanditVariantWeight field validation
- BanditStatusResponse serialization
- BanditUpdateRequest weight validation
"""

import pytest
from pydantic import ValidationError

from backend.app.schemas.bandit import (
    OptimizationType,
    BanditVariantWeight,
    BanditStatusResponse,
    BanditUpdateRequest,
)


# ===========================================================================
# TestOptimizationType
# ===========================================================================

class TestOptimizationType:
    """Tests for the OptimizationType enum."""

    def test_fixed_value(self):
        """OptimizationType.FIXED has value 'fixed'."""
        assert OptimizationType.FIXED == "fixed"

    def test_thompson_sampling_value(self):
        """OptimizationType.THOMPSON_SAMPLING has value 'thompson_sampling'."""
        assert OptimizationType.THOMPSON_SAMPLING == "thompson_sampling"

    def test_ucb1_value(self):
        """OptimizationType.UCB1 has value 'ucb1'."""
        assert OptimizationType.UCB1 == "ucb1"

    def test_epsilon_greedy_value(self):
        """OptimizationType.EPSILON_GREEDY has value 'epsilon_greedy'."""
        assert OptimizationType.EPSILON_GREEDY == "epsilon_greedy"

    def test_invalid_value_raises(self):
        """Unknown algorithm name raises ValueError."""
        with pytest.raises(ValueError):
            OptimizationType("invalid_algorithm")


# ===========================================================================
# TestBanditVariantWeight
# ===========================================================================

class TestBanditVariantWeight:
    """Tests for BanditVariantWeight schema."""

    def _valid_data(self, **overrides):
        data = {
            "variant_id": "v-001",
            "variant_name": "Treatment A",
            "current_weight": 0.6,
            "successes": 60,
            "pulls": 100,
            "conversion_rate": 0.6,
        }
        data.update(overrides)
        return data

    def test_valid_variant_weight(self):
        """Valid data creates BanditVariantWeight without errors."""
        bvw = BanditVariantWeight(**self._valid_data())
        assert bvw.variant_id == "v-001"
        assert bvw.variant_name == "Treatment A"
        assert bvw.current_weight == 0.6
        assert bvw.successes == 60
        assert bvw.pulls == 100
        assert bvw.conversion_rate == 0.6

    def test_zero_weight_is_valid(self):
        """A weight of 0.0 is accepted."""
        bvw = BanditVariantWeight(**self._valid_data(current_weight=0.0))
        assert bvw.current_weight == 0.0

    def test_full_weight_is_valid(self):
        """A weight of 1.0 is accepted."""
        bvw = BanditVariantWeight(**self._valid_data(current_weight=1.0))
        assert bvw.current_weight == 1.0


# ===========================================================================
# TestBanditStatusResponse
# ===========================================================================

class TestBanditStatusResponse:
    """Tests for BanditStatusResponse schema."""

    def _variant_weight(self, vid: str, weight: float, successes: int = 50,
                        pulls: int = 100):
        return BanditVariantWeight(
            variant_id=vid,
            variant_name=f"Variant {vid}",
            current_weight=weight,
            successes=successes,
            pulls=pulls,
            conversion_rate=successes / pulls if pulls else 0.0,
        )

    def test_valid_status_response(self):
        """Valid BanditStatusResponse serialises without error."""
        response = BanditStatusResponse(
            experiment_id="exp-123",
            algorithm=OptimizationType.THOMPSON_SAMPLING,
            current_weights=[
                self._variant_weight("v0", 0.4),
                self._variant_weight("v1", 0.6),
            ],
            total_pulls=200,
            regret_reduction_pct=12.5,
            recommendation="CONVERGING",
            last_updated="2026-03-01T10:00:00Z",
        )
        assert response.experiment_id == "exp-123"
        assert response.algorithm == OptimizationType.THOMPSON_SAMPLING
        assert len(response.current_weights) == 2
        assert response.total_pulls == 200
        assert response.recommendation == "CONVERGING"

    def test_current_weights_list_not_empty(self):
        """current_weights list with at least one item is valid."""
        response = BanditStatusResponse(
            experiment_id="exp-abc",
            algorithm=OptimizationType.UCB1,
            current_weights=[self._variant_weight("v0", 1.0)],
            total_pulls=50,
            regret_reduction_pct=None,
            recommendation="EXPLORING",
            last_updated=None,
        )
        assert len(response.current_weights) == 1

    def test_recommendation_exploring(self):
        """Recommendation 'EXPLORING' is stored correctly."""
        response = BanditStatusResponse(
            experiment_id="e1",
            algorithm=OptimizationType.EPSILON_GREEDY,
            current_weights=[self._variant_weight("v0", 1.0)],
            total_pulls=10,
            regret_reduction_pct=None,
            recommendation="EXPLORING",
            last_updated=None,
        )
        assert response.recommendation == "EXPLORING"

    def test_recommendation_converging(self):
        """Recommendation 'CONVERGING' is stored correctly."""
        response = BanditStatusResponse(
            experiment_id="e2",
            algorithm=OptimizationType.THOMPSON_SAMPLING,
            current_weights=[self._variant_weight("v0", 1.0)],
            total_pulls=500,
            regret_reduction_pct=15.0,
            recommendation="CONVERGING",
            last_updated="2026-01-01T00:00:00Z",
        )
        assert response.recommendation == "CONVERGING"

    def test_recommendation_deploying_variant(self):
        """Recommendation 'DEPLOYING_<name>' is stored correctly."""
        response = BanditStatusResponse(
            experiment_id="e3",
            algorithm=OptimizationType.UCB1,
            current_weights=[self._variant_weight("v1", 1.0, successes=900, pulls=1000)],
            total_pulls=1000,
            regret_reduction_pct=40.0,
            recommendation="DEPLOYING_Treatment",
            last_updated="2026-02-01T00:00:00Z",
        )
        assert "DEPLOYING" in response.recommendation

    def test_optional_fields_can_be_none(self):
        """regret_reduction_pct and last_updated are nullable."""
        response = BanditStatusResponse(
            experiment_id="e4",
            algorithm=OptimizationType.FIXED,
            current_weights=[self._variant_weight("v0", 0.5),
                             self._variant_weight("v1", 0.5)],
            total_pulls=0,
            regret_reduction_pct=None,
            recommendation="EXPLORING",
            last_updated=None,
        )
        assert response.regret_reduction_pct is None
        assert response.last_updated is None


# ===========================================================================
# TestBanditUpdateRequest
# ===========================================================================

class TestBanditUpdateRequest:
    """Tests for BanditUpdateRequest schema."""

    def test_valid_update_request_two_variants(self):
        """Weights summing to 1.0 with 2 variants passes validation."""
        req = BanditUpdateRequest(weights={"v0": 0.4, "v1": 0.6})
        assert req.weights == {"v0": 0.4, "v1": 0.6}

    def test_valid_update_request_five_variants(self):
        """Weights summing to 1.0 with 5 variants passes validation."""
        weights = {f"v{i}": 0.2 for i in range(5)}
        req = BanditUpdateRequest(weights=weights)
        assert len(req.weights) == 5

    def test_weights_must_sum_to_one(self):
        """Weights that do not sum to ~1.0 raise a ValidationError."""
        with pytest.raises(ValidationError):
            BanditUpdateRequest(weights={"v0": 0.3, "v1": 0.3})  # sum = 0.6

    def test_negative_weight_raises(self):
        """Negative weights raise a ValidationError."""
        with pytest.raises(ValidationError):
            BanditUpdateRequest(weights={"v0": -0.1, "v1": 1.1})

    def test_weights_summing_slightly_above_one_tolerated(self):
        """Floating-point drift just above 1.0 is tolerated (within 1e-6)."""
        # Python float arithmetic can produce 0.1+0.2+0.3+0.4 = 1.0000000000000002
        weights = {"v0": 0.1, "v1": 0.2, "v2": 0.3, "v3": 0.4}
        req = BanditUpdateRequest(weights=weights)
        assert abs(sum(req.weights.values()) - 1.0) < 1e-6

    def test_valid_update_ten_variants(self):
        """Weights across 10 variants summing to 1.0 passes validation."""
        weights = {f"v{i}": 0.1 for i in range(10)}
        req = BanditUpdateRequest(weights=weights)
        assert len(req.weights) == 10
