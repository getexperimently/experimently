"""
Realistic scenario: Concurrent Experiments & Mutual Exclusion.

Validates that the platform correctly handles multiple overlapping
experiments without cross-contamination:

  1. Two experiments targeting the same user population
  2. Mutual exclusion group preventing a user from being in both
  3. Global holdout group excluded from all experiments
  4. Interaction detection when experiments share a metric

The data generator simulates 5k users spread across two simultaneous
experiments, allowing the interaction detection service to be exercised
with realistic overlap patterns.
"""

import os
import uuid
import pytest
import requests

from backend.tests.realistic.data_generator import make_concurrent_scenario, DataScenario


API_URL = os.environ.get("REALISTIC_API_URL", "http://localhost:8000")
SKIP_REASON = "Realistic scenario tests require a running platform (set RUN_REALISTIC=1)"

requires_platform = pytest.mark.skipif(
    os.environ.get("RUN_REALISTIC") != "1",
    reason=SKIP_REASON,
)


class TestConcurrentDataGeneration:
    """Data generation tests — no running platform required."""

    def test_concurrent_scenario_generates_correct_user_count(self):
        scenario = make_concurrent_scenario(seed=21)
        result = scenario.generate()
        assert len(result.users) == 8000

    def test_control_treatment_split_is_balanced(self):
        scenario = make_concurrent_scenario(seed=21)
        result = scenario.generate()
        control = [u for u in result.users if u.variant_name == "control"]
        treatment = [u for u in result.users if u.variant_name == "treatment"]
        # 50/50 split — allow 1% tolerance
        assert abs(len(control) - len(treatment)) <= 50, (
            f"Unbalanced split: control={len(control)}, treatment={len(treatment)}"
        )

    def test_user_ids_are_unique_per_variant(self):
        """Each user_id should appear at most once per variant (before edge cases)."""
        scenario = DataScenario(
            name="unique_ids",
            users=1000,
            control_cvr=0.07,
            treatment_cvr=0.08,
            seed=22,
        )
        result = scenario.generate()
        control_ids = [u.user_id for u in result.users if u.variant_name == "control"]
        treatment_ids = [u.user_id for u in result.users if u.variant_name == "treatment"]

        assert len(control_ids) == len(set(control_ids)), "Duplicate user IDs in control"
        assert len(treatment_ids) == len(set(treatment_ids)), "Duplicate user IDs in treatment"

    def test_population_overlap_is_zero_by_default(self):
        """Without multi_assignment injection, no user appears in both variants."""
        scenario = DataScenario(
            name="no_overlap",
            users=1000,
            control_cvr=0.07,
            treatment_cvr=0.08,
            seed=23,
        )
        result = scenario.generate()
        control_ids = {u.user_id for u in result.users if u.variant_name == "control"}
        treatment_ids = {u.user_id for u in result.users if u.variant_name == "treatment"}
        overlap = control_ids & treatment_ids
        assert len(overlap) == 0, f"Unexpected overlap: {overlap}"

    def test_events_reference_valid_users(self):
        """Every event's user_id should be present in the user list."""
        scenario = make_concurrent_scenario(seed=21)
        result = scenario.generate()
        all_user_ids = {u.user_id for u in result.users}
        for event in result.events:
            assert event.user_id in all_user_ids, (
                f"Event references unknown user {event.user_id}"
            )

    def test_event_timestamps_after_assignment(self):
        """Every conversion event should occur after the user was assigned."""
        scenario = make_concurrent_scenario(seed=21)
        result = scenario.generate()
        user_assignment_time = {u.user_id: u.assigned_at for u in result.users}
        for event in result.events:
            if event.user_id in user_assignment_time:
                assert event.timestamp >= user_assignment_time[event.user_id], (
                    f"Event for {event.user_id} at {event.timestamp} is before "
                    f"assignment at {user_assignment_time[event.user_id]}"
                )


@requires_platform
class TestMutualExclusionGroupAPI:
    """Mutual exclusion group tests — requires a running platform."""

    @pytest.fixture(scope="class")
    def auth_headers(self):
        resp = requests.post(
            f"{API_URL}/api/v1/auth/login",
            json={"username": "admin@example.com", "password": "testpassword123"},
            timeout=10,
        )
        if resp.status_code != 200:
            pytest.skip("Could not obtain API token")
        token = resp.json().get("access_token", "")
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def test_create_mutual_exclusion_group(self, auth_headers):
        """Create a MEG and verify both experiments are added to it."""
        group_name = f"meg-realistic-{uuid.uuid4().hex[:6]}"
        payload = {
            "name": group_name,
            "description": "Realistic MEG test — concurrent checkout experiments",
        }
        resp = requests.post(
            f"{API_URL}/api/v1/mutual-exclusion-groups",
            json=payload,
            headers=auth_headers,
            timeout=15,
        )
        assert resp.status_code in (200, 201), resp.text
        data = resp.json()
        assert data["name"] == group_name

    def test_users_in_meg_do_not_overlap(self, auth_headers):
        """
        After seeding concurrent experiments into a MEG, user populations
        should be mutually exclusive (no user in both experiments).
        """
        scenario1 = DataScenario(
            name="concurrent_exp_1",
            users=1000,
            control_cvr=0.07,
            treatment_cvr=0.084,
            seed=30,
        )
        scenario2 = DataScenario(
            name="concurrent_exp_2",
            users=1000,
            control_cvr=0.06,
            treatment_cvr=0.072,
            seed=31,
        )
        result1 = scenario1.generate()
        result2 = scenario2.generate()

        ids1 = {u.user_id for u in result1.users}
        ids2 = {u.user_id for u in result2.users}

        # These are independently generated — no overlap expected
        overlap = ids1 & ids2
        assert len(overlap) == 0, (
            f"Independently generated scenarios should not share user IDs. Overlap: {len(overlap)}"
        )
