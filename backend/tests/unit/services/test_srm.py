"""
Unit tests for sample-ratio-mismatch detection (``services/srm_service.py``)
and the ``srm`` block of the results API.

Pure-function tests need no database; the endpoint tests use the same
mocked-DB ``TestClient`` pattern as ``test_results_api.py``.
"""

import uuid
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from scipy.stats import chi2 as chi2_dist

from backend.app.api.deps import get_current_user, get_db
from backend.app.main import app
from backend.app.models.user import User
from backend.app.schemas.results import (
    ExperimentResultsResponse,
)
from backend.app.schemas.results import (
    SRMResult as SRMSchema,
)
from backend.app.services.analysis_service import AnalysisService
from backend.app.services.srm_service import (
    SRM_P_VALUE_THRESHOLD,
    SRMResult,
    compute_srm,
    compute_srm_for_experiment,
)

# ---------------------------------------------------------------------------
# compute_srm — pure function
# ---------------------------------------------------------------------------


class TestComputeSrm:
    def test_balanced_split_has_no_warning(self):
        result = compute_srm({"a": 5000, "b": 5000}, {"a": 50, "b": 50})

        assert isinstance(result, SRMResult)
        assert result.chi2 == pytest.approx(0.0)
        assert result.p_value == pytest.approx(1.0)
        assert result.warning is False
        assert result.expected == {"a": 5000.0, "b": 5000.0}
        assert result.observed == {"a": 5000, "b": 5000}

    def test_small_noise_within_expectation_has_no_warning(self):
        # 5050 / 4950 on 10k is a ~1 sigma wobble: chi2 = 2 * 50^2 / 5000 = 1.0
        result = compute_srm({"a": 5050, "b": 4950}, {"a": 50, "b": 50})

        assert result is not None
        assert result.chi2 == pytest.approx(1.0)
        assert result.p_value == pytest.approx(chi2_dist.sf(1.0, 1))
        assert result.warning is False

    def test_sixty_forty_on_fifty_fifty_with_10k_warns(self):
        result = compute_srm({"a": 6000, "b": 4000}, {"a": 50, "b": 50})

        assert result is not None
        # chi2 = (1000^2 / 5000) * 2 = 400
        assert result.chi2 == pytest.approx(400.0)
        assert result.p_value < SRM_P_VALUE_THRESHOLD
        assert result.warning is True

    def test_warning_threshold_is_p_below_0_001(self):
        # chi2 with 1 dof: p = 0.001 at ~10.83.  Construct just above / below.
        # total 10,000 and a 50/50 split: chi2 = 2 * d^2 / 5000 → d = sqrt(5000 * chi2 / 2)
        boundary = chi2_dist.isf(SRM_P_VALUE_THRESHOLD, 1)
        d_below = int((5000 * (boundary - 0.5) / 2) ** 0.5)
        d_above = int((5000 * (boundary + 0.5) / 2) ** 0.5) + 1

        no_warn = compute_srm(
            {"a": 5000 + d_below, "b": 5000 - d_below}, {"a": 50, "b": 50}
        )
        warn = compute_srm(
            {"a": 5000 + d_above, "b": 5000 - d_above}, {"a": 50, "b": 50}
        )
        assert no_warn is not None and no_warn.warning is False
        assert warn is not None and warn.warning is True

    def test_single_variant_returns_none(self):
        assert compute_srm({"a": 100}, {"a": 100}) is None

    def test_zero_assignments_returns_none(self):
        assert compute_srm({}, {"a": 50, "b": 50}) is None
        assert compute_srm({"a": 0, "b": 0}, {"a": 50, "b": 50}) is None

    def test_allocations_not_summing_to_100_are_normalised(self):
        # 30 / 30 (sums to 60) must behave exactly like 50 / 50.
        base = compute_srm({"a": 6000, "b": 4000}, {"a": 50, "b": 50})
        scaled = compute_srm({"a": 6000, "b": 4000}, {"a": 30, "b": 30})
        fractions = compute_srm({"a": 6000, "b": 4000}, {"a": 0.5, "b": 0.5})

        assert base is not None and scaled is not None and fractions is not None
        assert scaled.chi2 == pytest.approx(base.chi2)
        assert scaled.expected == pytest.approx(base.expected)
        assert fractions.chi2 == pytest.approx(base.chi2)

    def test_unequal_allocation_is_respected(self):
        # 90/10 allocation with a 90/10 observed split: perfect fit.
        result = compute_srm({"a": 9000, "b": 1000}, {"a": 90, "b": 10})
        assert result is not None
        assert result.chi2 == pytest.approx(0.0)
        assert result.warning is False

        # Same counts judged against 50/50: a mismatch.
        mismatch = compute_srm({"a": 9000, "b": 1000}, {"a": 50, "b": 50})
        assert mismatch is not None and mismatch.warning is True

    def test_three_variants_use_two_degrees_of_freedom(self):
        obs = {"a": 3400, "b": 3300, "c": 3300}
        result = compute_srm(obs, {"a": 34, "b": 33, "c": 33})
        assert result is not None
        expected_stat = sum(
            (obs[k] - 10000 * w / 100) ** 2 / (10000 * w / 100)
            for k, w in {"a": 34, "b": 33, "c": 33}.items()
        )
        assert result.chi2 == pytest.approx(expected_stat)
        assert result.p_value == pytest.approx(chi2_dist.sf(expected_stat, 2))

    def test_zero_allocation_variant_excluded_from_test(self):
        # A variant with allocation 0 is not part of the randomised split.
        result = compute_srm({"a": 500, "b": 500, "c": 3}, {"a": 50, "b": 50, "c": 0})
        assert result is not None
        assert set(result.expected) == {"a", "b"}
        assert result.warning is False

        # Only one allocated variant left → undefined.
        assert compute_srm({"a": 500, "b": 5}, {"a": 100, "b": 0}) is None

    def test_missing_observed_variant_counts_as_zero(self):
        result = compute_srm({"a": 10000}, {"a": 50, "b": 50})
        assert result is not None
        assert result.observed == {"a": 10000, "b": 0}
        assert result.warning is True

    def test_observed_variant_outside_allocation_is_ignored(self):
        result = compute_srm({"a": 500, "b": 500, "ghost": 999}, {"a": 50, "b": 50})
        assert result is not None
        assert "ghost" not in result.observed
        assert result.warning is False

    def test_to_dict_matches_schema(self):
        result = compute_srm({"a": 6000, "b": 4000}, {"a": 50, "b": 50})
        assert result is not None
        schema = SRMSchema(**result.to_dict())
        assert schema.warning is True
        assert schema.chi2 == pytest.approx(400.0)
        assert schema.expected["a"] == pytest.approx(5000.0)
        assert schema.observed["b"] == 4000


