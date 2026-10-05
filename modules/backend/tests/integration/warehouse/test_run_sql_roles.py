"""Who reads a warehouse run, and its SQL (founder decisions D34 and D50).

A run -- an analysis or a preview, which is stored as a run with
``kind="preview"`` -- is read through ``GET /runs/{run_id}`` and listed through
``GET /experiments/{id}/runs``.  Both answer ADMIN, DEVELOPER and ANALYST (a
superuser counts as ADMIN), and every one of them gets every statement's SQL.
VIEWER, and a user whose role is NULL in the database, get 403
``role_required`` from all three reads, and the body carries no SQL, no
statement's SHA-256 and no ``results``.

The expected roles come from ``FIELD_ROLES`` in test_roles.py, not from the
endpoint, so the code and this test cannot drift together.  The filter value
planted in the metric source (``SENTINEL``) appears in the SQL and nowhere else
in a run, so its absence from the whole raw body proves the SQL was not
returned in any shape.
"""

from __future__ import annotations

import sys
import uuid
from typing import Any, Callable, Dict, List

import pytest
from sqlalchemy import update

from backend.app.models.user import User
from backend.tests.integration.conftest import HASHED_PASSWORD, make_client_for_user
from modules.backend.app.api.v1.endpoints import warehouse_analysis as wa
from modules.backend.tests.integration.warehouse.conftest import WA, ts
from modules.backend.tests.integration.warehouse.test_roles import (
    FIELD_ROLES,
    ROLES,
)

pytestmark = [pytest.mark.integration, pytest.mark.modules, pytest.mark.regression]

SENTINEL = "qa_sentinel_7f3a9c"
NO_ROLE = "no role"
SUPERUSER = "VIEWER superuser"

#: Statements each kind of run sends: an analysis runs its diagnostics and one
#: metric, a preview one statement.
STATEMENTS = {"analysis": 2, "preview": 1}


def _setup(wh) -> Dict[str, Any]:
    admin = wh.as_("ADMIN")
    experiment = wh.experiment(end=ts(10))
    wh.exposures(
        [
            ("u1", experiment.key, "control", ts(2)),
            ("u2", experiment.key, "treatment", ts(2)),
        ]
    )
    wh.events([("u1", ts(3), None), ("u2", ts(4), None)])
    connection = wh.athena_connection(admin, max_runs_per_day=200)
    assignment = wh.assignment_source(admin, connection["id"])
    metric = wh.metric_source(
        admin,
        connection["id"],
        filters=[{"column": "user_id", "operator": "ne", "value": SENTINEL}],
    )
    wh.validate(admin, assignment["id"])
    wh.validate(admin, metric["id"])
    started = wh.start_run(
        admin,
        experiment,
        {
            "connection_id": connection["id"],
            "assignment_source_id": assignment["id"],
            "metric_source_id": metric["id"],
        },
    )
    assert started.status_code == 202, started.text
    analysis = wh.wait_for_run(admin, started.json()["run_id"])
    assert analysis["status"] == "succeeded", analysis
    preview = admin.post(f"{WA}/sources/{metric['id']}/preview")
    assert preview.status_code == 200, preview.text
    return {
        "experiment": experiment.id,
        "analysis": analysis["id"],
        "preview": preview.json()["run_id"],
    }


def _no_role_client(wh):
    """A client for a user whose role is NULL in the database.

    ``User(role=None)`` is not enough: the column's default fires on insert
    and the user comes back as VIEWER.  So the row is inserted, its role set to
    NULL with an UPDATE, and the user re-read.
    """
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"wh_norole_{suffix}",
        email=f"wh_norole_{suffix}@int.test",
        full_name="Warehouse no role",
        hashed_password=HASHED_PASSWORD,
        is_active=True,
        is_superuser=False,
    )
    wh.db.add(user)
    wh.db.commit()
    wh.db.execute(update(User).where(User.id == user.id).values(role=None))
    wh.db.commit()
    wh.db.refresh(user)
    assert user.role is None, user.role
    assert wa.role_of(user) is None
    client = make_client_for_user(wh.db, user)
    wh.install()
    return client


def _clients(wh) -> Dict[str, Callable[[], Any]]:
    """A client factory per caller.  A client's authentication is the app's
    dependency override, which the next client replaces, so each one is made
    immediately before it is used."""
    clients: Dict[str, Callable[[], Any]] = {
        role: (lambda role=role: wh.as_(role)) for role in ROLES
    }
    clients[NO_ROLE] = lambda: _no_role_client(wh)
    clients[SUPERUSER] = lambda: wh.as_("VIEWER", superuser=True)
    return clients


