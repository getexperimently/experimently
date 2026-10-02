"""
The analysis status table (``backend/app/core/analysis_status.py``) and the
responses that carry it -- #217 (CUPED) and #219 (interaction analysis).

* The table's statuses are pinned literally, so a flipped entry fails here.
* Every labelled response reads the table when it is built: patching an entry
  changes the response, so no response can hard-code its own label.
* A notice is present exactly when the status is ``beta``.
* The three routes whose numbers are not computed as described are marked
  ``x-stability: beta`` in the live OpenAPI document; ``/interactions/scan``
  and ``/results/{id}`` are not.
* CUPED's ``none`` applies no adjustment (θ exactly 0.0), the pair analysis
  invents no sub-result, and ``/novelty`` never answers ``has_novelty: false``.
"""

import uuid
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.core import analysis_status as table
from backend.app.core.analysis_status import (
    ANALYSIS_STATUS,
    AnalysisLabel,
    analysis_notice,
    analysis_status,
)
from backend.app.schemas.interaction import (
    InteractionAnalysisResponse,
    InteractionPairResponse,
    NoveltyAnalysisResponse,
)
from backend.app.schemas.variance_reduction import (
    CupedResultsResponse,
    VarianceReductionMethod,
)
from backend.app.services.cuped_service import CupedService
from backend.app.services.interaction_detection_service import (
    InteractionDetectionService,
)

pytestmark = pytest.mark.unit

#: What this release says about each analysis.  Changing a status is a
#: decision: change it here and in the table together.
EXPECTED_STATUS = {
    "cuped": "beta",
    "interactions": "beta",
    "novelty": "beta",
    "sequential": "beta",
    "warehouse_proportion": "ga",
    "warehouse_mean": "ga",
}

EXPECTED_ISSUE = {"cuped": 217, "interactions": 219, "novelty": 219, "sequential": 232}


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------


def test_the_table_holds_exactly_the_expected_statuses():
    assert {name: label.status for name, label in ANALYSIS_STATUS.items()} == (
        EXPECTED_STATUS
    )


@pytest.mark.parametrize("name", sorted(EXPECTED_STATUS))
def test_a_notice_is_present_exactly_when_beta(name):
    label = ANALYSIS_STATUS[name]
    assert (label.status == "beta") == (label.notice is not None)
    if label.notice is not None:
        assert label.notice.startswith("Beta: ")
        issue = EXPECTED_ISSUE[name]
        assert label.notice.endswith(
            f"https://github.com/getexperimently/experimently/issues/{issue}"
        )


def test_the_label_refuses_beta_without_a_notice():
    with pytest.raises(ValueError):
        AnalysisLabel("beta")
    with pytest.raises(ValueError):
        AnalysisLabel("beta", "")


def test_the_label_refuses_ga_with_a_notice():
    with pytest.raises(ValueError):
        AnalysisLabel("ga", "Beta: something")


def test_the_label_refuses_an_unknown_status():
    with pytest.raises(ValueError):
        AnalysisLabel("alpha", "Beta: something")  # type: ignore[arg-type]


def test_an_unknown_analysis_is_a_key_error():
    with pytest.raises(KeyError):
        analysis_status("no-such-analysis")


# ---------------------------------------------------------------------------
# Every labelled response reads the table when it is built
# ---------------------------------------------------------------------------


def _cuped() -> CupedResultsResponse:
    return CupedResultsResponse(
        experiment_id=str(uuid.uuid4()),
        method=VarianceReductionMethod.NONE,
        metrics=[],
        computed_at="2026-09-27T00:00:00+00:00",
    )


def _pair() -> InteractionPairResponse:
    return InteractionPairResponse(
        experiment_a_id="a",
        experiment_b_id="b",
        overlap_coefficient=0.5,
        has_significant_overlap=True,
        overall_risk="medium",
    )


def _novelty() -> NoveltyAnalysisResponse:
    return NoveltyAnalysisResponse(recommendation="not computed")


