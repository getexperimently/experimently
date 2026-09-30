"""Bad input to ``POST /api/v1/power/sample-size`` answers 422, never 500.

The validator used to put the submitted value into its error message. A value
that cannot be encoded (a lone surrogate, sent as a JSON escape) then made the
error itself fail to serialise and the route answered 500. The message now
names the accepted values only.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app

URL = "/api/v1/power/sample-size"
BODY = '{"metric_type": "%s", "baseline_rate": 0.1, "minimum_detectable_effect": 0.05}'


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize("metric_type", ["median", "\\ud800"])
def test_an_unknown_metric_type_answers_422(client, metric_type):
    response = client.post(
        URL,
        content=(BODY % metric_type).encode(),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422, response.text
    assert "metric_type must be one of" in response.text


@pytest.mark.unit
@pytest.mark.regression
def test_a_ratio_metric_without_baseline_std_answers_422(client):
    """A ratio metric is sized like a mean, so it needs ``baseline_std`` too.

    Without it the calculator used to compare ``None`` with 0 and answer 500.
    """
    response = client.post(
        URL,
        json={
            "metric_type": "ratio",
            "baseline_rate": 0.1,
            "minimum_detectable_effect": 0.05,
        },
    )

    assert response.status_code == 422, response.text
    assert "baseline_std is required when metric_type='ratio'" in response.text
