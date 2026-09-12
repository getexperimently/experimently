"""
Unit tests for EP-022 Mutual Exclusion Group and Global Holdout schemas.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.schemas.global_holdout import (
    GlobalHoldoutCreate,
    GlobalHoldoutListResponse,
    GlobalHoldoutResponse,
    GlobalHoldoutUpdate,
    HoldoutCheckResponse,
)
from backend.app.schemas.mutual_exclusion_group import (
    AddExperimentToGroupRequest,
    ExperimentSummary,
    MutualExclusionGroupCreate,
    MutualExclusionGroupListResponse,
    MutualExclusionGroupResponse,
    MutualExclusionGroupStatus,
    MutualExclusionGroupUpdate,
    UserExperimentSelection,
)

# ---------------------------------------------------------------------------
# Mutual Exclusion Group Schemas
# ---------------------------------------------------------------------------


class TestMutualExclusionGroupCreate:
    """Tests for MutualExclusionGroupCreate schema."""

    def test_minimal_create(self):
        data = MutualExclusionGroupCreate(name="Search Experiments")
        assert data.name == "Search Experiments"
        assert data.traffic_allocation == 1.0
        assert data.description is None

    def test_full_create(self):
        data = MutualExclusionGroupCreate(
            name="Checkout Flow",
            description="Experiments on checkout page",
            traffic_allocation=0.8,
        )
        assert data.traffic_allocation == 0.8

    def test_name_required(self):
        with pytest.raises(ValidationError):
            MutualExclusionGroupCreate()

    def test_name_min_length(self):
        with pytest.raises(ValidationError):
            MutualExclusionGroupCreate(name="")

    def test_name_max_length(self):
        with pytest.raises(ValidationError):
            MutualExclusionGroupCreate(name="x" * 201)

    def test_traffic_allocation_min_zero(self):
        data = MutualExclusionGroupCreate(name="Test", traffic_allocation=0.0)
        assert data.traffic_allocation == 0.0

    def test_traffic_allocation_max_one(self):
        data = MutualExclusionGroupCreate(name="Test", traffic_allocation=1.0)
        assert data.traffic_allocation == 1.0

    def test_traffic_allocation_below_zero(self):
        with pytest.raises(ValidationError):
            MutualExclusionGroupCreate(name="Test", traffic_allocation=-0.1)

    def test_traffic_allocation_above_one(self):
        with pytest.raises(ValidationError):
            MutualExclusionGroupCreate(name="Test", traffic_allocation=1.1)


class TestMutualExclusionGroupUpdate:
    """Tests for MutualExclusionGroupUpdate schema."""

    def test_empty_update(self):
        data = MutualExclusionGroupUpdate()
        assert data.name is None
        assert data.traffic_allocation is None

    def test_partial_update(self):
        data = MutualExclusionGroupUpdate(name="Updated Name")
        assert data.name == "Updated Name"
        assert data.traffic_allocation is None

    def test_status_update(self):
        data = MutualExclusionGroupUpdate(status=MutualExclusionGroupStatus.ARCHIVED)
        assert data.status == MutualExclusionGroupStatus.ARCHIVED

    def test_traffic_allocation_update_validation(self):
        with pytest.raises(ValidationError):
            MutualExclusionGroupUpdate(traffic_allocation=1.5)


class TestMutualExclusionGroupResponse:
    """Tests for MutualExclusionGroupResponse schema."""

    def test_valid_response(self):
        now = datetime.now(timezone.utc)
        group_id = uuid4()
        resp = MutualExclusionGroupResponse(
            id=group_id,
            name="Search Experiments",
            description="All search experiments",
            traffic_allocation=0.8,
            status="active",
            owner_id=uuid4(),
            experiments=[],
            created_at=now,
            updated_at=now,
        )
        assert resp.id == group_id
        assert resp.status == "active"

    def test_response_with_experiments(self):
        now = datetime.now(timezone.utc)
        exp_id = uuid4()
        resp = MutualExclusionGroupResponse(
            id=uuid4(),
            name="Test",
            traffic_allocation=1.0,
            status="active",
            experiments=[
                ExperimentSummary(id=exp_id, name="Exp A", status="active"),
            ],
            created_at=now,
            updated_at=now,
        )
        assert len(resp.experiments) == 1
        assert resp.experiments[0].id == exp_id

    def test_status_enum_conversion(self):
        """Status enum values should be converted to strings."""
        from backend.app.models.mutual_exclusion_group import (
            MutualExclusionGroupStatus as ModelStatus,
        )

        now = datetime.now(timezone.utc)
        resp = MutualExclusionGroupResponse(
            id=uuid4(),
            name="Test",
            traffic_allocation=1.0,
            status=ModelStatus.ACTIVE,
            experiments=[],
            created_at=now,
            updated_at=now,
        )
        assert resp.status == "active"


class TestMutualExclusionGroupList:
    """Tests for MutualExclusionGroupListResponse schema."""

    def test_empty_list(self):
        resp = MutualExclusionGroupListResponse(items=[], total=0)
        assert resp.total == 0

    def test_list_with_items(self):
        now = datetime.now(timezone.utc)
        items = [
            MutualExclusionGroupResponse(
                id=uuid4(),
                name=f"Group {i}",
                traffic_allocation=1.0,
                status="active",
                experiments=[],
                created_at=now,
                updated_at=now,
            )
            for i in range(3)
        ]
        resp = MutualExclusionGroupListResponse(items=items, total=3)
        assert resp.total == 3


class TestAddExperimentToGroupRequest:
    """Tests for AddExperimentToGroupRequest schema."""

    def test_valid_request(self):
        exp_id = uuid4()
        req = AddExperimentToGroupRequest(experiment_id=exp_id)
        assert req.experiment_id == exp_id

    def test_experiment_id_required(self):
        with pytest.raises(ValidationError):
            AddExperimentToGroupRequest()


class TestUserExperimentSelection:
    """Tests for UserExperimentSelection schema."""

    def test_selected_experiment(self):
        exp_id = uuid4()
        group_id = uuid4()
        sel = UserExperimentSelection(
            user_id="user_123",
            group_id=group_id,
            selected_experiment_id=exp_id,
            is_excluded=False,
        )
        assert sel.selected_experiment_id == exp_id
        assert not sel.is_excluded

    def test_excluded_user(self):
        sel = UserExperimentSelection(
            user_id="user_456",
            group_id=uuid4(),
            selected_experiment_id=None,
            is_excluded=True,
        )
        assert sel.selected_experiment_id is None
        assert sel.is_excluded


# ---------------------------------------------------------------------------
# Global Holdout Schemas
# ---------------------------------------------------------------------------


class TestGlobalHoldoutCreate:
    """Tests for GlobalHoldoutCreate schema."""

    def test_minimal_create(self):
        data = GlobalHoldoutCreate(name="Production Holdout")
        assert data.name == "Production Holdout"
        assert data.holdout_percentage == 10
        assert data.is_active is False

    def test_full_create(self):
        data = GlobalHoldoutCreate(
            name="Test Holdout",
            description="5% holdout for baseline",
            holdout_percentage=5,
            is_active=True,
        )
        assert data.holdout_percentage == 5
        assert data.is_active is True

    def test_name_required(self):
        with pytest.raises(ValidationError):
            GlobalHoldoutCreate()

    def test_holdout_percentage_min_one(self):
        data = GlobalHoldoutCreate(name="Test", holdout_percentage=1)
        assert data.holdout_percentage == 1

    def test_holdout_percentage_max_twenty(self):
        data = GlobalHoldoutCreate(name="Test", holdout_percentage=20)
        assert data.holdout_percentage == 20

    def test_holdout_percentage_below_min(self):
        with pytest.raises(ValidationError):
            GlobalHoldoutCreate(name="Test", holdout_percentage=0)

    def test_holdout_percentage_above_max(self):
        with pytest.raises(ValidationError):
            GlobalHoldoutCreate(name="Test", holdout_percentage=21)


class TestGlobalHoldoutUpdate:
    """Tests for GlobalHoldoutUpdate schema."""

    def test_empty_update(self):
        data = GlobalHoldoutUpdate()
        assert data.holdout_percentage is None
        assert data.is_active is None

    def test_partial_update(self):
        data = GlobalHoldoutUpdate(holdout_percentage=15)
        assert data.holdout_percentage == 15

    def test_activate(self):
        data = GlobalHoldoutUpdate(is_active=True)
        assert data.is_active is True

    def test_invalid_percentage(self):
        with pytest.raises(ValidationError):
            GlobalHoldoutUpdate(holdout_percentage=25)


class TestGlobalHoldoutResponse:
    """Tests for GlobalHoldoutResponse schema."""

    def test_valid_response(self):
        now = datetime.now(timezone.utc)
        holdout_id = uuid4()
        resp = GlobalHoldoutResponse(
            id=holdout_id,
            name="Production Holdout",
            description="5% holdout",
            holdout_percentage=5,
            is_active=True,
            owner_id=uuid4(),
            created_at=now,
            updated_at=now,
        )
        assert resp.id == holdout_id
        assert resp.is_active is True


class TestHoldoutCheckResponse:
    """Tests for HoldoutCheckResponse schema."""

    def test_user_in_holdout(self):
        resp = HoldoutCheckResponse(
            user_id="user_001",
            is_in_holdout=True,
            holdout_percentage=10,
            bucket=5,
        )
        assert resp.is_in_holdout is True
        assert resp.bucket == 5

    def test_user_not_in_holdout(self):
        resp = HoldoutCheckResponse(
            user_id="user_002",
            is_in_holdout=False,
            holdout_percentage=10,
            bucket=50,
        )
        assert resp.is_in_holdout is False

    def test_bucket_range(self):
        with pytest.raises(ValidationError):
            HoldoutCheckResponse(
                user_id="user_003",
                is_in_holdout=False,
                holdout_percentage=10,
                bucket=100,
            )
