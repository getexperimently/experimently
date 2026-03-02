"""
Unit tests for variance reduction Pydantic schemas — Issue #21.

Tests validate:
- VarianceReductionConfig defaults and validation
- VarianceReductionMethod enum values
- Field range constraints
- CupedMetricResult serialization
- CupedResultsResponse structure
"""

import pytest
from pydantic import ValidationError

from backend.app.schemas.variance_reduction import (
    CupedMetricResult,
    CupedResultsResponse,
    VarianceReductionConfig,
    VarianceReductionMethod,
)


class TestVarianceReductionConfig:
    """Tests for VarianceReductionConfig schema."""

    def test_default_method_is_none(self):
        """Default method is VarianceReductionMethod.NONE."""
        config = VarianceReductionConfig()
        assert config.method == VarianceReductionMethod.NONE

    def test_default_covariate_lookback_days(self):
        """Default covariate_lookback_days is 7."""
        config = VarianceReductionConfig()
        assert config.covariate_lookback_days == 7

    def test_default_winsorization_percentile(self):
        """Default winsorization_percentile is 99.0."""
        config = VarianceReductionConfig()
        assert config.winsorization_percentile == 99.0

    def test_default_covariate_metric_id_is_none(self):
        """Default covariate_metric_id is None."""
        config = VarianceReductionConfig()
        assert config.covariate_metric_id is None

    def test_set_method_cuped(self):
        """Can set method to CUPED."""
        config = VarianceReductionConfig(method="cuped")
        assert config.method == VarianceReductionMethod.CUPED

    def test_set_method_winsorization(self):
        """Can set method to WINSORIZATION."""
        config = VarianceReductionConfig(method="winsorization")
        assert config.method == VarianceReductionMethod.WINSORIZATION

    def test_winsorization_percentile_min_50(self):
        """winsorization_percentile must be >= 50.0."""
        with pytest.raises(ValidationError):
            VarianceReductionConfig(winsorization_percentile=49.9)

    def test_winsorization_percentile_max_100(self):
        """winsorization_percentile must be <= 100.0."""
        with pytest.raises(ValidationError):
            VarianceReductionConfig(winsorization_percentile=100.1)

    def test_winsorization_percentile_valid_boundary_50(self):
        """winsorization_percentile=50.0 is valid."""
        config = VarianceReductionConfig(winsorization_percentile=50.0)
        assert config.winsorization_percentile == 50.0

    def test_winsorization_percentile_valid_boundary_100(self):
        """winsorization_percentile=100.0 is valid."""
        config = VarianceReductionConfig(winsorization_percentile=100.0)
        assert config.winsorization_percentile == 100.0

    def test_covariate_lookback_days_min_1(self):
        """covariate_lookback_days must be >= 1."""
        with pytest.raises(ValidationError):
            VarianceReductionConfig(covariate_lookback_days=0)

    def test_covariate_lookback_days_max_90(self):
        """covariate_lookback_days must be <= 90."""
        with pytest.raises(ValidationError):
            VarianceReductionConfig(covariate_lookback_days=91)

    def test_covariate_lookback_days_valid(self):
        """covariate_lookback_days=30 is valid."""
        config = VarianceReductionConfig(covariate_lookback_days=30)
        assert config.covariate_lookback_days == 30

    def test_from_attributes_config(self):
        """VarianceReductionConfig has from_attributes=True."""
        assert VarianceReductionConfig.model_config.get("from_attributes") is True


class TestVarianceReductionMethodEnum:
    """Tests for VarianceReductionMethod enum."""

    def test_none_value(self):
        """NONE enum value is 'none'."""
        assert VarianceReductionMethod.NONE.value == "none"

    def test_cuped_value(self):
        """CUPED enum value is 'cuped'."""
        assert VarianceReductionMethod.CUPED.value == "cuped"

    def test_cuped_plus_value(self):
        """CUPED_PLUS enum value is 'cuped_plus'."""
        assert VarianceReductionMethod.CUPED_PLUS.value == "cuped_plus"

    def test_winsorization_value(self):
        """WINSORIZATION enum value is 'winsorization'."""
        assert VarianceReductionMethod.WINSORIZATION.value == "winsorization"

    def test_all_enum_members(self):
        """VarianceReductionMethod has exactly 4 members."""
        members = list(VarianceReductionMethod)
        assert len(members) == 4


