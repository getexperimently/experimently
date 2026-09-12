"""Unit tests for GlobalHoldoutService (EP-022)."""

from unittest.mock import MagicMock, call, patch
from uuid import uuid4

import pytest

from backend.app.models.global_holdout import GlobalHoldout
from backend.app.services.global_holdout_service import (
    HOLDOUT_SALT,
    GlobalHoldoutService,
)


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def service(mock_db):
    return GlobalHoldoutService(mock_db)


# ------------------------------------------------------------------
# CRUD
# ------------------------------------------------------------------


class TestCreateHoldout:
    def test_creates_holdout_with_defaults(self, service, mock_db):
        result = service.create_holdout(name="Main Holdout")
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once()
        added = mock_db.add.call_args[0][0]
        assert added.name == "Main Holdout"
        assert added.holdout_percentage == 10
        assert added.is_active is False

    def test_creates_holdout_with_custom_fields(self, service, mock_db):
        owner = uuid4()
        service.create_holdout(
            name="Custom Holdout",
            description="Custom description",
            holdout_percentage=5,
            is_active=True,
            owner_id=owner,
        )
        added = mock_db.add.call_args[0][0]
        assert added.description == "Custom description"
        assert added.holdout_percentage == 5
        assert added.is_active is True
        assert added.owner_id == owner


