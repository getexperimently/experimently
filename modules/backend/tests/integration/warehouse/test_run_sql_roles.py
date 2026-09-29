"""A warehouse run's SQL is returned to ANALYST and above (founder decision D34).

Every other role allowed to read a run -- VIEWER, or a user with no role --
gets the run with ``statements: null``.  The whole list is withheld: not only
each statement's SQL but its kind, dialect and SHA-256 too.

The expected roles come from ``FIELD_ROLES`` in test_roles.py, not from the
endpoint, so the code and this test cannot drift together.  Each role reads an
analysis run and a preview run through ``GET /runs/{run_id}``, and the
experiment's runs through the list.  The filter value planted in the metric
source (``SENTINEL``) appears in the SQL and nowhere else in a run, so its
absence from the whole raw body proves the SQL was not returned in any shape.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, List

import pytest

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
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"wh_norole_{suffix}",
        email=f"wh_norole_{suffix}@int.test",
        full_name="Warehouse no role",
        hashed_password=HASHED_PASSWORD,
        is_active=True,
        is_superuser=False,
        role=None,
    )
    wh.db.add(user)
    wh.db.commit()
    wh.db.refresh(user)
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


def _gets_sql(who: str) -> bool:
    """From FIELD_ROLES alone: a superuser counts as ADMIN, no role as none."""
    role = "ADMIN" if who == SUPERUSER else who
    return role in FIELD_ROLES["statements"]


def _reads(client, ids) -> List[tuple]:
    """(label, kind of run, raw body, the run) for each way of reading a run."""
    out = []
    for kind in ("analysis", "preview"):
        response = client.get(f"{WA}/runs/{ids[kind]}")
        assert response.status_code == 200, response.text
        out.append((f"GET /runs ({kind})", kind, response.text, response.json()))
    response = client.get(f"{WA}/experiments/{ids['experiment']}/runs")
    assert response.status_code == 200, response.text
    runs = response.json()["runs"]
    assert [r["id"] for r in runs] == [ids["analysis"]], runs
    out.append(("GET /experiments/{id}/runs", "analysis", response.text, runs[0]))
    return out


def _wrong(wh, ids) -> List[tuple]:
    """Every (who, read, what is wrong) against FIELD_ROLES; empty when right."""
    clients = _clients(wh)
    # The hashes the readers are given, to look for in everyone else's bodies.
    hashes = set()
    for _, _, _, run in _reads(clients["ADMIN"](), ids):
        hashes.update(s.get("sha256") for s in run["statements"] or [])
    hashes.discard(None)
    assert len(hashes) == STATEMENTS["analysis"] + STATEMENTS["preview"], hashes
    wrong = []
    for who, make_client in clients.items():
        for label, kind, body, run in _reads(make_client(), ids):
            statements = run["statements"]
            if _gets_sql(who):
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
                if statements is not None:
                    wrong.append((who, label, "statements is null"))
                if SENTINEL in body:
                    wrong.append((who, label, "the planted filter appears"))
                if any(h in body for h in hashes):
                    wrong.append((who, label, "a statement's SHA-256 appears"))
    return wrong


def test_the_sql_a_run_sent_is_returned_to_the_field_roles_only(wh):
    ids = _setup(wh)
    # Vacuity guards: the table names a strict subset of the roles, and every
    # role is read as at least one reader and one non-reader.
    assert set(FIELD_ROLES) == {"statements"}
    assert set(FIELD_ROLES["statements"]) < set(ROLES)
    assert any(_gets_sql(r) for r in ROLES) and not all(_gets_sql(r) for r in ROLES)
    assert _wrong(wh, ids) == []


def _sql_for_everyone(original: Callable) -> Callable:
    return lambda run, *, include_sql: original(run, include_sql=True)


def _hashes_kept(original: Callable) -> Callable:
    def run_out(run, *, include_sql):
        out = original(run, include_sql=True)
        if not include_sql and out["statements"] is not None:
            out["statements"] = [
                {k: v for k, v in s.items() if k != "sql"} for s in out["statements"]
            ]
        return out

    return run_out


@pytest.mark.parametrize(
    "plant, expected",
    [
        (_sql_for_everyone, "statements is null"),
        (_hashes_kept, "a statement's SHA-256 appears"),
    ],
    ids=["sql-for-everyone", "only-the-sql-withheld"],
)
def test_the_check_fails_on_a_planted_defect(wh, monkeypatch, plant, expected):
    """The gate can fail: plant each defect in the serialiser and it reports it."""
    ids = _setup(wh)
    monkeypatch.setattr(wa, "run_out", plant(wa.run_out))
    wrong = _wrong(wh, ids)
    assert wrong, "the planted defect went unreported"
    assert {who for who, _, _ in wrong} == {"VIEWER", NO_ROLE}
    assert expected in {what for _, _, what in wrong}