def _reads_runs(who: str) -> bool:
    """From FIELD_ROLES alone: a superuser counts as ADMIN, no role as none.
    Since D50 the roles that read a run are exactly those that read its SQL."""
    role = "ADMIN" if who == SUPERUSER else who
    return role in FIELD_ROLES["statements"]


def _reads(client, ids) -> List[tuple]:
    """(label, kind of run, response) for each way of reading a run."""
    out = []
    for kind in ("analysis", "preview"):
        out.append((f"GET /runs ({kind})", kind, client.get(f"{WA}/runs/{ids[kind]}")))
    out.append(
        (
            "GET /experiments/{id}/runs",
            "analysis",
            client.get(f"{WA}/experiments/{ids['experiment']}/runs"),
        )
    )
    return out


def _the_run(label: str, response, ids) -> Dict[str, Any]:
    body = response.json()
    if label.startswith("GET /experiments"):
        runs = body["runs"]
        assert [r["id"] for r in runs] == [ids["analysis"]], runs
        return runs[0]
    return body


def _wrong(wh, ids) -> List[tuple]:
    """Every (who, read, what is wrong) against FIELD_ROLES; empty when right."""
    clients = _clients(wh)
    # The hashes the readers are given, to look for in everyone else's bodies.
    hashes = set()
    for label, _, response in _reads(clients["ADMIN"](), ids):
        assert response.status_code == 200, response.text
        run = _the_run(label, response, ids)
        hashes.update(s.get("sha256") for s in run["statements"] or [])
    hashes.discard(None)
    assert len(hashes) == STATEMENTS["analysis"] + STATEMENTS["preview"], hashes
    wrong = []
    for who, make_client in clients.items():
        for label, kind, response in _reads(make_client(), ids):
            body = response.text
            if _reads_runs(who):
                if response.status_code != 200:
                    wrong.append((who, label, "readers get 200"))
                    continue
                statements = _the_run(label, response, ids)["statements"]
                if (
                    not isinstance(statements, list)
                    or len(statements) != STATEMENTS[kind]
                    or not all(
                        isinstance(s.get("sql"), str) and s["sql"] for s in statements
                    )
                ):
                    wrong.append((who, label, "readers get every statement's SQL"))
                elif SENTINEL not in body:
                    wrong.append((who, label, "the planted filter is in the SQL"))
            else:
                detail = (
                    response.json().get("detail")
                    if response.status_code == 403
                    else None
                )
                if (
                    not isinstance(detail, dict)
                    or detail.get("code") != "role_required"
                ):
                    wrong.append((who, label, "refused with 403 role_required"))
                if SENTINEL in body:
                    wrong.append((who, label, "the planted filter appears"))
                if any(h in body for h in hashes):
                    wrong.append((who, label, "a statement's SHA-256 appears"))
                if '"results"' in body:
                    wrong.append((who, label, "results appear"))
    return wrong


def test_runs_and_their_sql_are_returned_to_the_field_roles_only(wh):
    ids = _setup(wh)
    # Vacuity guards: the table names a strict subset of the roles, and every
    # role is read as at least one reader and one non-reader.
    assert set(FIELD_ROLES) == {"statements"}
    assert set(FIELD_ROLES["statements"]) < set(ROLES)
    assert any(_reads_runs(r) for r in ROLES) and not all(_reads_runs(r) for r in ROLES)
    assert _wrong(wh, ids) == []


def _viewer_allowed_on(route: str) -> Callable:
    """Plant: ``route`` lets VIEWER through, as it did before D50."""
    original = wa.require

    def require(user, roles, action):
        if sys._getframe(1).f_code.co_name == route:
            roles = (*roles, "VIEWER")
        return original(user, roles, action)

    return require


@pytest.mark.parametrize("route", ["get_run", "list_runs"])
def test_the_check_fails_on_a_planted_defect(wh, monkeypatch, route):
    """The gate can fail: let VIEWER through on one read route and it reports
    VIEWER, and only VIEWER, there."""
    ids = _setup(wh)
    monkeypatch.setattr(wa, "require", _viewer_allowed_on(route))
    wrong = _wrong(wh, ids)
    assert wrong, "the planted defect went unreported"
    assert {who for who, _, _ in wrong} == {"VIEWER"}
    labels = {label for _, label, _ in wrong}
    if route == "get_run":
        assert labels == {"GET /runs (analysis)", "GET /runs (preview)"}
    else:
        assert labels == {"GET /experiments/{id}/runs"}
    assert "results appear" in {what for _, _, what in wrong}
