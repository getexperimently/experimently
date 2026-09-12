"""
Integration tests for EP-056 Power Calculator API.

Tests the full HTTP request/response cycle for:
  POST /api/v1/power/sample-size  — compute required sample size
  POST /api/v1/power/mde          — compute MDE for a fixed sample
  POST /api/v1/power/runtime      — estimate experiment runtime
  GET  /api/v1/power/curve        — power curve
  POST /api/v1/power/plan         — AI planning advice (Claude mocked)

Validation tests (422):
  - baseline_rate=0 → 422
  - mde=0 → 422
  - mde >= 1.0 → 422
  - alpha outside (0, 0.5) → 422
  - power outside (0, 1) → 422

Authentication:
  - No auth required for any power calculator endpoints

Note: Uses a local 'client' fixture that does NOT require a database
connection, since the power calculator endpoints perform pure CPU math
with no DB access.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app

# ---------------------------------------------------------------------------
# Local client fixture — no DB required for pure-math endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """
    TestClient for the power calculator endpoints.

    These endpoints have no auth or DB dependencies, so we can use the
    FastAPI app directly without any dependency overrides.
    """
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ---------------------------------------------------------------------------
# Sample-size payload helpers
# ---------------------------------------------------------------------------


def _sample_size_payload(**overrides) -> dict:
    base = {
        "baseline_rate": 0.10,
        "minimum_detectable_effect": 0.10,
        "alpha": 0.05,
        "power": 0.80,
        "n_variants": 2,
        "two_tailed": True,
        "metric_type": "proportion",
    }
    base.update(overrides)
    return base


def _mde_payload(**overrides) -> dict:
    base = {
        "sample_size_per_variant": 5000,
        "baseline_rate": 0.10,
        "alpha": 0.05,
        "power": 0.80,
        "n_variants": 2,
        "two_tailed": True,
    }
    base.update(overrides)
    return base


def _runtime_payload(**overrides) -> dict:
    base = {
        "required_sample_size": 5000,
        "daily_traffic": 1000,
        "traffic_allocation": 0.5,
        "n_variants": 2,
    }
    base.update(overrides)
    return base


def _plan_payload(**overrides) -> dict:
    base = {
        "experiment_name": "Test Experiment",
        "metric_description": "conversion rate from homepage to checkout",
        "baseline_rate": 0.10,
        "mde": 0.10,
        "runtime_days": 30.0,
        "business_context": "Q4 launch initiative",
    }
    base.update(overrides)
    return base


# ===========================================================================
# TestSampleSizeEndpoint
# ===========================================================================


class TestSampleSizeEndpoint:
    """POST /api/v1/power/sample-size"""

    def test_returns_200(self, client: TestClient):
        resp = client.post(
            "/api/v1/power/sample-size",
            json=_sample_size_payload(),
        )
        assert resp.status_code == 200, resp.text

    def test_response_has_per_variant(self, client: TestClient):
        resp = client.post("/api/v1/power/sample-size", json=_sample_size_payload())
        assert "per_variant" in resp.json()

    def test_response_has_total(self, client: TestClient):
        resp = client.post("/api/v1/power/sample-size", json=_sample_size_payload())
        assert "total" in resp.json()

    def test_total_equals_per_variant_times_n_variants(self, client: TestClient):
        resp = client.post("/api/v1/power/sample-size", json=_sample_size_payload())
        data = resp.json()
        assert data["total"] == data["per_variant"] * data["n_variants"]

    def test_response_has_mde_absolute(self, client: TestClient):
        resp = client.post("/api/v1/power/sample-size", json=_sample_size_payload())
        assert "mde_absolute" in resp.json()

    def test_response_has_mde_relative(self, client: TestClient):
        resp = client.post("/api/v1/power/sample-size", json=_sample_size_payload())
        assert "mde_relative" in resp.json()

    def test_response_has_confidence_level(self, client: TestClient):
        resp = client.post("/api/v1/power/sample-size", json=_sample_size_payload())
        data = resp.json()
        assert "confidence_level" in data
        assert abs(data["confidence_level"] - 0.95) < 1e-6

    def test_runtime_days_present_when_traffic_provided(self, client: TestClient):
        payload = _sample_size_payload(daily_traffic=5000, traffic_allocation=1.0)
        resp = client.post("/api/v1/power/sample-size", json=payload)
        data = resp.json()
        assert data["runtime_days"] is not None
        assert data["runtime_days"] > 0

    def test_runtime_days_null_when_no_traffic(self, client: TestClient):
        resp = client.post("/api/v1/power/sample-size", json=_sample_size_payload())
        data = resp.json()
        assert data["runtime_days"] is None

    def test_per_variant_is_positive_integer(self, client: TestClient):
        resp = client.post("/api/v1/power/sample-size", json=_sample_size_payload())
        data = resp.json()
        assert isinstance(data["per_variant"], int)
        assert data["per_variant"] > 0

    def test_three_variants_larger_than_two(self, client: TestClient):
        n_2 = client.post(
            "/api/v1/power/sample-size",
            json=_sample_size_payload(n_variants=2),
        ).json()["per_variant"]
        n_3 = client.post(
            "/api/v1/power/sample-size",
            json=_sample_size_payload(n_variants=3),
        ).json()["per_variant"]
        assert n_3 > n_2

    def test_metric_type_mean_requires_baseline_std(self, client: TestClient):
        payload = _sample_size_payload(metric_type="mean")
        # Without baseline_std → validation error
        resp = client.post("/api/v1/power/sample-size", json=payload)
        assert resp.status_code == 422

    def test_metric_type_mean_with_baseline_std_succeeds(self, client: TestClient):
        payload = _sample_size_payload(
            metric_type="mean",
            baseline_std=0.15,
            baseline_rate=0.50,
        )
        resp = client.post("/api/v1/power/sample-size", json=payload)
        assert resp.status_code == 200

    # Validation errors -------------------------------------------------

    def test_baseline_rate_zero_returns_422(self, client: TestClient):
        payload = _sample_size_payload(baseline_rate=0.0)
        resp = client.post("/api/v1/power/sample-size", json=payload)
        assert resp.status_code == 422

    def test_baseline_rate_one_returns_422(self, client: TestClient):
        payload = _sample_size_payload(baseline_rate=1.0)
        resp = client.post("/api/v1/power/sample-size", json=payload)
        assert resp.status_code == 422

    def test_mde_zero_returns_422(self, client: TestClient):
        payload = _sample_size_payload(minimum_detectable_effect=0.0)
        resp = client.post("/api/v1/power/sample-size", json=payload)
        assert resp.status_code == 422

    def test_mde_one_returns_422(self, client: TestClient):
        payload = _sample_size_payload(minimum_detectable_effect=1.0)
        resp = client.post("/api/v1/power/sample-size", json=payload)
        assert resp.status_code == 422

    def test_mde_above_one_returns_422(self, client: TestClient):
        payload = _sample_size_payload(minimum_detectable_effect=1.5)
        resp = client.post("/api/v1/power/sample-size", json=payload)
        assert resp.status_code == 422

    def test_alpha_zero_returns_422(self, client: TestClient):
        payload = _sample_size_payload(alpha=0.0)
        resp = client.post("/api/v1/power/sample-size", json=payload)
        assert resp.status_code == 422

    def test_power_zero_returns_422(self, client: TestClient):
        payload = _sample_size_payload(power=0.0)
        resp = client.post("/api/v1/power/sample-size", json=payload)
        assert resp.status_code == 422

    def test_power_one_returns_422(self, client: TestClient):
        payload = _sample_size_payload(power=1.0)
        resp = client.post("/api/v1/power/sample-size", json=payload)
        assert resp.status_code == 422


# ===========================================================================
# TestMDEEndpoint
# ===========================================================================


class TestMDEEndpoint:
    """POST /api/v1/power/mde"""

    def test_returns_200(self, client: TestClient):
        resp = client.post("/api/v1/power/mde", json=_mde_payload())
        assert resp.status_code == 200, resp.text

    def test_response_has_mde_absolute(self, client: TestClient):
        resp = client.post("/api/v1/power/mde", json=_mde_payload())
        assert "mde_absolute" in resp.json()

    def test_response_has_mde_relative(self, client: TestClient):
        resp = client.post("/api/v1/power/mde", json=_mde_payload())
        assert "mde_relative" in resp.json()

    def test_mde_relative_is_positive(self, client: TestClient):
        resp = client.post("/api/v1/power/mde", json=_mde_payload())
        data = resp.json()
        assert data["mde_relative"] > 0

    def test_total_sample_equals_per_variant_times_n(self, client: TestClient):
        resp = client.post("/api/v1/power/mde", json=_mde_payload())
        data = resp.json()
        assert data["total_sample"] == data["per_variant_sample"] * data["n_variants"]

    def test_larger_sample_gives_smaller_mde(self, client: TestClient):
        mde_small = client.post(
            "/api/v1/power/mde",
            json=_mde_payload(sample_size_per_variant=1000),
        ).json()["mde_relative"]

        mde_large = client.post(
            "/api/v1/power/mde",
            json=_mde_payload(sample_size_per_variant=100000),
        ).json()["mde_relative"]

        assert mde_large < mde_small

    def test_baseline_zero_returns_422(self, client: TestClient):
        resp = client.post("/api/v1/power/mde", json=_mde_payload(baseline_rate=0.0))
        assert resp.status_code == 422


# ===========================================================================
# TestRuntimeEndpoint
# ===========================================================================


class TestRuntimeEndpoint:
    """POST /api/v1/power/runtime"""

    def test_returns_200(self, client: TestClient):
        resp = client.post("/api/v1/power/runtime", json=_runtime_payload())
        assert resp.status_code == 200, resp.text

    def test_response_has_days_to_significance(self, client: TestClient):
        resp = client.post("/api/v1/power/runtime", json=_runtime_payload())
        assert "days_to_significance" in resp.json()

    def test_response_has_weeks_to_significance(self, client: TestClient):
        resp = client.post("/api/v1/power/runtime", json=_runtime_payload())
        assert "weeks_to_significance" in resp.json()

    def test_response_has_confidence_interval(self, client: TestClient):
        resp = client.post("/api/v1/power/runtime", json=_runtime_payload())
        data = resp.json()
        assert "confidence_interval_days" in data
        assert len(data["confidence_interval_days"]) == 2

    def test_weeks_is_days_over_seven(self, client: TestClient):
        payload = _runtime_payload(
            required_sample_size=7000, daily_traffic=1000, traffic_allocation=1.0
        )
        resp = client.post("/api/v1/power/runtime", json=payload)
        data = resp.json()
        assert (
            abs(data["weeks_to_significance"] - data["days_to_significance"] / 7) < 0.01
        )

    def test_higher_traffic_fewer_days(self, client: TestClient):
        days_low = client.post(
            "/api/v1/power/runtime",
            json=_runtime_payload(daily_traffic=100),
        ).json()["days_to_significance"]

        days_high = client.post(
            "/api/v1/power/runtime",
            json=_runtime_payload(daily_traffic=10000),
        ).json()["days_to_significance"]

        assert days_high < days_low

    def test_daily_traffic_per_variant_correct(self, client: TestClient):
        # 1000 * 0.5 / 2 = 250
        resp = client.post(
            "/api/v1/power/runtime",
            json=_runtime_payload(
                daily_traffic=1000, traffic_allocation=0.5, n_variants=2
            ),
        )
        data = resp.json()
        assert data["daily_traffic_per_variant"] == 250

    def test_zero_daily_traffic_returns_422(self, client: TestClient):
        resp = client.post(
            "/api/v1/power/runtime", json=_runtime_payload(daily_traffic=0)
        )
        assert resp.status_code == 422


# ===========================================================================
# TestPowerCurveEndpoint
# ===========================================================================


class TestPowerCurveEndpoint:
    """GET /api/v1/power/curve"""

    def test_returns_200(self, client: TestClient):
        resp = client.get("/api/v1/power/curve?baseline=0.10")
        assert resp.status_code == 200, resp.text

    def test_response_has_points(self, client: TestClient):
        resp = client.get("/api/v1/power/curve?baseline=0.10")
        data = resp.json()
        assert "points" in data
        assert isinstance(data["points"], list)

    def test_points_non_empty(self, client: TestClient):
        resp = client.get("/api/v1/power/curve?baseline=0.10")
        data = resp.json()
        assert len(data["points"]) > 0

    def test_each_point_has_required_fields(self, client: TestClient):
        resp = client.get("/api/v1/power/curve?baseline=0.10")
        data = resp.json()
        for point in data["points"]:
            assert "effect_size_relative" in point
            assert "sample_size_per_variant" in point
            assert "is_current_target" in point

    def test_sample_sizes_positive(self, client: TestClient):
        resp = client.get("/api/v1/power/curve?baseline=0.10")
        data = resp.json()
        for point in data["points"]:
            assert point["sample_size_per_variant"] > 0

    def test_mde_target_marks_closest_point(self, client: TestClient):
        resp = client.get("/api/v1/power/curve?baseline=0.10&mde=0.10")
        data = resp.json()
        targets = [p for p in data["points"] if p["is_current_target"]]
        assert len(targets) <= 1

    def test_without_mde_no_target_marked(self, client: TestClient):
        resp = client.get("/api/v1/power/curve?baseline=0.10")
        data = resp.json()
        targets = [p for p in data["points"] if p["is_current_target"]]
        assert len(targets) == 0

    def test_baseline_zero_returns_422(self, client: TestClient):
        resp = client.get("/api/v1/power/curve?baseline=0.0")
        assert resp.status_code == 422

    def test_baseline_one_returns_422(self, client: TestClient):
        resp = client.get("/api/v1/power/curve?baseline=1.0")
        assert resp.status_code == 422

    def test_response_includes_metadata(self, client: TestClient):
        resp = client.get("/api/v1/power/curve?baseline=0.10&alpha=0.05&power=0.80")
        data = resp.json()
        assert "baseline_rate" in data
        assert "alpha" in data
        assert "power_target" in data


# ===========================================================================
# TestPlanEndpoint
# ===========================================================================


class TestPlanEndpoint:
    """POST /api/v1/power/plan (AI planning advice, Claude mocked)."""

    @pytest.fixture(autouse=True)
    def mock_anthropic_unavailable(self, monkeypatch):
        """Ensure no real Anthropic API calls are made in integration tests."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def test_returns_200(self, client: TestClient):
        resp = client.post("/api/v1/power/plan", json=_plan_payload())
        assert resp.status_code == 200, resp.text

    def test_response_has_advice(self, client: TestClient):
        resp = client.post("/api/v1/power/plan", json=_plan_payload())
        data = resp.json()
        assert "advice" in data
        assert len(data["advice"]) > 0

    def test_response_has_generated_by(self, client: TestClient):
        resp = client.post("/api/v1/power/plan", json=_plan_payload())
        data = resp.json()
        assert "generated_by" in data
        assert data["generated_by"] in ("ai", "template")

    def test_generated_by_template_when_no_api_key(self, client: TestClient):
        resp = client.post("/api/v1/power/plan", json=_plan_payload())
        data = resp.json()
        assert data["generated_by"] == "template"

    def test_response_has_experiment_name(self, client: TestClient):
        resp = client.post(
            "/api/v1/power/plan",
            json=_plan_payload(experiment_name="My Power Test"),
        )
        data = resp.json()
        assert data["experiment_name"] == "My Power Test"

    def test_response_has_baseline_rate(self, client: TestClient):
        resp = client.post(
            "/api/v1/power/plan",
            json=_plan_payload(baseline_rate=0.25),
        )
        data = resp.json()
        assert abs(data["baseline_rate"] - 0.25) < 1e-6

    def test_response_has_mde(self, client: TestClient):
        resp = client.post(
            "/api/v1/power/plan",
            json=_plan_payload(mde=0.15),
        )
        data = resp.json()
        assert abs(data["mde"] - 0.15) < 1e-6

    def test_response_has_runtime_days(self, client: TestClient):
        resp = client.post(
            "/api/v1/power/plan",
            json=_plan_payload(runtime_days=45.0),
        )
        data = resp.json()
        assert abs(data["runtime_days"] - 45.0) < 0.01

    def test_experiment_name_too_short_returns_422(self, client: TestClient):
        resp = client.post(
            "/api/v1/power/plan",
            json=_plan_payload(experiment_name="AB"),  # < 3 chars
        )
        assert resp.status_code == 422

    def test_baseline_rate_zero_returns_422(self, client: TestClient):
        resp = client.post(
            "/api/v1/power/plan",
            json=_plan_payload(baseline_rate=0.0),
        )
        assert resp.status_code == 422

    def test_mde_zero_returns_422(self, client: TestClient):
        resp = client.post(
            "/api/v1/power/plan",
            json=_plan_payload(mde=0.0),
        )
        assert resp.status_code == 422

    def test_mde_one_returns_422(self, client: TestClient):
        resp = client.post(
            "/api/v1/power/plan",
            json=_plan_payload(mde=1.0),
        )
        assert resp.status_code == 422

    def test_business_context_optional(self, client: TestClient):
        payload = _plan_payload()
        del payload["business_context"]
        resp = client.post("/api/v1/power/plan", json=payload)
        assert resp.status_code == 200
