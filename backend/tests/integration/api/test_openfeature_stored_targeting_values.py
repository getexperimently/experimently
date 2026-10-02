"""The OpenFeature flag list reads a stored ``targeting_rules`` that is not a list.

``GET /api/v1/openfeature/flags`` builds each flag's ``rules`` from
``targeting_rules`` stored in the legacy list shape. A row whose stored value
is a JSON scalar (a number or a boolean) carries no legacy rules, so it is
listed with ``rules: []``, the same way the edge config treats it. These rows
are written straight through the ORM, because that is how such a value reaches
the table: the request schemas are not what put it there.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.main import app
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.user import User, UserRole

pytestmark = [pytest.mark.integration, pytest.mark.api]

HASHED_PASSWORD = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW"


@pytest.fixture
def owner(db_session) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"of_owner_{suffix}",
        email=f"of_owner_{suffix}@example.com",
        full_name="OpenFeature Owner",
        hashed_password=HASHED_PASSWORD,
        is_active=True,
        is_superuser=False,
        role=UserRole.DEVELOPER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def client(db_session, owner):
    def override_get_db():
        yield db_session

    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[deps.get_api_key] = lambda: owner
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(deps.get_db, None)
        app.dependency_overrides.pop(deps.get_api_key, None)


@pytest.mark.regression
def test_a_flag_whose_stored_targeting_value_is_a_scalar_is_listed_with_no_rules(
    client, db_session, owner
):
    """#535: a stored 42, true or 3.5 lists the flag with ``rules: []``.

    On the old code the list answered 500 for any of these rows.
    """
    suffix = uuid.uuid4().hex[:8]
    stored = {
        f"of-int-{suffix}": 42,
        f"of-bool-{suffix}": True,
        f"of-float-{suffix}": 3.5,
    }
    for key, value in stored.items():
        db_session.add(
            FeatureFlag(
                key=key,
                name=key,
                status=FeatureFlagStatus.ACTIVE,
                owner_id=owner.id,
                rollout_percentage=25,
                targeting_rules=value,
            )
        )
    db_session.commit()

    response = client.get("/api/v1/openfeature/flags")

    assert response.status_code == 200, response.text
    listed = {f["key"]: f for f in response.json()["flags"]}
    assert set(stored) <= set(listed)
    for key in stored:
        assert listed[key]["rules"] == []
        assert listed[key]["rollout_percentage"] == 25.0
