"""
Integration tests for experiment lifecycle & analytics API endpoints.

This file complements test_experiments_api.py (which covers list/create/get/
update/delete/start/pause happy paths) by exercising the remaining endpoints
in backend/app/api/v1/endpoints/experiments.py:

  PUT  /api/v1/experiments/{id}/schedule
  POST /api/v1/experiments/{id}/complete
  GET  /api/v1/experiments/{id}/results
  POST /api/v1/experiments/{id}/archive
  POST /api/v1/experiments/{id}/clone
  GET  /api/v1/experiments/{id}/daily-results
  GET  /api/v1/experiments/{id}/segmented-results/{segment_by}
  POST /api/v1/experiments/{id}/metadata
  GET  /api/v1/experiments/analysis/sample-size
  POST /api/v1/experiments/schedules/process
  GET  /api/v1/experiments/{id}/split-url/preview

It also targets the permission/403 branches of start/pause/get/update/delete
and the module-level `stats_z_score` helper.

IMPORTANT — dependency override caveat:
  `admin_client` / `developer_client` / `analyst_client` / `viewer_client`
  fixtures all call `make_client_for_user`, which mutates the *global*
  `app.dependency_overrides` dict. Requesting two of these client fixtures in
  the same test signature resolves them both *before* the test body runs, so
  the second fixture silently overwrites the first's auth override for the
  whole test (not just its own client instance) — both TestClient objects
  then act as the last-resolved user. To exercise "owner creates as admin,
  then a different role attempts access" scenarios correctly, we request only
  `admin_client` plus the target role's *_user* fixture (which does not
  touch overrides) and `db_session`, then build the second client mid-test
  via `make_client_for_user` after the admin actions are complete.

Product bug status (see coordinator follow-up): most of the bugs originally
documented here (blanket `except Exception` converting deliberate 4xx into
500; `pause`/`complete`/`archive`/`clone` serializing through the wrong
`metrics` attribute; `update_experiment_metadata` colliding with
SQLAlchemy's `Base.metadata`; `split_url_config` missing from
`_experiment_to_dict`) have since been FIXED in product code. Assertions
below now expect the correct status codes for those endpoints.

Two things are still genuinely broken and are asserted as such (see the
docstrings on the relevant tests for detail):
  - GET /{id}/results: AnalysisService.get_experiment_results()'s return
    shape doesn't match the ExperimentResults response_model (bug #4, not
    fixed).
  - calculate_experiment_sample_size's manual traffic_allocation bounds
    check and update_experiment's invalid-status fallback are dead code
    given the stricter Query/Pydantic validation that runs first (bug #7,
    not something to "fix" — just documenting unreachable code).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.api.v1.endpoints.experiments import stats_z_score
from backend.app.main import app as fastapi_app
from backend.tests.integration.conftest import make_client_for_user

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_create_payload(name: str = "Lifecycle Test Experiment") -> dict:
    """Return a minimal valid ExperimentCreate payload."""
    return {
        "name": name,
        "description": "Created by lifecycle integration tests",
        "hypothesis": "Lifecycle testing works",
        "experiment_type": "a_b",
        "variants": [
            {
                "name": "Control",
                "is_control": True,
                "traffic_allocation": 50,
                "description": "Control group",
            },
            {
                "name": "Treatment",
                "is_control": False,
                "traffic_allocation": 50,
                "description": "Treatment group",
            },
        ],
        "metrics": [
            {
                "name": "Conversion Rate",
                "event_name": "purchase",
                "metric_type": "conversion",
                "is_primary": True,
                "minimum_sample_size": 100,
            }
        ],
    }


def _create_experiment(
    client: TestClient, name: str = "Lifecycle Test Experiment"
) -> dict:
    """Create an experiment via the API and return the response JSON."""
    response = client.post("/api/v1/experiments/", json=_valid_create_payload(name))
    assert response.status_code == 201, f"Failed to create experiment: {response.text}"
    return response.json()


def _create_and_start(client: TestClient, name: str) -> dict:
    """Create a DRAFT experiment and transition it to ACTIVE."""
    exp = _create_experiment(client, name)
    start_response = client.post(f"/api/v1/experiments/{exp['id']}/start")
    assert start_response.status_code == 200, start_response.text
    return start_response.json()


def _split_url_payload(name: str, with_config: bool = True) -> dict:
    payload = _valid_create_payload(name)
    payload["experiment_type"] = "split_url"
    if with_config:
        payload["split_url_config"] = {
            "variants": [
                {
                    "name": "Control",
                    "url": "https://example.com/a",
                    "traffic_allocation": 50,
                },
                {
                    "name": "Treatment",
                    "url": "https://example.com/b",
                    "traffic_allocation": 50,
                },
            ],
            "cookie_ttl_days": 30,
        }
    return payload


# ---------------------------------------------------------------------------
# Start / pause - additional permission & error branches
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStartPausePermissions:
    """Permission (403) branches for start/pause not covered by test_experiments_api.py."""

    def test_analyst_cannot_start_other_users_experiment(
        self, admin_client, analyst_user, db_session
    ):
        """Analyst lacks UPDATE permission and doesn't own the experiment -> 403."""
        exp = _create_experiment(admin_client, "Analyst Start Forbidden")
        analyst_client = make_client_for_user(db_session, analyst_user)
        response = analyst_client.post(f"/api/v1/experiments/{exp['id']}/start")
        assert response.status_code == 403, response.text

    def test_viewer_cannot_pause_other_users_experiment(
        self, admin_client, viewer_user, db_session
    ):
        exp = _create_and_start(admin_client, "Viewer Pause Forbidden")
        viewer_client = make_client_for_user(db_session, viewer_user)
        response = viewer_client.post(f"/api/v1/experiments/{exp['id']}/pause")
        assert response.status_code == 403, response.text

    def test_pause_nonexistent_experiment_returns_404(self, admin_client):
        fake_id = "00000000-0000-0000-0000-000000000010"
        response = admin_client.post(f"/api/v1/experiments/{fake_id}/pause")
        assert response.status_code == 404, response.text

    def test_start_experiment_without_metrics_returns_400(
        self, admin_client, make_experiment, make_variant
    ):
        """Experiment with 2 variants but zero metrics cannot be started.

        `ExperimentCreate` requires >= 1 metric at the schema level, so this
        validation branch is unreachable via the public creation API. We
        construct the DB rows directly via the make_experiment/make_variant
        factories (owned by admin_user, matching admin_client) to reach it.
        """
        experiment = make_experiment(name="No Metrics Direct Start")
        make_variant(experiment, name="Control", is_control=True, traffic_allocation=50)
        make_variant(
            experiment, name="Treatment", is_control=False, traffic_allocation=50
        )

        response = admin_client.post(f"/api/v1/experiments/{experiment.id}/start")
        assert response.status_code == 400, response.text


