"""`GET /api/v1/admin/users?search=` filters the list, and `total` counts the matches (#651).

The dashboard's user table sent `search`, and the API ignored it: every search
answered 200 with every user and the unfiltered `total`. Now `search` is a
case-insensitive substring of exactly four named columns -- username, email,
first name and last name -- matched literally (`%`, `_`, backslash and `/` are
not wildcards), and `total` is counted from the same filtered query.

Every user here carries a tag unique to the test, and each escaping case plants
a near-miss sibling: with a unique tag alone an unescaped wildcard would still
match only one row and the test could not fail.
"""

from __future__ import annotations

import secrets
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Enum, String, func, select, text
from sqlalchemy.orm import sessionmaker

from backend.app.api import deps
from backend.app.api.v1.endpoints.admin import USER_SEARCH_COLUMNS
from backend.app.api.v1.endpoints.auth import create_local_access_token
from backend.app.core.config import settings
from backend.app.main import app
from backend.app.models.user import User, UserRole

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

USERS = "/api/v1/admin/users"


@pytest.fixture(autouse=True)
def _local_auth(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "CACHE_ENABLED", False)


@pytest.fixture
def fresh(test_db):
    factory = sessionmaker(bind=test_db, expire_on_commit=False)

    def run(work):
        session = factory()
        try:
            session.execute(text("SET search_path TO test_experimentation"))
            result = work(session)
            session.commit()
            return result
        finally:
            session.close()

    return run


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


@pytest.fixture
def tag() -> str:
    """A string no other test's user contains."""
    return f"s651{uuid.uuid4().hex[:10]}"


def _add(fresh, **fields) -> str:
    """Add a user and return its id. Unset username/email get unique filler."""
    filler = uuid.uuid4().hex[:12]
    values = {
        "username": f"u{filler}",
        "email": f"e{filler}@search.test",
        # Shaped like a stored bcrypt hash; nobody signs in as these users.
        "hashed_password": "$2b$12$" + secrets.token_urlsafe(40)[:53],
        "is_active": True,
        "is_superuser": False,
        "role": UserRole.VIEWER,
    }
    values.update(fields)

    def add(session):
        user = User(**values)
        session.add(user)
        session.flush()
        return str(user.id)

    return fresh(add)


@pytest.fixture
def headers(fresh):
    filler = uuid.uuid4().hex[:12]

    def add(session):
        user = User(
            username=f"admin{filler}",
            email=f"admin{filler}@search.test",
            hashed_password="unused: this user signs in by token only",
            is_active=True,
            is_superuser=True,
            role=UserRole.ADMIN,
        )
        session.add(user)
        session.flush()
        return create_local_access_token(user)

    return {"Authorization": f"Bearer {fresh(add)}"}


