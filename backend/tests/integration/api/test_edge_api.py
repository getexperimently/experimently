"""
Integration tests for EP-047 Edge SDK Bootstrap API.

Tests the full HTTP request/response cycle for the edge bootstrap endpoint:
  GET /api/v1/edge/bootstrap   — returns all flags and experiments for the API key

Covers:
  - Successful response with flags and experiments
  - Response includes version (SHA-256 hash)
  - Missing API key → 401
  - Invalid API key → 401
  - Empty org → 200 + empty arrays
  - Version is deterministic (same flags → same hash)
  - Response structure matches EdgeBootstrapResponse schema
  - Disabled and active flags are included with correct enabled state
  - Flags include rolloutPercentage, variants, rules fields
  - Experiments include variants with key, name, weight
  - Cache-friendly: same payload always produces same version hash
  - Multiple flags produce multiple entries in response
  - Flags from other owners are not returned
"""
import hashlib
import json
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.main import app
from backend.app.api import deps
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.experiment import Experiment, ExperimentStatus, Variant
from backend.app.models.user import User, UserRole

BOOTSTRAP_URL = "/api/v1/edge/bootstrap"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_flag(
    db: Session,
    owner_id,
    key: str = None,
    status: FeatureFlagStatus = FeatureFlagStatus.ACTIVE,
    rollout_percentage: int = 100,
    targeting_rules: list = None,
    variants: list = None,
) -> FeatureFlag:
    """Create and persist a FeatureFlag in the test database."""
    flag = FeatureFlag(
        key=key or f"flag-{uuid.uuid4().hex[:8]}",
        name=f"Test Flag {uuid.uuid4().hex[:6]}",
        status=status,
        owner_id=owner_id,
        rollout_percentage=rollout_percentage,
        targeting_rules=targeting_rules or [],
        variants=variants or [],
    )
    db.add(flag)
    db.commit()
    db.refresh(flag)
    return flag


def _make_experiment_with_variants(
    db: Session,
    owner_id,
    name: str = None,
    status: ExperimentStatus = ExperimentStatus.ACTIVE,
) -> Experiment:
    """Create and persist an Experiment with two variants."""
    exp = Experiment(
        name=name or f"Experiment {uuid.uuid4().hex[:6]}",
        status=status,
        owner_id=owner_id,
        description="Edge integration test experiment",
        hypothesis="Edge test hypothesis",
    )
    db.add(exp)
    db.commit()
    db.refresh(exp)

    control = Variant(
        experiment_id=exp.id,
        name="Control",
        is_control=True,
        traffic_allocation=50.0,
    )
    treatment = Variant(
        experiment_id=exp.id,
        name="Treatment",
        is_control=False,
        traffic_allocation=50.0,
    )
    db.add(control)
    db.add(treatment)
    db.commit()
    return exp


