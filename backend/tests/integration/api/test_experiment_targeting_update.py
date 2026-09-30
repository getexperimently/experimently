"""``PUT /experiments/{id}`` validates ``targeting_rules`` (#523, PR 1a).

Before, the route stored any dict: an unknown operator, a blank condition
from "+ Add Group", a flat ``{"country": ["US"]}``. Assignment then read each
of them as "no rules" and admitted everyone, while the stored value looked
restrictive. The update now answers 422 naming ``targeting_rules`` and writes
nothing.

Each request is a real one: a DEVELOPER who is not a superuser, a local JWT
from ``create_local_access_token``, and no dependency override except
``deps.get_db`` (see #470 for why ``make_client_for_user`` is not used). What
was stored is read back in a session of the test's own.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from backend.app.api import deps
from backend.app.api.v1.endpoints.auth import create_local_access_token
from backend.app.core.config import settings
from backend.app.main import app
from backend.app.models.experiment import Experiment
from backend.app.models.user import User, UserRole

pytestmark = [pytest.mark.integration, pytest.mark.requires_db, pytest.mark.regression]

EXPERIMENTS = "/api/v1/experiments"
PREFIX = "tgt523"

US = {"attribute": "country", "operator": "equals", "value": "US"}
GB = {"attribute": "country", "operator": "equals", "value": "GB"}
STORED = {
    "logical_operator": "AND",
    "groups": [{"logical_operator": "AND", "conditions": [US]}],
}

#: Refused on PUT; each was accepted with 200 before.
INVALID = {
    "unknown operator": {
        "logical_operator": "AND",
        "groups": [
            {"conditions": [{"attribute": "plan", "operator": "bogus_op", "value": 1}]}
        ],
    },
    "blank condition from + Add Group": {
        "logical_operator": "AND",
        "groups": [
            {"conditions": [US]},
            {"conditions": [{"attribute": "", "operator": "equals", "value": ""}]},
        ],
    },
    "flat dict": {"country": ["US", "CA"]},
    "unknown key": {"foo": 1},
    "bad semver": {
        "groups": [
            {
                "conditions": [
                    {"attribute": "v", "operator": "semver_gte", "value": "nope"}
                ]
            }
        ]
    },
    "groups not a list": {"groups": "nonsense"},
    "groups and rules": {"groups": [{"conditions": [GB]}], "rules": []},
}

#: What the dashboard's builder sends, ``id`` keys included.
BUILDER_GB = {
    "logical_operator": "AND",
    "groups": [
        {
            "id": "id-1-1",
            "logical_operator": "AND",
            "conditions": [{"id": "id-1-2", **GB}],
        }
    ],
}


@pytest.fixture(autouse=True)
def _local_auth(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "CACHE_ENABLED", False)


@pytest.fixture
def developer(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"{PREFIX}_developer_{suffix}",
        email=f"{PREFIX}_{suffix}@targeting.test",
        full_name="Targeting Update User",
        hashed_password="unused: this user signs in by token only",
        is_active=True,
        is_superuser=False,
        role=UserRole.DEVELOPER,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def fresh(test_db):
    factory = sessionmaker(bind=test_db, expire_on_commit=False)

    def read_rules(experiment_id):
        session = factory()
        try:
            session.execute(text("SET search_path TO test_experimentation"))
            return session.get(Experiment, uuid.UUID(experiment_id)).targeting_rules
        finally:
            session.close()

    return read_rules


@pytest.fixture
def client(test_db):
    factory = sessionmaker(bind=test_db, autocommit=False, autoflush=False)

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


def _auth(user):
    return {"Authorization": f"Bearer {create_local_access_token(user)}"}


@pytest.fixture
def experiment_id(client, developer):
    body = {
        "name": f"{PREFIX} {uuid.uuid4().hex[:8]}",
        "description": "Targeting validated on update",
        "hypothesis": "Invalid rules are refused",
        "experiment_type": "a_b",
        "targeting_rules": STORED,
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
    response = client.post(f"{EXPERIMENTS}/", json=body, headers=_auth(developer))
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.parametrize("name", list(INVALID))
def test_invalid_rules_are_refused_and_nothing_is_written(
    client, developer, experiment_id, fresh, name
):
    response = client.put(
        f"{EXPERIMENTS}/{experiment_id}",
        json={"targeting_rules": INVALID[name], "description": "changed too"},
        headers=_auth(developer),
    )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert [error["loc"][-1] for error in detail] == ["targeting_rules"], detail
    assert fresh(experiment_id) == STORED


@pytest.mark.parametrize(
    "rules",
    [BUILDER_GB, {}, None, {"groups": []}],
    ids=["builder payload", "empty dict", "null", "empty groups"],
)
def test_valid_rules_are_stored_as_sent(client, developer, experiment_id, fresh, rules):
    response = client.put(
        f"{EXPERIMENTS}/{experiment_id}",
        json={"targeting_rules": rules},
        headers=_auth(developer),
    )

    assert response.status_code == 200, response.text
    assert fresh(experiment_id) == rules


@pytest.mark.parametrize(
    "rules",
    [
        {
            "groups": [
                {
                    "conditions": [
                        {"attribute": "c", "operator": "zq_op_7731", "value": 1}
                    ]
                }
            ]
        },
        {
            "groups": [
                {
                    "conditions": [
                        {"attribute": "v", "operator": "semver_gt", "value": "zq-7731"}
                    ]
                }
            ]
        },
        {
            "groups": [
                {
                    "conditions": [
                        {"attribute": "n", "operator": "less_than", "value": "zq7731"}
                    ]
                }
            ]
        },
    ],
    ids=["operator", "semver value", "number value"],
)
def test_the_422_does_not_repeat_the_submitted_value(
    client, developer, experiment_id, rules
):
    response = client.put(
        f"{EXPERIMENTS}/{experiment_id}",
        json={"targeting_rules": rules},
        headers=_auth(developer),
    )

    assert response.status_code == 422, response.text
    assert "7731" not in response.text, response.text
    assert "targeting_rules" in response.text
