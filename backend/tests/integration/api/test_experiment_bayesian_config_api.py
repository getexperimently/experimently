"""
Bayesian analysis is turned on through the experiments API (#216).

Before the fix, ``ExperimentCreate`` and ``ExperimentUpdate`` did not declare
``bayesian_enabled`` or ``bayesian_config``: pydantic dropped them, the API
answered 201/200, and every experiment reported ``"is_enabled": false`` on
``GET /results/{id}/bayesian``.  The response and ``_experiment_to_dict`` also
omitted the sequential-testing and variance-reduction fields.

Pinned here, against a real database:

* create and update persist the Bayesian fields, and the Bayesian endpoint
  then reports ``is_enabled: true`` with one entry per variant;
* enabling with no config stores the ``BayesianConfig`` defaults;
* ``bayesian_decision`` is response-only: a client cannot set it;
* a malformed config is refused with 422 naming the field;
* the scheduler does not stop an ACTIVE experiment on a stored decision.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.schemas.bayesian import BayesianConfig

pytestmark = [pytest.mark.integration, pytest.mark.regression]


CUSTOM_CONFIG = {
    "prior_family": "beta",
    "alpha": 2.0,
    "beta": 3.0,
    "loss_threshold": 0.002,
    "rope": [-0.005, 0.005],
    "credible_level": 0.9,
}


def _payload(name: str, **extra) -> dict:
    payload = {
        "name": name,
        "hypothesis": "Green button increases conversion rate",
        "variants": [
            {"name": "control", "is_control": True, "traffic_allocation": 50},
            {"name": "treatment", "is_control": False, "traffic_allocation": 50},
        ],
        "metrics": [
            {"name": "Checkout", "event_name": "checkout_completed", "is_primary": True}
        ],
    }
    payload.update(extra)
    return payload


def _create(client: TestClient, name: str, **extra) -> dict:
    response = client.post("/api/v1/experiments/", json=_payload(name, **extra))
    assert response.status_code == 201, response.text
    return response.json()


def _stored(db_session: Session, experiment_id: str) -> Experiment:
    db_session.expire_all()
    return db_session.query(Experiment).filter(Experiment.id == experiment_id).one()


def _bayesian(client: TestClient, experiment_id: str) -> dict:
    response = client.get(f"/api/v1/results/{experiment_id}/bayesian")
    assert response.status_code == 200, response.text
    return response.json()


class TestTurningBayesianOn:
    def test_create_persists_config_and_enables_analysis(
        self, admin_client: TestClient, db_session: Session
    ):
        body = _create(
            admin_client,
            "Bayesian on create",
            bayesian_enabled=True,
            bayesian_config=CUSTOM_CONFIG,
        )
        assert body["bayesian_enabled"] is True
        assert body["bayesian_config"] == CUSTOM_CONFIG
        assert body["bayesian_decision"] is None

        stored = _stored(db_session, body["id"])
        assert stored.bayesian_enabled is True
        assert stored.bayesian_config == CUSTOM_CONFIG

        fetched = admin_client.get(f"/api/v1/experiments/{body['id']}")
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["bayesian_enabled"] is True
        assert fetched.json()["bayesian_config"] == CUSTOM_CONFIG

        result = _bayesian(admin_client, body["id"])
        assert result["is_enabled"] is True
        assert len(result["variant_results"]) == 2
        assert {v["variant_key"] for v in result["variant_results"]} == {
            "control",
            "treatment",
        }

    def test_create_enabled_without_config_stores_defaults(
        self, admin_client: TestClient, db_session: Session
    ):
        body = _create(admin_client, "Bayesian defaults", bayesian_enabled=True)
        defaults = BayesianConfig().model_dump(mode="json")
        assert body["bayesian_config"] == defaults
        assert _stored(db_session, body["id"]).bayesian_config == defaults

        result = _bayesian(admin_client, body["id"])
        assert result["is_enabled"] is True
        assert len(result["variant_results"]) == 2

    def test_create_without_bayesian_stays_off(
        self, admin_client: TestClient, db_session: Session
    ):
        body = _create(admin_client, "Bayesian off")
        assert body["bayesian_enabled"] is False
        assert body["bayesian_config"] is None
        assert _bayesian(admin_client, body["id"])["is_enabled"] is False

    def test_update_persists_config_and_enables_analysis(
        self, admin_client: TestClient, db_session: Session
    ):
        body = _create(admin_client, "Bayesian on update")
        assert _bayesian(admin_client, body["id"])["is_enabled"] is False

        response = admin_client.put(
            f"/api/v1/experiments/{body['id']}",
            json={"bayesian_enabled": True, "bayesian_config": CUSTOM_CONFIG},
        )
        assert response.status_code == 200, response.text
        assert response.json()["bayesian_enabled"] is True
        assert response.json()["bayesian_config"] == CUSTOM_CONFIG

        stored = _stored(db_session, body["id"])
        assert stored.bayesian_enabled is True
        assert stored.bayesian_config == CUSTOM_CONFIG

        result = _bayesian(admin_client, body["id"])
        assert result["is_enabled"] is True
        assert len(result["variant_results"]) == 2

    def test_update_enabled_without_config_stores_defaults(
        self, admin_client: TestClient, db_session: Session
    ):
        body = _create(admin_client, "Bayesian defaults on update")
        response = admin_client.put(
            f"/api/v1/experiments/{body['id']}", json={"bayesian_enabled": True}
        )
        assert response.status_code == 200, response.text
        defaults = BayesianConfig().model_dump(mode="json")
        assert response.json()["bayesian_config"] == defaults
        assert _stored(db_session, body["id"]).bayesian_config == defaults

    def test_update_enabled_keeps_a_stored_config(
        self, admin_client: TestClient, db_session: Session
    ):
        body = _create(
            admin_client,
            "Bayesian re-enable",
            bayesian_enabled=True,
            bayesian_config=CUSTOM_CONFIG,
        )
        off = admin_client.put(
            f"/api/v1/experiments/{body['id']}", json={"bayesian_enabled": False}
        )
        assert off.status_code == 200, off.text
        assert _bayesian(admin_client, body["id"])["is_enabled"] is False

        on = admin_client.put(
            f"/api/v1/experiments/{body['id']}", json={"bayesian_enabled": True}
        )
        assert on.status_code == 200, on.text
        assert _stored(db_session, body["id"]).bayesian_config == CUSTOM_CONFIG


class TestSiblingAnalysisFields:
    def test_sequential_and_variance_reduction_fields_are_returned(
        self, admin_client: TestClient, db_session: Session
    ):
        body = _create(
            admin_client,
            "Sibling fields",
            sequential_testing_enabled=True,
            sequential_testing_config={"method": "msprt", "tau_squared": 0.002},
            variance_reduction_config={"method": "winsorization"},
        )
        assert body["sequential_testing_enabled"] is True
        assert body["sequential_testing_config"]["tau_squared"] == 0.002
        assert body["variance_reduction_config"]["method"] == "winsorization"

        stored = _stored(db_session, body["id"])
        assert stored.sequential_testing_enabled is True
        assert stored.variance_reduction_config["method"] == "winsorization"

        updated = admin_client.put(
            f"/api/v1/experiments/{body['id']}",
            json={"variance_reduction_config": {"method": "none"}},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["variance_reduction_config"]["method"] == "none"
        assert updated.json()["sequential_testing_enabled"] is True


class TestDecisionIsResponseOnly:
    def test_put_bayesian_decision_is_ignored(
        self, admin_client: TestClient, db_session: Session
    ):
        body = _create(admin_client, "Decision is read-only", bayesian_enabled=True)

        response = admin_client.put(
            f"/api/v1/experiments/{body['id']}",
            json={"bayesian_decision": "STOP_WINNER"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["bayesian_decision"] is None
        assert _stored(db_session, body["id"]).bayesian_decision is None

    def test_post_bayesian_decision_is_ignored(
        self, admin_client: TestClient, db_session: Session
    ):
        body = _create(
            admin_client, "Decision on create", bayesian_decision="STOP_WINNER"
        )
        assert body["bayesian_decision"] is None
        assert _stored(db_session, body["id"]).bayesian_decision is None


class TestMalformedConfig:
    @pytest.mark.parametrize(
        ("config", "field"),
        [
            ({"alpha": -1}, "alpha"),
            ({"rope": [0.01, -0.01]}, "rope"),
            ({"prior_family": "cauchy"}, "prior_family"),
            ({"credible_level": 1.5}, "credible_level"),
        ],
    )
    def test_create_refuses_malformed_config(
        self, admin_client: TestClient, config: dict, field: str
    ):
        response = admin_client.post(
            "/api/v1/experiments/",
            json=_payload(
                "Malformed config", bayesian_enabled=True, bayesian_config=config
            ),
        )
        assert response.status_code == 422, response.text
        locations = [err["loc"] for err in response.json()["detail"]]
        assert ["body", "bayesian_config", field] in [
            list(loc[:3]) for loc in locations
        ], locations

    def test_update_refuses_malformed_config(
        self, admin_client: TestClient, db_session: Session
    ):
        body = _create(admin_client, "Malformed on update")
        response = admin_client.put(
            f"/api/v1/experiments/{body['id']}",
            json={"bayesian_enabled": True, "bayesian_config": {"loss_threshold": 0}},
        )
        assert response.status_code == 422, response.text
        locations = [list(err["loc"][:3]) for err in response.json()["detail"]]
        assert ["body", "bayesian_config", "loss_threshold"] in locations, locations
        assert _stored(db_session, body["id"]).bayesian_enabled is False


class TestSchedulerDoesNotStopOnDecision:
    @pytest.mark.parametrize("decision", ["STOP_WINNER", "STOP_FUTILE"])
    def test_active_experiment_with_stop_decision_stays_active(
        self, db_session: Session, make_experiment, decision: str
    ):
        from backend.app.core.scheduler import ExperimentScheduler

        experiment = make_experiment(
            name=f"Stored {decision}",
            status=ExperimentStatus.ACTIVE,
            start_date=datetime.now(timezone.utc) - timedelta(days=3),
            bayesian_enabled=True,
            bayesian_config=BayesianConfig().model_dump(mode="json"),
            bayesian_decision=decision,
        )
        experiment_id = experiment.id

        factory = sessionmaker(bind=db_session.get_bind())

        def scheduler_session():
            session = factory()
            session.execute(text("SET search_path TO test_experimentation"))
            return session

        with patch("backend.app.core.scheduler.SessionLocal", scheduler_session):
            asyncio.run(ExperimentScheduler().process_scheduled_experiments())

        stored = _stored(db_session, experiment_id)
        assert stored.status == ExperimentStatus.ACTIVE
        assert stored.bayesian_decision == decision


class TestClearingTheConfig:
    """An explicit ``bayesian_config: null`` must not silently reset the config.

    With Bayesian already on and ``bayesian_enabled`` absent from the PUT, a
    null config used to fall through to the "enabled with no config" fallback
    and replace a custom config with the defaults, answering 200.
    """

    def test_null_config_while_enabled_is_refused(
        self, admin_client: TestClient, db_session: Session
    ):
        body = _create(
            admin_client,
            "Clear while enabled",
            bayesian_enabled=True,
            bayesian_config=CUSTOM_CONFIG,
        )
        response = admin_client.put(
            f"/api/v1/experiments/{body['id']}", json={"bayesian_config": None}
        )
        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert [err["loc"] for err in detail] == [["body", "bayesian_config"]]
        assert "bayesian_enabled: false" in detail[0]["msg"]

        stored = _stored(db_session, body["id"])
        assert stored.bayesian_enabled is True
        assert stored.bayesian_config == CUSTOM_CONFIG

    def test_null_config_with_enabled_true_is_refused(
        self, admin_client: TestClient, db_session: Session
    ):
        body = _create(
            admin_client,
            "Clear and enable",
            bayesian_enabled=True,
            bayesian_config=CUSTOM_CONFIG,
        )
        response = admin_client.put(
            f"/api/v1/experiments/{body['id']}",
            json={"bayesian_enabled": True, "bayesian_config": None},
        )
        assert response.status_code == 422, response.text
        assert _stored(db_session, body["id"]).bayesian_config == CUSTOM_CONFIG

    def test_disable_and_null_together_clears(
        self, admin_client: TestClient, db_session: Session
    ):
        body = _create(
            admin_client,
            "Disable and clear",
            bayesian_enabled=True,
            bayesian_config=CUSTOM_CONFIG,
        )
        response = admin_client.put(
            f"/api/v1/experiments/{body['id']}",
            json={"bayesian_enabled": False, "bayesian_config": None},
        )
        assert response.status_code == 200, response.text
        assert response.json()["bayesian_enabled"] is False
        assert response.json()["bayesian_config"] is None

        stored = _stored(db_session, body["id"])
        assert stored.bayesian_enabled is False
        assert stored.bayesian_config is None
        assert _bayesian(admin_client, body["id"])["is_enabled"] is False

    def test_update_touching_neither_field_keeps_the_config(
        self, admin_client: TestClient, db_session: Session
    ):
        body = _create(
            admin_client,
            "Untouched config",
            bayesian_enabled=True,
            bayesian_config=CUSTOM_CONFIG,
        )
        response = admin_client.put(
            f"/api/v1/experiments/{body['id']}",
            json={"description": "renamed only"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["bayesian_config"] == CUSTOM_CONFIG

        stored = _stored(db_session, body["id"])
        assert stored.bayesian_enabled is True
        assert stored.bayesian_config == CUSTOM_CONFIG