# ---------------------------------------------------------------------------
# Get experiment - permission branch not covered by test_experiments_api.py
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetExperimentPermissions:
    """GET /api/v1/experiments/{id} — ownership-based 403 branch.

    Unlike deps.get_experiment_access (used by start/pause/etc.), the inline
    permission check in get_experiment requires ownership for *every*
    non-superuser regardless of role, once the READ-permission check passes.
    """

    def test_analyst_cannot_get_other_users_experiment(
        self, admin_client, analyst_user, db_session
    ):
        exp = _create_experiment(admin_client, "Get Analyst Forbidden")
        analyst_client = make_client_for_user(db_session, analyst_user)
        response = analyst_client.get(f"/api/v1/experiments/{exp['id']}")
        assert response.status_code == 403, response.text

    def test_viewer_cannot_get_other_users_experiment(
        self, admin_client, viewer_user, db_session
    ):
        exp = _create_experiment(admin_client, "Get Viewer Forbidden")
        viewer_client = make_client_for_user(db_session, viewer_user)
        response = viewer_client.get(f"/api/v1/experiments/{exp['id']}")
        assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------
# Update experiment - additional branches not covered by test_experiments_api.py
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestUpdateExperimentAdditional:
    """PUT /api/v1/experiments/{id} — status conversion & restricted fields."""

    def test_update_status_field_valid_value(self, admin_client):
        """Updating `status` to a valid string triggers the
        str -> ExperimentStatus enum conversion branch.
        """
        exp = _create_experiment(admin_client, "Update Status Valid")
        response = admin_client.put(
            f"/api/v1/experiments/{exp['id']}", json={"status": "paused"}
        )
        assert response.status_code == 200, response.text

    def test_update_status_field_invalid_value_returns_422(self, admin_client):
        """`ExperimentUpdate.status` is typed as `Optional[ExperimentStatus]`,
        so Pydantic itself rejects an invalid status string at request-
        parsing time (422). The endpoint's own
        `except (KeyError, ValueError): del update_data["status"]` fallback
        is therefore unreachable via HTTP -- dead code.
        """
        exp = _create_experiment(admin_client, "Update Status Invalid")
        response = admin_client.put(
            f"/api/v1/experiments/{exp['id']}", json={"status": "not_a_real_status"}
        )
        assert response.status_code == 422, response.text

    def test_update_restricted_field_on_active_experiment_returns_403(
        self, admin_client
    ):
        """Even a superuser cannot update `variants`/`metrics`/`start_date`/
        `end_date` once an experiment has left DRAFT status — this check is
        unconditional (not owner/permission gated).
        """
        exp = _create_and_start(admin_client, "Update Restricted Active")
        response = admin_client.put(
            f"/api/v1/experiments/{exp['id']}",
            json={
                "variants": [
                    {"name": "Control", "is_control": True, "traffic_allocation": 100}
                ]
            },
        )
        assert response.status_code == 403, response.text

    def test_non_superuser_owner_cannot_update_active_experiment_at_all(
        self, developer_client
    ):
        """The *first* status guard (non-DRAFT + non-superuser -> 403) is
        distinct from the restricted-fields guard above: it blocks even
        unrestricted fields like `name` for a non-superuser owner once the
        experiment has left DRAFT. developer_client is a real owner here
        (creates its own experiment), not superuser.
        """
        create_response = developer_client.post(
            "/api/v1/experiments/", json=_valid_create_payload("Dev Owns Active Exp")
        )
        assert create_response.status_code == 201, create_response.text
        exp_id = create_response.json()["id"]
        start_response = developer_client.post(f"/api/v1/experiments/{exp_id}/start")
        assert start_response.status_code == 200, start_response.text

        response = developer_client.put(
            f"/api/v1/experiments/{exp_id}", json={"name": "New Name"}
        )
        assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------
