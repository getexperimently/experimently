"""
Tests for the feature flag Pydantic schemas.

The ORM model only stores ``status`` (``FeatureFlagStatus``); the list-item
schema ``FeatureFlagReadExtended`` must expose that status (lower-cased, the
casing ``GET /feature-flags/{flag_id}`` uses) and derive ``is_active`` from it
instead of falling back to the ``is_active = True`` default.
"""

import uuid
from datetime import datetime

import pytest

from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.schemas.feature_flag import (
    FeatureFlagListResponse,
    FeatureFlagReadExtended,
)


def _flag(status) -> FeatureFlag:
    now = datetime(2024, 1, 1, 12, 0, 0)
    return FeatureFlag(
        id=uuid.uuid4(),
        key="checkout-v2",
        name="Checkout v2",
        description="New checkout",
        status=status,
        rollout_percentage=25,
        targeting_rules=None,
        tags=["checkout"],
        owner_id=uuid.uuid4(),
        created_at=now,
        updated_at=now,
    )


@pytest.mark.unit
class TestFeatureFlagReadExtendedStatus:
    """``status`` / ``is_active`` derivation from ORM instances and dicts."""

    def test_inactive_model_reports_inactive(self):
        read = FeatureFlagReadExtended.model_validate(_flag(FeatureFlagStatus.INACTIVE))
        assert read.status == "inactive"
        assert read.is_active is False

    def test_active_model_reports_active(self):
        read = FeatureFlagReadExtended.model_validate(_flag(FeatureFlagStatus.ACTIVE))
        assert read.status == "active"
        assert read.is_active is True

    def test_archived_model_is_not_active(self):
        read = FeatureFlagReadExtended.model_validate(_flag(FeatureFlagStatus.ARCHIVED))
        assert read.status == "archived"
        assert read.is_active is False

    def test_string_status_on_model_is_normalised(self):
        """CRUD helpers assign ``FeatureFlagStatus.X.value`` (a str) in-session."""
        flag = _flag(FeatureFlagStatus.INACTIVE)
        flag.status = FeatureFlagStatus.ACTIVE.value  # "ACTIVE"
        read = FeatureFlagReadExtended.model_validate(flag)
        assert read.status == "active"
        assert read.is_active is True

    def test_dict_status_overrides_conflicting_is_active(self):
        data = {
            "id": str(uuid.uuid4()),
            "key": "k",
            "name": "n",
            "is_active": True,
            "status": FeatureFlagStatus.INACTIVE,
            "created_at": datetime(2024, 1, 1),
            "updated_at": datetime(2024, 1, 1),
        }
        read = FeatureFlagReadExtended.model_validate(data)
        assert read.status == "inactive"
        assert read.is_active is False

    def test_dict_without_status_keeps_is_active(self):
        """Legacy callers (and cached list payloads) may only carry ``is_active``."""
        data = {
            "id": str(uuid.uuid4()),
            "key": "k",
            "name": "n",
            "is_active": False,
            "created_at": datetime(2024, 1, 1),
            "updated_at": datetime(2024, 1, 1),
        }
        read = FeatureFlagReadExtended.model_validate(data)
        assert read.status is None
        assert read.is_active is False

    def test_list_response_serialises_status_and_is_active(self):
        response = FeatureFlagListResponse(
            items=[_flag(FeatureFlagStatus.INACTIVE), _flag(FeatureFlagStatus.ACTIVE)],
            total=2,
            skip=0,
            limit=100,
        )
        dumped = response.model_dump(mode="json")
        assert [i["status"] for i in dumped["items"]] == ["inactive", "active"]
        assert [i["is_active"] for i in dumped["items"]] == [False, True]
