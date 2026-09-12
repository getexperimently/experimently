"""
Unit tests for segment Pydantic schemas.

Tests validation, defaults, and serialization for all segment schemas
used in the P3-C: Audience Segmentation API.
"""

import pytest
from pydantic import ValidationError

from backend.app.schemas.segment import (
    AudiencePreviewResponse,
    BulkSegmentMembershipRequest,
    BulkSegmentMembershipResponse,
    ExperimentSegmentLink,
    SegmentCreate,
    SegmentExperimentResponse,
    SegmentMembershipRequest,
    SegmentMembershipResponse,
    SegmentResponse,
    SegmentStatus,
    SegmentUpdate,
)

VALID_RULES = {
    "operator": "and",
    "conditions": [
        {"attribute": "country", "operator": "eq", "value": "US"},
    ],
}


class TestSegmentCreate:
    """Tests for SegmentCreate schema validation."""

    def test_valid_segment_create(self):
        """SegmentCreate accepts valid name and rules."""
        data = SegmentCreate(name="US Users", rules=VALID_RULES)
        assert data.name == "US Users"
        assert data.rules == VALID_RULES
        assert data.description is None

    def test_name_minimum_length_two(self):
        """Name must be at least 2 characters."""
        data = SegmentCreate(name="AB", rules=VALID_RULES)
        assert data.name == "AB"

    def test_name_too_short_raises_validation_error(self):
        """Name shorter than 2 characters fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            SegmentCreate(name="A", rules=VALID_RULES)
        errors = exc_info.value.errors()
        assert any("name" in str(e["loc"]) for e in errors)

    def test_name_maximum_length_128(self):
        """Name of exactly 128 characters is valid."""
        name = "A" * 128
        data = SegmentCreate(name=name, rules=VALID_RULES)
        assert len(data.name) == 128

    def test_name_too_long_raises_validation_error(self):
        """Name longer than 128 characters fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            SegmentCreate(name="A" * 129, rules=VALID_RULES)
        errors = exc_info.value.errors()
        assert any("name" in str(e["loc"]) for e in errors)

    def test_description_optional(self):
        """Description is optional."""
        data = SegmentCreate(name="My Segment", rules=VALID_RULES)
        assert data.description is None

    def test_description_max_length_512(self):
        """Description of 512 characters is valid."""
        desc = "D" * 512
        data = SegmentCreate(name="My Segment", rules=VALID_RULES, description=desc)
        assert len(data.description) == 512

    def test_description_too_long_raises_validation_error(self):
        """Description longer than 512 characters fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            SegmentCreate(name="My Segment", rules=VALID_RULES, description="D" * 513)
        errors = exc_info.value.errors()
        assert any("description" in str(e["loc"]) for e in errors)

    def test_rules_required(self):
        """Rules field is required."""
        with pytest.raises(ValidationError):
            SegmentCreate(name="My Segment")

    def test_rules_accepts_complex_dict(self):
        """Rules accepts any dict structure."""
        complex_rules = {
            "operator": "or",
            "conditions": [
                {"attribute": "plan", "operator": "eq", "value": "premium"},
                {"attribute": "age", "operator": "gte", "value": 18},
            ],
        }
        data = SegmentCreate(name="Complex Segment", rules=complex_rules)
        assert data.rules["operator"] == "or"


class TestSegmentUpdate:
    """Tests for SegmentUpdate schema — all fields optional."""

    def test_empty_update_is_valid(self):
        """SegmentUpdate allows all fields to be omitted."""
        data = SegmentUpdate()
        assert data.name is None
        assert data.description is None
        assert data.rules is None
        assert data.status is None

    def test_update_name_only(self):
        """Can update only the name."""
        data = SegmentUpdate(name="New Name")
        assert data.name == "New Name"

    def test_update_status_only(self):
        """Can update only the status."""
        data = SegmentUpdate(status=SegmentStatus.INACTIVE)
        assert data.status == SegmentStatus.INACTIVE

    def test_update_name_min_length_validation(self):
        """Name in update also requires minimum 2 characters."""
        with pytest.raises(ValidationError):
            SegmentUpdate(name="A")

    def test_update_name_max_length_validation(self):
        """Name in update also enforces maximum 128 characters."""
        with pytest.raises(ValidationError):
            SegmentUpdate(name="A" * 129)

    def test_update_all_fields(self):
        """SegmentUpdate accepts all fields together."""
        data = SegmentUpdate(
            name="Updated Name",
            description="New description",
            rules=VALID_RULES,
            status=SegmentStatus.ACTIVE,
        )
        assert data.name == "Updated Name"
        assert data.status == SegmentStatus.ACTIVE


class TestSegmentStatus:
    """Tests for SegmentStatus enum."""

    def test_active_status(self):
        assert SegmentStatus.ACTIVE == "active"

    def test_inactive_status(self):
        assert SegmentStatus.INACTIVE == "inactive"

    def test_archived_status(self):
        assert SegmentStatus.ARCHIVED == "archived"


class TestSegmentMembershipResponse:
    """Tests for SegmentMembershipResponse defaults."""

    def test_matched_rules_defaults_to_empty_list(self):
        """matched_rules defaults to empty list when not provided."""
        resp = SegmentMembershipResponse(
            segment_id="seg-1",
            segment_name="Test Segment",
            is_member=False,
        )
        assert resp.matched_rules == []

    def test_is_member_true(self):
        """is_member can be True with matched rules."""
        resp = SegmentMembershipResponse(
            segment_id="seg-1",
            segment_name="Test Segment",
            is_member=True,
            matched_rules=["country eq US"],
        )
        assert resp.is_member is True
        assert len(resp.matched_rules) == 1

    def test_is_member_false(self):
        """is_member can be False."""
        resp = SegmentMembershipResponse(
            segment_id="seg-2",
            segment_name="Premium Segment",
            is_member=False,
        )
        assert resp.is_member is False


class TestBulkSegmentMembershipRequest:
    """Tests for BulkSegmentMembershipRequest validation."""

    def test_valid_bulk_request(self):
        """Valid bulk request with segment ids."""
        req = BulkSegmentMembershipRequest(
            user_context={"country": "US"},
            segment_ids=["seg-1", "seg-2"],
        )
        assert len(req.segment_ids) == 2

    def test_max_50_segment_ids(self):
        """Accepts up to 50 segment IDs."""
        req = BulkSegmentMembershipRequest(
            user_context={"country": "US"},
            segment_ids=[f"seg-{i}" for i in range(50)],
        )
        assert len(req.segment_ids) == 50

    def test_more_than_50_segment_ids_raises_error(self):
        """More than 50 segment IDs raises a validation error."""
        with pytest.raises(ValidationError):
            BulkSegmentMembershipRequest(
                user_context={"country": "US"},
                segment_ids=[f"seg-{i}" for i in range(51)],
            )

    def test_empty_segment_ids_raises_error(self):
        """Empty segment_ids list raises a validation error."""
        with pytest.raises(ValidationError):
            BulkSegmentMembershipRequest(
                user_context={"country": "US"},
                segment_ids=[],
            )

    def test_user_context_required(self):
        """user_context is required."""
        with pytest.raises(ValidationError):
            BulkSegmentMembershipRequest(segment_ids=["seg-1"])


class TestBulkSegmentMembershipResponse:
    """Tests for BulkSegmentMembershipResponse."""

    def test_memberships_dict(self):
        """memberships contains segment_id -> bool mapping."""
        resp = BulkSegmentMembershipResponse(
            user_context={"country": "US"},
            memberships={"seg-1": True, "seg-2": False},
            evaluation_time_ms=2.5,
        )
        assert resp.memberships["seg-1"] is True
        assert resp.memberships["seg-2"] is False

    def test_evaluation_time_ms_is_float(self):
        """evaluation_time_ms is a float."""
        resp = BulkSegmentMembershipResponse(
            user_context={},
            memberships={},
            evaluation_time_ms=0.0,
        )
        assert isinstance(resp.evaluation_time_ms, float)


class TestAudiencePreviewResponse:
    """Tests for AudiencePreviewResponse schema."""

    def test_preview_response_fields(self):
        """AudiencePreviewResponse contains required keys."""
        resp = AudiencePreviewResponse(
            estimated_percentage=35.5,
            sample_size=1000,
            matched=355,
        )
        assert resp.estimated_percentage == 35.5
        assert resp.sample_size == 1000
        assert resp.matched == 355