class TestCupedMetricResult:
    """Tests for CupedMetricResult schema."""

    def _make_valid_result(self, **overrides):
        data = {
            "metric_id": "metric-123",
            "metric_name": "Conversion Rate",
            "adjusted_control_mean": 0.10,
            "adjusted_treatment_mean": 0.12,
            "adjusted_effect": 0.02,
            "adjusted_se": 0.005,
            "adjusted_p_value": 0.03,
            "adjusted_ci_lower": 0.01,
            "adjusted_ci_upper": 0.03,
            "variance_reduction_pct": 25.0,
            "theta": 0.75,
            "method": "cuped",
        }
        data.update(overrides)
        return CupedMetricResult(**data)

    def test_valid_metric_result(self):
        """CupedMetricResult with valid data serializes correctly."""
        result = self._make_valid_result()
        assert result.metric_id == "metric-123"
        assert result.metric_name == "Conversion Rate"
        assert result.adjusted_effect == 0.02
        assert result.method == VarianceReductionMethod.CUPED

    def test_all_fields_present(self):
        """CupedMetricResult has all required fields."""
        result = self._make_valid_result()
        assert hasattr(result, "metric_id")
        assert hasattr(result, "metric_name")
        assert hasattr(result, "adjusted_control_mean")
        assert hasattr(result, "adjusted_treatment_mean")
        assert hasattr(result, "adjusted_effect")
        assert hasattr(result, "adjusted_se")
        assert hasattr(result, "adjusted_p_value")
        assert hasattr(result, "adjusted_ci_lower")
        assert hasattr(result, "adjusted_ci_upper")
        assert hasattr(result, "variance_reduction_pct")
        assert hasattr(result, "theta")
        assert hasattr(result, "method")

    def test_metric_result_model_serializes_to_dict(self):
        """CupedMetricResult can be serialized to a dict."""
        result = self._make_valid_result()
        data = result.model_dump()
        assert isinstance(data, dict)
        assert data["metric_id"] == "metric-123"
        assert data["method"] == "cuped"


class TestCupedResultsResponse:
    """Tests for CupedResultsResponse schema."""

    def _make_metric(self):
        return CupedMetricResult(
            metric_id="m1",
            metric_name="Revenue",
            adjusted_control_mean=10.0,
            adjusted_treatment_mean=11.0,
            adjusted_effect=1.0,
            adjusted_se=0.2,
            adjusted_p_value=0.01,
            adjusted_ci_lower=0.6,
            adjusted_ci_upper=1.4,
            variance_reduction_pct=30.0,
            theta=0.5,
            method="cuped",
        )

    def test_valid_response(self):
        """CupedResultsResponse with valid data serializes correctly."""
        response = CupedResultsResponse(
            experiment_id="exp-abc",
            method="cuped",
            metrics=[self._make_metric()],
            computed_at="2026-03-02T00:00:00Z",
        )
        assert response.experiment_id == "exp-abc"
        assert response.method == VarianceReductionMethod.CUPED
        assert len(response.metrics) == 1
        assert response.computed_at == "2026-03-02T00:00:00Z"

    def test_empty_metrics_list(self):
        """CupedResultsResponse accepts an empty metrics list."""
        response = CupedResultsResponse(
            experiment_id="exp-xyz",
            method="none",
            metrics=[],
            computed_at="2026-03-02T00:00:00Z",
        )
        assert response.metrics == []

    def test_serializes_to_dict(self):
        """CupedResultsResponse can be serialized to a dict."""
        response = CupedResultsResponse(
            experiment_id="exp-abc",
            method="cuped",
            metrics=[self._make_metric()],
            computed_at="2026-03-02T00:00:00Z",
        )
        data = response.model_dump()
        assert isinstance(data, dict)
        assert data["experiment_id"] == "exp-abc"
        assert isinstance(data["metrics"], list)