# ---------------------------------------------------------------------------
# compute_srm_for_experiment — DB reads (mocked session)
# ---------------------------------------------------------------------------


class TestComputeSrmForExperiment:
    def _db(self, variant_rows, count_rows, optimization_type="fixed"):
        db = MagicMock()
        variant_query = MagicMock()
        variant_query.filter.return_value.all.return_value = variant_rows
        optimization_query = MagicMock()
        optimization_query.filter.return_value.scalar.return_value = optimization_type
        count_query = MagicMock()
        count_query.filter.return_value.group_by.return_value.all.return_value = (
            count_rows
        )
        db.query.side_effect = [variant_query, optimization_query, count_query]
        return db

    def test_reads_traffic_allocation_and_assignment_counts(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        db = self._db([(a, 50), (b, 50)], [(a, 6000), (b, 4000)])

        result = compute_srm_for_experiment(db, uuid.uuid4())

        assert result is not None
        assert result.observed == {str(a): 6000, str(b): 4000}
        assert result.warning is True

    def test_single_variant_experiment_returns_none_without_counting(self):
        a = uuid.uuid4()
        db = self._db([(a, 100)], [])

        assert compute_srm_for_experiment(db, uuid.uuid4()) is None
        assert db.query.call_count == 1  # never reached the assignment count

    def test_null_allocation_treated_as_zero(self):
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        db = self._db([(a, 50), (b, 50), (c, None)], [(a, 500), (b, 500)])

        result = compute_srm_for_experiment(db, uuid.uuid4())
        assert result is not None
        assert set(result.expected) == {str(a), str(b)}

    @pytest.mark.parametrize(
        "optimization_type", ["thompson_sampling", "ucb1", "epsilon_greedy"]
    )
    def test_adaptive_allocation_is_not_tested(self, optimization_type):
        """A bandit reallocates traffic on purpose — never an SRM warning.

        The same counts under ``fixed`` would warn (60/40 on a 50/50 split).
        """
        a, b = uuid.uuid4(), uuid.uuid4()
        db = self._db(
            [(a, 50), (b, 50)],
            [(a, 6000), (b, 4000)],
            optimization_type=optimization_type,
        )

        assert compute_srm_for_experiment(db, uuid.uuid4()) is None
        assert db.query.call_count == 2  # never reached the assignment count

        fixed = self._db([(a, 50), (b, 50)], [(a, 6000), (b, 4000)])
        result = compute_srm_for_experiment(fixed, uuid.uuid4())
        assert result is not None and result.warning is True

    def test_enum_valued_optimization_type_is_unwrapped(self):
        """The column may come back as an enum member rather than a string."""

        class _Opt:
            def __init__(self, value):
                self.value = value

        a, b = uuid.uuid4(), uuid.uuid4()
        counts = [(a, 6000), (b, 4000)]
        adaptive = self._db(
            [(a, 50), (b, 50)], counts, optimization_type=_Opt("thompson_sampling")
        )
        assert compute_srm_for_experiment(adaptive, uuid.uuid4()) is None

        fixed = self._db([(a, 50), (b, 50)], counts, optimization_type=_Opt("fixed"))
        assert compute_srm_for_experiment(fixed, uuid.uuid4()) is not None

    def test_missing_optimization_type_is_treated_as_fixed(self):
        """Legacy rows with a NULL optimization_type still get the test."""
        a, b = uuid.uuid4(), uuid.uuid4()
        db = self._db(
            [(a, 50), (b, 50)], [(a, 6000), (b, 4000)], optimization_type=None
        )

        result = compute_srm_for_experiment(db, uuid.uuid4())
        assert result is not None and result.warning is True


# ---------------------------------------------------------------------------
# GET /api/v1/results/{id} — srm block (mocked DB)
# ---------------------------------------------------------------------------


EXPERIMENT_UUID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
CONTROL_UUID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
TREATMENT_UUID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
METRIC_UUID = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")


def _results_dict() -> Dict[str, Any]:
    return {
        "experiment_id": str(EXPERIMENT_UUID),
        "experiment_name": "SRM test",
        "status": "active",
        "start_date": "2026-01-01T00:00:00+00:00",
        "end_date": None,
        "computed_at": "2026-03-01T12:00:00+00:00",
        "sample_size_adequate": True,
        "summary": {
            "total_users": 10000,
            "total_events": 1100,
            "has_winner": False,
            "recommendation": "CONTINUE_TESTING",
            "recommendation_reason": "not yet",
        },
        "metrics": [
            {
                "metric_id": str(METRIC_UUID),
                "metric_name": "Conversion",
                "metric_type": "conversion",
                "is_primary": True,
                "has_significant_result": False,
                "winning_variant_id": None,
                "variants": [
                    {
                        "variant_id": str(CONTROL_UUID),
                        "variant_name": "Control",
                        "is_control": True,
                        "sample_size": 6000,
                        "conversions": 600,
                        "mean": 0.1,
                        "confidence_interval": [0.09, 0.11],
                        "is_significant": False,
                    },
                    {
                        "variant_id": str(TREATMENT_UUID),
                        "variant_name": "Treatment",
                        "is_control": False,
                        "sample_size": 4000,
                        "conversions": 400,
                        "mean": 0.1,
                        "confidence_interval": [0.09, 0.11],
                        "p_value": 0.5,
                        "is_significant": False,
                    },
                ],
            }
        ],
    }


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def client(mock_db):
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.is_active = True
    user.is_superuser = True
    user.role = "ADMIN"

    def override_get_db():
        yield mock_db

    async def override_get_current_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides = {}


class TestResultsEndpointSrm:
    @pytest.mark.unit
    def test_srm_block_present_and_warning_on_mismatch(self, client, mock_db):
        srm = compute_srm(
            {str(CONTROL_UUID): 6000, str(TREATMENT_UUID): 4000},
            {str(CONTROL_UUID): 50, str(TREATMENT_UUID): 50},
        )
        with (
            patch.object(
                AnalysisService, "get_experiment_results", return_value=_results_dict()
            ),
            patch(
                "backend.app.api.v1.endpoints.results.compute_srm_for_experiment",
                return_value=srm,
            ) as mock_srm,
        ):
            response = client.get(
                f"/api/v1/results/{EXPERIMENT_UUID}", params={"use_cache": "false"}
            )

        assert response.status_code == 200, response.text
        mock_srm.assert_called_once()
        block = response.json()["srm"]
        assert block["warning"] is True
        assert block["chi2"] == pytest.approx(400.0)
        assert block["p_value"] < 0.001
        assert block["expected"] == {
            str(CONTROL_UUID): 5000.0,
            str(TREATMENT_UUID): 5000.0,
        }
        assert block["observed"] == {str(CONTROL_UUID): 6000, str(TREATMENT_UUID): 4000}

    @pytest.mark.unit
    def test_srm_null_when_undefined(self, client):
        with (
            patch.object(
                AnalysisService, "get_experiment_results", return_value=_results_dict()
            ),
            patch(
                "backend.app.api.v1.endpoints.results.compute_srm_for_experiment",
                return_value=None,
            ),
        ):
            response = client.get(
                f"/api/v1/results/{EXPERIMENT_UUID}", params={"use_cache": "false"}
            )

        assert response.status_code == 200, response.text
        assert "srm" in response.json()
        assert response.json()["srm"] is None

    @pytest.mark.unit
    def test_srm_failure_never_fails_the_response(self, client):
        with (
            patch.object(
                AnalysisService, "get_experiment_results", return_value=_results_dict()
            ),
            patch(
                "backend.app.api.v1.endpoints.results.compute_srm_for_experiment",
                side_effect=RuntimeError("db down"),
            ),
        ):
            response = client.get(
                f"/api/v1/results/{EXPERIMENT_UUID}", params={"use_cache": "false"}
            )

        assert response.status_code == 200, response.text
        assert response.json()["srm"] is None

    @pytest.mark.unit
    def test_srm_survives_cache_round_trip(self):
        srm = compute_srm({"a": 6000, "b": 4000}, {"a": 50, "b": 50})
        assert srm is not None
        payload = _results_dict()
        payload["srm"] = srm.to_dict()
        model = ExperimentResultsResponse(**payload)

        restored = ExperimentResultsResponse.model_validate_json(
            model.model_dump_json()
        )
        assert restored.srm is not None
        assert restored.srm.warning is True
        assert restored.srm.observed == {"a": 6000, "b": 4000}