class TestGetHoldout:
    def test_returns_holdout_when_found(self, service, mock_db):
        mock_holdout = MagicMock(spec=GlobalHoldout)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_holdout
        result = service.get_holdout(uuid4())
        assert result is mock_holdout

    def test_returns_none_when_not_found(self, service, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        result = service.get_holdout(uuid4())
        assert result is None


class TestGetActiveHoldout:
    def test_returns_active_holdout(self, service, mock_db):
        mock_holdout = MagicMock(spec=GlobalHoldout, is_active=True)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_holdout
        result = service.get_active_holdout()
        assert result is mock_holdout

    def test_returns_none_when_no_active(self, service, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        result = service.get_active_holdout()
        assert result is None


class TestListHoldouts:
    def test_lists_all_holdouts(self, service, mock_db):
        holdouts = [MagicMock(), MagicMock()]
        mock_db.query.return_value.offset.return_value.limit.return_value.all.return_value = holdouts
        result = service.list_holdouts()
        assert result == holdouts

    def test_lists_with_pagination(self, service, mock_db):
        mock_db.query.return_value.offset.return_value.limit.return_value.all.return_value = []
        service.list_holdouts(skip=5, limit=10)
        mock_db.query.return_value.offset.assert_called_with(5)
        mock_db.query.return_value.offset.return_value.limit.assert_called_with(10)


class TestUpdateHoldout:
    def test_returns_none_when_not_found(self, service, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        result = service.update_holdout(uuid4(), name="New")
        assert result is None

    def test_updates_name(self, service, mock_db):
        mock_holdout = MagicMock(spec=GlobalHoldout)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_holdout
        service.update_holdout(uuid4(), name="Updated")
        assert mock_holdout.name == "Updated"
        mock_db.commit.assert_called_once()

    def test_updates_holdout_percentage(self, service, mock_db):
        mock_holdout = MagicMock(spec=GlobalHoldout)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_holdout
        service.update_holdout(uuid4(), holdout_percentage=15)
        assert mock_holdout.holdout_percentage == 15

    def test_updates_description(self, service, mock_db):
        mock_holdout = MagicMock(spec=GlobalHoldout)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_holdout
        service.update_holdout(uuid4(), description="new desc")
        assert mock_holdout.description == "new desc"


# ------------------------------------------------------------------
# Activation / Deactivation
# ------------------------------------------------------------------


class TestActivateHoldout:
    def test_activating_deactivates_others(self, service, mock_db):
        """Activating a holdout should deactivate all other active holdouts first."""
        mock_holdout = MagicMock(spec=GlobalHoldout)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_holdout

        service.activate_holdout(uuid4())

        # _deactivate_all is called internally which does query().filter().update()
        assert mock_holdout.is_active is True
        mock_db.flush.assert_called()
        mock_db.commit.assert_called()

    def test_activate_returns_none_when_not_found(self, service, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        result = service.activate_holdout(uuid4())
        assert result is None


class TestDeactivateHoldout:
    def test_deactivates_holdout(self, service, mock_db):
        mock_holdout = MagicMock(spec=GlobalHoldout)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_holdout
        service.deactivate_holdout(uuid4())
        assert mock_holdout.is_active is False
        mock_db.commit.assert_called()

    def test_deactivate_returns_none_when_not_found(self, service, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        result = service.deactivate_holdout(uuid4())
        assert result is None


# ------------------------------------------------------------------
# User Holdout Check
# ------------------------------------------------------------------


class TestIsUserInHoldout:
    def test_returns_false_when_no_active_holdout(self, service, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        is_in, pct, bucket = service.is_user_in_holdout("user_123")
        assert is_in is False
        assert pct == 0
        assert bucket == 0

    @patch.object(GlobalHoldoutService, "_get_holdout_bucket")
    def test_user_in_holdout(self, mock_bucket, service, mock_db):
        """User with bucket < holdout_percentage should be in holdout."""
        mock_holdout = MagicMock(spec=GlobalHoldout)
        mock_holdout.holdout_percentage = 10
        mock_holdout.is_active = True
        mock_db.query.return_value.filter.return_value.first.return_value = mock_holdout

        mock_bucket.return_value = 5  # 5 < 10 => in holdout
        is_in, pct, bucket = service.is_user_in_holdout("user_123")
        assert is_in is True
        assert pct == 10
        assert bucket == 5

    @patch.object(GlobalHoldoutService, "_get_holdout_bucket")
    def test_user_not_in_holdout(self, mock_bucket, service, mock_db):
        """User with bucket >= holdout_percentage should NOT be in holdout."""
        mock_holdout = MagicMock(spec=GlobalHoldout)
        mock_holdout.holdout_percentage = 10
        mock_holdout.is_active = True
        mock_db.query.return_value.filter.return_value.first.return_value = mock_holdout

        mock_bucket.return_value = 50  # 50 >= 10 => not in holdout
        is_in, pct, bucket = service.is_user_in_holdout("user_456")
        assert is_in is False
        assert pct == 10
        assert bucket == 50


class TestIsUserInHoldoutStatic:
    def test_user_in_holdout_static(self):
        """Static method: bucket < percentage => in holdout."""
        # Find a user that hashes to a low bucket
        bucket = GlobalHoldoutService._get_holdout_bucket_static("user_123")
        is_in, returned_bucket = GlobalHoldoutService.is_user_in_holdout_static(
            "user_123", 100
        )
        assert is_in is True
        assert returned_bucket == bucket

    def test_user_not_in_holdout_static(self):
        """Static method: bucket >= percentage => not in holdout."""
        is_in, bucket = GlobalHoldoutService.is_user_in_holdout_static("user_123", 0)
        assert is_in is False


# ------------------------------------------------------------------
# Determinism & Distribution
# ------------------------------------------------------------------


class TestDeterministicBucketing:
    def test_same_user_same_bucket(self):
        """Same user_id always produces the same bucket."""
        bucket1 = GlobalHoldoutService._get_holdout_bucket_static("user_123")
        bucket2 = GlobalHoldoutService._get_holdout_bucket_static("user_123")
        assert bucket1 == bucket2

    def test_different_users_can_get_different_buckets(self):
        """Different user_ids should (generally) produce different buckets."""
        buckets = set()
        for i in range(50):
            b = GlobalHoldoutService._get_holdout_bucket_static(f"user_{i}")
            buckets.add(b)
        # With 50 users, we should see more than 1 distinct bucket
        assert len(buckets) > 1

    def test_bucket_range(self):
        """All buckets should be in [0, 99]."""
        for i in range(200):
            bucket = GlobalHoldoutService._get_holdout_bucket_static(f"user_{i}")
            assert 0 <= bucket <= 99

    def test_uniform_distribution(self):
        """Buckets should be roughly uniformly distributed across 0-99."""
        bucket_counts = [0] * 100
        num_users = 10000
        for i in range(num_users):
            bucket = GlobalHoldoutService._get_holdout_bucket_static(f"test_user_{i}")
            bucket_counts[bucket] += 1

        # Each bucket should get roughly num_users/100 = 100 users
        expected = num_users / 100
        for count in bucket_counts:
            # Allow +/- 50% deviation (generous tolerance for hash uniformity)
            assert count > expected * 0.5, f"Bucket underrepresented: {count}"
            assert count < expected * 1.5, f"Bucket overrepresented: {count}"

    def test_holdout_salt_is_used(self):
        """Bucket computation uses the global holdout salt, not arbitrary salt."""
        import hashlib
        import struct

        user_id = "salt_test_user"
        combined = f"{user_id}:{HOLDOUT_SALT}".encode("utf-8")
        hash_bytes = hashlib.md5(combined).digest()[:4]
        hash_int = struct.unpack("<I", hash_bytes)[0]
        expected_bucket = hash_int % 100

        actual_bucket = GlobalHoldoutService._get_holdout_bucket_static(user_id)
        assert actual_bucket == expected_bucket


class TestCountHoldouts:
    def test_count_returns_value(self, service, mock_db):
        mock_db.query.return_value.count.return_value = 3
        result = service.count_holdouts()
        assert result == 3
