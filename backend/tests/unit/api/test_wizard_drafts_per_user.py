"""Wizard drafts are per user, and step data sets only step fields.

Every per-draft operation under ``/api/v1/wizard/drafts/{draft_id}`` answers
a draft that belongs to another user exactly as it answers one that does not
exist (404, same body), and leaves the draft as it was. Step data may only
carry step fields: ``id``, ``user_id`` and ``current_step`` belong to the
draft and are refused with a fixed 422 that does not repeat what was sent.

No database is needed: drafts live in process memory, and the refused submit
never reaches the session (``get_db`` is replaced by a mock that would fail
the test if it were used to create anything).
"""

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.main import app
from backend.app.models.user import User, UserRole
from backend.app.services.experiment_wizard_service import (
    ExperimentWizardService,
    _drafts,
)

pytestmark = pytest.mark.unit

HYPOTHESIS = "We believe a shorter checkout will lift completed orders."


def _user(role: UserRole = UserRole.DEVELOPER, is_superuser: bool = False) -> User:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.username = f"user_{uuid.uuid4().hex[:8]}"
    user.email = f"{user.username}@example.com"
    user.is_active = True
    user.is_superuser = is_superuser
    user.role = role
    return user


@pytest.fixture(autouse=True)
def _isolated():
    _drafts.clear()
    yield
    _drafts.clear()
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db_mock():
    session = MagicMock(name="db-session")
    app.dependency_overrides[deps.get_db] = lambda: session
    return session


def _as(user: User) -> None:
    app.dependency_overrides[deps.get_current_active_user] = lambda: user


def _owner_draft(client: TestClient, owner: User) -> str:
    """A complete draft owned by *owner*; returns its id."""
    _as(owner)
    draft_id = client.post(
        "/api/v1/wizard/drafts", json={"experiment_type": "ab"}
    ).json()["id"]
    response = client.put(
        f"/api/v1/wizard/drafts/{draft_id}/step",
        json={
            "step": "define_hypothesis",
            "data": {"hypothesis": HYPOTHESIS, "primary_metric_id": "orders"},
        },
    )
    assert response.status_code == 200, response.text
    return draft_id