# Delete experiment - ownership branch not covered by test_experiments_api.py
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDeleteExperimentOwnership:
    """DELETE /api/v1/experiments/{id} — non-owner (not superuser) 403 branch."""

    def test_analyst_cannot_delete_other_users_draft_experiment(
        self, admin_client, analyst_user, db_session
    ):
        exp = _create_experiment(admin_client, "Delete Analyst Forbidden")
        analyst_client = make_client_for_user(db_session, analyst_user)
        response = analyst_client.delete(
            f"/api/v1/experiments/{exp['id']}",
            params={"experiment_key": exp["id"]},
        )
        assert response.status_code == 403, response.text

    def test_analyst_cannot_create_an_experiment(self, analyst_client):
        """ANALYST has READ and LIST on EXPERIMENT, not CREATE.

        Regression: the endpoint used to gate creation on the substring
        "viewer" appearing in the username, so an analyst (and any VIEWER not
        named "viewer") could create experiments.
        """
        response = analyst_client.post(
            "/api/v1/experiments/", json=_valid_create_payload("Analyst Create Attempt")
        )
        assert response.status_code == 403, response.text

    def test_analyst_owner_without_delete_permission_returns_403(
        self, analyst_client, analyst_user, db_session
    ):
        """An owner who lacks DELETE still cannot delete.

        The analyst cannot create through the API, so the experiment is
        seeded directly with the analyst as owner; this exercises the
        `check_permission(..., Action.DELETE)` branch rather than the
        ownership-mismatch branch above.
        """
        from backend.app.models.experiment import Experiment, ExperimentStatus

        experiment = Experiment(
            name=f"Analyst Owns Draft {uuid.uuid4().hex[:8]}",
            key=f"analyst_owns_{uuid.uuid4().hex[:8]}",
            description="Owned by the analyst, seeded directly",
            hypothesis="Ownership does not grant DELETE",
            status=ExperimentStatus.DRAFT,
            owner_id=analyst_user.id,
        )
        db_session.add(experiment)
        db_session.commit()
        db_session.refresh(experiment)
        exp_id = str(experiment.id)

        response = analyst_client.delete(
            f"/api/v1/experiments/{exp_id}", params={"experiment_key": exp_id}
        )
        assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------
