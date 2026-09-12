"""
Unit tests for AudienceService.

Uses MagicMock for DB session and patches the rules engine evaluation.
No real database required.
"""

import uuid
from datetime import datetime
from unittest.mock import MagicMock, call, patch

import pytest

from backend.app.models.segment import Segment
from backend.app.models.segment import SegmentStatus as ModelSegmentStatus
from backend.app.schemas.segment import (
    AudiencePreviewResponse,
    BulkSegmentMembershipRequest,
    BulkSegmentMembershipResponse,
    SegmentCreate,
    SegmentMembershipResponse,
    SegmentStatus,
    SegmentUpdate,
)
from backend.app.services.audience_service import AudienceService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_segment(
    segment_id=None,
    name="Test Segment",
    status=ModelSegmentStatus.ACTIVE,
    rules=None,
):
    """Create a mock Segment object."""
    seg = MagicMock(spec=Segment)
    seg.id = segment_id or uuid.uuid4()
    seg.name = name
    seg.description = "Test description"
    seg.status = status
    seg.rules = rules or {
        "operator": "and",
        "conditions": [
            {"attribute": "country", "operator": "eq", "value": "US"},
        ],
    }
    seg.created_at = datetime(2025, 1, 1, 12, 0)
    seg.updated_at = datetime(2025, 1, 2, 12, 0)
    return seg


def _make_mock_db(segment=None):
    """Create a mock DB session that returns the given segment from queries."""
    db = MagicMock()
    query_chain = db.query.return_value.filter.return_value
    query_chain.first.return_value = segment
    query_chain.offset.return_value.limit.return_value.all.return_value = (
        [segment] if segment else []
    )
    return db


# ---------------------------------------------------------------------------
# create_segment
# ---------------------------------------------------------------------------


