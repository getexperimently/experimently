"""Who may do what: every warehouse route against a non-superuser of each role."""

from __future__ import annotations

import pytest

from modules.backend.tests.integration.warehouse.conftest import ATHENA_BODY, WA, ts
from modules.backend.tests.smoke.test_module_route_table import (
    EXPECTED_WAREHOUSE_ROUTES,
)

pytestmark = [pytest.mark.integration, pytest.mark.modules]

A, D, AN, V = "ADMIN", "DEVELOPER", "ANALYST", "VIEWER"
ROLES = (A, D, AN, V)

#: Fields of a response that only some of the roles allowed on the route are
#: given; every other role gets the field as null.  One entry per field, with
#: the roles that get it (founder decision D34: a run's SQL is returned to
#: ANALYST and above).  Since D50 a run is read by these same roles only, so
#: the field is no narrower than its routes.  test_run_sql_roles.py derives its
#: expectations from this table.
FIELD_ROLES = {"statements": ("ADMIN", "DEVELOPER", "ANALYST")}


def _setup(wh):
    admin = wh.as_(A)
    experiment = wh.experiment(end=ts(10))
    wh.exposures([("u1", experiment.key, "control", ts(2))])
    wh.events([("u1", ts(3), None)])
    connection = wh.athena_connection(admin, max_runs_per_day=200)
    assignment = wh.assignment_source(admin, connection["id"])
    metric = wh.metric_source(admin, connection["id"])
    wh.validate(admin, assignment["id"])
    wh.validate(admin, metric["id"])
    run = wh.start_run(
        admin,
        experiment,
        {
            "connection_id": connection["id"],
            "assignment_source_id": assignment["id"],
            "metric_source_id": metric["id"],
        },
    )
    run_id = run.json()["run_id"]
    wh.wait_for_run(admin, run_id)
    return {
        "experiment": experiment,
        "connection": connection["id"],
        "assignment": assignment["id"],
        "metric": metric["id"],
        "run": run_id,
    }


def _source_body(kind: str, connection_id: str, name: str) -> dict:
    if kind == "assignment":
        return {
            "kind": "assignment",
            "connection_id": connection_id,
            "name": name,
            "table": "main.exposures",
            "columns": {
                "unit_id": "user_id",
                "experiment_key": "experiment_key",
                "variant": "variant",
                "exposed_at": "exposed_at",
            },
        }
    return {
        "kind": "metric",
        "connection_id": connection_id,
        "name": name,
        "table": "main.events",
        "columns": {"unit_id": "user_id", "event_at": "event_at"},
        "metric_type": "proportion",
    }


