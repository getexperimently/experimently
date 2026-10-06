"""``GET /api/v1/experiments/{experiment_id}`` names the experiment's owner (#921).

The read carries ``owner_name``: the owner's full name, else their username
when it contains no ``@``, else ``null``; never their email. It is looked up
on every read, cached or not, and is never written to the cache. The list and
the other experiment routes answer with ``ExperimentResponse`` and do not
carry it.

Everything runs through the real routes and service against the test
database; only authentication is overridden, as in every other test in this
directory, and the cache is a stub with the two calls the read makes on it.
Each experiment is created through the API by its owner, and read by a
VIEWER who is someone else.
"""

from __future__ import annotations

import json
import uuid
from typing import Dict, Optional

import pytest
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.api.deps import CacheControl
from backend.app.api.v1.endpoints.experiments import _owner_name
from backend.app.main import app
from backend.app.models.user import User, UserRole
from backend.tests.integration.conftest import HASHED_PASSWORD, make_client_for_user

pytestmark = [pytest.mark.integration, pytest.mark.regression]

BASE = "/api/v1/experiments"


def _owner(
    db_session: Session,
    *,
    username: str,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> User:
    """A DEVELOPER, who may create experiments. The email is never shown."""
    user = User(
        username=username,
        email=f"owner.{uuid.uuid4().hex[:8]}@mail.int.test",
        hashed_password=HASHED_PASSWORD,
        is_active=True,
        is_superuser=False,
        role=UserRole.DEVELOPER,
    )
    user.first_name = first_name
    user.last_name = last_name
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _create_as(db_session: Session, owner: User) -> Dict:
    """An experiment created through the API by ``owner``."""
    name = f"Owner name {uuid.uuid4().hex[:8]}"
    created = make_client_for_user(db_session, owner).post(
        f"{BASE}/",
        json={
            "name": name,
            "description": "Owned by a developer",
            "hypothesis": "The read names the owner",
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
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["owner_id"] == str(owner.id)
    return created.json()


def _remove_account(db_session: Session, admin_user: User, user_id: str) -> None:
    """Remove ``user_id``'s account through the API, as a superuser."""
    removed = make_client_for_user(db_session, admin_user).delete(
        f"/api/v1/users/{user_id}"
    )
    assert removed.status_code == 204, removed.text


class _StubRedis:
    """The two calls the detail read makes on the cache, over a dict."""

    def __init__(self) -> None:
        self.store: Dict[str, str] = {}

    async def get(self, key: str) -> Optional[str]:
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.store[key] = value


def _cached_viewer(db_session: Session, viewer_user: User, redis: _StubRedis):
    """``viewer_user``'s client with the experiment cache on, over ``redis``."""
    client = make_client_for_user(db_session, viewer_user)

    async def cache_on() -> CacheControl:
        return CacheControl(enabled=True, redis=redis)

    app.dependency_overrides[deps.get_cache_control] = cache_on
    return client


# ---------------------------------------------------------------------------
# D1: a name, never an email
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "first_name, last_name, username_shape, expected",
    [
        ("Ada", "Lovelace", "plain", "Ada Lovelace"),
        (None, None, "plain", "username"),
        (None, None, "email", None),
    ],
    ids=["full_name", "username", "email_shaped_username"],
)
def test_a_viewer_reads_the_owners_name_and_never_an_email(
    db_session: Session,
    viewer_user: User,
    first_name: Optional[str],
    last_name: Optional[str],
    username_shape: str,
    expected: Optional[str],
) -> None:
    suffix = uuid.uuid4().hex[:8]
    username = (
        f"ada.{suffix}@example.com" if username_shape == "email" else f"ada_{suffix}"
    )
    owner = _owner(
        db_session, username=username, first_name=first_name, last_name=last_name
    )
    experiment = _create_as(db_session, owner)

    read = make_client_for_user(db_session, viewer_user).get(
        f"{BASE}/{experiment['id']}"
    )
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["owner_id"] == str(owner.id)
    assert body["owner_name"] == (username if expected == "username" else expected)

    # No address reaches the reader: not the email, and not a username that
    # is one.
    assert owner.email not in read.text
    assert "@" not in read.text


# ---------------------------------------------------------------------------
# EM 10: an experiment with no owner
# ---------------------------------------------------------------------------


def test_an_experiment_whose_creators_account_was_removed_has_no_owner_name(
    db_session: Session, admin_user: User, viewer_user: User
) -> None:
    owner = _owner(
        db_session,
        username=f"gone_{uuid.uuid4().hex[:8]}",
        first_name="Ada",
        last_name="Lovelace",
    )
    experiment = _create_as(db_session, owner)
    _remove_account(db_session, admin_user, str(owner.id))

    read = make_client_for_user(db_session, viewer_user).get(
        f"{BASE}/{experiment['id']}"
    )
    assert read.status_code == 200, read.text
    assert read.json()["owner_id"] is None
    assert read.json()["owner_name"] is None


def test_the_lookup_answers_none_for_no_owner_and_for_an_unknown_one(
    db_session: Session,
) -> None:
    assert _owner_name(db_session, None) is None
    assert _owner_name(db_session, uuid.uuid4()) is None


# ---------------------------------------------------------------------------
# D2: the cached read carries the current name, and the cache holds none
# ---------------------------------------------------------------------------


def test_a_cached_read_carries_the_current_name(
    db_session: Session, viewer_user: User
) -> None:
    owner = _owner(
        db_session,
        username=f"ada_{uuid.uuid4().hex[:8]}",
        first_name="Ada",
        last_name="Lovelace",
    )
    experiment = _create_as(db_session, owner)
    url = f"{BASE}/{experiment['id']}"
    key = f"experiment:{experiment['id']}"

    redis = _StubRedis()
    client = _cached_viewer(db_session, viewer_user, redis)

    first = client.get(url)
    assert first.status_code == 200, first.text
    assert first.json()["owner_name"] == "Ada Lovelace"

    # The read was cached, without the name.
    assert key in redis.store, "the detail was not written to the cache"
    stored = json.loads(redis.store[key])
    assert stored["id"] == experiment["id"]
    assert "owner_name" not in stored
    assert "Lovelace" not in redis.store[key]

    # A marker only the cache holds, so the next answer provably comes from it.
    redis.store[key] = json.dumps({**stored, "name": "from-cache"})

    owner.first_name = "Grace"
    owner.last_name = "Hopper"
    db_session.commit()

    second = client.get(url)
    assert second.status_code == 200, second.text
    assert second.json()["name"] == "from-cache"
    assert second.json()["owner_name"] == "Grace Hopper"


def test_a_cached_read_whose_owner_was_removed_answers_with_no_name(
    db_session: Session, admin_user: User, viewer_user: User
) -> None:
    owner = _owner(
        db_session,
        username=f"ada_{uuid.uuid4().hex[:8]}",
        first_name="Ada",
        last_name="Lovelace",
    )
    owner_id = str(owner.id)
    experiment = _create_as(db_session, owner)
    url = f"{BASE}/{experiment['id']}"
    key = f"experiment:{experiment['id']}"
    redis = _StubRedis()

    first = _cached_viewer(db_session, viewer_user, redis).get(url)
    assert first.status_code == 200, first.text
    assert first.json()["owner_name"] == "Ada Lovelace"

    # Removing the account does not touch the experiment cache, so the
    # cached entry still names the removed owner's id.
    _remove_account(db_session, admin_user, owner_id)
    assert json.loads(redis.store[key])["owner_id"] == owner_id

    second = _cached_viewer(db_session, viewer_user, redis).get(url)
    assert second.status_code == 200, second.text
    assert second.json()["owner_id"] == owner_id
    assert second.json()["owner_name"] is None


# ---------------------------------------------------------------------------
# D3: only the read carries it
# ---------------------------------------------------------------------------


def test_the_list_and_the_update_carry_no_owner_name(
    db_session: Session, viewer_user: User
) -> None:
    owner = _owner(
        db_session,
        username=f"ada_{uuid.uuid4().hex[:8]}",
        first_name="Ada",
        last_name="Lovelace",
    )
    experiment = _create_as(db_session, owner)
    assert "owner_name" not in experiment

    updated = make_client_for_user(db_session, owner).put(
        f"{BASE}/{experiment['id']}", json={"description": "Changed"}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["description"] == "Changed"
    assert "owner_name" not in updated.json()

    listed = make_client_for_user(db_session, viewer_user).get(
        f"{BASE}/", params={"search": experiment["name"]}
    )
    assert listed.status_code == 200, listed.text
    items = {item["id"]: item for item in listed.json()["items"]}
    assert experiment["id"] in items
    assert "owner_name" not in items[experiment["id"]]
