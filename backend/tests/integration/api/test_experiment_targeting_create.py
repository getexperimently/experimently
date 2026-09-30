"""``POST /experiments`` validates ``targeting_rules`` (#523, PR 2).

Before, create stored any dict: an unknown operator, the blank condition that
"+ Add Group" adds, a flat ``{"country": ["US"]}`` (the OpenAPI example).
Assignment then read each of them as "no rules" and admitted everyone, while
the guided setup's Review step said "Targeting: 1 rule group". Create now
answers 422 naming ``targeting_rules`` and writes nothing, exactly as the
update does since #532.

Clone is the deliberate exception: it copies the source's stored rules as
they are, so an experiment whose rules predate validation can still be cloned.

Each request is a real one: a DEVELOPER who is not a superuser, a local JWT
from ``create_local_access_token``, and no dependency override except
``deps.get_db``. What was stored is read back in a session of the test's own.
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
PREFIX = "tgtcreate523"

US = {"attribute": "country", "operator": "equals", "value": "US"}
GB = {"attribute": "country", "operator": "equals", "value": "GB"}

#: Refused on create; each was accepted with 201 before.
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
    "blank attribute": {
        "groups": [
            {"conditions": [{"attribute": " ", "operator": "equals", "value": "x"}]}
        ]
    },
    "flat dict (the old OpenAPI example)": {
        "country": ["US", "CA"],
        "device": ["desktop", "mobile"],
    },
    "unknown key": {"foo": 1},
    "group with no conditions": {"groups": [{"conditions": []}]},
    "groups and rules": {"groups": [{"conditions": [GB]}], "rules": []},
    "list of rules": [{"type": "context", "attribute": "country", "value": "US"}],
}

#: What ``frontend/src/components/experiments/new/formState.ts`` sends: the
#: builder's own object, ``id`` keys and upper-case operators included, with
#: every value as the text the input holds. One condition per operator family
#: the builder offers.
BUILDER_PAYLOAD = {
    "logical_operator": "AND",
    "groups": [
        {
            "id": "id-1759230000000-1",
            "logical_operator": "AND",
            "conditions": [
                {
                    "id": "id-1759230000000-2",
                    "attribute": "user.country",
                    "operator": "in",
                    "value": "US, CA",
                },
                {
                    "id": "id-1759230000000-3",
                    "attribute": "user.age",
                    "operator": "greater_than",
                    "value": "18",
                },
                {
                    "id": "id-1759230000000-4",
                    "attribute": "app.version",
                    "operator": "semver_gte",
                    "value": "2.3.1",
                },
            ],
        },
        {
            "id": "id-1759230000000-5",
            "logical_operator": "OR",
            "conditions": [
                {
                    "id": "id-1759230000000-6",
                    "attribute": "session.new_user",
                    "operator": "equals",
                    "value": "true",
                },
                {
                    "id": "id-1759230000000-7",
                    "attribute": "user.tags",
                    "operator": "array_contains",
                    "value": "beta",
                },
                {
                    "id": "id-1759230000000-8",
                    "attribute": "user.plan",
                    "operator": "is_null",
                    "value": None,
                },
            ],
        },
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
        full_name="Targeting Create User",
        hashed_password="unused: this user signs in by token only",
        is_active=True,
        is_superuser=False,
        role=UserRole.DEVELOPER,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def factory(test_db):
    return sessionmaker(bind=test_db, expire_on_commit=False)


def _session(factory):
    session = factory()
    session.execute(text("SET search_path TO test_experimentation"))
    return session


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


def _body(name, rules):
    return {
        "name": name,
        "description": "Targeting validated on create",
        "hypothesis": "Invalid rules are refused",
        "experiment_type": "a_b",
        "targeting_rules": rules,
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


def _stored(factory, **where):
    session = _session(factory)
    try:
        return session.query(Experiment).filter_by(**where).all()
    finally:
        session.close()


@pytest.mark.parametrize("name", list(INVALID))
def test_invalid_rules_are_refused_on_create_and_nothing_is_written(
    client, developer, factory, name
):
    title = f"{PREFIX} {uuid.uuid4().hex[:8]}"
    response = client.post(
        f"{EXPERIMENTS}/", json=_body(title, INVALID[name]), headers=_auth(developer)
    )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert [error["loc"][-1] for error in detail] == ["targeting_rules"], detail
    assert _stored(factory, name=title) == []


@pytest.mark.parametrize(
    "rules",
    [BUILDER_PAYLOAD, {}, None, {"groups": []}],
    ids=["builder payload", "empty dict", "null", "empty groups"],
)
def test_valid_rules_are_created_as_sent(client, developer, factory, rules):
    title = f"{PREFIX} {uuid.uuid4().hex[:8]}"
    response = client.post(
        f"{EXPERIMENTS}/", json=_body(title, rules), headers=_auth(developer)
    )

    assert response.status_code == 201, response.text
    [row] = _stored(factory, name=title)
    assert row.targeting_rules == rules


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
    ],
    ids=["operator", "semver value"],
)
def test_the_create_422_does_not_repeat_the_submitted_value(client, developer, rules):
    response = client.post(
        f"{EXPERIMENTS}/",
        json=_body(f"{PREFIX} {uuid.uuid4().hex[:8]}", rules),
        headers=_auth(developer),
    )

    assert response.status_code == 422, response.text
    assert "7731" not in response.text, response.text
    assert "targeting_rules" in response.text


def test_clone_copies_stored_rules_that_create_would_refuse(client, developer, factory):
    """Clone is not validated: stored rules are copied as they are (EM cond. 7)."""
    flat = {"country": ["US"]}
    title = f"{PREFIX} {uuid.uuid4().hex[:8]}"
    created = client.post(
        f"{EXPERIMENTS}/", json=_body(title, None), headers=_auth(developer)
    )
    assert created.status_code == 201, created.text
    source_id = created.json()["id"]

    # Written through the ORM, as rules stored before validation were.
    session = _session(factory)
    try:
        session.get(Experiment, uuid.UUID(source_id)).targeting_rules = flat
        session.commit()
    finally:
        session.close()

    response = client.post(f"{EXPERIMENTS}/{source_id}/clone", headers=_auth(developer))

    assert response.status_code == 201, response.text
    clone_id = response.json()["id"]
    assert clone_id != source_id
    assert response.json()["targeting_rules"] == flat
    [row] = _stored(factory, id=uuid.UUID(clone_id))
    assert row.targeting_rules == flat