def _cases(wh, ids):
    """(route, action text, allowed roles, preparation, request) per route."""
    e, c, a, m, r = (
        ids["experiment"].id,
        ids["connection"],
        ids["assignment"],
        ids["metric"],
        ids["run"],
    )
    counter = iter(range(10_000))

    def fresh_connection():
        return wh.athena_connection(wh.as_(A))["id"]

    def fresh_source(kind):
        body = _source_body(kind, c, f"{kind}-{next(counter)}")
        return wh.as_(A).post(f"{WA}/sources", json=body).json()["id"]

    run_body = {
        "connection_id": c,
        "assignment_source_id": a,
        "metric_source_ids": [m],
    }
    everyone, readers, editors, admin = ROLES, (A, D, AN), (A, D), (A,)
    return [
        (
            ("GET", f"{WA}/connectors"),
            "Listing warehouse connectors",
            everyone,
            None,
            lambda cl, x: cl.get(f"{WA}/connectors"),
        ),
        (
            ("GET", f"{WA}/connections"),
            "Viewing warehouse connections",
            readers,
            None,
            lambda cl, x: cl.get(f"{WA}/connections"),
        ),
        (
            ("POST", f"{WA}/connections"),
            "Creating a warehouse connection",
            admin,
            None,
            lambda cl, x: cl.post(f"{WA}/connections", json=ATHENA_BODY),
        ),
        (
            ("GET", f"{WA}/connections/{{connection_id}}"),
            "Viewing warehouse connections",
            readers,
            None,
            lambda cl, x: cl.get(f"{WA}/connections/{c}"),
        ),
        (
            ("PUT", f"{WA}/connections/{{connection_id}}"),
            "Changing a warehouse connection",
            admin,
            None,
            lambda cl, x: cl.put(
                f"{WA}/connections/{c}", json={**ATHENA_BODY, "max_runs_per_day": 200}
            ),
        ),
        (
            ("DELETE", f"{WA}/connections/{{connection_id}}"),
            "Deleting a warehouse connection",
            admin,
            fresh_connection,
            lambda cl, x: cl.delete(f"{WA}/connections/{x}"),
        ),
        (
            ("POST", f"{WA}/connections/{{connection_id}}/test"),
            "Testing a warehouse connection",
            admin,
            None,
            lambda cl, x: cl.post(f"{WA}/connections/{c}/test"),
        ),
        (
            ("POST", f"{WA}/connections/{{connection_id}}/regenerate-key"),
            "Regenerating a connection's key",
            admin,
            None,
            lambda cl, x: cl.post(f"{WA}/connections/{c}/regenerate-key"),
        ),
        (
            ("POST", f"{WA}/connections/test"),
            "Testing a warehouse connection",
            admin,
            None,
            lambda cl, x: cl.post(f"{WA}/connections/test", json=ATHENA_BODY),
        ),
        (
            ("GET", f"{WA}/sources"),
            "Viewing warehouse sources",
            readers,
            None,
            lambda cl, x: cl.get(f"{WA}/sources"),
        ),
        (
            ("POST", f"{WA}/sources"),
            "Creating an assignment source",
            editors,
            None,
            lambda cl, x: cl.post(
                f"{WA}/sources", json=_source_body("assignment", c, f"n{next(counter)}")
            ),
        ),
        (
            ("POST", f"{WA}/sources"),
            "Creating a metric source",
            readers,
            None,
            lambda cl, x: cl.post(
                f"{WA}/sources", json=_source_body("metric", c, f"n{next(counter)}")
            ),
        ),
        (
            ("GET", f"{WA}/sources/{{source_id}}"),
            "Viewing warehouse sources",
            readers,
            None,
            lambda cl, x: cl.get(f"{WA}/sources/{a}"),
        ),
        (
            ("PUT", f"{WA}/sources/{{source_id}}"),
            "Editing an assignment source",
            editors,
            lambda: fresh_source("assignment"),
            lambda cl, x: cl.put(
                f"{WA}/sources/{x}",
                json={
                    k: v
                    for k, v in _source_body(
                        "assignment", c, f"u{next(counter)}"
                    ).items()
                    if k != "connection_id"
                },
            ),
        ),
        (
            ("PUT", f"{WA}/sources/{{source_id}}"),
            "Editing a metric source",
            readers,
            lambda: fresh_source("metric"),
            lambda cl, x: cl.put(
                f"{WA}/sources/{x}",
                json={
                    k: v
                    for k, v in _source_body("metric", c, f"u{next(counter)}").items()
                    if k != "connection_id"
                },
            ),
        ),
        (
            ("DELETE", f"{WA}/sources/{{source_id}}"),
            "Deleting an assignment source",
            editors,
            lambda: fresh_source("assignment"),
            lambda cl, x: cl.delete(f"{WA}/sources/{x}"),
        ),
        (
            ("DELETE", f"{WA}/sources/{{source_id}}"),
            "Deleting a metric source",
            editors,
            lambda: fresh_source("metric"),
            lambda cl, x: cl.delete(f"{WA}/sources/{x}"),
        ),
        (
            ("POST", f"{WA}/sources/{{source_id}}/validate"),
            "Validating an assignment source",
            editors,
            None,
            lambda cl, x: cl.post(f"{WA}/sources/{a}/validate"),
        ),
        (
            ("POST", f"{WA}/sources/{{source_id}}/validate"),
            "Validating a metric source",
            readers,
            None,
            lambda cl, x: cl.post(f"{WA}/sources/{m}/validate"),
        ),
        (
            ("POST", f"{WA}/sources/{{source_id}}/preview"),
            "Previewing an assignment source",
            editors,
            None,
            lambda cl, x: cl.post(f"{WA}/sources/{a}/preview"),
        ),
        (
            ("POST", f"{WA}/sources/{{source_id}}/preview"),
            "Previewing a metric source",
            readers,
            None,
            lambda cl, x: cl.post(f"{WA}/sources/{m}/preview"),
        ),
        (
            ("POST", f"{WA}/experiments/{{experiment_id}}/runs"),
            "Starting a warehouse analysis",
            editors,
            None,
            lambda cl, x: cl.post(f"{WA}/experiments/{e}/runs", json=run_body),
        ),
        (
            ("GET", f"{WA}/experiments/{{experiment_id}}/runs"),
            "Viewing warehouse analyses",
            readers,
            None,
            lambda cl, x: cl.get(f"{WA}/experiments/{e}/runs"),
        ),
        (
            ("GET", f"{WA}/runs/{{run_id}}"),
            "Viewing warehouse analyses",
            readers,
            None,
            lambda cl, x: cl.get(f"{WA}/runs/{r}"),
        ),
    ]


def _roles_text(roles) -> str:
    if len(roles) == 1:
        return f"the {roles[0]} role"
    return "the " + ", ".join(roles[:-1]) + f" or {roles[-1]} role"


def test_role_matrix(wh):
    """Each route answers 403 -- naming the role needed and the caller's -- to
    exactly the roles the plan's table excludes, and never to the others."""
    ids = _setup(wh)
    cases = _cases(wh, ids)
    assert {route for route, *_ in cases} == EXPECTED_WAREHOUSE_ROUTES
    wrong = []
    for route, action, allowed, prepare, call in cases:
        for role in ROLES:
            # Anything the call needs is made first, as ADMIN; then the call
            # is made as the role under test.
            prepared = prepare() if prepare else None
            response = call(wh.as_(role), prepared)
            if role in allowed:
                if response.status_code == 403 or response.status_code >= 500:
                    wrong.append((route, role, response.status_code, response.text))
                if wh.gate is None:
                    run_id = (
                        response.json().get("run_id")
                        if response.status_code == 202
                        else None
                    )
                    if run_id:
                        wh.wait_for_run(wh.as_(A), run_id)
            else:
                expected = {
                    "code": "role_required",
                    "message": f"{action} requires {_roles_text(allowed)}; you are {role}.",
                }
                if response.status_code != 403 or response.json()["detail"] != expected:
                    wrong.append((route, role, response.status_code, response.text))
    assert wrong == []


def test_a_superuser_counts_as_admin(wh):
    client = wh.as_("VIEWER", superuser=True)
    response = client.post(f"{WA}/connections", json=ATHENA_BODY)
    assert response.status_code == 201, response.text


def test_the_refusal_names_both_roles(wh):
    response = wh.as_("DEVELOPER").post(f"{WA}/connections", json=ATHENA_BODY)
    assert response.status_code == 403
    assert response.json()["detail"]["message"] == (
        "Creating a warehouse connection requires the ADMIN role; you are DEVELOPER."
    )
