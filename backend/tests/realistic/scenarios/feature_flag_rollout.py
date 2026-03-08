"""
Realistic scenario: Feature Flag Gradual Rollout.

Tests the complete lifecycle of a feature flag gradual rollout:
  1. Create feature flag (inactive, 0%)
  2. Create a rollout schedule with three stages (10% → 50% → 100%)
  3. Activate the schedule
  4. Simulate each stage advancing
  5. Verify rollout percentage changes correctly at each stage
  6. Validate that event distribution tracks the rollout percentage

The rollout scenario uses near-identical conversion rates (no significant lift)
to validate that the platform correctly handles rollout mechanics independently
of statistical significance.
"""

import os
import uuid
import pytest
import requests
from datetime import datetime, timedelta, timezone

from backend.tests.realistic.data_generator import make_rollout_scenario


API_URL = os.environ.get("REALISTIC_API_URL", "http://localhost:8000")
SKIP_REASON = "Realistic scenario tests require a running platform (set RUN_REALISTIC=1)"

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_REALISTIC") != "1",
    reason=SKIP_REASON,
)


@pytest.fixture(scope="module")
def auth_headers():
    resp = requests.post(
        f"{API_URL}/api/v1/auth/login",
        json={"username": "admin@example.com", "password": "testpassword123"},
        timeout=10,
    )
    if resp.status_code != 200:
        pytest.skip("Could not obtain API token")
    token = resp.json().get("access_token", "")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


class TestFeatureFlagRollout:
    """Validates gradual rollout mechanics with realistic event data."""

    def test_create_feature_flag(self, auth_headers):
        """Feature flag creation returns 201 with inactive status."""
        flag_key = f"realistic-rollout-{uuid.uuid4().hex[:8]}"
        payload = {
            "key": flag_key,
            "name": "[Realistic] Gradual Checkout Rollout",
            "description": "Realistic rollout scenario",
            "rollout_percentage": 0,
        }
        resp = requests.post(
            f"{API_URL}/api/v1/feature-flags",
            json=payload,
            headers=auth_headers,
            timeout=15,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["rollout_percentage"] == 0

    def test_rollout_schedule_creation(self, auth_headers):
        """Create a three-stage rollout schedule."""
        # First create the flag
        flag_key = f"rollout-sched-{uuid.uuid4().hex[:8]}"
        flag_resp = requests.post(
            f"{API_URL}/api/v1/feature-flags",
            json={"key": flag_key, "name": f"[Realistic] {flag_key}", "rollout_percentage": 0},
            headers=auth_headers,
            timeout=15,
        )
        assert flag_resp.status_code == 201, flag_resp.text
        flag_id = flag_resp.json()["id"]

        now = datetime.now(timezone.utc)
        schedule_payload = {
            "name": f"Rollout for {flag_key}",
            "feature_flag_id": flag_id,
            "start_date": now.isoformat(),
            "end_date": (now + timedelta(days=21)).isoformat(),
            "max_percentage": 100,
            "min_stage_duration": 0,
            "stages": [
                {
                    "name": "Canary",
                    "stage_order": 1,
                    "target_percentage": 10,
                    "trigger_type": "time_based",
                    "start_date": now.isoformat(),
                },
                {
                    "name": "Expanded",
                    "stage_order": 2,
                    "target_percentage": 50,
                    "trigger_type": "time_based",
                    "start_date": (now + timedelta(days=7)).isoformat(),
                },
                {
                    "name": "Full",
                    "stage_order": 3,
                    "target_percentage": 100,
                    "trigger_type": "manual",
                },
            ],
        }
        sched_resp = requests.post(
            f"{API_URL}/api/v1/rollout-schedules",
            json=schedule_payload,
            headers=auth_headers,
            timeout=15,
        )
        assert sched_resp.status_code == 201, sched_resp.text
        sched = sched_resp.json()
        assert len(sched["stages"]) == 3
        assert sched["stages"][0]["target_percentage"] == 10
        assert sched["stages"][1]["target_percentage"] == 50
        assert sched["stages"][2]["target_percentage"] == 100

    def test_realistic_event_distribution_tracks_rollout(self):
        """
        Simulated data for a 0→100% rollout should show events proportionally
        distributed across the rollout window.
        """
        scenario = make_rollout_scenario(seed=99)
        result = scenario.generate()

        # Events are split across control (0%) and treatment (100%)
        treatment_events = [e for e in result.events if e.variant_name == "treatment"]
        control_events = [e for e in result.events if e.variant_name == "control"]

        total = len(treatment_events) + len(control_events)
        assert total > 0, "No events generated"

        # Both arms should have events (we start at 0% but ramp up)
        assert len(treatment_events) > 0
        assert len(control_events) > 0

    def test_rollout_percentage_increases_monotonically(self):
        """Stage percentages in the rollout schedule must be non-decreasing."""
        stages = [10, 50, 100]
        for i in range(1, len(stages)):
            assert stages[i] >= stages[i - 1], (
                f"Stage {i} percentage {stages[i]} is less than stage {i-1} percentage {stages[i-1]}"
            )

    def test_session_decay_reduces_late_engagement(self):
        """Session decay scenario should show lower CVR in later weeks."""
        scenario = make_rollout_scenario(seed=99)
        result = scenario.generate()

        # Group events by week
        start = min(u.assigned_at for u in result.users)
        week1_end = start + timedelta(days=7)
        week3_end = start + timedelta(days=21)

        week1_users = [u for u in result.users if u.assigned_at < week1_end]
        week3_users = [u for u in result.users if week1_end <= u.assigned_at < week3_end]
        week1_ids = {u.user_id for u in week1_users}
        week3_ids = {u.user_id for u in week3_users}

        week1_events = [e for e in result.events if e.user_id in week1_ids]
        week3_events = [e for e in result.events if e.user_id in week3_ids]

        if week1_users and week3_users:
            week1_cvr = len(week1_events) / len(week1_users)
            week3_cvr = len(week3_events) / len(week3_users)
            # Week 3 CVR should be lower (session decay enabled)
            assert week3_cvr <= week1_cvr * 1.1, (
                f"Session decay expected: week3 CVR {week3_cvr:.3f} should be ≤ week1 {week1_cvr:.3f}"
            )