def _search(client, headers, term, **params):
    response = client.get(USERS, params={"search": term, **params}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _ids(body) -> set[str]:
    return {item["id"] for item in body["items"]}


# --- 651-1: the filter and the filtered total -----------------------------------


@pytest.mark.regression
def test_search_filters_the_list_and_total_counts_the_matches(
    client, headers, fresh, tag
):
    wanted = {_add(fresh, username=f"{tag}-{n}") for n in range(3)}
    _add(fresh, username=f"s651other{uuid.uuid4().hex[:8]}")

    body = _search(client, headers, tag)

    assert body["total"] == 3
    assert _ids(body) == wanted


def test_without_search_the_list_and_total_are_unchanged(client, headers, fresh):
    response = client.get(USERS, params={"limit": 1}, headers=headers)

    assert response.status_code == 200, response.text
    everyone = fresh(lambda s: s.scalar(select(func.count()).select_from(User)))
    assert response.json()["total"] == everyone
    assert set(response.json()) == {"items", "total", "skip", "limit"}


# --- 651-2: exactly four named columns ------------------------------------------


@pytest.mark.regression
def test_each_of_the_four_columns_matches(client, headers, fresh, tag):
    by_field = {
        "username": _add(fresh, username=f"x{tag}x"),
        "email": _add(fresh, email=f"x{tag}x@search.test"),
        "first_name": _add(fresh, first_name=f"First{tag}"),
        "last_name": _add(fresh, last_name=f"Last{tag}"),
    }

    found = _ids(_search(client, headers, tag))

    missing = {field for field, uid in by_field.items() if uid not in found}
    assert missing == set(), f"not matched through: {missing}"
    assert found == set(by_field.values())


@pytest.mark.regression
def test_the_search_covers_exactly_four_named_columns(client, headers, fresh):
    """A value held only in any other free-text column of a user matches nothing.

    ``role`` is left out: an enum's few fixed values are words ("VIEWER") that
    a username may legitimately contain.
    """
    assert [c.key for c in USER_SEARCH_COLUMNS] == [
        "username",
        "email",
        "first_name",
        "last_name",
    ]
    uid = _add(fresh, external_id=f"ext-{uuid.uuid4().hex}")

    def stored(session):
        user = session.get(User, uuid.UUID(uid))
        named = {c.key for c in USER_SEARCH_COLUMNS}
        return {
            column.name: getattr(user, column.name)
            for column in User.__table__.columns
            if isinstance(column.type, String)
            and not isinstance(column.type, Enum)
            and column.name not in named
        }

    others = fresh(stored)
    # Not vacuous: there are other free-text columns, and every one is set.
    assert len(others) >= 2, sorted(others)
    assert all(others.values()), sorted(n for n, v in others.items() if not v)

    for name, value in others.items():
        middle = len(value) // 2
        probe = value[middle - 3 : middle + 3]
        body = _search(client, headers, probe)
        assert uid not in _ids(body), f"matched through {name}"
        assert body["total"] == 0, f"{name}: {body['total']}"


# --- 651-3..6: literal matching -------------------------------------------------


@pytest.mark.regression
def test_percent_is_literal(client, headers, fresh, tag):
    wanted = _add(fresh, username=f"{tag}%z")
    _add(fresh, username=f"{tag}abcz")

    body = _search(client, headers, f"{tag}%z")

    assert _ids(body) == {wanted}
    assert body["total"] == 1


@pytest.mark.regression
def test_underscore_is_literal(client, headers, fresh, tag):
    wanted = _add(fresh, username=f"{tag}_q")
    _add(fresh, username=f"{tag}Xq")

    body = _search(client, headers, f"{tag}_q")

    assert _ids(body) == {wanted}
    assert body["total"] == 1


@pytest.mark.regression
def test_backslash_and_slash_are_literal(client, headers, fresh, tag):
    backslash = _add(fresh, username=f"{tag}\\q")
    _add(fresh, username=f"{tag}q")
    double_slash = _add(fresh, username=f"{tag}//q")
    single_slash = _add(fresh, username=f"{tag}/q")

    assert _ids(_search(client, headers, f"{tag}\\")) == {backslash}
    assert _ids(_search(client, headers, f"{tag}//")) == {double_slash}
    assert _ids(_search(client, headers, f"{tag}/")) == {double_slash, single_slash}
    # A lone backslash is a term like any other, not an error.
    assert backslash in _ids(_search(client, headers, "\\", limit=100))


@pytest.mark.regression
def test_a_unicode_term_matches_in_the_same_case(client, headers, fresh, tag):
    wanted = _add(fresh, username=f"{tag}Zoë")
    _add(fresh, username=f"{tag}Zoe")

    body = _search(client, headers, f"{tag}Zoë")

    assert _ids(body) == {wanted}


def test_the_search_ignores_letter_case(client, headers, fresh, tag):
    wanted = _add(fresh, username=f"{tag}Mixed")

    assert _ids(_search(client, headers, f"{tag}mIXED".upper())) == {wanted}


def test_each_column_is_matched_on_its_own(client, headers, fresh, tag):
    """A first and last name together are not one term (as documented)."""
    wanted = _add(fresh, first_name=f"Jane{tag}", last_name=f"Smith{tag}")

    assert _ids(_search(client, headers, f"Smith{tag}")) == {wanted}
    assert _search(client, headers, f"Jane{tag} Smith{tag}")["total"] == 0


# --- 651-7, 651-8: empty result, paging -----------------------------------------


@pytest.mark.regression
def test_a_search_matching_nothing_answers_an_empty_list(client, headers, tag):
    body = _search(client, headers, f"{tag}-none")

    assert body == {"items": [], "total": 0, "skip": 0, "limit": 100}


@pytest.mark.regression
def test_paging_walks_the_filtered_list(client, headers, fresh, tag):
    wanted = {_add(fresh, username=f"{tag}-{n}") for n in range(7)}

    pages = [_search(client, headers, tag, skip=skip, limit=3) for skip in (0, 3, 6, 9)]

    assert [len(p["items"]) for p in pages] == [3, 3, 1, 0]
    assert all(p["total"] == 7 for p in pages)
    seen = [_ids(p) for p in pages[:3]]
    assert not (seen[0] & seen[1] or seen[0] & seen[2] or seen[1] & seen[2])
    assert seen[0] | seen[1] | seen[2] == wanted


# --- 651-9: parameter edges -----------------------------------------------------


def test_whitespace_only_search_lists_everyone(client, headers):
    plain = client.get(USERS, params={"limit": 1}, headers=headers).json()

    body = _search(client, headers, "   ", limit=1)

    assert body["total"] == plain["total"]


def test_surrounding_spaces_are_ignored(client, headers, fresh, tag):
    wanted = _add(fresh, username=f"{tag}pad")

    assert _ids(_search(client, headers, f"  {tag}pad  ")) == {wanted}


@pytest.mark.regression
def test_a_search_longer_than_100_characters_is_refused(client, headers):
    assert _search(client, headers, "a" * 100)["items"] is not None
    response = client.get(USERS, params={"search": "a" * 101}, headers=headers)

    assert response.status_code == 422, response.text


@pytest.mark.regression
def test_a_search_with_a_nul_character_is_refused(client, headers):
    response = client.get(USERS, params={"search": "a\x00b"}, headers=headers)

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "search must not contain a NUL character"


def test_the_paging_limits_are_unchanged(client, headers):
    assert client.get(USERS, params={"limit": 101}, headers=headers).status_code == 422
    assert client.get(USERS, params={"skip": -1}, headers=headers).status_code == 422
