"""Pin the sample-size calculator's answer for one documented case.

``GET /api/v1/experiments/analysis/sample-size`` treats
``minimum_detectable_effect`` as a *relative* change: a 12% baseline with a 5%
MDE compares 12% against 12.6%, not against 17%. The dashboard's guided setup
and the "Creating an Experiment" guide both quote the answer below, so a
change to the formula has to change this test too.

With the defaults (power 0.8, two-sided significance 0.05, two variants) the
answer is 47,034 users per variant and 94,068 in total. Reading the MDE as an
absolute change (``baseline_rate + mde``) gives 775 per variant instead.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.main import app
from backend.app.models.user import User, UserRole

SAMPLE_SIZE_URL = "/api/v1/experiments/analysis/sample-size"


@pytest.fixture
def client():
    user = MagicMock(spec=User)
    user.id = 1
    user.username = "analyst"
    user.email = "analyst@example.com"
    user.role = UserRole.ANALYST
    user.is_active = True
    user.is_superuser = False
    user.hashed_password = "hashed"

    app.dependency_overrides[deps.get_current_active_user] = lambda: user
    app.dependency_overrides[deps.get_current_user] = lambda: user
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides = {}


@pytest.mark.unit
@pytest.mark.regression
def test_twelve_percent_baseline_five_percent_relative_mde(client):
    response = client.get(
        SAMPLE_SIZE_URL,
        params={"baseline_rate": 0.12, "minimum_detectable_effect": 0.05},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["statistical_power"] == 0.8
    assert body["significance_level"] == 0.05
    assert body["samples_per_variant"] == 47034
    assert body["total_samples"] == 94068
