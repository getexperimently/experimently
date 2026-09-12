"""
Unit tests for real-time counters Pydantic schemas (P2-B TDD).

Tests cover:
- CounterType enum values
- VariantCounters conversion_rate computation
- IncrementRequest amount validation (ge=1, le=1000)
- BulkIncrementRequest min/max items
- CounterResetRequest reason validation
- ExperimentCounters structure
"""

import pytest
from pydantic import ValidationError

from backend.app.schemas.realtime_counters import (
    BulkIncrementRequest,
    BulkIncrementResponse,
    CounterResetRequest,
    CounterType,
    ExperimentCounters,
    IncrementRequest,
    IncrementResponse,
    VariantCounters,
)

# ---------------------------------------------------------------------------
# CounterType enum
# ---------------------------------------------------------------------------


class TestCounterTypeEnum:
    def test_assignment_value(self):
        assert CounterType.ASSIGNMENT == "assignment"

    def test_event_value(self):
        assert CounterType.EVENT == "event"

    def test_conversion_value(self):
        assert CounterType.CONVERSION == "conversion"

    def test_invalid_counter_type_raises_error(self):
        with pytest.raises(ValidationError):
            IncrementRequest(
                experiment_id="exp-1",
                variant_id="variant-a",
                counter_type="invalid_type",
            )

    def test_all_counter_types_iterable(self):
        types = list(CounterType)
        assert len(types) == 3


# ---------------------------------------------------------------------------
# VariantCounters
# ---------------------------------------------------------------------------


class TestVariantCounters:
    def test_default_counters_are_zero(self):
        vc = VariantCounters(
            variant_id="v1",
            variant_name="Control",
            is_control=True,
        )
        assert vc.assignments == 0
        assert vc.events == 0
        assert vc.conversions == 0
        assert vc.conversion_rate == 0.0

    def test_explicit_values_stored(self):
        vc = VariantCounters(
            variant_id="v2",
            variant_name="Treatment",
            is_control=False,
            assignments=100,
            events=80,
            conversions=25,
            conversion_rate=0.25,
        )
        assert vc.assignments == 100
        assert vc.events == 80
        assert vc.conversions == 25
        assert vc.conversion_rate == 0.25

    def test_is_control_false_for_treatment(self):
        vc = VariantCounters(
            variant_id="v2",
            variant_name="Treatment",
            is_control=False,
        )
        assert vc.is_control is False

    def test_is_control_true_for_control(self):
        vc = VariantCounters(
            variant_id="v1",
            variant_name="Control",
            is_control=True,
        )
        assert vc.is_control is True

    def test_conversion_rate_can_be_float(self):
        vc = VariantCounters(
            variant_id="v1",
            variant_name="Control",
            is_control=True,
            assignments=200,
            conversions=50,
            conversion_rate=0.25,
        )
        assert isinstance(vc.conversion_rate, float)


# ---------------------------------------------------------------------------
# ExperimentCounters
# ---------------------------------------------------------------------------


class TestExperimentCounters:
    def test_basic_structure(self):
        ec = ExperimentCounters(
            experiment_id="exp-abc",
            total_assignments=500,
            total_events=400,
            total_conversions=100,
            variants=[],
        )
        assert ec.experiment_id == "exp-abc"
        assert ec.experiment_name is None
        assert ec.total_assignments == 500
        assert ec.last_updated is None

    def test_with_experiment_name_and_timestamp(self):
        ec = ExperimentCounters(
            experiment_id="exp-xyz",
            experiment_name="Homepage CTA Test",
            total_assignments=1000,
            total_events=900,
            total_conversions=150,
            variants=[],
            last_updated="2026-03-01T12:00:00Z",
        )
        assert ec.experiment_name == "Homepage CTA Test"
        assert ec.last_updated == "2026-03-01T12:00:00Z"

    def test_with_multiple_variants(self):
        variants = [
            VariantCounters(
                variant_id="v1",
                variant_name="Control",
                is_control=True,
                assignments=500,
                conversions=75,
                conversion_rate=0.15,
            ),
            VariantCounters(
                variant_id="v2",
                variant_name="Treatment",
                is_control=False,
                assignments=500,
                conversions=125,
                conversion_rate=0.25,
            ),
        ]
        ec = ExperimentCounters(
            experiment_id="exp-abc",
            total_assignments=1000,
            total_events=800,
            total_conversions=200,
            variants=variants,
        )
        assert len(ec.variants) == 2
        assert ec.variants[0].is_control is True
        assert ec.variants[1].is_control is False


# ---------------------------------------------------------------------------
# IncrementRequest
# ---------------------------------------------------------------------------


