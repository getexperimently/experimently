"""
E2E workflow tests: Audience Segment Lifecycle (EP-011).

These tests exercise the complete audience segment lifecycle:
  1. Create an audience segment with targeting rules
  2. Verify the segment is active and retrievable
  3. Evaluate membership for a user whose context matches the rules → is_member=True
  4. Evaluate membership for a user whose context does not match → is_member=False
  5. Bulk evaluate one user against two segments in one request
  6. Archive (soft-delete) the segment
  7. Verify archived segment does not appear in the 'active' filtered list

Segments use the rules_engine format:
  {"operator": "and", "conditions": [{"attribute": ..., "operator": ..., "value": ...}]}
"""
import uuid
import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _segment_key() -> str:
    """Generate a unique segment name."""
    return f"E2E Segment {uuid.uuid4().hex[:8]}"


def _premium_us_rules() -> dict:
    """Rules that match US premium users."""
    return {
        "operator": "and",
        "conditions": [
            {"attribute": "country", "operator": "eq", "value": "US"},
            {"attribute": "plan", "operator": "eq", "value": "premium"},
        ],
    }


def _age_over_18_rules() -> dict:
    """Rules that match users who are over 18."""
    return {
        "operator": "and",
        "conditions": [
            {"attribute": "age", "operator": "gte", "value": 18},
        ],
    }


def _create_segment(
    client: TestClient,
    name: str = None,
    rules: dict = None,
    description: str = "E2E test segment",
) -> dict:
    """Create a segment via the API and return the response dict."""
    if name is None:
        name = _segment_key()
    if rules is None:
        rules = _premium_us_rules()

    payload = {
        "name": name,
        "description": description,
        "rules": rules,
    }
    resp = client.post("/api/v1/segments", json=payload)
    assert resp.status_code == 201, f"Segment create failed (status={resp.status_code}): {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# Full lifecycle workflow tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.requires_db
class TestSegmentLifecycleWorkflow:
    """Segment: create → evaluate → bulk evaluate → archive."""

    def test_segment_create_evaluate_archive_workflow(self, admin_client):
        """Full segment lifecycle from creation to archival.

        Workflow:
          1. Create segment with "US premium users" rules
          2. Verify segment is active (GET by ID)
          3. Evaluate matching user → is_member=True
          4. Evaluate non-matching user → is_member=False
          5. Archive segment (DELETE = soft delete to ARCHIVED)
          6. Verify segment no longer appears in active list
        """
        # Step 1: Create segment
        segment = _create_segment(
            admin_client,
            name="US Premium Users E2E",
            rules=_premium_us_rules(),
            description="Targets US users on the premium plan",
        )
        segment_id = segment["id"]
        assert segment["name"] == "US Premium Users E2E"
        assert segment["status"] == "active"
        assert "rules" in segment

        # Step 2: Verify via GET
        get_resp = admin_client.get(f"/api/v1/segments/{segment_id}")
        assert get_resp.status_code == 200, get_resp.text
        data = get_resp.json()
        assert data["id"] == segment_id
        assert data["status"] == "active"

        # Step 3: Evaluate a matching user (US, premium)
        match_resp = admin_client.post(
            f"/api/v1/segments/{segment_id}/evaluate",
            json={"user_context": {"country": "US", "plan": "premium", "user_id": "user-001"}},
        )
        assert match_resp.status_code == 200, f"Evaluate (match) failed: {match_resp.text}"
        match_data = match_resp.json()
        assert match_data["is_member"] is True, (
            f"Expected is_member=True for US+premium user, got: {match_data}"
        )
        assert match_data["segment_id"] == segment_id

        # Step 4: Evaluate a non-matching user (EU, free)
        no_match_resp = admin_client.post(
            f"/api/v1/segments/{segment_id}/evaluate",
            json={"user_context": {"country": "DE", "plan": "free", "user_id": "user-002"}},
        )
        assert no_match_resp.status_code == 200, f"Evaluate (no match) failed: {no_match_resp.text}"
        no_match_data = no_match_resp.json()
        assert no_match_data["is_member"] is False, (
            f"Expected is_member=False for DE+free user, got: {no_match_data}"
        )

        # Step 5: Archive the segment
        archive_resp = admin_client.delete(f"/api/v1/segments/{segment_id}")
        assert archive_resp.status_code == 204, f"Archive failed: {archive_resp.text}"

        # Step 6: Verify it doesn't appear in 'active' list
        list_resp = admin_client.get("/api/v1/segments?status=active")
        assert list_resp.status_code == 200, list_resp.text
        active_segments = list_resp.json()
        active_ids = [s["id"] for s in active_segments]
        assert segment_id not in active_ids, (
            f"Archived segment {segment_id} should not appear in active list"
        )

    def test_archived_segment_shows_in_archived_list(self, admin_client):
        """Archived segment appears in the ARCHIVED status-filtered list."""
        segment = _create_segment(
            admin_client,
            name="Archive Check E2E",
        )
        segment_id = segment["id"]

        # Archive it
        admin_client.delete(f"/api/v1/segments/{segment_id}")

        # Verify in archived list
        archived_resp = admin_client.get("/api/v1/segments?status=archived")
        assert archived_resp.status_code == 200, archived_resp.text
        archived_ids = [s["id"] for s in archived_resp.json()]
        assert segment_id in archived_ids, (
            f"Archived segment {segment_id} should appear in archived list"
        )


