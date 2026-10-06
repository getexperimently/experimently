"""``POST /api/v1/power/plan`` answers with the built-in planning advice.

The advice comes from the planner's own rules whatever the API's environment:
with ``ANTHROPIC_API_KEY`` set, the route constructs no Anthropic client and
``generated_by`` is ``"template"``.

Both client classes are replaced by a recorder that notes the construction and
then raises. The assertion is on the recorder, not only on the answer: a
construction that raised would otherwise be indistinguishable from one that
never happened.
"""

import anthropic
import pytest
from anthropic import _base_client
from fastapi.testclient import TestClient

from backend.app.main import app

URL = "/api/v1/power/plan"
BODY = {
    "experiment_name": "Checkout CTA Button Test",
    "metric_description": "checkout conversion rate from cart page",
    "baseline_rate": 0.05,
    "mde": 0.10,
    "runtime_days": 12.5,
    "business_context": "Q4 launch, mobile-only segment",
}


@pytest.fixture
def constructed(monkeypatch):
    """Set the key and record every Anthropic client the request constructs."""
    calls: list[dict] = []

    def record(*args, **kwargs):
        calls.append(kwargs)
        raise RuntimeError("an Anthropic client was constructed")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-key")
    monkeypatch.setattr(anthropic, "Anthropic", record)
    monkeypatch.setattr(anthropic, "AsyncAnthropic", record)
    # A class bound at import time (`from anthropic import Anthropic`) is not the
    # module attribute; every client's base constructor is.
    monkeypatch.setattr(_base_client.SyncAPIClient, "__init__", record)
    monkeypatch.setattr(_base_client.AsyncAPIClient, "__init__", record)
    return calls


@pytest.mark.unit
@pytest.mark.regression
def test_the_plan_is_the_builtin_advice_with_the_key_set(constructed):
    response = TestClient(app, raise_server_exceptions=False).post(URL, json=BODY)

    assert response.status_code == 200, response.text
    assert response.json()["generated_by"] == "template"
    assert constructed == []