class TestIncrementRequest:
    def test_default_amount_is_one(self):
        req = IncrementRequest(
            experiment_id="exp-1",
            variant_id="v1",
            counter_type=CounterType.ASSIGNMENT,
        )
        assert req.amount == 1

    def test_custom_amount_stored(self):
        req = IncrementRequest(
            experiment_id="exp-1",
            variant_id="v1",
            counter_type=CounterType.EVENT,
            amount=5,
        )
        assert req.amount == 5

    def test_amount_minimum_is_one(self):
        with pytest.raises(ValidationError):
            IncrementRequest(
                experiment_id="exp-1",
                variant_id="v1",
                counter_type=CounterType.ASSIGNMENT,
                amount=0,
            )

    def test_amount_zero_raises_validation_error(self):
        with pytest.raises(ValidationError):
            IncrementRequest(
                experiment_id="exp-1",
                variant_id="v1",
                counter_type=CounterType.CONVERSION,
                amount=0,
            )

    def test_amount_maximum_is_1000(self):
        req = IncrementRequest(
            experiment_id="exp-1",
            variant_id="v1",
            counter_type=CounterType.EVENT,
            amount=1000,
        )
        assert req.amount == 1000

    def test_amount_over_1000_raises_error(self):
        with pytest.raises(ValidationError):
            IncrementRequest(
                experiment_id="exp-1",
                variant_id="v1",
                counter_type=CounterType.EVENT,
                amount=1001,
            )

    def test_negative_amount_raises_error(self):
        with pytest.raises(ValidationError):
            IncrementRequest(
                experiment_id="exp-1",
                variant_id="v1",
                counter_type=CounterType.ASSIGNMENT,
                amount=-1,
            )


# ---------------------------------------------------------------------------
# IncrementResponse
# ---------------------------------------------------------------------------


class TestIncrementResponse:
    def test_valid_response(self):
        resp = IncrementResponse(
            experiment_id="exp-1",
            variant_id="v1",
            counter_type=CounterType.ASSIGNMENT,
            new_value=42,
        )
        assert resp.new_value == 42
        assert resp.counter_type == CounterType.ASSIGNMENT


# ---------------------------------------------------------------------------
# BulkIncrementRequest
# ---------------------------------------------------------------------------


class TestBulkIncrementRequest:
    def test_single_increment_valid(self):
        bulk = BulkIncrementRequest(
            increments=[
                IncrementRequest(
                    experiment_id="exp-1",
                    variant_id="v1",
                    counter_type=CounterType.ASSIGNMENT,
                )
            ]
        )
        assert len(bulk.increments) == 1

    def test_empty_increments_raises_error(self):
        with pytest.raises(ValidationError):
            BulkIncrementRequest(increments=[])

    def test_100_increments_is_valid(self):
        increments = [
            IncrementRequest(
                experiment_id=f"exp-{i}",
                variant_id="v1",
                counter_type=CounterType.EVENT,
            )
            for i in range(100)
        ]
        bulk = BulkIncrementRequest(increments=increments)
        assert len(bulk.increments) == 100

    def test_101_increments_raises_error(self):
        increments = [
            IncrementRequest(
                experiment_id=f"exp-{i}",
                variant_id="v1",
                counter_type=CounterType.EVENT,
            )
            for i in range(101)
        ]
        with pytest.raises(ValidationError):
            BulkIncrementRequest(increments=increments)


# ---------------------------------------------------------------------------
# BulkIncrementResponse
# ---------------------------------------------------------------------------


class TestBulkIncrementResponse:
    def test_valid_response(self):
        resp = BulkIncrementResponse(
            processed=5,
            failed=1,
            results=[
                IncrementResponse(
                    experiment_id="exp-1",
                    variant_id="v1",
                    counter_type=CounterType.ASSIGNMENT,
                    new_value=10,
                )
            ],
        )
        assert resp.processed == 5
        assert resp.failed == 1
        assert len(resp.results) == 1

    def test_empty_results_list_is_valid(self):
        resp = BulkIncrementResponse(processed=0, failed=0, results=[])
        assert resp.results == []


# ---------------------------------------------------------------------------
# CounterResetRequest
# ---------------------------------------------------------------------------


class TestCounterResetRequest:
    def test_full_reset_request(self):
        req = CounterResetRequest(
            experiment_id="exp-1",
            reason="Experiment restarted after configuration change",
        )
        assert req.variant_id is None
        assert req.counter_type is None
        assert req.reason == "Experiment restarted after configuration change"

    def test_targeted_variant_reset(self):
        req = CounterResetRequest(
            experiment_id="exp-1",
            variant_id="v2",
            reason="Variant data corrupted",
        )
        assert req.variant_id == "v2"
        assert req.counter_type is None

    def test_targeted_counter_type_reset(self):
        req = CounterResetRequest(
            experiment_id="exp-1",
            counter_type=CounterType.CONVERSION,
            reason="Conversion tracking bug fixed",
        )
        assert req.counter_type == CounterType.CONVERSION

    def test_empty_reason_raises_error(self):
        with pytest.raises(ValidationError):
            CounterResetRequest(
                experiment_id="exp-1",
                reason="",
            )

    def test_reason_over_256_chars_raises_error(self):
        with pytest.raises(ValidationError):
            CounterResetRequest(
                experiment_id="exp-1",
                reason="x" * 257,
            )

    def test_reason_exactly_256_chars_is_valid(self):
        req = CounterResetRequest(
            experiment_id="exp-1",
            reason="x" * 256,
        )
        assert len(req.reason) == 256