BUILDERS = {"cuped": _cuped, "interactions": _pair, "novelty": _novelty}


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_a_response_carries_the_tables_current_label(name):
    body = BUILDERS[name]().model_dump(mode="json")
    assert body["analysis_status"] == analysis_status(name) == EXPECTED_STATUS[name]
    assert body["analysis_notice"] == analysis_notice(name)


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_a_response_follows_a_changed_table_entry(name, monkeypatch):
    """Flip the entry to ga: the response must follow, with no notice."""
    monkeypatch.setitem(table.ANALYSIS_STATUS, name, AnalysisLabel("ga"))
    body = BUILDERS[name]().model_dump(mode="json")
    assert body["analysis_status"] == "ga"
    assert body["analysis_notice"] is None


def test_the_stable_scan_schema_is_not_labelled():
    """/interactions/scan is stable: its item schema gains no field."""
    assert "analysis_status" not in InteractionAnalysisResponse.model_fields
    assert "analysis_notice" not in InteractionAnalysisResponse.model_fields


# ---------------------------------------------------------------------------
# The routes: beta in the OpenAPI document, labelled in the answer
# ---------------------------------------------------------------------------

BETA_OPERATIONS = {
    ("get", "/api/v1/results/{experiment_id}/cuped"),
    ("get", "/api/v1/interactions/{exp_a_id}/{exp_b_id}"),
    ("get", "/api/v1/interactions/{exp_a_id}/{exp_b_id}/novelty"),
}

STILL_STABLE = {
    ("get", "/api/v1/interactions/scan"),
    ("get", "/api/v1/results/{experiment_id}"),
}


@pytest.fixture(scope="module")
def openapi():
    from backend.app.main import app

    return app.openapi()


@pytest.mark.parametrize("method,path", sorted(BETA_OPERATIONS))
def test_demoted_routes_are_beta_in_the_openapi_document(openapi, method, path):
    operation = openapi["paths"][path][method]
    assert operation.get("x-stability") == "beta"
    assert operation["summary"].startswith("Beta: ")


@pytest.mark.parametrize("method,path", sorted(STILL_STABLE))
def test_the_neighbouring_routes_stay_stable(openapi, method, path):
    assert "x-stability" not in openapi["paths"][path][method]


@pytest.fixture
def client():
    from backend.app.api.deps import get_current_active_user, get_db
    from backend.app.main import app

    user = MagicMock()
    user.is_active = True
    user.is_superuser = True
    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: MagicMock()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _users(first, second):
    return patch.object(
        InteractionDetectionService,
        "_get_experiment_users",
        side_effect=[first, second],
    )


SHARED_40 = {f"shared-user-{i}" for i in range(40)}


def test_pair_route_answers_with_the_tables_label(client, monkeypatch):
    a, b = uuid.uuid4(), uuid.uuid4()
    with _users(SHARED_40, SHARED_40):
        body = client.get(f"/api/v1/interactions/{a}/{b}").json()
    assert body["analysis_status"] == "beta"
    assert body["analysis_notice"] == analysis_notice("interactions")

    monkeypatch.setitem(table.ANALYSIS_STATUS, "interactions", AnalysisLabel("ga"))
    with _users(SHARED_40, SHARED_40):
        body = client.get(f"/api/v1/interactions/{a}/{b}").json()
    assert body["analysis_status"] == "ga"
    assert body["analysis_notice"] is None


def test_pair_route_with_no_overlap_is_labelled_too(client):
    a, b = uuid.uuid4(), uuid.uuid4()
    with _users({"u1"}, {"u2"}):
        body = client.get(f"/api/v1/interactions/{a}/{b}").json()
    assert body["overlap_coefficient"] == 0.0
    assert body["overall_risk"] == "low"
    assert body["analysis_status"] == "beta"


