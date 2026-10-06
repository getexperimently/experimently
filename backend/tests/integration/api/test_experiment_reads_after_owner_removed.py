"""An experiment whose creator's account was removed still reads and lists,
with ``owner_id: null``.

``experiments.owner_id`` is ``ON DELETE SET NULL``, so removing the account
through ``DELETE /api/v1/users/{id}`` leaves the experiment with no owner.
``ExperimentResponse.owner_id`` is optional and the serialiser writes ``None``
(not the string ``"None"``) for it, so ``GET /api/v1/experiments/{id}`` and
``GET /api/v1/experiments/`` answer 200 with ``owner_id: null``.

Each case removes the account through that route. Everything runs through
the real routes and service against the test database; only authentication
is overridden, as in every other test in this directory.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from backend.app.models.experiment import Experiment
from backend.app.models.user import User, UserRole
from backend.tests.integration.conftest import HASHED_PASSWORD, make_client_for_user

pytestmark = [pytest.mark.integration, pytest.mark.regression]


def _developer(db_session: Session) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"owner_{suffix}",
        email=f"owner_{suffix}@int.test",
        full_name="Experiment Owner",
        hashed_password=HASHED_PASSWORD,
        is_active=True,
        is_superuser=False,
        role=UserRole.DEVELOPER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _create_payload(name: str) -> dict:
    return {
        "name": name,
        "description": "Owned by a developer",
        "hypothesis": "Reads survive the owner's removal",
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


@pytest.mark.parametrize("removed_by", ["superuser", "own_account"])
def test_experiment_reads_after_owner_account_removed(
    db_session: Session, admin_user: User, removed_by: str
) -> None:
    developer = _developer(db_session)
    developer_id = str(developer.id)

    # The developer creates the experiment, so the route records it as owner.
    name = f"Owned {removed_by} {uuid.uuid4().hex[:8]}"
    developer_client = make_client_for_user(db_session, developer)
    created = developer_client.post("/api/v1/experiments/", json=_create_payload(name))
    assert created.status_code == 201, created.text
    experiment_id = created.json()["id"]
    assert created.json()["owner_id"] == developer_id

    # Remove the account through the API.
    if removed_by == "own_account":
        removed = developer_client.delete(f"/api/v1/users/{developer_id}")
    else:
        removed = make_client_for_user(db_session, admin_user).delete(
            f"/api/v1/users/{developer_id}"
        )
    assert removed.status_code == 204, removed.text

    # The row is still there, with no owner.
    db_session.expire_all()
    row = db_session.get(Experiment, uuid.UUID(experiment_id))
    assert row is not None
    assert row.owner_id is None
    assert db_session.get(User, uuid.UUID(developer_id)) is None

    # The read and the list both answer 200 with owner_id null.
    admin_client = make_client_for_user(db_session, admin_user)

    read = admin_client.get(f"/api/v1/experiments/{experiment_id}")
    assert read.status_code == 200, read.text
    assert read.json()["id"] == experiment_id
    assert read.json()["owner_id"] is None

    listed = admin_client.get("/api/v1/experiments/", params={"search": name})
    assert listed.status_code == 200, listed.text
    items = {item["id"]: item for item in listed.json()["items"]}
    assert experiment_id in items
    assert items[experiment_id]["owner_id"] is None
