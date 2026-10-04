"""``GET /api/v1/interactions/scan`` when its database reads fail (#853).

The two reads behind ``/scan`` used to end in ``except Exception: return
[]`` / ``return set()``, so a failed query answered 200 with
``total_active_experiments: 0`` -- "no active experiments" -- instead of an
error.  Now the reads raise and the route answers 500 with the fixed
``failure_detail`` sentence, while an ``HTTPException`` (the 403 for a VIEWER,
or a 404/422 raised underneath) still passes through unchanged.

The AST check (X1) pins the shape: neither helper catches anything, and the
route's only handlers are ``except HTTPException: raise`` followed by
``except Exception as exc: raise unexpected_failure(exc, ..., db=db)``.
"""

import ast
import inspect
import textwrap
from typing import List
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend.app.api.deps import get_current_active_user, get_db
from backend.app.api.v1.endpoints import interactions as interactions_module
from backend.app.main import app
from backend.app.models.user import UserRole
from backend.app.services.interaction_detection_service import (
    InteractionDetectionService,
)

pytestmark = [pytest.mark.unit]

URL = "/api/v1/interactions/scan"
SENTENCE = "Could not scan the active experiments for interactions"
REQUEST_ID = "scan-853-a"
FIXED_BODY = {"detail": f"{SENTENCE} (request ID: {REQUEST_ID})."}
SERVICE = "backend.app.api.v1.endpoints.interactions.InteractionDetectionService"


def _db_error() -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception("server closed the connection"))


def _client_for(role: UserRole, mock_db: MagicMock):
    user = MagicMock()
    user.id = uuid4()
    user.is_active = True
    user.is_superuser = False
    user.role = role

    def _get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_active_user] = lambda: user
    return TestClient(app)


@pytest.fixture
def scan_client():
    clients: List[TestClient] = []

    def _make(role: UserRole = UserRole.DEVELOPER, mock_db=None):
        db = mock_db if mock_db is not None else MagicMock()
        client = _client_for(role, db)
        clients.append(client)
        return client, db

    yield _make
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# The regression: a failed read is a 500, not "no active experiments"
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_scan_answers_500_with_the_fixed_body_when_the_experiments_read_fails(
    scan_client,
):
    """#853: the first read (active experiments) failing used to give 200, 0."""
    db = MagicMock()
    db.query.side_effect = _db_error()
    client, _ = scan_client(mock_db=db)

    resp = client.get(URL, headers={"X-Request-ID": REQUEST_ID})

    assert resp.status_code == 500, resp.text
    assert resp.json() == FIXED_BODY
    assert "total_active_experiments" not in resp.text
    assert "server closed" not in resp.text
    db.rollback.assert_called_once()


@pytest.mark.regression
def test_scan_answers_500_when_the_assignments_read_fails(scan_client):
    """#853: the second read (each experiment's users) failing used to count
    as "nobody assigned", so the pair was dropped and the scan answered 200."""
    ids = [MagicMock(id=uuid4()), MagicMock(id=uuid4())]
    experiments_query = MagicMock()
    experiments_query.filter.return_value.all.return_value = ids

    def _query(column):
        # Every experiments read succeeds; every assignments read fails.
        if getattr(column, "key", None) == "user_id":
            raise _db_error()
        return experiments_query

    db = MagicMock()
    db.query.side_effect = _query
    client, _ = scan_client(mock_db=db)

    resp = client.get(URL, headers={"X-Request-ID": REQUEST_ID})

    assert resp.status_code == 500, resp.text
    assert resp.json() == FIXED_BODY


def test_scan_still_answers_200_when_the_reads_succeed(scan_client):
    """The happy path through the real helpers is unchanged."""
    client, _ = scan_client()  # MagicMock rows iterate as empty

    resp = client.get(URL)

    assert resp.status_code == 200, resp.text
    assert resp.json()["total_active_experiments"] == 0


# ---------------------------------------------------------------------------
# X2: an HTTPException passes through
# ---------------------------------------------------------------------------