def test_novelty_route_answers_with_the_tables_label(client, monkeypatch):
    a, b = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setitem(table.ANALYSIS_STATUS, "novelty", AnalysisLabel("ga"))
    with _users(SHARED_40, SHARED_40):
        body = client.get(f"/api/v1/interactions/{a}/{b}/novelty").json()
    assert body["analysis_status"] == "ga"
    assert body["analysis_notice"] is None


# ---------------------------------------------------------------------------
# #219: nothing invented from user counts; novelty never false
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_219_case_shared_users_give_overlap_and_null_sub_results(client):
    """40 shared users, no events: overlap 1.0 and null sub-results."""
    a, b = uuid.uuid4(), uuid.uuid4()
    with _users(SHARED_40, SHARED_40):
        body = client.get(f"/api/v1/interactions/{a}/{b}").json()
    assert body["overlap_coefficient"] == 1.0
    assert body["has_significant_overlap"] is True
    assert body["interaction_result"] is None
    assert body["novelty_result"] is None
    assert body["sutva_result"] is None
    assert body["overall_risk"] == "high"


@pytest.mark.regression
@pytest.mark.parametrize(
    "first,second",
    [
        (SHARED_40, SHARED_40),  # overlap 1.0
        ({"u1", "u2", "u3"}, {"u2", "u3", "u4"}),  # overlap 0.5
        ({"u1"}, {"u2"}),  # no overlap
        (set(), set()),  # no users at all
    ],
)
def test_novelty_never_answers_has_novelty_false(client, first, second):
    a, b = uuid.uuid4(), uuid.uuid4()
    with _users(first, second):
        response = client.get(f"/api/v1/interactions/{a}/{b}/novelty")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["has_novelty"] is not False
    assert body["computed"] is False
    assert body["has_novelty"] is None
    assert body["decline_rate"] is None


def test_the_novelty_schema_refuses_a_default_false():
    with pytest.raises(ValidationError):
        NoveltyAnalysisResponse(computed=False, has_novelty=False, recommendation="x")
    with pytest.raises(ValidationError):
        NoveltyAnalysisResponse(computed=True, recommendation="x")


@pytest.mark.parametrize(
    "overlap,risk",
    [(0.0, "low"), (0.3, "low"), (0.31, "medium"), (0.6, "medium"), (0.61, "high")],
)
def test_risk_comes_from_the_overlap_bands(overlap, risk):
    assert InteractionDetectionService.risk_from_overlap(overlap) == risk


def test_scan_items_carry_null_sub_results(client):
    """The stable scan keeps its shape; its items simply have no sub-results."""
    service = InteractionDetectionService
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    with (
        patch.object(service, "_get_active_experiment_ids", return_value=ids),
        _users(SHARED_40, SHARED_40),
    ):
        body = client.get("/api/v1/interactions/scan").json()
    [item] = body["analyses"]
    assert item["interaction_result"] is None
    assert item["novelty_result"] is None
    assert item["sutva_result"] is None
    assert body["high_risk_pairs"] == 1
    assert "analysis_status" not in item


# ---------------------------------------------------------------------------
# #217: ``none`` applies no adjustment
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_cuped_none_gives_theta_exactly_zero_and_the_raw_estimate():
    # The outcome correlates with the covariate, so an estimated θ is far from 0.
    rng = np.random.default_rng(217)
    cx = np.arange(200, dtype=float)
    tx = np.arange(200, dtype=float)
    cy = (cx < 20).astype(float)
    ty = (tx < 50).astype(float) + rng.normal(0.0, 0.01, 200)

    adjusted = CupedService.compute_cuped_effect(cy, cx, ty, tx)
    assert abs(adjusted.theta) > 1e-4  # the probe: θ is estimable here

    none = CupedService.compute_cuped_effect(cy, cx, ty, tx, adjust=False)
    assert none.theta == 0.0
    assert none.variance_reduction_pct == 0.0
    assert none.adjusted_control_mean == float(cy.mean())
    assert none.adjusted_treatment_mean == float(ty.mean())
    assert none.adjusted_effect == float(ty.mean()) - float(cy.mean())