# Update experiment schedule
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestUpdateExperimentSchedule:
    """PUT /api/v1/experiments/{id}/schedule"""

    def test_admin_can_schedule_draft_experiment(self, admin_client):
        exp = _create_experiment(admin_client, "Schedule Draft Exp")
        start_date = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        end_date = (datetime.now(timezone.utc) + timedelta(days=8)).isoformat()

        response = admin_client.put(
            f"/api/v1/experiments/{exp['id']}/schedule",
            json={"start_date": start_date, "end_date": end_date, "time_zone": "UTC"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["id"] == exp["id"]

    def test_schedule_nonexistent_experiment_returns_404(self, admin_client):
        fake_id = "00000000-0000-0000-0000-000000000011"
        start_date = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        end_date = (datetime.now(timezone.utc) + timedelta(days=8)).isoformat()
        response = admin_client.put(
            f"/api/v1/experiments/{fake_id}/schedule",
            json={"start_date": start_date, "end_date": end_date},
        )
        assert response.status_code == 404, response.text

    def test_schedule_active_experiment_returns_400(self, admin_client):
        """Scheduling requires DRAFT or PAUSED status."""
        exp = _create_and_start(admin_client, "Schedule Active Exp")
        start_date = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        end_date = (datetime.now(timezone.utc) + timedelta(days=8)).isoformat()

        response = admin_client.put(
            f"/api/v1/experiments/{exp['id']}/schedule",
            json={"start_date": start_date, "end_date": end_date},
        )
        assert response.status_code == 400, response.text

    def test_schedule_end_before_start_returns_422(self, admin_client):
        """end_date <= start_date is rejected by ScheduleConfig's Pydantic
        model_validator at the request-parsing layer (422) before the
        endpoint body -- and its service-level ValueError fallback for the
        same condition -- ever runs.
        """
        exp = _create_experiment(admin_client, "Schedule Bad Dates Exp")
        start_date = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        end_date = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

        response = admin_client.put(
            f"/api/v1/experiments/{exp['id']}/schedule",
            json={"start_date": start_date, "end_date": end_date},
        )
        assert response.status_code == 422, response.text

    def test_analyst_cannot_schedule_other_users_experiment(
        self, admin_client, analyst_user, db_session
    ):
        exp = _create_experiment(admin_client, "Schedule Analyst Forbidden")
        analyst_client = make_client_for_user(db_session, analyst_user)
        start_date = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        end_date = (datetime.now(timezone.utc) + timedelta(days=8)).isoformat()

        response = analyst_client.put(
            f"/api/v1/experiments/{exp['id']}/schedule",
            json={"start_date": start_date, "end_date": end_date},
        )
        assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------
# Complete experiment
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCompleteExperiment:
    """POST /api/v1/experiments/{id}/complete"""

    def test_admin_can_complete_active_experiment(self, admin_client):
        exp = _create_and_start(admin_client, "Complete Me")
        response = admin_client.post(f"/api/v1/experiments/{exp['id']}/complete")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "completed"
        assert data["end_date"] is not None
        assert len(data["metrics"]) == 1

    def test_complete_draft_experiment_returns_400(self, admin_client):
        exp = _create_experiment(admin_client, "Complete Draft Attempt")
        response = admin_client.post(f"/api/v1/experiments/{exp['id']}/complete")
        assert response.status_code == 400, response.text

    def test_complete_nonexistent_experiment_returns_404(self, admin_client):
        fake_id = "00000000-0000-0000-0000-000000000012"
        response = admin_client.post(f"/api/v1/experiments/{fake_id}/complete")
        assert response.status_code == 404, response.text

    def test_viewer_cannot_complete_other_users_experiment(
        self, admin_client, viewer_user, db_session
    ):
        exp = _create_and_start(admin_client, "Complete Viewer Forbidden")
        viewer_client = make_client_for_user(db_session, viewer_user)
        response = viewer_client.post(f"/api/v1/experiments/{exp['id']}/complete")
        assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------
# Get experiment results
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetExperimentResults:
    """GET /api/v1/experiments/{id}/results

    Delegates to the analytics results engine (same payload as
    GET /api/v1/results/{id} with default options) after applying the
    experiment access rules.
    """

    def test_get_results_for_active_experiment(self, admin_client):
        exp = _create_and_start(admin_client, "Results Active Exp")
        response = admin_client.get(f"/api/v1/experiments/{exp['id']}/results")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["experiment_id"] == exp["id"]
        assert data["experiment_name"] == exp["name"]
        assert data["status"].lower() == "active"
        assert data["confidence_level"] == 0.95
        # Same shape as the analytics results endpoint
        mirror = admin_client.get(f"/api/v1/results/{exp['id']}")
        assert mirror.status_code == 200, mirror.text
        assert set(data.keys()) == set(mirror.json().keys())

    def test_get_results_for_draft_experiment_returns_400(self, admin_client):
        exp = _create_experiment(admin_client, "Results Draft Exp")
        response = admin_client.get(f"/api/v1/experiments/{exp['id']}/results")
        assert response.status_code == 400, response.text

    def test_get_results_nonexistent_experiment_returns_404(self, admin_client):
        fake_id = "00000000-0000-0000-0000-000000000013"
        response = admin_client.get(f"/api/v1/experiments/{fake_id}/results")
        assert response.status_code == 404, response.text

    def test_analyst_cannot_get_results_for_other_users_experiment(
        self, admin_client, analyst_user, db_session
    ):
        exp = _create_and_start(admin_client, "Results Analyst Forbidden")
        analyst_client = make_client_for_user(db_session, analyst_user)
        response = analyst_client.get(f"/api/v1/experiments/{exp['id']}/results")
        assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------
# Archive experiment
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestArchiveExperiment:
    """POST /api/v1/experiments/{id}/archive"""

    def test_admin_can_archive_draft_experiment(self, admin_client):
        exp = _create_experiment(admin_client, "Archive Me")
        response = admin_client.post(f"/api/v1/experiments/{exp['id']}/archive")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "archived"
        assert len(data["metrics"]) == 1

    def test_archive_already_archived_returns_400(self, admin_client):
        exp = _create_experiment(admin_client, "Double Archive")
        first = admin_client.post(f"/api/v1/experiments/{exp['id']}/archive")
        assert first.status_code == 200, first.text

        second = admin_client.post(f"/api/v1/experiments/{exp['id']}/archive")
        assert second.status_code == 400, second.text

    def test_archive_nonexistent_experiment_returns_404(self, admin_client):
        fake_id = "00000000-0000-0000-0000-000000000014"
        response = admin_client.post(f"/api/v1/experiments/{fake_id}/archive")
        assert response.status_code == 404, response.text

    def test_viewer_cannot_archive_other_users_experiment(
        self, admin_client, viewer_user, db_session
    ):
        exp = _create_experiment(admin_client, "Archive Viewer Forbidden")
        viewer_client = make_client_for_user(db_session, viewer_user)
        response = viewer_client.post(f"/api/v1/experiments/{exp['id']}/archive")
        assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------
# Clone experiment
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCloneExperiment:
    """POST /api/v1/experiments/{id}/clone"""

    def test_admin_can_clone_experiment(self, admin_client):
        """Cloning copies the variants and metric definitions into a new DRAFT
        experiment with its own id and key."""
        exp = _create_experiment(admin_client, "Clone Source")
        response = admin_client.post(f"/api/v1/experiments/{exp['id']}/clone")
        assert response.status_code == 201, response.text
        clone = response.json()

        assert clone["id"] != exp["id"]
        assert clone["status"].lower() == "draft"
        assert clone.get("key") != exp.get("key")
        assert sorted(v["name"] for v in clone["variants"]) == sorted(
            v["name"] for v in exp["variants"]
        )
        assert [m["name"] for m in clone["metrics"]] == [
            m["name"] for m in exp["metrics"]
        ]
        assert [m["event_name"] for m in clone["metrics"]] == [
            m["event_name"] for m in exp["metrics"]
        ]

    def test_clone_nonexistent_experiment_returns_404(self, admin_client):
        fake_id = "00000000-0000-0000-0000-000000000015"
        response = admin_client.post(f"/api/v1/experiments/{fake_id}/clone")
        assert response.status_code == 404, response.text

    def test_analyst_cannot_clone_other_users_experiment(
        self, admin_client, analyst_user, db_session
    ):
        exp = _create_experiment(admin_client, "Clone Analyst Forbidden")
        analyst_client = make_client_for_user(db_session, analyst_user)
        response = analyst_client.post(f"/api/v1/experiments/{exp['id']}/clone")
        assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------
# Daily experiment results
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDailyExperimentResults:
    """GET /api/v1/experiments/{id}/daily-results"""

    def test_get_daily_results_for_active_experiment(self, admin_client):
        exp = _create_and_start(admin_client, "Daily Results Active")
        response = admin_client.get(f"/api/v1/experiments/{exp['id']}/daily-results")
        assert response.status_code == 200, response.text
        assert isinstance(response.json(), list)

    def test_get_daily_results_with_metric_id(self, admin_client):
        exp = _create_and_start(admin_client, "Daily Results Metric Filter")
        metric_id = exp["metrics"][0]["id"]
        response = admin_client.get(
            f"/api/v1/experiments/{exp['id']}/daily-results",
            params={"metric_id": metric_id},
        )
        assert response.status_code == 200, response.text
        assert isinstance(response.json(), list)

    def test_get_daily_results_draft_experiment_returns_400(self, admin_client):
        exp = _create_experiment(admin_client, "Daily Results Draft")
        response = admin_client.get(f"/api/v1/experiments/{exp['id']}/daily-results")
        assert response.status_code == 400, response.text

    def test_get_daily_results_nonexistent_returns_404(self, admin_client):
        fake_id = "00000000-0000-0000-0000-000000000016"
        response = admin_client.get(f"/api/v1/experiments/{fake_id}/daily-results")
        assert response.status_code == 404, response.text

    def test_viewer_cannot_get_daily_results_for_other_users_experiment(
        self, admin_client, viewer_user, db_session
    ):
        exp = _create_and_start(admin_client, "Daily Results Viewer Forbidden")
        viewer_client = make_client_for_user(db_session, viewer_user)
        response = viewer_client.get(f"/api/v1/experiments/{exp['id']}/daily-results")
        assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------
# Segmented experiment results
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSegmentedExperimentResults:
    """GET /api/v1/experiments/{id}/segmented-results/{segment_by}"""

    def test_get_segmented_results_for_active_experiment(self, admin_client):
        exp = _create_and_start(admin_client, "Segmented Results Active")
        response = admin_client.get(
            f"/api/v1/experiments/{exp['id']}/segmented-results/country"
        )
        assert response.status_code == 200, response.text
        assert isinstance(response.json(), dict)

    def test_get_segmented_results_with_metric_id(self, admin_client):
        exp = _create_and_start(admin_client, "Segmented Results Metric Filter")
        metric_id = exp["metrics"][0]["id"]
        response = admin_client.get(
            f"/api/v1/experiments/{exp['id']}/segmented-results/country",
            params={"metric_id": metric_id},
        )
        assert response.status_code == 200, response.text
        assert isinstance(response.json(), dict)

    def test_get_segmented_results_draft_returns_400(self, admin_client):
        exp = _create_experiment(admin_client, "Segmented Results Draft")
        response = admin_client.get(
            f"/api/v1/experiments/{exp['id']}/segmented-results/country"
        )
        assert response.status_code == 400, response.text

    def test_get_segmented_results_nonexistent_returns_404(self, admin_client):
        fake_id = "00000000-0000-0000-0000-000000000017"
        response = admin_client.get(
            f"/api/v1/experiments/{fake_id}/segmented-results/country"
        )
        assert response.status_code == 404, response.text

    def test_analyst_cannot_get_segmented_results_for_other_users_experiment(
        self, admin_client, analyst_user, db_session
    ):
        exp = _create_and_start(admin_client, "Segmented Results Analyst Forbidden")
        analyst_client = make_client_for_user(db_session, analyst_user)
        response = analyst_client.get(
            f"/api/v1/experiments/{exp['id']}/segmented-results/country"
        )
        assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------
# Update experiment metadata
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestUpdateExperimentMetadata:
    """POST /api/v1/experiments/{id}/metadata"""

    def test_update_metadata(self, admin_client):
        exp = _create_experiment(admin_client, "Metadata Update Exp")
        response = admin_client.post(
            f"/api/v1/experiments/{exp['id']}/metadata",
            json={"notes": "some learnings", "insight_score": 5},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["experiment_metadata"]["notes"] == "some learnings"
        assert data["experiment_metadata"]["insight_score"] == 5

    def test_update_metadata_merges_with_existing_keys(self, admin_client):
        """A second call merges new keys without dropping previously-set ones."""
        exp = _create_experiment(admin_client, "Metadata Merge Exp")
        first = admin_client.post(
            f"/api/v1/experiments/{exp['id']}/metadata", json={"a": 1}
        )
        assert first.status_code == 200, first.text

        second = admin_client.post(
            f"/api/v1/experiments/{exp['id']}/metadata", json={"b": 2}
        )
        assert second.status_code == 200, second.text
        merged = second.json()["experiment_metadata"]
        assert merged["a"] == 1
        assert merged["b"] == 2

    def test_update_metadata_nonexistent_experiment_returns_404(self, admin_client):
        fake_id = "00000000-0000-0000-0000-000000000018"
        response = admin_client.post(
            f"/api/v1/experiments/{fake_id}/metadata", json={"notes": "x"}
        )
        assert response.status_code == 404, response.text

    def test_viewer_cannot_update_metadata_for_other_users_experiment(
        self, admin_client, viewer_user, db_session
    ):
        exp = _create_experiment(admin_client, "Metadata Viewer Forbidden")
        viewer_client = make_client_for_user(db_session, viewer_user)
        response = viewer_client.post(
            f"/api/v1/experiments/{exp['id']}/metadata", json={"notes": "x"}
        )
        assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------
# Calculate sample size
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCalculateSampleSize:
    """GET /api/v1/experiments/analysis/sample-size"""

    def test_basic_sample_size_calculation(self, admin_client):
        response = admin_client.get(
            "/api/v1/experiments/analysis/sample-size",
            params={"baseline_rate": 0.1, "minimum_detectable_effect": 0.1},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["samples_per_variant"] > 0
        assert data["total_samples"] == data["samples_per_variant"] * 2
        assert data["estimated_duration_days"] is None

    def test_sample_size_one_sided(self, admin_client):
        response = admin_client.get(
            "/api/v1/experiments/analysis/sample-size",
            params={
                "baseline_rate": 0.2,
                "minimum_detectable_effect": 0.05,
                "is_one_sided": True,
            },
        )
        assert response.status_code == 200, response.text

    def test_sample_size_with_traffic_estimates_short_duration(self, admin_client):
        """Large daily_traffic + high allocation -> short duration note."""
        response = admin_client.get(
            "/api/v1/experiments/analysis/sample-size",
            params={
                "baseline_rate": 0.3,
                "minimum_detectable_effect": 0.5,
                "daily_traffic": 1000000,
                "traffic_allocation": 1.0,
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["estimated_duration_days"] is not None
        assert "days" in data["estimated_duration_days"]

    def test_sample_size_with_traffic_estimates_long_duration(self, admin_client):
        """Small daily_traffic + tiny effect -> long duration note (>90 days)."""
        response = admin_client.get(
            "/api/v1/experiments/analysis/sample-size",
            params={
                "baseline_rate": 0.05,
                "minimum_detectable_effect": 0.02,
                "daily_traffic": 50,
                "traffic_allocation": 0.1,
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["estimated_duration_days"]["days"] > 90
        assert data["notes"] is not None

    def test_sample_size_custom_variant_count(self, admin_client):
        response = admin_client.get(
            "/api/v1/experiments/analysis/sample-size",
            params={
                "baseline_rate": 0.15,
                "minimum_detectable_effect": 0.2,
                "variant_count": 4,
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["total_samples"] == data["samples_per_variant"] * 4

    def test_sample_size_invalid_baseline_rate_returns_422(self, admin_client):
        response = admin_client.get(
            "/api/v1/experiments/analysis/sample-size",
            params={"baseline_rate": 1.5, "minimum_detectable_effect": 0.1},
        )
        assert response.status_code == 422, response.text

    def test_sample_size_missing_required_params_returns_422(self, admin_client):
        response = admin_client.get("/api/v1/experiments/analysis/sample-size")
        assert response.status_code == 422, response.text

    def test_sample_size_custom_significance_and_power(self, admin_client):
        """Exercises non-exact-match z-score central-region approximation branch."""
        response = admin_client.get(
            "/api/v1/experiments/analysis/sample-size",
            params={
                "baseline_rate": 0.12,
                "minimum_detectable_effect": 0.15,
                "significance_level": 0.07,
                "statistical_power": 0.85,
            },
        )
        assert response.status_code == 200, response.text

    def test_sample_size_traffic_allocation_out_of_range_returns_422(
        self, admin_client
    ):
        """The endpoint has a manual `traffic_allocation <= 0 or > 1` 400
        check, but it is dead code: the Query parameter itself already
        declares gt=0, le=1, so FastAPI rejects out-of-range values with 422
        before the handler body ever runs.
        """
        response = admin_client.get(
            "/api/v1/experiments/analysis/sample-size",
            params={
                "baseline_rate": 0.1,
                "minimum_detectable_effect": 0.1,
                "daily_traffic": 1000,
                "traffic_allocation": 1.5,
            },
        )
        assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# stats_z_score helper (module-level function). Both alpha/beta inputs to it
# are always < 0.5 through the sample-size endpoint (significance_level and
# 1-statistical_power are bounded well below 0.5), so the upper-region
# (p >= 0.97575) branch is unreachable via HTTP; we exercise it directly.
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStatsZScoreHelper:
    def test_exact_common_values(self):
        assert stats_z_score(0.05) == 1.96
        assert stats_z_score(0.01) == 2.58
        assert stats_z_score(0.1) == 1.65
        assert stats_z_score(0.2) == 1.28
        assert stats_z_score(0.5) == 0.67

    def test_lower_region_approximation(self):
        """p < 0.02425 -> large-magnitude negative z (left tail)."""
        z = stats_z_score(0.001)
        assert z < -2.5

    def test_central_region_approximation_left_of_median(self):
        """0.02425 <= p < 0.5 -> negative z."""
        z = stats_z_score(0.3)
        assert -1 < z < 0

    def test_central_region_approximation_right_of_median(self):
        """0.5 < p < 0.97575 -> positive z."""
        z = stats_z_score(0.7)
        assert 0 < z < 1

    def test_upper_region_approximation(self):
        """p >= 0.97575 -> large-magnitude positive z (right tail)."""
        z = stats_z_score(0.999)
        assert z > 2.5

    def test_invalid_probability_raises_value_error(self):
        with pytest.raises(ValueError):
            stats_z_score(0)
        with pytest.raises(ValueError):
            stats_z_score(1)
        with pytest.raises(ValueError):
            stats_z_score(-0.1)


# ---------------------------------------------------------------------------
# Trigger schedule processing (admin-only)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTriggerScheduleProcessing:
    """POST /api/v1/experiments/schedules/process"""

    def test_admin_can_trigger_schedule_processing(self, admin_client):
        response = admin_client.post("/api/v1/experiments/schedules/process")
        assert response.status_code == 202, response.text
        assert "status" in response.json()

    def test_developer_cannot_trigger_schedule_processing(self, developer_client):
        response = developer_client.post("/api/v1/experiments/schedules/process")
        assert response.status_code == 403, response.text

    def test_analyst_cannot_trigger_schedule_processing(self, analyst_client):
        response = analyst_client.post("/api/v1/experiments/schedules/process")
        assert response.status_code == 403, response.text

    def test_viewer_cannot_trigger_schedule_processing(self, viewer_client):
        response = viewer_client.post("/api/v1/experiments/schedules/process")
        assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------
# Preview split URL assignment
# ---------------------------------------------------------------------------


@pytest.mark.enterprise
@pytest.mark.integration
class TestPreviewSplitUrlAssignment:
    """GET /api/v1/experiments/{id}/split-url/preview"""

    def test_admin_preview_split_url_assignment_with_stored_config(self, admin_client):
        """`_experiment_to_dict()` now includes `split_url_config`, so the
        preview endpoint returns a deterministic variant assignment.
        """
        payload = _split_url_payload("Split URL Preview Exp")
        create_response = admin_client.post("/api/v1/experiments/", json=payload)
        assert create_response.status_code == 201, create_response.text
        exp_id = create_response.json()["id"]

        response = admin_client.get(
            f"/api/v1/experiments/{exp_id}/split-url/preview",
            params={"user_id": "user-abc-123"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["experiment_id"] == exp_id
        assert data["user_id"] == "user-abc-123"
        assert data["variant_name"] in ("Control", "Treatment")
        assert data["url"] in ("https://example.com/a", "https://example.com/b")
        assert data["traffic_allocation"] == 50

    def test_preview_assignment_is_deterministic_for_same_user(self, admin_client):
        """The same (user_id, experiment) pair always resolves to the same
        variant (stable hashing), across repeated calls.
        """
        payload = _split_url_payload("Split URL Preview Deterministic Exp")
        create_response = admin_client.post("/api/v1/experiments/", json=payload)
        assert create_response.status_code == 201, create_response.text
        exp_id = create_response.json()["id"]

        first = admin_client.get(
            f"/api/v1/experiments/{exp_id}/split-url/preview",
            params={"user_id": "stable-user-42"},
        )
        second = admin_client.get(
            f"/api/v1/experiments/{exp_id}/split-url/preview",
            params={"user_id": "stable-user-42"},
        )
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json()["variant_name"] == second.json()["variant_name"]
        assert first.json()["url"] == second.json()["url"]

    def test_developer_can_preview_split_url_assignment(self, developer_client):
        payload = _split_url_payload("Split URL Preview Dev Exp")
        create_response = developer_client.post("/api/v1/experiments/", json=payload)
        assert create_response.status_code == 201, create_response.text
        exp_id = create_response.json()["id"]

        response = developer_client.get(
            f"/api/v1/experiments/{exp_id}/split-url/preview",
            params={"user_id": "user-xyz"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["variant_name"] in ("Control", "Treatment")

    def test_analyst_cannot_preview_split_url_assignment(
        self, admin_client, analyst_user, db_session
    ):
        payload = _split_url_payload("Split URL Preview Analyst Forbidden")
        create_response = admin_client.post("/api/v1/experiments/", json=payload)
        assert create_response.status_code == 201, create_response.text
        exp_id = create_response.json()["id"]

        analyst_client = make_client_for_user(db_session, analyst_user)
        response = analyst_client.get(
            f"/api/v1/experiments/{exp_id}/split-url/preview",
            params={"user_id": "user-1"},
        )
        assert response.status_code == 403, response.text

    def test_viewer_cannot_preview_split_url_assignment(
        self, admin_client, viewer_user, db_session
    ):
        payload = _split_url_payload("Split URL Preview Viewer Forbidden")
        create_response = admin_client.post("/api/v1/experiments/", json=payload)
        assert create_response.status_code == 201, create_response.text
        exp_id = create_response.json()["id"]

        viewer_client = make_client_for_user(db_session, viewer_user)
        response = viewer_client.get(
            f"/api/v1/experiments/{exp_id}/split-url/preview",
            params={"user_id": "user-1"},
        )
        assert response.status_code == 403, response.text

    def test_preview_nonexistent_experiment_returns_404(self, admin_client):
        fake_id = "00000000-0000-0000-0000-000000000019"
        response = admin_client.get(
            f"/api/v1/experiments/{fake_id}/split-url/preview",
            params={"user_id": "user-1"},
        )
        assert response.status_code == 404, response.text

    def test_preview_non_split_url_experiment_returns_400(self, admin_client):
        """A regular a_b experiment cannot be previewed via split-url endpoint."""
        exp = _create_experiment(admin_client, "Preview Wrong Type Exp")
        response = admin_client.get(
            f"/api/v1/experiments/{exp['id']}/split-url/preview",
            params={"user_id": "user-1"},
        )
        assert response.status_code == 400, response.text

    def test_preview_split_url_without_config_returns_400(self, admin_client):
        """split_url experiment_type but no split_url_config set -> 400."""
        payload = _split_url_payload("Split URL No Config Exp", with_config=False)
        create_response = admin_client.post("/api/v1/experiments/", json=payload)
        assert create_response.status_code == 201, create_response.text
        exp_id = create_response.json()["id"]

        response = admin_client.get(
            f"/api/v1/experiments/{exp_id}/split-url/preview",
            params={"user_id": "user-1"},
        )
        assert response.status_code == 400, response.text
