"""What the SDK routes answer when they cannot store what they were sent.

Each route answers a fixed sentence followed by the request ID (the response's
``X-Request-ID``), never the error itself, and keeps its status: 500 for the
single routes and for a whole error-report batch, 200 with a per-item entry in
``errors`` for the two batch routes. A request ID of the wrong shape is left
out of the sentence. The full error goes to the server log.

Bodies are compared for exact equality, so nothing but the documented sentence
can be in them.
"""

import contextlib
import io
import json
import logging
import uuid

import pytest
import structlog
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.v1.endpoints import client_errors
from backend.app.models.assignment import Assignment
from backend.app.models.event import Event
from backend.app.models.experiment import ExperimentStatus, Variant
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.metrics.metric import ErrorLog
from backend.app.schemas.tracking import EventCreate
from backend.app.services.assignment_service import AssignmentService
from backend.app.services.event_service import EventService
from backend.app.services.metrics_service import MetricsService
from backend.tests.integration.helpers import unique_flag_key

pytestmark = [pytest.mark.integration, pytest.mark.regression]

MARK = "marker-398-Zq"
REQUEST_ID = "prb-398-1"
WRONG_SHAPE_ID = "<b>x</b>"

ASSIGN = "Could not assign the user to the experiment"
EVENT = "Could not store the event"
REPORT = "Could not store the error report"
REPORTS = "Could not store the error reports"
BATCH_ITEM = "Could not store this event"
REPORT_ITEM = "Could not store this error report"


def _with_id(sentence: str, request_id: str = REQUEST_ID) -> str:
    return f"{sentence} (request ID: {request_id})."


