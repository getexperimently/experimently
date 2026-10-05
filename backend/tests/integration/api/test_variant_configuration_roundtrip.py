"""A variant configuration created with ``POST /experiments`` reaches the SDK unchanged (#442).

The dashboard's create form sends each variant's ``configuration`` as the JSON
object the user typed. These tests create an experiment the way the form does,
start it, and read the configuration back from the experiment response (what
the experiment page shows) and from ``POST /tracking/assign`` (what an SDK
receives). Nested values, non-ASCII text, and every JSON value type must come
back equal; a variant created without a configuration must come back ``null``,
not ``{}``.

The other tracking tests write ``configuration`` straight into the database, so
none of them covers the path from the create request.
"""

import uuid

import pytest

from backend.app.models.assignment import Assignment
from backend.app.models.experiment import Experiment

pytestmark = [pytest.mark.integration, pytest.mark.api]

#: Every JSON value type, nesting, and text outside ASCII.
CONFIGURATION = {
    "headline": "Un clic, c’est fait ✓ 日本語",
    "layout": {
        "columns": 2,
        "steps": ["cart", "pay"],
        "nested": {"deep": [1, {"x": None}]},
    },
    "express": True,
    "disabled": False,
    "discount": 0.15,
    "count": 3,
    "badge": None,
    "empty_list": [],
    "empty_object": {},
}


def _create_payload(suffix: str, configuration: dict | None) -> dict:
    treatment = {"name": "Treatment", "is_control": False, "traffic_allocation": 100}
    if configuration is not None:
        treatment["configuration"] = configuration
    return {
        "name": f"Configuration round trip {suffix}",
        "key": f"config_roundtrip_{suffix}",
        "experiment_type": "a_b",
        # All traffic to the treatment, so every assignment returns its configuration.
        "variants": [
            {"name": "Control", "is_control": True, "traffic_allocation": 0},
            treatment,
        ],
        "metrics": [
            {
                "name": "Conversion",
                "event_name": "conversion",
                "metric_type": "conversion",
                "is_primary": True,
            }
        ],
        "bayesian_enabled": True,
    }


@pytest.fixture
def created_ids(db_session):
    ids: list[str] = []
    yield ids
    db_session.rollback()
    for experiment_id in ids:
        db_session.query(Assignment).filter(
            Assignment.experiment_id == experiment_id
        ).delete()
        experiment = db_session.get(Experiment, uuid.UUID(experiment_id))
        if experiment is not None:
            db_session.delete(experiment)
    db_session.commit()


def _create_and_start(client, payload: dict, created_ids: list[str]) -> dict:
    created = client.post("/api/v1/experiments/", json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    created_ids.append(body["id"])
    started = client.post(f"/api/v1/experiments/{body['id']}/start")
    assert started.status_code == 200, started.text
    return body


def test_configuration_from_create_comes_back_unchanged_from_assign(
    admin_client, created_ids
):
    suffix = uuid.uuid4().hex[:8]
    created = _create_and_start(
        admin_client, _create_payload(suffix, CONFIGURATION), created_ids
    )

    by_name = {v["name"]: v for v in created["variants"]}
    assert by_name["Treatment"]["configuration"] == CONFIGURATION
    assert by_name["Control"]["configuration"] is None
    assert created["bayesian_enabled"] is True

    shown = admin_client.get(f"/api/v1/experiments/{created['id']}")
    assert shown.status_code == 200, shown.text
    shown_by_name = {v["name"]: v for v in shown.json()["variants"]}
    assert shown_by_name["Treatment"]["configuration"] == CONFIGURATION

    assigned = admin_client.post(
        "/api/v1/tracking/assign",
        json={"experiment_key": created["key"], "user_id": f"user-{suffix}"},
    )
    assert assigned.status_code == 200, assigned.text
    data = assigned.json()
    assert data["variant_name"] == "Treatment"
    assert data["configuration"] == CONFIGURATION
    # Numbers keep their JSON type: 0.15 stays a float, 3 stays an int.
    assert isinstance(data["configuration"]["discount"], float)
    assert isinstance(data["configuration"]["count"], int)
    assert data["configuration"]["headline"] == "Un clic, c’est fait ✓ 日本語"


def test_a_variant_created_without_configuration_assigns_null(
    admin_client, created_ids
):
    suffix = uuid.uuid4().hex[:8]
    created = _create_and_start(
        admin_client, _create_payload(suffix, None), created_ids
    )

    assigned = admin_client.post(
        "/api/v1/tracking/assign",
        json={"experiment_key": created["key"], "user_id": f"user-{suffix}"},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["configuration"] is None


@pytest.mark.parametrize("configuration", [[1, 2], "blue", 1, True])
def test_create_refuses_a_configuration_that_is_not_an_object(
    admin_client, configuration
):
    """The form refuses these before sending; the API refuses them too."""
    payload = _create_payload(uuid.uuid4().hex[:8], None)
    payload["variants"][1]["configuration"] = configuration
    response = admin_client.post("/api/v1/experiments/", json=payload)
    assert response.status_code == 422, response.text
    locations = [tuple(item["loc"]) for item in response.json()["detail"]]
    assert ("body", "variants", 1, "configuration") in locations
