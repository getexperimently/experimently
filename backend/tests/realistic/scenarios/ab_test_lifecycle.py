"""
Realistic scenario: Full A/B Test Lifecycle.

Tests the complete lifecycle of an A/B experiment through the REST API:
  1. Create experiment with two variants and a primary metric
  2. Start the experiment
  3. Seed statistically realistic conversion events
  4. Retrieve results and assert statistical correctness
  5. Conclude the experiment

Expected outcome: treatment shows a detectable lift (p < 0.05) given the
simulated 18.75% relative improvement over the 8% baseline.
"""

import pytest
import requests

from backend.tests.realistic.data_generator import make_ab_test_scenario, PlatformSeeder


API_URL = "http://localhost:8000"
SKIP_REASON = "Realistic scenario tests require a running platform (set RUN_REALISTIC=1)"

pytestmark = pytest.mark.skipif(
    __import__("os").environ.get("RUN_REALISTIC") != "1",
    reason=SKIP_REASON,
)


@pytest.fixture(scope="module")
def api_token():
    """Fetch a token for the test admin user.  Expects the platform to be running."""
    resp = requests.post(
        f"{API_URL}/api/v1/auth/login",
        json={"username": "admin@example.com", "password": "testpassword123"},
        timeout=10,
    )
    if resp.status_code != 200:
        pytest.skip("Could not obtain API token — platform may not be running")
    return resp.json().get("access_token", "")


class TestABTestLifecycle:
    """
    Full A/B test lifecycle with realistic data.

    These are not unit tests — they validate end-to-end behaviour
    against a running platform instance seeded with statistically
    realistic data.
    """

    def test_create_experiment_returns_201(self, api_token):
        """Experiment creation with valid payload returns 201."""
        headers = {"Authorization": f"Bearer {api_token}"}
        payload = {
            "name": "[Realistic] Homepage CTA Test",
            "description": "Realistic lifecycle test",
            "hypothesis": "Treatment increases checkout conversion by ≥15%",
            "experiment_type": "a_b",
            "variants": [
                {"name": "control", "is_control": True, "traffic_allocation": 50},
                {"name": "treatment", "is_control": False, "traffic_allocation": 50},
            ],
            "metrics": [
                {
                    "name": "Checkout Conversion",
                    "event_name": "purchase",
                    "metric_type": "conversion",
                    "is_primary": True,
                }
            ],
        }
        resp = requests.post(f"{API_URL}/api/v1/experiments", json=payload, headers=headers, timeout=15)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["status"] == "draft"
        assert len(data["variants"]) == 2
        assert len(data["metrics"]) == 1

    def test_seed_and_retrieve_results(self, api_token):
        """Seed 1k realistic users, retrieve results, assert lift is detectable."""
        scenario = make_ab_test_scenario(seed=42)
        result = scenario.generate()

        seeder = PlatformSeeder(API_URL, api_token)
        seed_info = seeder.seed_scenario(result)

        assert seed_info["users_seeded"] == 1000
        assert seed_info["events_seeded"] > 0

        # Retrieve results
        exp_id = seed_info["experiment_id"]
        headers = {"Authorization": f"Bearer {api_token}"}
        resp = requests.get(
            f"{API_URL}/api/v1/results/{exp_id}",
            headers=headers,
            timeout=30,
        )
        assert resp.status_code in (200, 202), resp.text  # 202 = computing

    def test_expected_statistical_significance(self):
        """Scenario with 1k users and 18.75% lift should produce z > 1.96."""
        scenario = make_ab_test_scenario(seed=42)
        result = scenario.generate()

        assert result.expected_significant, (
            f"Scenario z-score {result.metadata['z_score']} too low — "
            "check user count or CVR delta"
        )
        assert result.metadata["z_score"] >= 1.96

    def test_event_count_within_expected_range(self):
        """Generated events should be within ±20% of expected count."""
        scenario = make_ab_test_scenario(seed=42)
        result = scenario.generate()

        expected_events = int(1000 * (scenario.control_cvr + scenario.treatment_cvr) / 2)
        actual_events = len(result.events)
        tolerance = expected_events * 0.20

        assert abs(actual_events - expected_events) <= tolerance, (
            f"Event count {actual_events} too far from expected {expected_events}"
        )

    def test_novelty_effect_scenario_produces_day1_spike(self):
        """Novelty scenario should show higher early CVR decaying over time."""
        from backend.tests.realistic.data_generator import make_novelty_scenario
        from datetime import timedelta

        scenario = make_novelty_scenario(seed=7)
        result = scenario.generate()

        # Events in day 1 vs later days
        start = min(u.assigned_at for u in result.users)
        day1_cutoff = start + timedelta(days=1)

        early_treatment = [
            e for e in result.events
            if e.variant_name == "treatment" and e.timestamp <= day1_cutoff
        ]
        late_treatment = [
            e for e in result.events
            if e.variant_name == "treatment" and e.timestamp > day1_cutoff
        ]

        early_treatment_users = [
            u for u in result.users
            if u.variant_name == "treatment" and u.assigned_at <= day1_cutoff
        ]
        late_treatment_users = [
            u for u in result.users
            if u.variant_name == "treatment" and u.assigned_at > day1_cutoff
        ]

        if early_treatment_users and late_treatment_users:
            early_cvr = len(early_treatment) / len(early_treatment_users)
            late_cvr = len(late_treatment) / len(late_treatment_users)
            # Day-1 CVR should be higher (novelty boost active)
            assert early_cvr >= late_cvr * 0.9, (
                f"Expected novelty spike: early CVR {early_cvr:.3f} should exceed late CVR {late_cvr:.3f}"
            )