def _user() -> str:
    return f"u398-{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def experiment(db_session, make_experiment):
    """An ACTIVE experiment with a control and a treatment variant."""
    suffix = uuid.uuid4().hex[:8]
    created = make_experiment(
        name=f"Failure messages {suffix}",
        key=f"failure-messages-{suffix}",
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
    db_session.refresh(created)
    yield created
    db_session.rollback()
    db_session.query(Event).filter(Event.experiment_id == created.id).delete()
    db_session.query(Assignment).filter(Assignment.experiment_id == created.id).delete()
    db_session.commit()


@pytest.fixture
def flag(db_session, make_feature_flag):
    """An ACTIVE flag; its error rows and the flag itself are removed afterwards."""
    created = make_feature_flag(
        key=unique_flag_key("failmsg"),
        name="Failure messages flag",
        status=FeatureFlagStatus.ACTIVE,
        rollout_percentage=25,
    )
    yield created
    db_session.rollback()
    db_session.query(ErrorLog).filter(ErrorLog.feature_flag_id == created.id).delete()
    db_session.query(FeatureFlag).filter(FeatureFlag.id == created.id).delete()
    db_session.commit()


def _committed(db_session: Session, statement: str, **params) -> int:
    """Count rows on a connection of its own, i.e. only what was committed."""
    with db_session.get_bind().connect() as conn:
        conn.execute(text("SET search_path TO test_experimentation"))
        return conn.execute(text(statement), params).scalar()


# ---------------------------------------------------------------------------
# One case per changed branch: how to make it fail, and where the answer is
# ---------------------------------------------------------------------------


def _raise(*args, **kwargs):
    raise RuntimeError(MARK)


def _fail_assign(monkeypatch):
    monkeypatch.setattr(AssignmentService, "assign_user", _raise)


def _fail_track(monkeypatch):
    monkeypatch.setattr(EventService, "track_event", _raise)


def _fail_log_error(monkeypatch):
    monkeypatch.setattr(MetricsService, "log_error", staticmethod(_raise))


def _fail_resolve(monkeypatch):
    monkeypatch.setattr(client_errors, "_resolve_targets", _raise)


def _fail_add_all(monkeypatch):
    monkeypatch.setattr(Session, "add_all", _raise)


def _detail(resp):
    return resp.json()["detail"]


def _first_item_error(resp):
    body = resp.json()
    assert body["success_count"] == 0
    assert body["failure_count"] == 1
    assert len(body["errors"]) == 1
    assert body["errors"][0]["index"] == 0
    return body["errors"][0]["error"]


# (id, url, body(experiment, flag), make it fail, status, sentence, read answer)
CASES = [
    (
        "assign",
        "/api/v1/tracking/assign",
        lambda e, f: {"experiment_key": e.key, "user_id": _user()},
        _fail_assign,
        500,
        ASSIGN,
        _detail,
    ),
    (
        "track",
        "/api/v1/tracking/track",
        lambda e, f: {
            "event_type": "click",
            "user_id": _user(),
            "experiment_key": e.key,
        },
        _fail_track,
        500,
        EVENT,
        _detail,
    ),
    (
        "events",
        "/api/v1/tracking/events",
        lambda e, f: {
            "event_type": "click",
            "event_name": "click",
            "user_id": _user(),
            "experiment_id": str(e.id),
        },
        _fail_track,
        500,
        EVENT,
        _detail,
    ),
    (
        "batch-item",
        "/api/v1/tracking/batch",
        lambda e, f: {
            "events": [
                {"event_type": "click", "user_id": _user(), "experiment_key": e.key}
            ]
        },
        _fail_track,
        200,
        BATCH_ITEM,
        _first_item_error,
    ),
    (
        "errors",
        "/api/v1/tracking/errors",
        lambda e, f: {"feature_flag_key": f.key, "error_type": "crash", "message": "m"},
        _fail_log_error,
        500,
        REPORT,
        _detail,
    ),
    (
        "errors-batch-item",
        "/api/v1/tracking/errors/batch",
        lambda e, f: {
            "errors": [
                {"feature_flag_key": f.key, "error_type": "crash", "message": "m"}
            ]
        },
        _fail_resolve,
        200,
        REPORT_ITEM,
        _first_item_error,
    ),
    (
        "errors-batch-whole",
        "/api/v1/tracking/errors/batch",
        lambda e, f: {
            "errors": [
                {"feature_flag_key": f.key, "error_type": "crash", "message": "m"}
            ]
        },
        _fail_add_all,
        500,
        REPORTS,
        _detail,
    ),
]


@pytest.mark.parametrize(
    "url,body,fail,status,sentence,answer",
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_a_failed_store_answers_the_fixed_sentence_with_the_request_id(
    admin_client: TestClient,
    experiment,
    flag,
    monkeypatch,
    caplog,
    url,
    body,
    fail,
    status,
    sentence,
    answer,
) -> None:
    fail(monkeypatch)
    caplog.set_level(logging.INFO)

    resp = admin_client.post(
        url, json=body(experiment, flag), headers={"X-Request-ID": REQUEST_ID}
    )

    assert resp.status_code == status, resp.text
    assert resp.headers["x-request-id"] == REQUEST_ID
    assert answer(resp) == _with_id(sentence)
    assert MARK not in resp.text
    logged = [
        r
        for r in caplog.records
        if r.levelno == logging.ERROR
        and r.exc_info
        and isinstance(r.exc_info[1], RuntimeError)
        and str(r.exc_info[1]) == MARK
    ]
    assert logged, "the full error must reach the server log"


@pytest.mark.parametrize(
    "url,body,fail,status,sentence,answer",
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_a_request_id_of_the_wrong_shape_is_left_out_of_the_sentence(
    admin_client: TestClient,
    experiment,
    flag,
    monkeypatch,
    url,
    body,
    fail,
    status,
    sentence,
    answer,
) -> None:
    fail(monkeypatch)

    resp = admin_client.post(
        url, json=body(experiment, flag), headers={"X-Request-ID": WRONG_SHAPE_ID}
    )

    assert resp.status_code == status, resp.text
    assert answer(resp) == f"{sentence}."


# ---------------------------------------------------------------------------
# Failures the database itself raises
# ---------------------------------------------------------------------------


def test_a_track_whose_metadata_the_database_refuses_answers_the_fixed_sentence(
    admin_client: TestClient, experiment
) -> None:
    resp = admin_client.post(
        "/api/v1/tracking/track",
        json={
            "event_type": "click",
            "user_id": _user(),
            "experiment_key": experiment.key,
            "metadata": {"note": "a\u0000b"},
        },
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert resp.status_code == 500
    assert resp.json() == {"detail": _with_id(EVENT)}


def test_an_event_for_an_unknown_experiment_id_answers_the_fixed_sentence(
    admin_client: TestClient,
) -> None:
    resp = admin_client.post(
        "/api/v1/tracking/events",
        json={
            "event_type": "click",
            "event_name": "click",
            "user_id": _user(),
            "experiment_id": str(uuid.uuid4()),
        },
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert resp.status_code == 500
    assert resp.json() == {"detail": _with_id(EVENT)}


def test_a_batch_item_whose_metadata_the_database_refuses_answers_the_fixed_sentence(
    admin_client: TestClient, experiment
) -> None:
    resp = admin_client.post(
        "/api/v1/tracking/batch",
        json={
            "events": [
                {
                    "event_type": "click",
                    "user_id": _user(),
                    "experiment_key": experiment.key,
                    "metadata": {"note": "a\u0000b"},
                },
                {
                    "event_type": "click",
                    "user_id": _user(),
                    "experiment_key": experiment.key,
                },
            ]
        },
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success_count"] == 1
    assert body["failure_count"] == 1
    assert [(e["index"], e["error"]) for e in body["errors"]] == [
        (0, _with_id(BATCH_ITEM))
    ]


def test_an_error_report_the_database_refuses_answers_the_fixed_sentence(
    admin_client: TestClient, flag
) -> None:
    resp = admin_client.post(
        "/api/v1/tracking/errors",
        json={
            "feature_flag_key": flag.key,
            "error_type": "crash",
            "message": "a\u0000b",
        },
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert resp.status_code == 500
    assert resp.json() == {"detail": _with_id(REPORT)}


def test_an_error_report_batch_the_database_refuses_answers_the_fixed_sentence(
    admin_client: TestClient, db_session, flag
) -> None:
    resp = admin_client.post(
        "/api/v1/tracking/errors/batch",
        json={
            "errors": [
                {"feature_flag_key": flag.key, "error_type": "crash", "message": "ok"},
                {
                    "feature_flag_key": flag.key,
                    "error_type": "crash",
                    "message": "a\u0000b",
                },
            ]
        },
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert resp.status_code == 500
    assert resp.json() == {"detail": _with_id(REPORTS)}
    assert (
        _committed(
            db_session,
            "select count(*) from error_logs where feature_flag_id = :f",
            f=str(flag.id),
        )
        == 0
    )


# ---------------------------------------------------------------------------
# A lookup that fails in the middle of a batch
# ---------------------------------------------------------------------------


def _fail_nth_flag_lookup(monkeypatch, db_session: Session, n: int) -> None:
    """Make the n-th feature-flag lookup of a request fail in the database.

    ``SELECT 1/0`` is refused by Postgres itself (division by zero), so the
    request's transaction is left the way a real failed lookup leaves it.
    The test's own session is left alone.
    """
    real = Session.query
    seen = {"n": 0}

    def query(self, *args, **kwargs):
        if self is not db_session and args and args[0] is FeatureFlag:
            seen["n"] += 1
            if seen["n"] == n:
                self.execute(text("SELECT 1/0"))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Session, "query", query)


def test_a_failed_lookup_in_an_event_batch_fails_only_that_item(
    admin_client: TestClient, db_session, experiment, flag, monkeypatch
) -> None:
    users = [_user() for _ in range(3)]
    _fail_nth_flag_lookup(monkeypatch, db_session, 1)

    resp = admin_client.post(
        "/api/v1/tracking/batch",
        json={
            "events": [
                {
                    "event_type": "a",
                    "user_id": users[0],
                    "experiment_key": experiment.key,
                },
                {
                    "event_type": "a",
                    "user_id": users[1],
                    "experiment_key": experiment.key,
                    "feature_flag_key": flag.key,
                },
                {
                    "event_type": "a",
                    "user_id": users[2],
                    "experiment_key": experiment.key,
                },
            ]
        },
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert resp.status_code == 200, resp.text
    assert resp.headers["x-request-id"] == REQUEST_ID
    body = resp.json()
    # The failed item is rolled back on its own, so the item after it is
    # still stored.
    assert body["success_count"] == 2
    assert body["failure_count"] == 1
    assert [(e["index"], e["error"]) for e in body["errors"]] == [
        (1, _with_id(BATCH_ITEM)),
    ]
    stored = [
        _committed(db_session, "select count(*) from events where user_id = :u", u=user)
        for user in users
    ]
    assert stored == [1, 0, 1]


def test_a_failed_lookup_in_an_error_report_batch_fails_only_that_item(
    admin_client: TestClient, db_session, flag, monkeypatch
) -> None:
    _fail_nth_flag_lookup(monkeypatch, db_session, 2)

    resp = admin_client.post(
        "/api/v1/tracking/errors/batch",
        json={
            "errors": [
                {
                    "feature_flag_key": flag.key,
                    "error_type": "crash",
                    "message": f"m{i}",
                }
                for i in range(3)
            ]
        },
        headers={"X-Request-ID": REQUEST_ID},
    )

    # The failed item is rolled back on its own, so the reports around it are
    # still stored.
    assert resp.status_code == 200, resp.text
    assert resp.headers["x-request-id"] == REQUEST_ID
    body = resp.json()
    assert body["success_count"] == 2
    assert body["failure_count"] == 1
    assert [(e["index"], e["error"]) for e in body["errors"]] == [
        (1, _with_id(REPORT_ITEM)),
    ]
    assert (
        _committed(
            db_session,
            "select count(*) from error_logs where feature_flag_id = :f",
            f=str(flag.id),
        )
        == 2
    )


# ---------------------------------------------------------------------------
# Items refused for their own content keep their message
# ---------------------------------------------------------------------------


def test_an_invalid_event_in_a_batch_keeps_its_own_message(
    admin_client: TestClient, experiment
) -> None:
    user_id = _user()
    # event_name may be 255 characters in a request but 100 in a stored event.
    name = "n" * 150
    with pytest.raises(ValueError) as refused:
        EventCreate(
            user_id=user_id,
            event_type="click",
            event_name=name,
            experiment_id=str(experiment.id),
        )

    resp = admin_client.post(
        "/api/v1/tracking/batch",
        json={
            "events": [
                {
                    "event_type": "click",
                    "event_name": name,
                    "user_id": user_id,
                    "experiment_key": experiment.key,
                }
            ]
        },
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert resp.status_code == 200, resp.text
    assert _first_item_error(resp) == str(refused.value)


# ---------------------------------------------------------------------------
# The log line carries the request ID
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _json_logs():
    """Render every log record as the production JSON line, into a buffer."""
    from backend.app.core.logger import configure_logging

    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    saved = structlog.get_config()
    buffer = io.StringIO()
    configure_logging(log_level="INFO", json_logs=True, stream=buffer)
    try:
        yield buffer
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in handlers:
            root.addHandler(handler)
        root.setLevel(level)
        structlog.configure(**saved)


def test_the_failure_log_line_carries_the_request_id(
    admin_client: TestClient, experiment, monkeypatch
) -> None:
    _fail_track(monkeypatch)

    with _json_logs() as buffer:
        resp = admin_client.post(
            "/api/v1/tracking/track",
            json={
                "event_type": "click",
                "user_id": _user(),
                "experiment_key": experiment.key,
            },
            headers={"X-Request-ID": REQUEST_ID},
        )

    assert resp.status_code == 500
    lines = []
    for raw in buffer.getvalue().splitlines():
        try:
            lines.append(json.loads(raw))
        except ValueError:
            continue
    failures = [
        line
        for line in lines
        if line.get("event") == "Tracking event failed (RuntimeError)"
    ]
    assert len(failures) == 1, buffer.getvalue()[-3000:]
    assert failures[0]["request_id"] == REQUEST_ID
    assert failures[0]["level"] == "error"
    assert MARK in failures[0]["exception"]
