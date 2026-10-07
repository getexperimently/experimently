"""AI design and results interpretation give up on Claude after 30 seconds.

With ``ANTHROPIC_API_KEY`` set, ``POST /api/v1/ai/design`` and
``POST /api/v1/ai/interpret/{experiment_id}`` call Claude through
``AIDesignService``. Each call's client is built with a 30-second timeout and
one retry, so an attempt that has no answer after 30 seconds is abandoned, it
is tried at most twice, and then the route answers with its template.

The key is set to a value that is not a key. Nothing leaves the process: the
first test replaces the client classes with a recorder that raises, the second
gives the real client a transport that never answers, and every test fails if
anything opens a network connection.
"""

import socket
from unittest.mock import MagicMock

import anthropic
import httpx2
import pytest
from anthropic import _base_client
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.main import app
from backend.app.models.user import User, UserRole
from backend.app.services.ai_design_service import AIDesignService

pytestmark = [pytest.mark.unit, pytest.mark.regression]

NOT_A_KEY = "sk-ant-test-not-a-key"

DESIGN_BODY = {
    "description": "Test a shorter checkout form to raise conversion",
    "experiment_type": "checkout",
}
INTERPRET_BODY = {
    "experiment_id": "exp-1",
    "variant_name": "treatment",
    "p_value": 0.01,
    "relative_improvement_pct": 4.2,
}
RESULTS = {
    "p_value": 0.01,
    "relative_improvement_pct": 4.2,
    "variant_name": "treatment",
}

#: The timeout of every attempt, as the transport sees it.
THIRTY_SECONDS = {"connect": 30.0, "read": 30.0, "write": 30.0, "pool": 30.0}


@pytest.fixture(autouse=True)
def no_connections(monkeypatch):
    """Fail the test if anything opens a network connection."""
    opened: list = []

    def refuse(self, address, *args, **kwargs):
        opened.append(address)
        raise OSError("a test opened a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    yield
    assert opened == []


@pytest.fixture
def constructed(monkeypatch):
    """Set the key and record every Anthropic client a request constructs."""
    calls: list[dict] = []

    def record(*args, **kwargs):
        calls.append(kwargs)
        raise RuntimeError("an Anthropic client was constructed")

    monkeypatch.setenv("ANTHROPIC_API_KEY", NOT_A_KEY)
    monkeypatch.setattr(anthropic, "Anthropic", record)
    monkeypatch.setattr(anthropic, "AsyncAnthropic", record)
    # A class bound at import time (`from anthropic import Anthropic`) is not the
    # module attribute; every client's base constructor is.
    monkeypatch.setattr(_base_client.SyncAPIClient, "__init__", record)
    monkeypatch.setattr(_base_client.AsyncAPIClient, "__init__", record)
    return calls


@pytest.fixture
def viewer_client():
    """A TestClient whose requests are made by a VIEWER."""
    user = MagicMock(spec=User)
    user.id = 1
    user.username = "viewer"
    user.email = "viewer@example.com"
    user.role = UserRole.VIEWER
    user.is_active = True
    user.is_superuser = False
    user.hashed_password = "hashed"
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[deps.get_current_active_user] = lambda: user
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.mark.parametrize(
    ("path", "body", "field", "template"),
    [
        pytest.param(
            "/api/v1/ai/design",
            DESIGN_BODY,
            "confidence",
            "template_based",
            id="design",
        ),
        pytest.param(
            "/api/v1/ai/interpret/exp-1",
            INTERPRET_BODY,
            "generated_by",
            "template",
            id="interpret",
        ),
    ],
)
def test_the_client_has_a_30_second_timeout_and_one_retry(
    constructed, viewer_client, path, body, field, template
):
    response = viewer_client.post(path, json=body)

    assert response.status_code == 200, response.text
    # The recorder raised, so the route answered with its template.
    assert response.json()[field] == template
    settings = [(c.get("timeout"), c.get("max_retries")) for c in constructed]
    assert settings == [(30.0, 1)]


@pytest.fixture
def unanswered(monkeypatch):
    """Claude never answers: each attempt times out and is recorded."""
    attempts: list[dict] = []

    def no_answer(request):
        attempts.append(request.extensions["timeout"])
        raise httpx2.ReadTimeout("no answer", request=request)

    real = anthropic.Anthropic

    def build(**kwargs):
        # The client the service asked for, given a transport that never answers.
        transport = httpx2.MockTransport(no_answer)
        return real(http_client=httpx2.Client(transport=transport), **kwargs)

    monkeypatch.setenv("ANTHROPIC_API_KEY", NOT_A_KEY)
    monkeypatch.setattr(anthropic, "Anthropic", build)
    return attempts


def test_a_design_claude_does_not_answer_is_tried_twice_then_the_template(
    unanswered,
):
    suggestion = AIDesignService.suggest_experiment_design(
        description=DESIGN_BODY["description"], experiment_type="checkout"
    )

    assert suggestion.confidence == "template_based"
    assert unanswered == [THIRTY_SECONDS, THIRTY_SECONDS]


def test_an_interpretation_claude_does_not_answer_is_tried_twice_then_the_template(
    unanswered,
):
    interpretation = AIDesignService.interpret_results(RESULTS)

    assert interpretation.generated_by == "template"
    assert unanswered == [THIRTY_SECONDS, THIRTY_SECONDS]