def _owner_view(client: TestClient, owner: User, draft_id: str) -> dict:
    _as(owner)
    response = client.get(f"/api/v1/wizard/drafts/{draft_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _missing_answer(client: TestClient, method: str, suffix: str, **kwargs):
    """The answer for a draft id that does not exist at all."""
    return client.request(
        method, f"/api/v1/wizard/drafts/{uuid.uuid4()}{suffix}", **kwargs
    )


# ---------------------------------------------------------------------------
# Another user's draft is answered as a missing one, and is left unchanged
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize(
    "role, is_superuser",
    [
        (UserRole.DEVELOPER, False),
        (UserRole.VIEWER, False),
        (UserRole.ADMIN, True),
    ],
    ids=["developer", "viewer", "superuser"],
)
def test_get_another_users_draft_is_404(client, role, is_superuser):
    owner = _user()
    draft_id = _owner_draft(client, owner)
    before = _owner_view(client, owner, draft_id)

    _as(_user(role, is_superuser))
    response = client.get(f"/api/v1/wizard/drafts/{draft_id}")
    missing = _missing_answer(client, "GET", "")

    assert response.status_code == 404, response.text
    assert response.json() == missing.json()
    assert HYPOTHESIS not in response.text
    assert _owner_view(client, owner, draft_id) == before


@pytest.mark.regression
def test_put_step_on_another_users_draft_is_404_and_changes_nothing(client):
    owner = _user()
    draft_id = _owner_draft(client, owner)
    before = _owner_view(client, owner, draft_id)

    body = {"step": "targeting", "data": {"hypothesis": "Rewritten by someone else"}}
    _as(_user())
    response = client.put(f"/api/v1/wizard/drafts/{draft_id}/step", json=body)
    missing = _missing_answer(client, "PUT", "/step", json=body)

    assert response.status_code == 404, response.text
    assert response.json() == missing.json()
    assert _owner_view(client, owner, draft_id) == before


@pytest.mark.regression
def test_submit_another_users_draft_is_404_and_creates_nothing(client, db_mock):
    owner = _user()
    draft_id = _owner_draft(client, owner)
    before = _owner_view(client, owner, draft_id)

    _as(_user())
    response = client.post(f"/api/v1/wizard/drafts/{draft_id}/submit")
    missing = _missing_answer(client, "POST", "/submit")

    assert response.status_code == 404, response.text
    assert response.json() == missing.json()
    assert not db_mock.add.called and not db_mock.commit.called
    # The owner's draft is still there, as it was.
    assert _owner_view(client, owner, draft_id) == before


def test_owner_can_still_submit_their_own_draft(client, db_mock, monkeypatch):
    """The contrast case: the owner's submit reaches experiment creation."""
    from backend.app.services.experiment_service import ExperimentService

    created = {"id": uuid.uuid4()}
    monkeypatch.setattr(
        ExperimentService, "create_experiment", lambda self, **kw: created
    )
    owner = _user()
    draft_id = _owner_draft(client, owner)

    _as(owner)
    response = client.post(f"/api/v1/wizard/drafts/{draft_id}/submit")

    assert response.status_code == 200, response.text
    assert response.json()["experiment_id"] == str(created["id"])


@pytest.mark.regression
def test_delete_draft_by_another_user_keeps_the_draft():
    owner = ExperimentWizardService.create_draft(user_id="owner-1")

    assert ExperimentWizardService.delete_draft(owner.id, "someone-else") is False
    assert ExperimentWizardService.get_draft(owner.id, "owner-1") is owner
    assert ExperimentWizardService.delete_draft(owner.id, "owner-1") is True
    assert ExperimentWizardService.get_draft(owner.id, "owner-1") is None


def test_list_shows_only_the_callers_drafts(client):
    owner, other = _user(), _user()
    _owner_draft(client, owner)

    _as(other)
    assert client.get("/api/v1/wizard/drafts").json()["total"] == 0
    _as(owner)
    assert client.get("/api/v1/wizard/drafts").json()["total"] == 1


# ---------------------------------------------------------------------------
# Step data sets step fields only
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize("field", ["user_id", "id", "current_step"])
def test_step_data_cannot_set_draft_identity_fields(client, field):
    owner = _user()
    draft_id = _owner_draft(client, owner)
    before = _owner_view(client, owner, draft_id)

    marker = f"value-{uuid.uuid4().hex}"
    values = {"user_id": marker, "id": marker, "current_step": "review"}
    _as(owner)
    # An unknown step does not advance current_step, so any change to it
    # would come from the data alone.
    response = client.put(
        f"/api/v1/wizard/drafts/{draft_id}/step",
        json={"step": "not-a-step", "data": {field: values[field], "mde": 0.2}},
    )

    assert response.status_code == 422, response.text
    assert marker not in response.text
    after = _owner_view(client, owner, draft_id)
    assert after == before  # mde was not applied either: all or nothing
    listed = client.get("/api/v1/wizard/drafts").json()
    assert [d["id"] for d in listed["drafts"]] == [draft_id]


@pytest.mark.regression
def test_step_data_with_an_unknown_key_is_refused_with_a_fixed_message(client):
    owner = _user()
    draft_id = _owner_draft(client, owner)
    marker = f"key-{uuid.uuid4().hex}"

    _as(owner)
    first = client.put(
        f"/api/v1/wizard/drafts/{draft_id}/step",
        json={"step": "targeting", "data": {marker: 1}},
    )
    second = client.put(
        f"/api/v1/wizard/drafts/{draft_id}/step",
        json={"step": "targeting", "data": {"user_id": "x"}},
    )

    assert first.status_code == second.status_code == 422
    assert first.json() == second.json()
    assert marker not in first.text


def test_step_fields_are_still_saved(client):
    owner = _user()
    draft_id = _owner_draft(client, owner)

    _as(owner)
    response = client.put(
        f"/api/v1/wizard/drafts/{draft_id}/step",
        json={"step": "sample_size", "data": {"baseline_rate": 0.1, "mde": 0.05}},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["baseline_rate"], body["mde"], body["current_step"]) == (
        0.1,
        0.05,
        "review",
    )


# ---------------------------------------------------------------------------
# Every wizard operation is marked deprecated
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_every_wizard_operation_is_deprecated():
    paths = app.openapi()["paths"]
    operations = {
        (method.upper(), path): operation
        for path, item in paths.items()
        if path.startswith("/api/v1/wizard/")
        for method, operation in item.items()
    }
    assert set(operations) == {
        ("POST", "/api/v1/wizard/drafts"),
        ("GET", "/api/v1/wizard/drafts"),
        ("GET", "/api/v1/wizard/drafts/{draft_id}"),
        ("PUT", "/api/v1/wizard/drafts/{draft_id}/step"),
        ("POST", "/api/v1/wizard/validate"),
        ("POST", "/api/v1/wizard/drafts/{draft_id}/submit"),
    }
    assert {k for k, op in operations.items() if op.get("deprecated") is not True} == (
        set()
    )