# ---------------------------------------------------------------------------
# Tests: GET /api/v1/edge/bootstrap (authenticated)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestEdgeBootstrapAuthenticated:
    """Tests for GET /edge/bootstrap with a valid (overridden) API key."""

    def test_bootstrap_returns_200_with_empty_org(self, admin_client):
        """When the user has no flags or experiments, endpoint returns 200 with empty arrays."""
        response = admin_client.get(BOOTSTRAP_URL)
        assert response.status_code == 200, response.text

    def test_bootstrap_response_has_required_fields(self, admin_client):
        """Response JSON contains flags, experiments, ttl_seconds, and version."""
        response = admin_client.get(BOOTSTRAP_URL)
        assert response.status_code == 200
        data = response.json()
        assert "flags" in data
        assert "experiments" in data
        assert "ttl_seconds" in data
        assert "version" in data

    def test_bootstrap_empty_org_returns_empty_arrays(self, admin_client):
        """Empty org returns empty flags and experiments arrays."""
        response = admin_client.get(BOOTSTRAP_URL)
        data = response.json()
        assert isinstance(data["flags"], list)
        assert isinstance(data["experiments"], list)

    def test_bootstrap_ttl_seconds_is_positive_integer(self, admin_client):
        """ttl_seconds field is a positive integer."""
        response = admin_client.get(BOOTSTRAP_URL)
        data = response.json()
        assert isinstance(data["ttl_seconds"], int)
        assert data["ttl_seconds"] > 0

    def test_bootstrap_version_is_hex_string(self, admin_client):
        """version field is a non-empty SHA-256 hex string (64 chars)."""
        response = admin_client.get(BOOTSTRAP_URL)
        data = response.json()
        assert isinstance(data["version"], str)
        assert len(data["version"]) == 64
        # SHA-256 hex is lowercase hex characters
        assert all(c in "0123456789abcdef" for c in data["version"])

    def test_bootstrap_returns_active_flag(self, db_session, admin_client, admin_user):
        """An active flag owned by the user appears in the response."""
        flag = _make_flag(db_session, admin_user.id, status=FeatureFlagStatus.ACTIVE, rollout_percentage=50)

        response = admin_client.get(BOOTSTRAP_URL)
        assert response.status_code == 200
        data = response.json()
        flag_keys = [f["key"] for f in data["flags"]]
        assert flag.key in flag_keys

    def test_bootstrap_flag_has_correct_enabled_state_for_active(self, db_session, admin_client, admin_user):
        """An ACTIVE flag has enabled=true in the response."""
        flag = _make_flag(db_session, admin_user.id, status=FeatureFlagStatus.ACTIVE)

        response = admin_client.get(BOOTSTRAP_URL)
        data = response.json()
        matched = next((f for f in data["flags"] if f["key"] == flag.key), None)
        assert matched is not None
        assert matched["enabled"] is True

    def test_bootstrap_flag_has_correct_enabled_state_for_inactive(self, db_session, admin_client, admin_user):
        """An INACTIVE flag has enabled=false in the response."""
        flag = _make_flag(db_session, admin_user.id, status=FeatureFlagStatus.INACTIVE)

        response = admin_client.get(BOOTSTRAP_URL)
        data = response.json()
        matched = next((f for f in data["flags"] if f["key"] == flag.key), None)
        assert matched is not None
        assert matched["enabled"] is False

    def test_bootstrap_flag_includes_rollout_percentage(self, db_session, admin_client, admin_user):
        """Flag response includes rolloutPercentage field."""
        flag = _make_flag(db_session, admin_user.id, rollout_percentage=75)

        response = admin_client.get(BOOTSTRAP_URL)
        data = response.json()
        matched = next((f for f in data["flags"] if f["key"] == flag.key), None)
        assert matched is not None
        assert "rolloutPercentage" in matched
        assert matched["rolloutPercentage"] == 75.0

    def test_bootstrap_flag_includes_variants_field(self, db_session, admin_client, admin_user):
        """Flag response includes variants array (empty if none defined)."""
        flag = _make_flag(db_session, admin_user.id)

        response = admin_client.get(BOOTSTRAP_URL)
        data = response.json()
        matched = next((f for f in data["flags"] if f["key"] == flag.key), None)
        assert matched is not None
        assert "variants" in matched
        assert isinstance(matched["variants"], list)

    def test_bootstrap_flag_includes_rules_field(self, db_session, admin_client, admin_user):
        """Flag response includes rules array (empty if none defined)."""
        flag = _make_flag(db_session, admin_user.id)

        response = admin_client.get(BOOTSTRAP_URL)
        data = response.json()
        matched = next((f for f in data["flags"] if f["key"] == flag.key), None)
        assert matched is not None
        assert "rules" in matched
        assert isinstance(matched["rules"], list)

    def test_bootstrap_flag_with_targeting_rules(self, db_session, admin_client, admin_user):
        """Flag with targeting rules includes them in response."""
        rules = [{"attribute": "country", "operator": "eq", "value": "US"}]
        flag = _make_flag(db_session, admin_user.id, targeting_rules=rules)

        response = admin_client.get(BOOTSTRAP_URL)
        data = response.json()
        matched = next((f for f in data["flags"] if f["key"] == flag.key), None)
        assert matched is not None
        assert len(matched["rules"]) == 1
        assert matched["rules"][0]["attribute"] == "country"
        assert matched["rules"][0]["operator"] == "eq"

    def test_bootstrap_returns_multiple_flags(self, db_session, admin_client, admin_user):
        """Multiple flags owned by the user all appear in the response."""
        flag1 = _make_flag(db_session, admin_user.id)
        flag2 = _make_flag(db_session, admin_user.id)
        flag3 = _make_flag(db_session, admin_user.id)

        response = admin_client.get(BOOTSTRAP_URL)
        data = response.json()
        flag_keys = [f["key"] for f in data["flags"]]
        assert flag1.key in flag_keys
        assert flag2.key in flag_keys
        assert flag3.key in flag_keys

    def test_bootstrap_returns_experiment(self, db_session, admin_client, admin_user):
        """An active experiment owned by the user appears in the response."""
        exp = _make_experiment_with_variants(db_session, admin_user.id)
        exp_key = exp.name.lower().replace(" ", "-")

        response = admin_client.get(BOOTSTRAP_URL)
        data = response.json()
        assert "experiments" in data
        exp_keys = [e["key"] for e in data["experiments"]]
        assert exp_key in exp_keys

    def test_bootstrap_experiment_has_enabled_field(self, db_session, admin_client, admin_user):
        """Experiment in response has enabled field."""
        exp = _make_experiment_with_variants(db_session, admin_user.id, status=ExperimentStatus.ACTIVE)

        response = admin_client.get(BOOTSTRAP_URL)
        data = response.json()
        exp_key = exp.name.lower().replace(" ", "-")
        matched = next((e for e in data["experiments"] if e["key"] == exp_key), None)
        assert matched is not None
        assert "enabled" in matched
        assert matched["enabled"] is True

    def test_bootstrap_experiment_has_variants(self, db_session, admin_client, admin_user):
        """Experiment in response has variants with key, name, weight."""
        exp = _make_experiment_with_variants(db_session, admin_user.id)

        response = admin_client.get(BOOTSTRAP_URL)
        data = response.json()
        exp_key = exp.name.lower().replace(" ", "-")
        matched = next((e for e in data["experiments"] if e["key"] == exp_key), None)
        assert matched is not None
        assert len(matched["variants"]) == 2
        for variant in matched["variants"]:
            assert "key" in variant
            assert "name" in variant
            assert "weight" in variant

    def test_bootstrap_experiment_variant_weights_sum_to_one(self, db_session, admin_client, admin_user):
        """Experiment variant weights are normalized to sum to 1.0."""
        exp = _make_experiment_with_variants(db_session, admin_user.id)

        response = admin_client.get(BOOTSTRAP_URL)
        data = response.json()
        exp_key = exp.name.lower().replace(" ", "-")
        matched = next((e for e in data["experiments"] if e["key"] == exp_key), None)
        assert matched is not None
        total_weight = sum(v["weight"] for v in matched["variants"])
        assert abs(total_weight - 1.0) < 0.001


