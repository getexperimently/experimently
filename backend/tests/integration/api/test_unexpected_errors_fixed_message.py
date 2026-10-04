"""What the remaining routes answer when they fail unexpectedly.

The experiment and results routes were changed first
(``test_experiment_errors_fixed_message.py``); these are the rest. Each used to
put the text of whatever it caught into the response. Now each answers a fixed
sentence with the request ID and logs the full error under that ID. Deliberate
4xx messages are unchanged.

Each case makes a call inside the route's ``try`` raise an error whose text
carries marker strings, then checks the status is unchanged, the answer is
exactly the documented sentence with the request ID, and no marker reached the
body.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from backend.app.api import deps
from backend.app.api.v1.endpoints import audit_logs as audit_logs_endpoints
from backend.app.api.v1.endpoints import bulk_toggle as bulk_toggle_endpoints
from backend.app.api.v1.endpoints import client_errors as client_errors_endpoints
from backend.app.api.v1.endpoints import feature_flags as feature_flags_endpoints
from backend.app.api.v1.endpoints import llm_proxy as llm_proxy_endpoints
from backend.app.api.v1.endpoints import notifications as notifications_endpoints
from backend.app.api.v1.endpoints import power_calculator as power_endpoints
from backend.app.api.v1.endpoints import tracking as tracking_endpoints
from backend.app.main import app
from backend.app.models.experiment import ExperimentStatus, Variant
from backend.app.models.feature_flag import FeatureFlagStatus
from backend.app.models.llm_experiment import LLMExperimentStatus
from backend.app.services.audit_service import AuditService
from backend.app.services.llm_proxy_service import GeminiError
from backend.tests.integration.conftest import make_client_for_user

pytestmark = [pytest.mark.integration, pytest.mark.regression]

#: What the planted error says. None of it may reach a response body.
CANARY = "CANARY UPDATE experimentation.x Failing row contains (42, secret)"
FORBIDDEN_IN_BODY = ("CANARY", "UPDATE ", "Failing row")

REQUEST_ID = "fixed-msg-540b"
HEADERS = {"X-Request-ID": REQUEST_ID}


def _with_id(sentence: str) -> str:
    return f"{sentence} (request ID: {REQUEST_ID})."


def _boom(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError(CANARY)


async def _async_boom(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError(CANARY)


def _validation_error() -> ValidationError:
    """A real pydantic ValidationError whose text repeats the CANARY input."""

    class _Strict(BaseModel):
        number: int

    try:
        _Strict(number=CANARY)
    except ValidationError as exc:
        assert "CANARY" in str(exc)  # the planted error does carry it
        return exc
    raise AssertionError("unreachable")


def _clean(response) -> None:
    assert response.headers["x-request-id"] == REQUEST_ID
    for marker in FORBIDDEN_IN_BODY:
        assert marker not in response.text, f"{marker!r} reached the body"


def _assert_fixed(response, status_code: int, sentence: str) -> None:
    assert response.status_code == status_code, response.text
    assert response.json() == {"detail": _with_id(sentence)}
    _clean(response)


@pytest.fixture
def as_user(db_session):
    """``as_user(user)`` -> a client acting as ``user`` (one per test)."""

    def make(user) -> TestClient:
        make_client_for_user(db_session, user)
        return TestClient(app, raise_server_exceptions=False)

    yield make
    app.dependency_overrides.clear()


@pytest.fixture
def flag(make_feature_flag):
    return make_feature_flag(
        key=f"fixedmsg-{uuid.uuid4().hex[:8]}", status=FeatureFlagStatus.INACTIVE
    )


# --- feature flags --------------------------------------------------------------


@pytest.mark.parametrize(
    "verb,sentence",
    [
        ("toggle", "Could not toggle the feature flag"),
        ("enable", "Could not enable the feature flag"),
        ("disable", "Could not disable the feature flag"),
    ],
)
def test_a_flag_status_change_answers_the_fixed_message(
    as_user, developer_user, flag, monkeypatch, verb, sentence
):
    # The last call inside each route's `try`, after the commit. (It was the
    # flag cache invalidation until the flag cache was deleted, #630.)
    monkeypatch.setattr(feature_flags_endpoints, "ToggleResponse", _boom)
    client = as_user(developer_user)
    response = client.post(
        f"/api/v1/feature-flags/{flag.id}/{verb}", json={}, headers=HEADERS
    )
    _assert_fixed(response, 500, sentence)


def test_a_bulk_toggle_item_reports_the_fixed_message(
    as_user, developer_user, flag, monkeypatch
):
    # Something unexpected fails while one flag is being changed.
    monkeypatch.setattr(bulk_toggle_endpoints, "transition", _boom)
    client = as_user(developer_user)
    response = client.post(
        "/api/v1/feature-flags/bulk-toggle",
        json={"flag_ids": [str(flag.id)], "action": "enable"},
        headers=HEADERS,
    )
    assert response.status_code == 200, response.text
    (result,) = response.json()["results"]
    assert result["success"] is False
    assert result["error"] == _with_id("Could not change this flag")
    _clean(response)


# --- LLM proxy ------------------------------------------------------------------


def _active_llm_experiment(monkeypatch):
    monkeypatch.setattr(
        llm_proxy_endpoints._experiment_service,
        "get_experiment",
        lambda db, experiment_id: SimpleNamespace(status=LLMExperimentStatus.ACTIVE),
    )


def test_an_llm_completion_failure_answers_the_fixed_message(
    as_user, viewer_user, monkeypatch
):
    _active_llm_experiment(monkeypatch)
    monkeypatch.setattr(llm_proxy_endpoints._proxy_service, "complete", _async_boom)
    client = as_user(viewer_user)
    response = client.post(
        f"/api/v1/llm-experiments/{uuid.uuid4()}/complete",
        json={"user_id": "u1"},
        headers=HEADERS,
    )
    _assert_fixed(response, 502, "The LLM provider could not complete the request")


def test_a_gemini_error_keeps_its_own_sentence(as_user, viewer_user, monkeypatch):
    """The Gemini client's sentences are written by us and stay (pinned also by
    test_llm_experiments_api.py)."""

    async def gemini_refuses(*args: Any, **kwargs: Any) -> Any:
        raise GeminiError("Gemini API returned HTTP 400: API key not valid.")

    _active_llm_experiment(monkeypatch)
    monkeypatch.setattr(llm_proxy_endpoints._proxy_service, "complete", gemini_refuses)
    client = as_user(viewer_user)
    response = client.post(
        f"/api/v1/llm-experiments/{uuid.uuid4()}/complete",
        json={"user_id": "u1"},
        headers=HEADERS,
    )
    assert response.status_code == 502, response.text
    assert response.json() == {
        "detail": "LLM provider error: Gemini API returned HTTP 400: API key not valid."
    }


# --- notifications, power, audit ------------------------------------------------


def test_a_test_notification_failure_answers_the_fixed_message(
    as_user, developer_user, monkeypatch
):
    monkeypatch.setattr(notifications_endpoints, "NotificationService", _boom)
    client = as_user(developer_user)
    response = client.post(
        "/api/v1/notifications/test",
        json={"channel": "webhook", "message": "hello"},
        headers=HEADERS,
    )
    _assert_fixed(response, 500, "Could not send the test notification")


def test_a_planning_advice_failure_answers_the_fixed_message(monkeypatch):
    monkeypatch.setattr(power_endpoints._planner, "get_planning_advice", _async_boom)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/power/plan",
            json={
                "experiment_name": "Checkout test",
                "metric_description": "Checkout conversion rate",
                "baseline_rate": 0.1,
                "mde": 0.05,
                "runtime_days": 14,
                "business_context": "",
            },
            headers=HEADERS,
        )
    _assert_fixed(response, 500, "Could not generate the planning advice")


def test_an_audit_log_failure_keeps_its_sentence_with_the_request_id(
    as_user, analyst_user, monkeypatch
):
    monkeypatch.setattr(AuditService, "get_audit_logs", _boom)
    client = as_user(analyst_user)
    response = client.get("/api/v1/audit-logs/", headers=HEADERS)
    _assert_fixed(response, 500, "Failed to retrieve audit logs")


def test_an_audit_log_row_that_does_not_build_is_not_a_400(
    as_user, analyst_user, monkeypatch
):
    """``ValidationError`` is a ``ValueError``: it used to take the 400 branch
    and answer pydantic's text, which repeats the row."""

    def raise_validation(*args: Any, **kwargs: Any) -> Any:
        raise _validation_error()

    monkeypatch.setattr(
        audit_logs_endpoints.AuditLogResponse, "model_validate", raise_validation
    )
    monkeypatch.setattr(
        AuditService, "get_audit_logs", lambda **kwargs: ([object()], 1)
    )
    client = as_user(analyst_user)
    response = client.get("/api/v1/audit-logs/", headers=HEADERS)
    _assert_fixed(response, 500, "Failed to retrieve audit logs")