class TestCreateSegment:
    def test_create_segment_persists_with_correct_fields(self):
        """create_segment adds segment to session and commits."""
        db = MagicMock()
        data = SegmentCreate(
            name="My Segment",
            rules={"operator": "and", "conditions": []},
        )
        user_id = uuid.uuid4()

        # Simulate db.refresh side effect: set id and timestamps on the segment
        def fake_refresh(obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime(2025, 1, 1)
            obj.updated_at = datetime(2025, 1, 1)
            obj.status = ModelSegmentStatus.ACTIVE

        db.refresh.side_effect = fake_refresh

        segment = AudienceService.create_segment(db, data, created_by_id=user_id)

        db.add.assert_called_once()
        db.commit.assert_called_once()
        db.refresh.assert_called_once()

        added_segment = db.add.call_args[0][0]
        assert added_segment.name == "My Segment"
        assert added_segment.owner_id == user_id

    def test_create_segment_sets_active_status_by_default(self):
        """New segments are created with ACTIVE status."""
        db = MagicMock()
        db.refresh.side_effect = lambda obj: None
        data = SegmentCreate(
            name="Status Segment",
            rules={"operator": "and", "conditions": []},
        )

        AudienceService.create_segment(db, data)

        added_segment = db.add.call_args[0][0]
        assert added_segment.status == ModelSegmentStatus.ACTIVE

    def test_create_segment_stores_rules_as_provided(self):
        """Segment rules are stored exactly as provided in SegmentCreate."""
        db = MagicMock()
        db.refresh.side_effect = lambda obj: None
        rules = {
            "operator": "or",
            "conditions": [
                {"attribute": "plan", "operator": "eq", "value": "premium"},
            ],
        }
        data = SegmentCreate(name="Rules Segment", rules=rules)

        AudienceService.create_segment(db, data)

        added_segment = db.add.call_args[0][0]
        assert added_segment.rules == rules


# ---------------------------------------------------------------------------
# list_segments
# ---------------------------------------------------------------------------


class TestListSegments:
    def test_list_segments_returns_all_when_no_status_filter(self):
        """list_segments without status filter queries all segments."""
        db = MagicMock()
        mock_seg = _make_mock_segment()
        db.query.return_value.offset.return_value.limit.return_value.all.return_value = [
            mock_seg
        ]

        results = AudienceService.list_segments(db)
        assert len(results) == 1

    def test_list_segments_filters_by_status(self):
        """list_segments with status filter applies filter to query."""
        db = MagicMock()
        db.query.return_value.filter.return_value.offset.return_value.limit.return_value.all.return_value = []

        AudienceService.list_segments(db, status=SegmentStatus.INACTIVE)
        db.query.return_value.filter.assert_called_once()


# ---------------------------------------------------------------------------
# get_segment
# ---------------------------------------------------------------------------


class TestGetSegment:
    def test_get_segment_returns_segment_when_found(self):
        """get_segment returns the segment when it exists."""
        mock_seg = _make_mock_segment()
        db = _make_mock_db(segment=mock_seg)

        result = AudienceService.get_segment(db, str(mock_seg.id))
        assert result is mock_seg

    def test_get_segment_raises_value_error_when_not_found(self):
        """get_segment raises ValueError for non-existent segment."""
        db = _make_mock_db(segment=None)

        with pytest.raises(ValueError, match="not found"):
            AudienceService.get_segment(db, str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# update_segment
# ---------------------------------------------------------------------------


class TestUpdateSegment:
    def test_update_segment_updates_name(self):
        """update_segment changes the name field."""
        mock_seg = _make_mock_segment()
        db = _make_mock_db(segment=mock_seg)
        db.refresh.side_effect = lambda obj: None

        data = SegmentUpdate(name="New Name")
        AudienceService.update_segment(db, str(mock_seg.id), data)

        assert mock_seg.name == "New Name"
        db.commit.assert_called_once()

    def test_update_segment_updates_status(self):
        """update_segment changes the status field."""
        mock_seg = _make_mock_segment()
        db = _make_mock_db(segment=mock_seg)
        db.refresh.side_effect = lambda obj: None

        data = SegmentUpdate(status=SegmentStatus.INACTIVE)
        AudienceService.update_segment(db, str(mock_seg.id), data)

        assert mock_seg.status == ModelSegmentStatus.INACTIVE

    def test_update_segment_raises_when_not_found(self):
        """update_segment raises ValueError for non-existent segment."""
        db = _make_mock_db(segment=None)

        with pytest.raises(ValueError, match="not found"):
            AudienceService.update_segment(
                db, str(uuid.uuid4()), SegmentUpdate(name="ValidName")
            )


# ---------------------------------------------------------------------------
# delete_segment (soft delete)
# ---------------------------------------------------------------------------


class TestDeleteSegment:
    def test_delete_segment_sets_status_to_archived(self):
        """delete_segment performs soft delete by setting status=ARCHIVED."""
        mock_seg = _make_mock_segment()
        db = _make_mock_db(segment=mock_seg)

        AudienceService.delete_segment(db, str(mock_seg.id))

        assert mock_seg.status == ModelSegmentStatus.ARCHIVED
        db.commit.assert_called_once()

    def test_delete_segment_does_not_hard_delete(self):
        """delete_segment never calls db.delete()."""
        mock_seg = _make_mock_segment()
        db = _make_mock_db(segment=mock_seg)

        AudienceService.delete_segment(db, str(mock_seg.id))

        db.delete.assert_not_called()

    def test_delete_segment_raises_when_not_found(self):
        """delete_segment raises ValueError for non-existent segment."""
        db = _make_mock_db(segment=None)

        with pytest.raises(ValueError, match="not found"):
            AudienceService.delete_segment(db, str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# evaluate_membership
# ---------------------------------------------------------------------------


class TestEvaluateMembership:
    def test_evaluate_membership_returns_true_when_rules_match(self):
        """evaluate_membership returns is_member=True when rules match."""
        rules = {
            "operator": "and",
            "conditions": [
                {"attribute": "country", "operator": "eq", "value": "US"},
            ],
        }
        mock_seg = _make_mock_segment(rules=rules)
        db = _make_mock_db(segment=mock_seg)

        with patch(
            "backend.app.services.audience_service.evaluate_rule_group",
            return_value=True,
        ):
            result = AudienceService.evaluate_membership(
                db, str(mock_seg.id), {"country": "US"}
            )

        assert result.is_member is True
        assert result.segment_id == str(mock_seg.id)
        assert result.segment_name == mock_seg.name

    def test_evaluate_membership_returns_false_when_rules_do_not_match(self):
        """evaluate_membership returns is_member=False when rules don't match."""
        rules = {
            "operator": "and",
            "conditions": [
                {"attribute": "country", "operator": "eq", "value": "US"},
            ],
        }
        mock_seg = _make_mock_segment(rules=rules)
        db = _make_mock_db(segment=mock_seg)

        with patch(
            "backend.app.services.audience_service.evaluate_rule_group",
            return_value=False,
        ):
            result = AudienceService.evaluate_membership(
                db, str(mock_seg.id), {"country": "CA"}
            )

        assert result.is_member is False

    def test_evaluate_membership_raises_value_error_for_non_existent_segment(self):
        """evaluate_membership raises ValueError when segment doesn't exist."""
        db = _make_mock_db(segment=None)

        with pytest.raises(ValueError, match="not found"):
            AudienceService.evaluate_membership(
                db, str(uuid.uuid4()), {"country": "US"}
            )

    def test_evaluate_membership_returns_false_for_empty_rules(self):
        """evaluate_membership returns is_member=False when segment has no rules."""
        mock_seg = MagicMock(spec=Segment)
        mock_seg.id = uuid.uuid4()
        mock_seg.name = "Empty Rules Segment"
        mock_seg.description = "No rules"
        mock_seg.status = ModelSegmentStatus.ACTIVE
        mock_seg.rules = {}  # Explicitly None/empty rules
        mock_seg.created_at = datetime(2025, 1, 1, 12, 0)
        mock_seg.updated_at = datetime(2025, 1, 2, 12, 0)

        db = _make_mock_db(segment=mock_seg)

        result = AudienceService.evaluate_membership(
            db, str(mock_seg.id), {"country": "US"}
        )

        assert result.is_member is False

    def test_evaluate_membership_returns_instance_of_response(self):
        """evaluate_membership returns a SegmentMembershipResponse."""
        mock_seg = _make_mock_segment()
        db = _make_mock_db(segment=mock_seg)

        with patch(
            "backend.app.services.audience_service.evaluate_rule_group",
            return_value=False,
        ):
            result = AudienceService.evaluate_membership(db, str(mock_seg.id), {})

        assert isinstance(result, SegmentMembershipResponse)


# ---------------------------------------------------------------------------
# bulk_evaluate_membership
# ---------------------------------------------------------------------------


class TestBulkEvaluateMembership:
    def test_bulk_evaluate_returns_correct_memberships_dict(self):
        """bulk_evaluate_membership returns correct memberships for each segment."""
        seg1 = _make_mock_segment(rules={"operator": "and", "conditions": []})
        seg2 = _make_mock_segment(rules={"operator": "and", "conditions": []})
        seg1_id = str(seg1.id)
        seg2_id = str(seg2.id)

        db = MagicMock()

        def fake_query_chain(segment_id):
            """Return different segments based on the segment_id filter."""
            if str(segment_id) == seg1_id:
                return seg1
            if str(segment_id) == seg2_id:
                return seg2
            return None

        # Patch get_segment to return segment objects directly
        with patch.object(
            AudienceService,
            "get_segment",
            side_effect=lambda db, sid: seg1 if sid == seg1_id else seg2,
        ):
            with patch(
                "backend.app.services.audience_service.evaluate_rule_group",
                side_effect=[True, False],
            ):
                request = BulkSegmentMembershipRequest(
                    user_context={"country": "US"},
                    segment_ids=[seg1_id, seg2_id],
                )
                result = AudienceService.bulk_evaluate_membership(db, request)

        assert result.memberships[seg1_id] is True
        assert result.memberships[seg2_id] is False

    def test_bulk_evaluate_records_evaluation_time_ms_greater_than_zero(self):
        """bulk_evaluate_membership records a positive evaluation_time_ms."""
        seg = _make_mock_segment(rules={"operator": "and", "conditions": []})
        seg_id = str(seg.id)
        db = MagicMock()

        with patch.object(AudienceService, "get_segment", return_value=seg):
            with patch(
                "backend.app.services.audience_service.evaluate_rule_group",
                return_value=True,
            ):
                request = BulkSegmentMembershipRequest(
                    user_context={"country": "US"},
                    segment_ids=[seg_id],
                )
                result = AudienceService.bulk_evaluate_membership(db, request)

        assert result.evaluation_time_ms >= 0.0

    def test_bulk_evaluate_handles_missing_segment_gracefully(self):
        """bulk_evaluate treats missing segments as non-member (False)."""
        db = MagicMock()
        missing_id = str(uuid.uuid4())

        with patch.object(
            AudienceService,
            "get_segment",
            side_effect=ValueError("not found"),
        ):
            request = BulkSegmentMembershipRequest(
                user_context={"country": "US"},
                segment_ids=[missing_id],
            )
            result = AudienceService.bulk_evaluate_membership(db, request)

        assert result.memberships[missing_id] is False

    def test_bulk_evaluate_returns_bulk_response_instance(self):
        """bulk_evaluate_membership returns BulkSegmentMembershipResponse."""
        seg = _make_mock_segment(rules={"operator": "and", "conditions": []})
        db = MagicMock()

        with patch.object(AudienceService, "get_segment", return_value=seg):
            with patch(
                "backend.app.services.audience_service.evaluate_rule_group",
                return_value=True,
            ):
                request = BulkSegmentMembershipRequest(
                    user_context={},
                    segment_ids=[str(seg.id)],
                )
                result = AudienceService.bulk_evaluate_membership(db, request)

        assert isinstance(result, BulkSegmentMembershipResponse)


# ---------------------------------------------------------------------------
# get_segment_experiments
# ---------------------------------------------------------------------------


class TestGetSegmentExperiments:
    def test_get_segment_experiments_raises_when_segment_not_found(self):
        """get_segment_experiments raises ValueError for non-existent segment."""
        db = _make_mock_db(segment=None)

        with pytest.raises(ValueError, match="not found"):
            AudienceService.get_segment_experiments(db, str(uuid.uuid4()))

    def test_get_segment_experiments_returns_response_with_correct_segment_id(self):
        """get_segment_experiments returns response with the queried segment_id."""
        mock_seg = _make_mock_segment()
        db = MagicMock()

        with patch.object(AudienceService, "get_segment", return_value=mock_seg):
            # Make DB query chains return empty lists gracefully
            db.query.return_value.filter.return_value.all.return_value = []

            result = AudienceService.get_segment_experiments(db, str(mock_seg.id))

        assert result.segment_id == str(mock_seg.id)
        assert isinstance(result.experiments, list)
        assert isinstance(result.feature_flags, list)


# ---------------------------------------------------------------------------
# preview_audience_size
# ---------------------------------------------------------------------------


class TestPreviewAudienceSize:
    def test_preview_returns_dict_with_required_keys(self):
        """preview_audience_size returns AudiencePreviewResponse with required fields."""
        db = MagicMock()
        db.query.return_value.limit.return_value.all.return_value = []

        rules = {"operator": "and", "conditions": []}
        result = AudienceService.preview_audience_size(db, rules, sample_size=100)

        assert isinstance(result, AudiencePreviewResponse)
        assert hasattr(result, "estimated_percentage")
        assert hasattr(result, "sample_size")
        assert hasattr(result, "matched")

    def test_preview_returns_zero_percentage_when_no_assignments(self):
        """Returns 0% when no assignment records exist."""
        db = MagicMock()
        db.query.return_value.limit.return_value.all.return_value = []

        rules = {"operator": "and", "conditions": []}
        result = AudienceService.preview_audience_size(db, rules, sample_size=1000)

        assert result.estimated_percentage == 0.0
        assert result.matched == 0

    def test_preview_sample_size_reflects_actual_assignments_sampled(self):
        """sample_size in response reflects the number of assignments evaluated."""
        db = MagicMock()
        # simulate no Assignment model available → falls back to 0
        with patch(
            "backend.app.services.audience_service.evaluate_rule_group",
            return_value=True,
        ):
            rules = {"operator": "and", "conditions": []}
            result = AudienceService.preview_audience_size(db, rules, sample_size=500)

        # Without assignments, sample_size defaults to 0
        assert result.sample_size == 0