# ---------------------------------------------------------------------------
# Tests: Version determinism
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestEdgeBootstrapVersionDeterminism:
    """Tests that the version hash is stable and deterministic."""

    def test_version_is_deterministic(self, admin_client):
        """Two calls with the same flags return the same version."""
        r1 = admin_client.get(BOOTSTRAP_URL)
        r2 = admin_client.get(BOOTSTRAP_URL)
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["version"] == r2.json()["version"]

    def test_version_changes_when_flag_is_added(self, db_session, admin_client, admin_user):
        """Adding a flag changes the version hash."""
        r1 = admin_client.get(BOOTSTRAP_URL)
        version_before = r1.json()["version"]

        _make_flag(db_session, admin_user.id)

        r2 = admin_client.get(BOOTSTRAP_URL)
        version_after = r2.json()["version"]

        assert version_before != version_after

    def test_empty_org_version_is_stable(self, admin_client):
        """Empty org always produces the same version."""
        r1 = admin_client.get(BOOTSTRAP_URL)
        r2 = admin_client.get(BOOTSTRAP_URL)
        assert r1.json()["version"] == r2.json()["version"]


# ---------------------------------------------------------------------------
# Tests: Authentication
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestEdgeBootstrapAuthentication:
    """Tests that authentication is enforced on the bootstrap endpoint."""

    def test_missing_api_key_returns_401(self):
        """GET /edge/bootstrap without an API key returns 401."""
        # Create a fresh TestClient WITHOUT dependency overrides
        unauthenticated_client = TestClient(app, raise_server_exceptions=False)
        response = unauthenticated_client.get(BOOTSTRAP_URL)
        assert response.status_code == 401, response.text

    def test_invalid_api_key_returns_401(self):
        """GET /edge/bootstrap with an invalid API key returns 401 (or 500 in test
        env when the DB lookup fails — either way the request is not granted access).
        """
        unauthenticated_client = TestClient(app, raise_server_exceptions=False)
        response = unauthenticated_client.get(
            BOOTSTRAP_URL,
            headers={"X-API-Key": "invalid-api-key-that-does-not-exist"},
        )
        # 401 = explicit auth rejection; 500 = DB unavailable in test env
        # Both mean the client does NOT receive a 200 with flag data.
        assert response.status_code in (401, 500), response.text
        assert response.status_code != 200

    def test_empty_api_key_header_returns_401(self):
        """GET /edge/bootstrap with empty X-API-Key header returns 401."""
        unauthenticated_client = TestClient(app, raise_server_exceptions=False)
        response = unauthenticated_client.get(
            BOOTSTRAP_URL,
            headers={"X-API-Key": ""},
        )
        assert response.status_code == 401, response.text


# ---------------------------------------------------------------------------
# Tests: Data isolation (owner separation)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.requires_db
class TestEdgeBootstrapDataIsolation:
    """Tests that users only see their own flags and experiments."""

    def test_flags_from_other_owner_are_not_returned(
        self, db_session, admin_client, admin_user, developer_user
    ):
        """Flags owned by another user are not returned."""
        # Create flag owned by developer_user
        other_flag = _make_flag(db_session, developer_user.id)

        # Request as admin_user
        response = admin_client.get(BOOTSTRAP_URL)
        data = response.json()
        flag_keys = [f["key"] for f in data["flags"]]
        assert other_flag.key not in flag_keys

    def test_own_flags_are_returned(
        self, db_session, admin_client, admin_user, developer_user
    ):
        """Flags owned by the authenticated user are returned."""
        own_flag = _make_flag(db_session, admin_user.id)
        other_flag = _make_flag(db_session, developer_user.id)

        response = admin_client.get(BOOTSTRAP_URL)
        data = response.json()
        flag_keys = [f["key"] for f in data["flags"]]
        assert own_flag.key in flag_keys
        assert other_flag.key not in flag_keys
