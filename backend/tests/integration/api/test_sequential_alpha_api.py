"""
The sequential significance level, end to end through the database (#222).

An experiment created or updated through ``/api/v1/experiments/`` with
``sequential_testing_config.alpha`` is analysed at that level by
``GET /api/v1/results/{id}/sequential``: the mSPRT boundary is 1/alpha.  On
main the input schema had no ``alpha``, so the value was dropped on the way in
and every analysis ran at 0.05.

The experiment has no assignments, so the counts are zero; the boundary does
not depend on them.
"""

import uuid

import pytest
from fastapi.testclient import TestClient


def _payload(sequential_config: dict) -> dict:
    return {
        "name": f"Sequential alpha {uuid.uuid4().hex[:8]}",
        "description": "Sequential alpha integration test",
        "hypothesis": "The configured significance level is used",
        "experiment_type": "a_b",
        "variants": [
            {"name": "Control", "is_control": True, "traffic_allocation": 50},
            {"name": "Treatment", "is_control": False, "traffic_allocation": 50},
        ],
        "metrics": [
            {
                "name": "Checkout Conversion",
                "event_name": "checkout",
                "metric_type": "conversion",
                "is_primary": True,
            }
        ],
        "sequential_testing_enabled": True,
        "sequential_testing_config": sequential_config,
    }


def _create(client: TestClient, sequential_config: dict) -> str:
    response = client.post("/api/v1/experiments/", json=_payload(sequential_config))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _boundary(client: TestClient, experiment_id: str, **params) -> float:
    response = client.get(f"/api/v1/results/{experiment_id}/sequential", params=params)
    assert response.status_code == 200, response.text
    return response.json()["msprt_result"]["boundary"]


@pytest.mark.integration
@pytest.mark.regression
def test_alpha_saved_on_create_gives_boundary_100(client):
    experiment_id = _create(client, {"method": "msprt", "alpha": 0.01})
    assert _boundary(client, experiment_id) == pytest.approx(100.0)


@pytest.mark.integration
def test_no_alpha_spending_table_for_a_stored_experiment(client):
    experiment_id = _create(client, {"spending_function": "pocock", "planned_looks": 4})
    response = client.get(f"/api/v1/results/{experiment_id}/sequential")
    assert response.status_code == 200, response.text
    assert response.json()["alpha_spending"] == []


@pytest.mark.integration
def test_alpha_saved_on_update_is_used(client):
    experiment_id = _create(client, {"method": "msprt"})
    assert _boundary(client, experiment_id) == pytest.approx(20.0)

    response = client.put(
        f"/api/v1/experiments/{experiment_id}",
        json={"sequential_testing_config": {"method": "msprt", "alpha": 0.02}},
    )
    assert response.status_code == 200, response.text
    assert _boundary(client, experiment_id) == pytest.approx(50.0)


@pytest.mark.integration
def test_alpha_query_overrides_the_saved_alpha(client):
    experiment_id = _create(client, {"alpha": 0.01})
    assert _boundary(client, experiment_id, alpha=0.1) == pytest.approx(10.0)


@pytest.mark.integration
@pytest.mark.parametrize("bad", [0, 0.25])
def test_alpha_outside_range_is_refused_on_create(client, bad):
    response = client.post(
        "/api/v1/experiments/", json=_payload({"method": "msprt", "alpha": bad})
    )
    assert response.status_code == 422, response.text