def test_an_audit_log_refusal_keeps_its_text(as_user, analyst_user, monkeypatch):
    def refuse(**kwargs: Any) -> Any:
        raise ValueError("Limit must be between 1 and 1000")

    monkeypatch.setattr(AuditService, "get_audit_logs", refuse)
    client = as_user(analyst_user)
    response = client.get("/api/v1/audit-logs/", headers=HEADERS)
    assert response.status_code == 400
    assert response.json() == {"detail": "Limit must be between 1 and 1000"}


# --- the development sign-in -----------------------------------------------------


def test_a_failed_development_sign_in_answers_the_fixed_message(monkeypatch):
    monkeypatch.setattr(deps, "dev_auth_bypass_active", lambda: True)
    monkeypatch.setattr(deps, "_get_or_create_dev_user", _boom)
    app.dependency_overrides.clear()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/experiments/", headers=HEADERS)
    _assert_fixed(response, 500, "Could not sign in the development user")


# --- tracking: pydantic's text never reaches the answer --------------------------


@pytest.fixture
def tracked_experiment(db_session, make_experiment):
    suffix = uuid.uuid4().hex[:8]
    created = make_experiment(
        name=f"Fixed msg {suffix}",
        key=f"fixed-msg-{suffix}",
        status=ExperimentStatus.ACTIVE,
    )
    for name, is_control in (("control", True), ("treatment", False)):
        db_session.add(
            Variant(
                experiment_id=created.id,
                name=name,
                is_control=is_control,
                traffic_allocation=50,
                configuration={},
            )
        )
    db_session.commit()
    return created


