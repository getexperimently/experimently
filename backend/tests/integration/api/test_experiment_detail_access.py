"""Who can open an experiment: ``GET /api/v1/experiments/{id}``.

Real database, real local-JWT authentication -- only ``deps.get_db`` is
overridden, so every request goes through ``get_current_user`` ->
``get_current_active_user`` and the endpoint's own checks exactly as a
dashboard session does.

The route used to answer 403 to every caller who was not a superuser, the
experiment's own creator included. ``ExperimentService.get_experiment_by_id``
returns a dict, and ``check_ownership`` looked for an ``owner_id`` *attribute*,
so ownership never matched. The dashboard's experiment page calls exactly this
route, and guided setup redirects to it after create, so a DEVELOPER could
create an experiment and then not open it.

Fixing only the ownership lookup would still have been wrong: the check
required ownership of ADMIN, DEVELOPER and ANALYST as well, while the list
endpoint -- which returns the same ``ExperimentResponse`` for every experiment
-- admits everyone the role table grants ``Action.LIST`` (#83, #205). The role
table is the authority, and it grants ``Action.READ`` on experiments to all
four roles, so all four can open any experiment.

The tests use non-superusers throughout: a superuser bypasses every check, and
the Browser E2E journeys passed for exactly that reason.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from backend.app.api import deps
from backend.app.core.config import settings
from backend.app.core.security import create_local_access_token, get_password_hash
from backend.app.main import app
from backend.app.models.user import User, UserRole

pytestmark = [pytest.mark.integration, pytest.mark.regression]

URL = "/api/v1/experiments/"


@pytest.fixture(autouse=True)
def _local_auth_no_cache(monkeypatch):
    # The shipped auth path, with no bypass; and no cache, so every response
    # is the endpoint's own decision rather than a stored one.
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "CACHE_ENABLED", False)


def _make_user(db_session, role, is_superuser=False):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"detail_{role.value}_{suffix}",
        email=f"detail_{role.value}_{suffix}@detail.test",
        full_name="Experiment Detail User",
        hashed_password=get_password_hash("Demo1234!"),
        is_active=True,
        is_superuser=is_superuser,
        role=role,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _auth(user):
    return {"Authorization": f"Bearer {create_local_access_token(user)}"}


@pytest.fixture
def client(db_session):
    engine = db_session.get_bind()
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        session = factory()
        session.execute(text("SET search_path TO test_experimentation"))
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[deps.get_db] = override_get_db
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
    finally:
        app.dependency_overrides.pop(deps.get_db, None)


def _payload():
    return {
        "name": f"Detail access {uuid.uuid4().hex[:8]}",
        "description": "Opened after create, as guided setup does",
        "hypothesis": "The creator can open what they created",
        "experiment_type": "a_b",
        "variants": [
            {"name": "Control", "is_control": True, "traffic_allocation": 50},
            {"name": "Treatment", "is_control": False, "traffic_allocation": 50},
        ],
        "metrics": [
            {
                "name": "Conversion Rate",
                "event_name": "purchase",
                "metric_type": "conversion",
                "is_primary": True,
            }
        ],
    }


@pytest.fixture
def owner(db_session):
    """A non-superuser DEVELOPER -- the ordinary dashboard user."""
    return _make_user(db_session, UserRole.DEVELOPER)


@pytest.fixture
def experiment_id(client, owner):
    """Created through the API, so ``owner_id`` is whatever create records."""
    response = client.post(URL, json=_payload(), headers=_auth(owner))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["owner_id"] == str(owner.id), body
    return body["id"]


def test_the_creator_can_open_the_experiment_they_just_created(
    client, owner, experiment_id
):
    """The reported bug: create, then open -- the guided-setup redirect."""
    response = client.get(f"{URL}{experiment_id}", headers=_auth(owner))

    assert response.status_code == 200, response.text
    assert response.json()["id"] == experiment_id


@pytest.mark.parametrize(
    "role",
    [UserRole.ADMIN, UserRole.DEVELOPER, UserRole.ANALYST, UserRole.VIEWER],
)
def test_every_role_can_open_an_experiment_it_does_not_own(
    client, db_session, experiment_id, role
):
    """Every role carries ``Action.READ`` on experiments, as it does LIST.

    The list already hands each of these callers the same ``ExperimentResponse``
    for this experiment, so refusing the detail protected nothing.
    """
    caller = _make_user(db_session, role)

    response = client.get(f"{URL}{experiment_id}", headers=_auth(caller))

    assert response.status_code == 200, (role, response.text)
    assert response.json()["id"] == experiment_id

    listed = client.get(URL, params={"limit": 500}, headers=_auth(caller))
    assert listed.status_code == 200, listed.text
    assert experiment_id in {item["id"] for item in listed.json()["items"]}


def test_a_superuser_can_open_it(client, db_session, experiment_id):
    superuser = _make_user(db_session, UserRole.ADMIN, is_superuser=True)

    response = client.get(f"{URL}{experiment_id}", headers=_auth(superuser))

    assert response.status_code == 200, response.text


def test_a_role_without_read_is_still_refused(
    client, db_session, experiment_id, monkeypatch
):
    """The role table still decides: take READ away and the answer is 403.

    Every shipped role carries READ, so without this nothing would notice the
    remaining check being deleted along with the ownership one.
    """
    from backend.app.core import permissions
    from backend.app.core.permissions import Action, ResourceType

    viewer = _make_user(db_session, UserRole.VIEWER)
    table = {
        role: dict(grants) for role, grants in permissions.ROLE_PERMISSIONS.items()
    }
    table[UserRole.VIEWER][ResourceType.EXPERIMENT] = [Action.LIST]
    monkeypatch.setattr(permissions, "ROLE_PERMISSIONS", table)

    response = client.get(f"{URL}{experiment_id}", headers=_auth(viewer))

    assert response.status_code == 403, response.text


def test_no_token_is_still_refused(client, experiment_id):
    """Widening who may read must not reach the unauthenticated."""
    response = client.get(f"{URL}{experiment_id}")

    assert response.status_code == 401, response.text


def test_an_unknown_experiment_is_404_not_403(client, owner):
    response = client.get(f"{URL}{uuid.uuid4()}", headers=_auth(owner))

    assert response.status_code == 404, response.text