def test_scan_403_for_a_viewer_passes_through(scan_client):
    client, db = scan_client(role=UserRole.VIEWER)

    resp = client.get(URL)

    assert resp.status_code == 403
    assert resp.json() == {
        "detail": "DEVELOPER role or higher is required to access interaction analysis."
    }
    db.rollback.assert_not_called()


@pytest.mark.parametrize("code", [404, 422])
def test_scan_http_exception_raised_underneath_passes_through(scan_client, code):
    client, _ = scan_client()
    with patch(SERVICE) as MockSvc:
        MockSvc.return_value.scan_active_experiments.side_effect = HTTPException(
            status_code=code, detail=f"planted {code}"
        )
        resp = client.get(URL)

    assert resp.status_code == code
    assert resp.json() == {"detail": f"planted {code}"}


# ---------------------------------------------------------------------------
# The helpers raise
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_get_active_experiment_ids_raises_on_a_database_error():
    db = MagicMock()
    db.query.side_effect = _db_error()
    with pytest.raises(OperationalError):
        InteractionDetectionService()._get_active_experiment_ids(db)


@pytest.mark.regression
def test_get_experiment_users_raises_on_a_database_error():
    db = MagicMock()
    db.query.side_effect = _db_error()
    with pytest.raises(OperationalError):
        InteractionDetectionService()._get_experiment_users(str(uuid4()), db)


# ---------------------------------------------------------------------------
# X1: the only handler shape allowed
# ---------------------------------------------------------------------------


def _function_node(func) -> ast.FunctionDef:
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    node = tree.body[0]
    assert isinstance(node, ast.FunctionDef)
    return node


def _is_reraise_http(handler: ast.ExceptHandler) -> bool:
    return (
        isinstance(handler.type, ast.Name)
        and handler.type.id == "HTTPException"
        and handler.name is None
        and len(handler.body) == 1
        and isinstance(handler.body[0], ast.Raise)
        and handler.body[0].exc is None
    )


def _is_unexpected_failure(handler: ast.ExceptHandler) -> bool:
    if not (
        isinstance(handler.type, ast.Name)
        and handler.type.id == "Exception"
        and handler.name is not None
        and len(handler.body) == 1
        and isinstance(handler.body[0], ast.Raise)
    ):
        return False
    call = handler.body[0].exc
    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "unexpected_failure"
        and len(call.args) == 3
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id == handler.name
        and all(isinstance(a, ast.Constant) for a in call.args[1:])
        and any(
            k.arg == "db" and isinstance(k.value, ast.Name) and k.value.id == "db"
            for k in call.keywords
        )
    )


def _handler_problems(func, *, route: bool) -> List[str]:
    node = _function_node(func)
    first_line = inspect.getsourcelines(func)[1]
    problems: List[str] = []
    tries = [n for n in ast.walk(node) if isinstance(n, ast.Try)]
    for t in tries:
        line = first_line + t.lineno - 1
        shape_ok = (
            route
            and len(t.handlers) == 2
            and _is_reraise_http(t.handlers[0])
            and _is_unexpected_failure(t.handlers[1])
            and not t.orelse
            and not t.finalbody
        )
        if not shape_ok:
            problems.append(
                f"{func.__qualname__} line {line}: a try whose handlers are not "
                "exactly `except HTTPException: raise` + `except Exception as "
                "exc: raise unexpected_failure(exc, ..., db=db)`"
            )
        for h in t.handlers:
            if all(isinstance(s, (ast.Return, ast.Pass, ast.Continue)) for s in h.body):
                problems.append(
                    f"{func.__qualname__} line {first_line + h.lineno - 1}: "
                    "an except that only returns, passes or continues"
                )
    if route and len(tries) != 1:
        problems.append(
            f"{func.__qualname__}: expected exactly one try, found {len(tries)}"
        )
    return problems


@pytest.mark.parametrize(
    "func, route",
    [
        (InteractionDetectionService._get_active_experiment_ids, False),
        (InteractionDetectionService._get_experiment_users, False),
        (interactions_module.scan_interactions, True),
    ],
    ids=["_get_active_experiment_ids", "_get_experiment_users", "scan_interactions"],
)
def test_x1_no_swallowing_handler(func, route):
    assert _handler_problems(func, route=route) == []