#: Fits EventRequest.event_name (255) but not EventCreate.event_name (100): the
#: model the route builds inside its ``try`` refuses it.
LONG_EVENT_NAME = "zq540" + "n" * 140


def test_an_event_the_stored_model_refuses_names_the_field_only(
    as_user, admin_user, tracked_experiment
):
    client = as_user(admin_user)
    response = client.post(
        "/api/v1/tracking/track",
        json={
            "event_type": "purchase",
            "event_name": LONG_EVENT_NAME,
            "user_id": "u-540",
            "experiment_key": tracked_experiment.key,
        },
        headers=HEADERS,
    )
    assert response.status_code == 422, response.text
    assert response.json() == {"detail": "Invalid event: event_name not valid"}
    assert "zq540" not in response.text


def test_a_batch_event_the_stored_model_refuses_names_the_field_only(
    as_user, admin_user, tracked_experiment
):
    client = as_user(admin_user)
    response = client.post(
        "/api/v1/tracking/batch",
        json={
            "events": [
                {
                    "event_type": "purchase",
                    "event_name": LONG_EVENT_NAME,
                    "user_id": "u-540",
                    "experiment_key": tracked_experiment.key,
                }
            ]
        },
        headers=HEADERS,
    )
    assert response.status_code == 200, response.text
    (error,) = response.json()["errors"]
    assert error["error"] == "Invalid event: event_name not valid"
    assert "zq540" not in response.text


def test_an_assignment_response_that_does_not_build_is_a_500(
    as_user, admin_user, tracked_experiment, monkeypatch
):
    def refuse(**kwargs: Any) -> Any:
        raise _validation_error()

    monkeypatch.setattr(tracking_endpoints, "VariantAssignmentResponse", refuse)
    client = as_user(admin_user)
    response = client.post(
        "/api/v1/tracking/assign",
        json={"experiment_key": tracked_experiment.key, "user_id": "u-540"},
        headers=HEADERS,
    )
    _assert_fixed(response, 500, "Could not assign the user to the experiment")


def test_a_batch_error_report_the_stored_model_refuses_names_the_field_only(
    as_user, admin_user, make_feature_flag, monkeypatch
):
    flag = make_feature_flag(key=f"fixedmsg-err-{uuid.uuid4().hex[:6]}")

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise _validation_error()

    monkeypatch.setattr(client_errors_endpoints, "_to_error_log_create", refuse)
    client = as_user(admin_user)
    response = client.post(
        "/api/v1/tracking/errors/batch",
        json={
            "errors": [
                {
                    "error_type": "TypeError",
                    "message": "boom",
                    "user_id": "u-540",
                    "feature_flag_key": flag.key,
                }
            ]
        },
        headers=HEADERS,
    )
    assert response.status_code == 200, response.text
    (failure,) = response.json()["errors"]
    assert failure["error"] == "Invalid report: number not valid"
    _clean(response)