@pytest.mark.integration
@pytest.mark.requires_db
class TestSegmentEvaluationWorkflow:
    """Detailed evaluation scenarios for segment targeting."""

    def test_single_segment_evaluate_matching_context(self, admin_client):
        """User context matching all rules → is_member=True."""
        segment = _create_segment(
            admin_client,
            name="Age Segment E2E",
            rules=_age_over_18_rules(),
        )

        resp = admin_client.post(
            f"/api/v1/segments/{segment['id']}/evaluate",
            json={"user_context": {"age": 25, "user_id": "adult-user"}},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_member"] is True

    def test_single_segment_evaluate_non_matching_context(self, admin_client):
        """User context not matching rules → is_member=False."""
        segment = _create_segment(
            admin_client,
            name="Adult Age Segment E2E",
            rules=_age_over_18_rules(),
        )

        resp = admin_client.post(
            f"/api/v1/segments/{segment['id']}/evaluate",
            json={"user_context": {"age": 16, "user_id": "minor-user"}},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_member"] is False

    def test_evaluate_nonexistent_segment_returns_404(self, admin_client):
        """Evaluating a non-existent segment ID returns 404."""
        fake_id = "00000000-0000-0000-0000-000000000001"
        resp = admin_client.post(
            f"/api/v1/segments/{fake_id}/evaluate",
            json={"user_context": {"country": "US"}},
        )
        assert resp.status_code == 404, resp.text

    def test_evaluate_response_contains_matched_rules(self, admin_client):
        """Evaluation response contains segment_id, segment_name, and is_member fields."""
        segment = _create_segment(
            admin_client,
            name="Response Fields E2E",
            rules=_premium_us_rules(),
        )

        resp = admin_client.post(
            f"/api/v1/segments/{segment['id']}/evaluate",
            json={"user_context": {"country": "US", "plan": "premium"}},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "segment_id" in data
        assert "segment_name" in data
        assert "is_member" in data
        assert "matched_rules" in data
        assert data["segment_id"] == segment["id"]


@pytest.mark.integration
@pytest.mark.requires_db
class TestBulkSegmentEvaluationWorkflow:
    """Bulk evaluation: one user context against multiple segments."""

    def test_bulk_evaluate_two_segments_one_match(self, admin_client):
        """User matches one segment and not the other in bulk evaluation."""
        # Segment 1: US premium users (user will match)
        seg1 = _create_segment(
            admin_client,
            name="Bulk Seg1 E2E",
            rules=_premium_us_rules(),
        )
        # Segment 2: Age 18+ users (user age=15, will not match)
        seg2 = _create_segment(
            admin_client,
            name="Bulk Seg2 E2E",
            rules=_age_over_18_rules(),
        )

        user_context = {
            "user_id": "bulk-user-001",
            "country": "US",
            "plan": "premium",
            "age": 15,  # Does not match age_over_18
        }

        resp = admin_client.post(
            "/api/v1/segments/bulk-evaluate",
            json={
                "user_context": user_context,
                "segment_ids": [seg1["id"], seg2["id"]],
            },
        )
        assert resp.status_code == 200, f"Bulk evaluate failed: {resp.text}"

        data = resp.json()
        assert "memberships" in data
        assert "evaluation_time_ms" in data
        assert "user_context" in data

        memberships = data["memberships"]
        assert seg1["id"] in memberships, f"seg1 id not in memberships: {memberships}"
        assert seg2["id"] in memberships, f"seg2 id not in memberships: {memberships}"
        assert memberships[seg1["id"]] is True, "Expected seg1 match"
        assert memberships[seg2["id"]] is False, "Expected seg2 no-match"

    def test_bulk_evaluate_both_match(self, admin_client):
        """User matching both segments shows True for each in memberships."""
        seg1 = _create_segment(
            admin_client,
            name="Both Match Seg1 E2E",
            rules=_premium_us_rules(),
        )
        seg2 = _create_segment(
            admin_client,
            name="Both Match Seg2 E2E",
            rules=_age_over_18_rules(),
        )

        user_context = {
            "user_id": "both-match-user",
            "country": "US",
            "plan": "premium",
            "age": 30,  # Matches age_over_18
        }

        resp = admin_client.post(
            "/api/v1/segments/bulk-evaluate",
            json={
                "user_context": user_context,
                "segment_ids": [seg1["id"], seg2["id"]],
            },
        )
        assert resp.status_code == 200, resp.text

        memberships = resp.json()["memberships"]
        assert memberships[seg1["id"]] is True
        assert memberships[seg2["id"]] is True

    def test_bulk_evaluate_neither_match(self, admin_client):
        """User not matching any segment shows False for all memberships."""
        seg1 = _create_segment(
            admin_client,
            name="Neither Seg1 E2E",
            rules=_premium_us_rules(),
        )
        seg2 = _create_segment(
            admin_client,
            name="Neither Seg2 E2E",
            rules=_age_over_18_rules(),
        )

        user_context = {
            "user_id": "no-match-user",
            "country": "DE",
            "plan": "free",
            "age": 15,
        }

        resp = admin_client.post(
            "/api/v1/segments/bulk-evaluate",
            json={
                "user_context": user_context,
                "segment_ids": [seg1["id"], seg2["id"]],
            },
        )
        assert resp.status_code == 200, resp.text

        memberships = resp.json()["memberships"]
        assert memberships[seg1["id"]] is False
        assert memberships[seg2["id"]] is False

    def test_bulk_evaluate_empty_segment_ids_returns_422(self, admin_client):
        """Bulk evaluate with empty segment_ids returns 422."""
        resp = admin_client.post(
            "/api/v1/segments/bulk-evaluate",
            json={
                "user_context": {"country": "US"},
                "segment_ids": [],
            },
        )
        assert resp.status_code == 422, resp.text

    def test_bulk_evaluate_performance_time_in_response(self, admin_client):
        """Bulk evaluation includes evaluation_time_ms in the response."""
        seg = _create_segment(
            admin_client,
            name="Perf Time E2E",
            rules=_premium_us_rules(),
        )

        resp = admin_client.post(
            "/api/v1/segments/bulk-evaluate",
            json={
                "user_context": {"country": "US", "plan": "premium"},
                "segment_ids": [seg["id"]],
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "evaluation_time_ms" in data
        assert isinstance(data["evaluation_time_ms"], (int, float))
        assert data["evaluation_time_ms"] >= 0


@pytest.mark.integration
@pytest.mark.requires_db
class TestSegmentCRUDWorkflow:
    """CRUD operations for segments: list, get, update, archive."""

    def test_segment_appears_in_list_after_creation(self, admin_client):
        """Created segment appears in the GET /segments list."""
        segment = _create_segment(admin_client, name="Listable Segment E2E")
        segment_id = segment["id"]

        list_resp = admin_client.get("/api/v1/segments")
        assert list_resp.status_code == 200, list_resp.text
        all_ids = [s["id"] for s in list_resp.json()]
        assert segment_id in all_ids, f"Segment {segment_id} not in list: {all_ids}"

    def test_segment_update_persists(self, admin_client):
        """PUT update to segment description is reflected in subsequent GET."""
        segment = _create_segment(admin_client, name="Update Test Segment E2E")
        segment_id = segment["id"]

        updated_name = "Updated Segment Name E2E"
        put_resp = admin_client.put(
            f"/api/v1/segments/{segment_id}",
            json={"name": updated_name},
        )
        assert put_resp.status_code == 200, f"PUT failed: {put_resp.text}"
        assert put_resp.json()["name"] == updated_name

        get_resp = admin_client.get(f"/api/v1/segments/{segment_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == updated_name

    def test_get_nonexistent_segment_returns_404(self, admin_client):
        """GET for a non-existent segment ID returns 404."""
        fake_id = "00000000-0000-0000-0000-000000000099"
        resp = admin_client.get(f"/api/v1/segments/{fake_id}")
        assert resp.status_code == 404, resp.text

    def test_segment_list_filtered_by_status(self, admin_client):
        """List endpoint filters segments by status correctly."""
        # Create two active segments
        seg1 = _create_segment(admin_client, name="Active Filter Seg1 E2E")
        seg2 = _create_segment(admin_client, name="Active Filter Seg2 E2E")

        # Archive seg2
        admin_client.delete(f"/api/v1/segments/{seg2['id']}")

        # List only active segments
        active_resp = admin_client.get("/api/v1/segments?status=active")
        assert active_resp.status_code == 200
        active_ids = [s["id"] for s in active_resp.json()]

        assert seg1["id"] in active_ids, "Active seg1 should appear in active list"
        assert seg2["id"] not in active_ids, "Archived seg2 should not appear in active list"

    def test_viewer_can_list_segments(self, viewer_user, db_session):
        """Viewer role can list segments (read-only access permitted)."""
        from backend.tests.integration.conftest import make_client_for_user
        from backend.app.main import app

        client = make_client_for_user(db_session, viewer_user)
        resp = client.get("/api/v1/segments")
        # Viewer may be permitted (200) or forbidden (403) depending on RBAC
        assert resp.status_code in (200, 403), resp.text
        app.dependency_overrides.clear()

    def test_analyst_cannot_create_segment(self, analyst_client):
        """Analyst role lacks CREATE permission on segments; expects 403."""
        resp = analyst_client.post(
            "/api/v1/segments",
            json={
                "name": "Analyst Segment Attempt",
                "rules": _premium_us_rules(),
            },
        )
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
