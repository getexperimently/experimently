"""
Integration tests for the EP-016 Analytics Results Engine.

These service-level integration tests verify that the statistical pipeline
works end-to-end: test selection, test execution, effect size computation,
and confidence interval construction all work together consistently.

Unlike unit tests (which test methods in isolation), these tests wire
multiple AnalysisService methods together to confirm the pipeline produces
internally consistent results under realistic conditions.

No real PostgreSQL connection is required — the DB session is mocked with
MagicMock so the statistical logic can be exercised in isolation.

Endpoint cache-behavior tests in TestResultsEndpointCacheBehavior exercise
the FastAPI layer using TestClient with mocked dependencies.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.api.deps import get_db, get_current_user
from backend.app.models.user import User
from backend.app.services.analysis_service import AnalysisService


# ---------------------------------------------------------------------------
# Shared UUIDs
# ---------------------------------------------------------------------------

EXPERIMENT_UUID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_UUID = uuid.UUID("12345678-1234-5678-1234-567812345678")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service() -> AnalysisService:
    """Return an AnalysisService backed by a MagicMock DB session."""
    mock_db = MagicMock()
    return AnalysisService(db=mock_db)


def _make_mock_user(is_superuser: bool = True) -> MagicMock:
    """Return a mock User suitable for dependency injection."""
    user = MagicMock(spec=User)
    user.id = USER_UUID
    user.email = "test@example.com"
    user.is_active = True
    user.is_superuser = is_superuser
    user.role = "ADMIN" if is_superuser else "VIEWER"
    return user


# ---------------------------------------------------------------------------
# Test Class 1 — AnalysisService statistical pipeline
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAnalysisServiceIntegration:
    """
    End-to-end tests for the AnalysisService statistical pipeline.

    Each test exercises multiple service methods together and asserts that the
    results are internally consistent (e.g. positive Cohen's h when treatment
    outperforms control, Wilson CI that stays within [0, 1], etc.).
    """

    # ------------------------------------------------------------------
    # Test 1: Full conversion metric pipeline
    # ------------------------------------------------------------------

    def test_full_conversion_metric_pipeline(self):
        """
        Verify the complete conversion-metric analysis pipeline is consistent.

        Set-up:
          - control:   n=1000, conversions=100 (p=0.10)
          - treatment: n=1000, conversions=120 (p=0.12)

        The pipeline should:
          1. Select the z_test for a large-sample conversion metric.
          2. Produce a p-value in the range (0.05, 0.25) — directional but not
             strongly significant given the modest sample.
          3. Compute a positive Cohen's h (treatment > control) with label in
             ["negligible", "small"].
          4. Produce a Wilson CI for the control rate that contains 0.10 and
             stays within (0, 1).
        """
        service = _make_service()

        control_n = 1000
        control_conv = 100
        treatment_n = 1000
        treatment_conv = 120

        p_control = control_conv / control_n    # 0.10
        p_treatment = treatment_conv / treatment_n  # 0.12

        # Step 1 — test selection
        test_name = service.select_statistical_test("conversion", control_n, treatment_n)
        assert test_name == "z_test", (
            f"Expected 'z_test' for large-sample conversion metric, got {test_name!r}"
        )

        # Step 2 — z-test for proportions
        p_value = service.z_test_proportions(
            control_conv, control_n, treatment_conv, treatment_n
        )
        assert 0.0 <= p_value <= 1.0, f"p-value {p_value} is out of [0, 1]"
        # 10% → 12% with n=1000 is a modest signal; expect p in (0.05, 0.25)
        assert 0.05 < p_value < 0.25, (
            f"Expected p-value in (0.05, 0.25) for a 2pp lift with n=1000, got {p_value:.4f}"
        )

        # Step 3 — Cohen's h effect size
        h, label = service.cohens_h(p_control, p_treatment)
        assert h > 0, (
            f"Cohen's h should be positive when treatment > control, got h={h:.4f}"
        )
        assert label in ("negligible", "small"), (
            f"Expected 'negligible' or 'small' for a 2pp lift, got {label!r}"
        )

        # Step 4 — Wilson confidence interval for control rate
        lower, upper = service.wilson_confidence_interval(control_conv, control_n, 0.95)
        assert 0.0 < lower, f"Wilson CI lower {lower:.4f} should be > 0"
        assert lower < p_control < upper, (
            f"True rate {p_control} should lie inside CI ({lower:.4f}, {upper:.4f})"
        )
        assert upper < 1.0, f"Wilson CI upper {upper:.4f} should be < 1"

        # Internal consistency: positive h is consistent with treatment > control
        assert (h > 0) == (p_treatment > p_control), (
            "Sign of Cohen's h must match direction of treatment vs. control"
        )

    # ------------------------------------------------------------------
    # Test 2: Full continuous metric pipeline
    # ------------------------------------------------------------------

    def test_full_continuous_metric_pipeline(self):
        """
        Verify the continuous-metric analysis pipeline is consistent.

        Use non-constant data with a known mean difference so that Welch's
        t-test produces a valid (non-NaN) p-value.

        Set-up:
          - control:   [3.0, 3.5, 4.0] repeated 500/3 times  (mean ≈ 3.5)
          - treatment: [3.8, 4.3, 4.8] repeated 500/3 times  (mean ≈ 4.3, Δ = 0.8)

        The pipeline should:
          1. Select 'welch_t_test' for a non-conversion metric.
          2. Produce p < 0.001 (means differ by 0.8, small within-group variance).
          3. Produce Cohen's d > 0 with label == "large" (d >> 0.8).
        """
        service = _make_service()

        # Non-constant data: cycle [3.0, 3.5, 4.0] and [3.8, 4.3, 4.8]
        control = [3.0 + (i % 3) * 0.5 for i in range(500)]    # mean = 3.5
        treatment = [3.8 + (i % 3) * 0.5 for i in range(500)]  # mean = 4.3

        # Step 1 — test selection for a revenue metric
        test_name = service.select_statistical_test("revenue", len(control), len(treatment))
        assert test_name == "welch_t_test", (
            f"Expected 'welch_t_test' for revenue metric, got {test_name!r}"
        )

        # Step 2 — Welch's t-test
        p_value = service.welch_t_test(control, treatment)
        assert not (p_value != p_value), "p-value must not be NaN"  # isnan check
        assert p_value < 0.001, (
            f"Expected p < 0.001 for a large mean difference with small variance, "
            f"got p={p_value:.6f}"
        )

        # Step 3 — Cohen's d effect size
        d, label = service.cohens_d(control, treatment)
        assert d > 0, (
            f"Cohen's d should be positive when treatment mean > control mean, got d={d:.4f}"
        )
        # With mean diff = 0.8 and small pooled std (≈ 0.408), d ≈ 1.96 → "large"
        assert label == "large", (
            f"Expected 'large' effect for a 0.8-unit mean difference with std≈0.41, "
            f"got {label!r} (d={d:.4f})"
        )

    # ------------------------------------------------------------------
    # Test 3: Bonferroni correction raises the significance threshold
    # ------------------------------------------------------------------

    def test_bonferroni_raises_significance_threshold(self):
        """
        Bonferroni correction multiplies each p-value by the number of tests.

        A borderline p=0.03 that would be significant at alpha=0.05 without
        correction becomes 0.09 after Bonferroni with 3 metrics — no longer
        significant.  A strongly significant p=0.01 stays below 0.05.
        """
        service = _make_service()

        alpha = 0.05
        n_tests = 3

        # Borderline p-value: significant before, not after correction
        raw_p_borderline = 0.03
        corrected_borderline = service.apply_bonferroni_correction(raw_p_borderline, n_tests)
        assert abs(corrected_borderline - 0.09) < 1e-9, (
            f"Expected Bonferroni-corrected p = 0.09, got {corrected_borderline}"
        )
        assert corrected_borderline > alpha, (
            f"Corrected p={corrected_borderline} should be > alpha={alpha} (not significant)"
        )

        # Strongly significant p-value: still significant after correction
        raw_p_strong = 0.01
        corrected_strong = service.apply_bonferroni_correction(raw_p_strong, n_tests)
        assert abs(corrected_strong - 0.03) < 1e-9, (
            f"Expected Bonferroni-corrected p = 0.03, got {corrected_strong}"
        )
        assert corrected_strong < alpha, (
            f"Corrected p={corrected_strong} should be < alpha={alpha} (still significant)"
        )

        # Edge case: Bonferroni cannot push p above 1.0
        p_near_one = service.apply_bonferroni_correction(0.9, 3)
        assert p_near_one <= 1.0, f"Bonferroni result must be clamped to 1.0, got {p_near_one}"

    # ------------------------------------------------------------------
    # Test 4: Sample-size calculator consistency
    # ------------------------------------------------------------------

    def test_sample_size_calculator_consistency(self):
        """
        Verify that sample-size estimates respect well-known monotone relationships:

          - Higher power target requires a larger sample (n_high_power > n_low).
          - Larger MDE requires a smaller sample (n_large_mde < n_low).
          - The baseline result is at least 100 (sanity lower bound).

        Parameters used:
          baseline_rate=0.10, mde=0.02, alpha=0.05, power=0.80 (reference)
        """
        service = _make_service()

        # Reference configuration
        n_low = service.calculate_required_sample_size(
            baseline_rate=0.10,
            minimum_detectable_effect=0.02,
            alpha=0.05,
            power=0.80,
        )

        # Higher power requires more data
        n_high_power = service.calculate_required_sample_size(
            baseline_rate=0.10,
            minimum_detectable_effect=0.02,
            alpha=0.05,
            power=0.90,
        )

        # Larger MDE → easier to detect → fewer observations needed
        n_large_mde = service.calculate_required_sample_size(
            baseline_rate=0.10,
            minimum_detectable_effect=0.04,  # 2× the reference MDE
            alpha=0.05,
            power=0.80,
        )

        assert n_low >= 100, (
            f"Required sample size {n_low} should be at least 100 for a reasonable config"
        )
        assert n_high_power > n_low, (
            f"Higher power target (0.90) must require more observations than (0.80): "
            f"{n_high_power} vs {n_low}"
        )
        assert n_large_mde < n_low, (
            f"Larger MDE (0.04) must require fewer observations than (0.02): "
            f"{n_large_mde} vs {n_low}"
        )

        # Return values must be positive integers
        for n in (n_low, n_high_power, n_large_mde):
            assert isinstance(n, int), f"Sample size must be an int, got {type(n)}"
            assert n >= 1, f"Sample size must be >= 1, got {n}"

    # ------------------------------------------------------------------
    # Test 5: Wilson CI vs. normal approximation for extreme rates
    # ------------------------------------------------------------------

    def test_wilson_ci_vs_normal_approximation_for_extreme_rates(self):
        """
        For extreme proportions (p ≈ 0.02, n=50) the normal approximation CI
        extends below zero, which is nonsensical for a probability.

        The Wilson score interval is bounded by construction and must satisfy:
          - lower > 0   (does not go negative)
          - upper < 1   (does not exceed one)
          - lower < p_hat < upper  (observed rate inside the interval)

        The corresponding normal-approximation interval would give:
          p_hat ± 1.96 * sqrt(p*(1-p)/n) = 0.02 ± 0.039 → lower ≈ -0.019
        which is invalid.
        """
        service = _make_service()

        successes = 1
        total = 50
        p_hat = successes / total  # 0.02

        lower, upper = service.wilson_confidence_interval(successes, total, 0.95)

        assert lower > 0.0, (
            f"Wilson CI lower bound {lower:.6f} must be > 0 for extreme proportions"
        )
        assert upper < 1.0, (
            f"Wilson CI upper bound {upper:.6f} must be < 1"
        )
        assert lower < p_hat < upper, (
            f"Observed rate {p_hat} must lie inside Wilson CI ({lower:.6f}, {upper:.6f})"
        )

        # Demonstrate normal approximation failure for contrast
        import math
        z = 1.96
        se = math.sqrt(p_hat * (1.0 - p_hat) / total)
        normal_lower = p_hat - z * se
        assert normal_lower < 0.0, (
            "Normal approximation lower bound should be < 0 (demonstrating its limitation)"
        )

        # Wilson is strictly tighter on the wrong side
        assert lower > normal_lower, (
            f"Wilson lower {lower:.4f} should be above normal-approx lower {normal_lower:.4f}"
        )

    # ------------------------------------------------------------------
    # Test 6: Effect-size label boundaries
    # ------------------------------------------------------------------

    def test_effect_size_label_boundaries(self):
        """
        Verify the EP-016 Cohen's h thresholds are applied consistently:
          - |h| < 0.2  → "negligible"
          - 0.2 <= |h| < 0.5 → "small"
          - 0.5 <= |h| < 0.8 → "medium"
          - |h| >= 0.8 → "large"

        Test cases:
          - cohens_h(0.10, 0.11) — tiny lift (h ≈ 0.033) → "negligible"
          - cohens_h(0.10, 0.20) — moderate lift (h ≈ 0.20) → "small" or "negligible"
          - cohens_h(0.10, 0.50) — large lift (h ≈ 0.927) → "large"
        """
        service = _make_service()

        # Tiny change: 10% → 11%, h ≈ 0.033
        h_tiny, label_tiny = service.cohens_h(0.10, 0.11)
        assert label_tiny == "negligible", (
            f"h≈0.033 (10%→11%) should be 'negligible', got {label_tiny!r}"
        )
        assert h_tiny > 0, "h should be positive when p2 > p1"

        # Moderate change: 10% → 20%, h ≈ 0.20 (right on the boundary)
        h_moderate, label_moderate = service.cohens_h(0.10, 0.20)
        assert label_moderate in ("negligible", "small"), (
            f"h≈0.20 (10%→20%) should be 'small' or 'negligible', got {label_moderate!r}"
        )
        assert h_moderate > 0, "h should be positive when p2 > p1"

        # Large change: 10% → 50%, h ≈ 0.927 — clearly large
        h_large, label_large = service.cohens_h(0.10, 0.50)
        assert label_large == "large", (
            f"h≈0.927 (10%→50%) should be 'large', got {label_large!r} (h={h_large:.3f})"
        )
        assert h_large > 0.8, (
            f"Cohen's h for 10%→50% should be > 0.8, got {h_large:.4f}"
        )

        # Symmetry: reversing p1 and p2 gives the same magnitude but opposite sign
        h_rev, _ = service.cohens_h(0.50, 0.10)
        import math
        assert math.isclose(abs(h_large), abs(h_rev), rel_tol=1e-9), (
            "cohens_h should produce the same magnitude regardless of direction"
        )
        assert h_rev < 0, "h should be negative when p2 < p1"


# ---------------------------------------------------------------------------
# Test Class 2 — Results endpoint cache behaviour
# ---------------------------------------------------------------------------

# Minimal valid result dict that the endpoint can serialise to ExperimentResultsResponse.
# The summary and metrics lists are empty/minimal so we avoid full schema validation noise
# — the tests here focus on whether the service was called, not on the response shape.
_VALID_RESULT_DICT: Dict[str, Any] = {
    "experiment_id": str(EXPERIMENT_UUID),
    "experiment_name": "Cache Integration Test Experiment",
    "status": "active",
    "start_date": None,
    "end_date": None,
    "confidence_level": 0.95,
    "correction_method": "none",
    "computed_at": datetime.now(timezone.utc).isoformat(),
    "sample_size_adequate": False,
    "metrics": [],
    "summary": {
        "total_users": 0,
        "total_events": 0,
        "total_conversions": 0,
        "duration_days": None,
        "has_winner": False,
        "winning_variant_id": None,
        "recommendation": "CONTINUE_TESTING",
        "recommendation_reason": "Insufficient data collected so far.",
    },
}


@pytest.mark.integration
class TestResultsEndpointCacheBehavior:
    """
    Integration tests for the cache-read / cache-write logic in
    GET /api/v1/results/{experiment_id}.

    Each test overrides the get_db and get_current_user FastAPI dependencies
    so no real database or Cognito connection is needed.  The CacheService is
    patched to control whether a cache hit or miss is simulated.
    """

    # ------------------------------------------------------------------
    # Fixtures (defined as methods for use inside the class)
    # ------------------------------------------------------------------

    @pytest.fixture(autouse=True)
    def setup_app_overrides(self):
        """
        Override FastAPI dependencies for the duration of each test, then
        clean up so subsequent tests start with a clean slate.
        """
        mock_db = MagicMock()
        mock_user = _make_mock_user(is_superuser=True)

        def override_get_db():
            try:
                yield mock_db
            finally:
                pass

        async def override_get_current_user():
            return mock_user

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = override_get_current_user

        yield mock_db, mock_user

        app.dependency_overrides = {}

    @pytest.fixture
    def client(self, setup_app_overrides):
        """Return a TestClient with the dependency overrides active."""
        with TestClient(app) as tc:
            yield tc

    # ------------------------------------------------------------------
    # Test 7: Cache miss triggers service call
    # ------------------------------------------------------------------

    def test_cache_miss_triggers_service_call(self, client: TestClient):
        """
        When the cache returns None (cache miss), AnalysisService must be called.

        The endpoint falls through to the service layer and returns HTTP 200.
        """
        mock_cache = MagicMock()
        mock_cache.get.return_value = None  # cache miss

        with patch(
            "backend.app.api.v1.endpoints.results._get_cache_service",
            return_value=mock_cache,
        ):
            with patch.object(
                AnalysisService,
                "get_experiment_results",
                return_value=_VALID_RESULT_DICT,
            ) as mock_get_results:
                response = client.get(
                    f"/api/v1/results/{EXPERIMENT_UUID}",
                    params={"use_cache": "true"},
                )

        assert response.status_code == 200, (
            f"Expected 200 on cache miss, got {response.status_code}: {response.text}"
        )
        mock_get_results.assert_called_once(), (
            "AnalysisService.get_experiment_results must be called on a cache miss"
        )

    # ------------------------------------------------------------------
    # Test 8: Cache hit skips service call
    # ------------------------------------------------------------------

    def test_cache_hit_skips_service_call(self, client: TestClient):
        """
        When the cache returns a valid JSON string, the endpoint must return
        that cached payload without calling AnalysisService.

        This is the primary performance optimisation: cached results avoid
        an expensive DB round-trip.
        """
        # Build a minimal serialisable payload that ExperimentResultsResponse accepts.
        from backend.app.schemas.results import (
            ExperimentResultsResponse,
            ExperimentSummary,
            RecommendationAction,
            CorrectionMethod,
        )

        cached_response = ExperimentResultsResponse(
            experiment_id=EXPERIMENT_UUID,
            experiment_name="Cached Experiment",
            status="active",
            start_date=None,
            end_date=None,
            confidence_level=0.95,
            correction_method=CorrectionMethod.NONE,
            sample_size_adequate=False,
            computed_at=datetime.now(timezone.utc),
            summary=ExperimentSummary(
                total_users=0,
                total_events=0,
                total_conversions=None,
                duration_days=None,
                has_winner=False,
                winning_variant_id=None,
                recommendation=RecommendationAction.CONTINUE_TESTING,
                recommendation_reason="From cache.",
            ),
            metrics=[],
        )
        cached_json = cached_response.model_dump_json()

        mock_cache = MagicMock()
        mock_cache.get.return_value = cached_json  # cache hit

        with patch(
            "backend.app.api.v1.endpoints.results._get_cache_service",
            return_value=mock_cache,
        ):
            with patch.object(
                AnalysisService,
                "get_experiment_results",
            ) as mock_get_results:
                response = client.get(
                    f"/api/v1/results/{EXPERIMENT_UUID}",
                    params={"use_cache": "true"},
                )

        assert response.status_code == 200, (
            f"Expected 200 on cache hit, got {response.status_code}: {response.text}"
        )
        mock_get_results.assert_not_called(), (
            "AnalysisService.get_experiment_results must NOT be called when cache hits"
        )

    # ------------------------------------------------------------------
    # Test 9: use_cache=false bypasses the cache
    # ------------------------------------------------------------------

    def test_use_cache_false_bypasses_cache(self, client: TestClient):
        """
        Passing ?use_cache=false must force the endpoint to call AnalysisService
        even when cached data is available.

        This is the mechanism operators use to force a fresh computation after
        new events arrive mid-experiment.
        """
        # Provide valid cached data — should be ignored
        mock_cache = MagicMock()
        mock_cache.get.return_value = json.dumps({"some": "cached_data"})  # would be a hit

        with patch(
            "backend.app.api.v1.endpoints.results._get_cache_service",
            return_value=mock_cache,
        ):
            with patch.object(
                AnalysisService,
                "get_experiment_results",
                return_value=_VALID_RESULT_DICT,
            ) as mock_get_results:
                response = client.get(
                    f"/api/v1/results/{EXPERIMENT_UUID}",
                    params={"use_cache": "false"},
                )

        assert response.status_code == 200, (
            f"Expected 200 with use_cache=false, got {response.status_code}: {response.text}"
        )
        mock_get_results.assert_called_once(), (
            "AnalysisService.get_experiment_results must be called when use_cache=false"
        )

    # ------------------------------------------------------------------
    # Test 10: POST invalidate-cache returns {"status": "ok"}
    # ------------------------------------------------------------------

    def test_invalidate_cache_returns_ok(self, client: TestClient):
        """
        POST /api/v1/results/{experiment_id}/invalidate-cache must return
        HTTP 200 with JSON body {"status": "ok", "experiment_id": "..."}.

        The endpoint is superuser-only; the fixture installs an admin user so
        the authorisation check passes.
        """
        mock_cache = MagicMock()
        mock_cache.clear.return_value = None

        with patch(
            "backend.app.api.v1.endpoints.results._get_cache_service",
            return_value=mock_cache,
        ):
            # Also need to mock get_current_superuser since this endpoint uses it
            with patch(
                "backend.app.api.deps.get_current_superuser",
                return_value=_make_mock_user(is_superuser=True),
            ):
                response = client.post(
                    f"/api/v1/results/{EXPERIMENT_UUID}/invalidate-cache"
                )

        assert response.status_code == 200, (
            f"Expected 200 for cache invalidation, got {response.status_code}: {response.text}"
        )
        data = response.json()
        assert data.get("status") == "ok", (
            f"Response JSON must contain {{\"status\": \"ok\"}}, got {data}"
        )
        assert "experiment_id" in data, (
            f"Response JSON must contain 'experiment_id', got {data}"
        )
