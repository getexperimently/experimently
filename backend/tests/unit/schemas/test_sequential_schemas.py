"""
Unit tests for EP-021 Sequential Testing schemas.
"""

import pytest
from pydantic import ValidationError

from backend.app.schemas.sequential import (
    AlphaSpendingBoundaryResponse,
    ConfidenceSequenceResponse,
    EvidencePointResponse,
    EvidenceStrength,
    LongRunningRiskResponse,
    MSPRTResultResponse,
    SequentialTestingConfig,
    SequentialTestingMethod,
    SequentialTestingResponse,
    SpendingFunction,
)


class TestSequentialTestingConfig:
    """Tests for SequentialTestingConfig schema."""

    def test_default_config(self):
        config = SequentialTestingConfig()
        assert config.tau_squared == 0.001
        assert config.spending_function == SpendingFunction.OBRIEN_FLEMING
        assert config.planned_looks == 10
        assert config.alpha == 0.05

    def test_custom_config(self):
        config = SequentialTestingConfig(
            tau_squared=0.01,
            spending_function=SpendingFunction.POCOCK,
            planned_looks=5,
            alpha=0.10,
        )
        assert config.tau_squared == 0.01
        assert config.spending_function == SpendingFunction.POCOCK
        assert config.planned_looks == 5
        assert config.alpha == 0.10

    def test_tau_squared_must_be_positive(self):
        with pytest.raises(ValidationError):
            SequentialTestingConfig(tau_squared=0.0)

    def test_tau_squared_must_not_exceed_one(self):
        with pytest.raises(ValidationError):
            SequentialTestingConfig(tau_squared=1.5)

    def test_planned_looks_min_one(self):
        with pytest.raises(ValidationError):
            SequentialTestingConfig(planned_looks=0)

    def test_planned_looks_max_hundred(self):
        with pytest.raises(ValidationError):
            SequentialTestingConfig(planned_looks=101)

    def test_alpha_must_be_positive(self):
        with pytest.raises(ValidationError):
            SequentialTestingConfig(alpha=0.0)

    def test_alpha_must_be_less_than_one(self):
        with pytest.raises(ValidationError):
            SequentialTestingConfig(alpha=1.0)

    def test_optional_expected_duration(self):
        config = SequentialTestingConfig(expected_duration_days=30)
        assert config.expected_duration_days == 30

    def test_optional_required_sample_size(self):
        config = SequentialTestingConfig(required_sample_size=5000)
        assert config.required_sample_size == 5000


class TestMSPRTResultResponse:
    """Tests for MSPRTResultResponse schema."""

    def test_valid_result(self):
        result = MSPRTResultResponse(
            lambda_ratio=25.0,
            always_valid_p_value=0.04,
            can_stop=True,
            evidence_strength=EvidenceStrength.STRONG_FOR_EFFECT,
            boundary=20.0,
        )
        assert result.lambda_ratio == 25.0
        assert result.can_stop is True

    def test_inconclusive_result(self):
        result = MSPRTResultResponse(
            lambda_ratio=5.0,
            always_valid_p_value=0.2,
            can_stop=False,
            evidence_strength=EvidenceStrength.INCONCLUSIVE,
            boundary=20.0,
        )
        assert result.can_stop is False
        assert result.evidence_strength == EvidenceStrength.INCONCLUSIVE


class TestConfidenceSequenceResponse:
    """Tests for ConfidenceSequenceResponse schema."""

    def test_valid_ci(self):
        cs = ConfidenceSequenceResponse(
            lower=-0.05, upper=0.10, width=0.15, sample_size=1000
        )
        assert cs.width == 0.15
        assert cs.sample_size == 1000

    def test_sample_size_non_negative(self):
        with pytest.raises(ValidationError):
            ConfidenceSequenceResponse(
                lower=-0.05, upper=0.10, width=0.15, sample_size=-1
            )


class TestEvidencePointResponse:
    """Tests for EvidencePointResponse schema."""

    def test_valid_point(self):
        pt = EvidencePointResponse(
            sample_size=500, lambda_ratio=10.0, always_valid_p_value=0.1, can_stop=False
        )
        assert pt.sample_size == 500
        assert pt.can_stop is False


class TestSequentialTestingResponse:
    """Tests for SequentialTestingResponse schema."""

    def test_full_response(self):
        resp = SequentialTestingResponse(
            method=SequentialTestingMethod.MSPRT,
            msprt_result=MSPRTResultResponse(
                lambda_ratio=25.0,
                always_valid_p_value=0.04,
                can_stop=True,
                evidence_strength=EvidenceStrength.STRONG_FOR_EFFECT,
                boundary=20.0,
            ),
            confidence_sequence=ConfidenceSequenceResponse(
                lower=0.01, upper=0.08, width=0.07, sample_size=2000
            ),
            evidence_trajectory=[],
            alpha_spending=[],
            long_running_risk=None,
            recommended_action="stop_for_effect",
        )
        assert resp.method == SequentialTestingMethod.MSPRT
        assert resp.recommended_action == "stop_for_effect"

    def test_continue_action(self):
        resp = SequentialTestingResponse(
            method=SequentialTestingMethod.ALWAYS_VALID,
            recommended_action="continue",
        )
        assert resp.recommended_action == "continue"

    def test_invalid_recommended_action(self):
        with pytest.raises(ValidationError):
            SequentialTestingResponse(
                method=SequentialTestingMethod.MSPRT,
                recommended_action="invalid_action",
            )

    def test_null_optional_fields(self):
        resp = SequentialTestingResponse(
            method=SequentialTestingMethod.MSPRT,
            recommended_action="continue",
        )
        assert resp.msprt_result is None
        assert resp.confidence_sequence is None
        assert resp.long_running_risk is None
        assert resp.evidence_trajectory == []
        assert resp.alpha_spending == []
