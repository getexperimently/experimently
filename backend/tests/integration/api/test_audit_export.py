"""``GET /api/v1/audit-logs/export`` (#221): the filtered log as CSV or JSON.

Every test writes its own entries against an entity id unique to the test and
filters on it, so rows other tests leave in the shared database never reach
an assertion. The readers are real users of their role; nothing patches the
permission rule.

What is pinned here:

* the list route's filters, with both dates inclusive, and its order;
* the CSV header and column order, RFC 4180 quoting, CSV rows equal to JSON
  rows, and export cells made safe for spreadsheets;
* zero matches is a 200 with a header row or ``[]``;
* above the cap the answer is 422 and nothing is cut short;
* ``X-Total-Count`` is the number of entries in the file, and an entry written
  after the request arrived is left out of both;
* more than one batch streams complete, the session open until the end;
* the list route's access rule: DEVELOPER and VIEWER get only their own rows,
  whatever ``user_id`` they send;
* exporting writes no audit entry.
"""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api import deps
from backend.app.api.v1.endpoints import audit_logs as audit_routes
from backend.app.main import app
from backend.app.models.audit_log import ActionType, AuditLog, EntityType
from backend.app.models.user import User, UserRole
from backend.app.services import audit_export
from backend.tests.integration.conftest import HASHED_PASSWORD, make_client_for_user

pytestmark = [pytest.mark.integration, pytest.mark.api]

EXPORT = "/api/v1/audit-logs/export"
BASE = datetime(2025, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def plain_admin(db_session: Session) -> User:
    """An ADMIN who is not a superuser, so the role is what is tested."""
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"export_admin_{suffix}",
        email=f"export_admin_{suffix}@int.test",
        full_name="Export Admin",
        hashed_password=HASHED_PASSWORD,
        is_active=True,
        is_superuser=False,
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _entry(user, entity_id, minutes, action=ActionType.TOGGLE_DISABLE, **extra):
    fields = {
        "id": uuid.uuid4(),
        "user_id": user.id if user is not None else None,
        "user_email": user.email if user is not None else "system:safety-monitor",
        "action_type": action.value,
        "entity_type": EntityType.FEATURE_FLAG.value,
        "entity_id": entity_id,
        "entity_name": "Export flag",
        "old_value": "ACTIVE",
        "new_value": "INACTIVE",
        "reason": None,
        "timestamp": BASE + timedelta(minutes=minutes),
    }
    fields.update(extra)
    return AuditLog(**fields)


def _write(db_session, rows):
    db_session.add_all(rows)
    db_session.commit()
    return rows


def _json(response):
    assert response.status_code == 200, response.text
    return json.loads(response.text)


def _csv(response):
    assert response.status_code == 200, response.text
    return list(csv.reader(io.StringIO(response.text, newline="")))


# ---------------------------------------------------------------------------
# Filters, order and format
# ---------------------------------------------------------------------------


def test_each_filter_returns_exactly_its_rows_newest_first(
    db_session, admin_user, developer_user
):
    entity = uuid.uuid4()
    rows = _write(
        db_session,
        [
            _entry(admin_user, entity, 0, ActionType.FEATURE_FLAG_CREATE),
            _entry(admin_user, entity, 10, ActionType.TOGGLE_ENABLE),
            _entry(developer_user, entity, 20, ActionType.TOGGLE_DISABLE),
            _entry(admin_user, entity, 30, ActionType.TOGGLE_ENABLE),
            _entry(developer_user, entity, 40, ActionType.FEATURE_FLAG_UPDATE),
        ],
    )
    ids = [str(r.id) for r in rows]
    client = make_client_for_user(db_session, admin_user)

    def got(**params):
        body = _json(client.get(EXPORT, params={"entity_id": str(entity), **params}))
        return [item["id"] for item in body]

    assert got() == ids[::-1]
    assert got(action_type="toggle_enable") == [ids[3], ids[1]]
    assert got(user_id=str(developer_user.id)) == [ids[4], ids[2]]
    assert got(entity_type="feature_flag") == ids[::-1]
    assert got(entity_type="experiment") == []
    # Both dates are inclusive: the rows exactly at 10 and 30 minutes are in.
    assert got(
        from_date=(BASE + timedelta(minutes=10)).isoformat(),
        to_date=(BASE + timedelta(minutes=30)).isoformat(),
    ) == [ids[3], ids[2], ids[1]]


def test_csv_has_the_pinned_header_and_equals_the_json(db_session, admin_user):
    entity = uuid.uuid4()
    canary = 'one, "two"\nthree'
    _write(
        db_session,
        [
            _entry(admin_user, entity, 0, reason=canary),
            _entry(admin_user, entity, 1, old_value=None, new_value='{"a": 1}'),
        ],
    )
    client = make_client_for_user(db_session, admin_user)
    params = {"entity_id": str(entity)}
    items = _json(client.get(EXPORT, params=params))
    table = _csv(client.get(EXPORT, params={**params, "format": "csv"}))

    assert table[0] == [
        "id",
        "timestamp",
        "user_id",
        "user_email",
        "action_type",
        "action_description",
        "entity_type",
        "entity_id",
        "entity_name",
        "old_value",
        "new_value",
        "reason",
    ]
    assert len(table) == 1 + len(items) == 3
    for row, item in zip(table[1:], items):
        assert row == [
            "" if item[c] is None else str(item[c]) for c in audit_export.CSV_COLUMNS
        ]
    # The comma, the quotes and the newline stay inside one cell.
    assert table[2][-1] == canary
    # The JSON items are the list route's items.
    listed = client.get("/api/v1/audit-logs/", params=params).json()["items"]
    assert items == listed


def test_zero_matches_is_a_header_or_an_empty_array(db_session, admin_user):
    client = make_client_for_user(db_session, admin_user)
    params = {"entity_id": str(uuid.uuid4())}
    as_json = client.get(EXPORT, params=params)
    assert _json(as_json) == []
    assert as_json.headers["x-total-count"] == "0"
    as_csv = client.get(EXPORT, params={**params, "format": "csv"})
    assert _csv(as_csv) == [list(audit_export.CSV_COLUMNS)]
    assert as_csv.headers["x-total-count"] == "0"


def test_headers_name_the_file_and_the_format(db_session, admin_user):
    client = make_client_for_user(db_session, admin_user)
    params = {"entity_id": str(uuid.uuid4())}
    for fmt, media in (("json", "application/json"), ("csv", "text/csv")):
        response = client.get(EXPORT, params={**params, "format": fmt})
        assert response.headers["content-type"].startswith(media)
        assert re.fullmatch(
            rf'attachment; filename="audit-log-\d{{8}}T\d{{6}}Z\.{fmt}"',
            response.headers["content-disposition"],
        )
    # JSON is the default.
    default = client.get(EXPORT, params=params)
    assert default.headers["content-type"].startswith("application/json")


def test_refusals_match_the_list_route(db_session, admin_user):
    client = make_client_for_user(db_session, admin_user)
    assert client.get(EXPORT, params={"format": "xml"}).status_code == 422
    for params in (
        {"action_type": "nope"},
        {"entity_type": "nope"},
        {"from_date": BASE.isoformat(), "to_date": BASE.isoformat()},
    ):
        exported = client.get(EXPORT, params=params)
        listed = client.get("/api/v1/audit-logs/", params=params)
        assert exported.status_code == listed.status_code == 400
        assert exported.json() == listed.json()
        assert "nope" not in exported.text


@pytest.mark.parametrize("lead", ["=", "+", "-", "@", "\t", "\r"])
def test_export_cells_are_made_safe_for_spreadsheets(db_session, admin_user, lead):
    entity = uuid.uuid4()
    value = f"{lead}1+2"
    _write(
        db_session,
        [_entry(admin_user, entity, 0, reason=value, entity_name=value)],
    )
    client = make_client_for_user(db_session, admin_user)
    params = {"entity_id": str(entity)}
    row = _csv(client.get(EXPORT, params={**params, "format": "csv"}))[1]
    by_column = dict(zip(audit_export.CSV_COLUMNS, row))
    assert by_column["reason"] == "'" + value
    assert by_column["entity_name"] == "'" + value
    # JSON carries the stored text unchanged.
    assert _json(client.get(EXPORT, params=params))[0]["reason"] == value


def test_a_cell_with_the_sign_inside_is_left_alone(db_session, admin_user):
    entity = uuid.uuid4()
    _write(db_session, [_entry(admin_user, entity, 0, reason="a=b, c-d")])
    client = make_client_for_user(db_session, admin_user)
    row = _csv(client.get(EXPORT, params={"entity_id": str(entity), "format": "csv"}))[
        1
    ]
    assert row[-1] == "a=b, c-d"


# ---------------------------------------------------------------------------
# The cap, the count and the snapshot
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", ["json", "csv"])
def test_the_cap_is_refused_never_cut_short(db_session, admin_user, monkeypatch, fmt):
    cap = 5
    monkeypatch.setattr(audit_export, "EXPORT_MAX_ROWS", cap)
    entity = uuid.uuid4()
    _write(db_session, [_entry(admin_user, entity, m) for m in range(cap)])
    client = make_client_for_user(db_session, admin_user)
    params = {"entity_id": str(entity), "format": fmt}

    at_cap = client.get(EXPORT, params=params)
    assert at_cap.status_code == 200
    assert at_cap.headers["x-total-count"] == str(cap)
    received = len(_json(at_cap)) if fmt == "json" else len(_csv(at_cap)) - 1
    assert received == cap

    _write(db_session, [_entry(admin_user, entity, cap)])
    over = client.get(EXPORT, params=params)
    assert over.status_code == 422
    assert over.json()["detail"] == (
        f"{cap + 1} entries match these filters; an export holds at most {cap}. "
        "Narrow from_date and to_date, or filter by action_type or entity_type."
    )


def test_the_cap_is_fifty_thousand():
    assert audit_export.EXPORT_MAX_ROWS == 50_000


def test_an_entry_written_after_the_request_is_not_exported(
    db_session, admin_user, monkeypatch
):
    """``to_date`` is pinned to the request time.

    An entry is written between the COUNT and the first row of the body. It
    matches every filter, so only the pin keeps it out: the file holds
    exactly ``X-Total-Count`` entries and not the new one.
    """
    entity = uuid.uuid4()
    _write(db_session, [_entry(admin_user, entity, m) for m in range(3)])
    late_id = uuid.uuid4()
    factory = sessionmaker(bind=db_session.get_bind())
    original = audit_routes._stream_items

    def write_then_stream(query, fmt):
        monkeypatch.setattr(audit_routes, "_stream_items", original)
        other = factory()
        try:
            other.execute(text("SET search_path TO test_experimentation"))
            other.add(
                _entry(
                    admin_user,
                    entity,
                    0,
                    id=late_id,
                    timestamp=datetime.now(timezone.utc),
                )
            )
            other.commit()
        finally:
            other.close()
        return original(query, fmt)

    monkeypatch.setattr(audit_routes, "_stream_items", write_then_stream)
    client = make_client_for_user(db_session, admin_user)
    response = client.get(EXPORT, params={"entity_id": str(entity)})
    items = _json(response)
    assert response.headers["x-total-count"] == "3"
    assert len(items) == 3
    assert str(late_id) not in {item["id"] for item in items}
    # The entry exists: a later export includes it.
    assert len(_json(client.get(EXPORT, params={"entity_id": str(entity)}))) == 4


@pytest.mark.parametrize("fmt", ["json", "csv"])
def test_more_than_one_batch_streams_complete_with_the_session_open(
    db_session, admin_user, monkeypatch, fmt
):
    total = 2 * audit_export.EXPORT_BATCH_SIZE + 500
    entity = uuid.uuid4()
    db_session.bulk_save_objects([_entry(admin_user, entity, m) for m in range(total)])
    db_session.commit()

    client = make_client_for_user(db_session, admin_user)
    events = []
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False)

    def tracked_db():
        session = factory()
        session.execute(text("SET search_path TO test_experimentation"))
        try:
            yield session
        finally:
            events.append("closed")
            session.close()

    app.dependency_overrides[deps.get_db] = tracked_db
    original = audit_export.entry_item

    def counted(row):
        events.append("row")
        return original(row)

    monkeypatch.setattr(audit_export, "entry_item", counted)
    response = client.get(EXPORT, params={"entity_id": str(entity), "format": fmt})
    received = len(_json(response)) if fmt == "json" else len(_csv(response)) - 1
    assert response.headers["x-total-count"] == str(total)
    assert received == total
    # Every row was read before the session closed.
    assert events.count("row") == total
    assert events[-1] == "closed"


# ---------------------------------------------------------------------------
# Access, and no entry for the export itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role_fixture", ["developer_user", "viewer_user"])
def test_developer_and_viewer_export_only_their_own_rows(
    request, db_session, admin_user, role_fixture
):
    reader = request.getfixturevalue(role_fixture)
    entity = uuid.uuid4()
    mine, theirs = _write(
        db_session,
        [_entry(reader, entity, 0), _entry(admin_user, entity, 1)],
    )
    client = make_client_for_user(db_session, reader)
    for params in (
        {"entity_id": str(entity)},
        {"entity_id": str(entity), "user_id": str(admin_user.id)},
    ):
        for fmt in ("json", "csv"):
            response = client.get(EXPORT, params={**params, "format": fmt})
            assert response.status_code == 200
            assert str(theirs.id) not in response.text
            assert admin_user.email not in response.text
            assert response.headers["x-total-count"] == "1"
            assert str(mine.id) in response.text


@pytest.mark.parametrize("role_fixture", ["plain_admin", "analyst_user"])
def test_admin_and_analyst_export_every_row(
    request, db_session, developer_user, role_fixture
):
    reader = request.getfixturevalue(role_fixture)
    entity = uuid.uuid4()
    rows = _write(
        db_session,
        [_entry(developer_user, entity, 0), _entry(None, entity, 1)],
    )
    client = make_client_for_user(db_session, reader)
    body = _json(client.get(EXPORT, params={"entity_id": str(entity)}))
    assert {item["id"] for item in body} == {str(r.id) for r in rows}
    scoped = _json(
        client.get(
            EXPORT,
            params={"entity_id": str(entity), "user_id": str(developer_user.id)},
        )
    )
    assert [item["id"] for item in scoped] == [str(rows[0].id)]


def test_an_anonymous_export_is_refused():
    response = TestClient(app).get(EXPORT)
    assert response.status_code == 401


def test_exporting_writes_no_audit_entry(db_session, admin_user):
    entity = uuid.uuid4()
    _write(db_session, [_entry(admin_user, entity, 0)])
    client = make_client_for_user(db_session, admin_user)

    def count():
        db_session.expire_all()
        return db_session.query(func.count(AuditLog.id)).scalar()

    before = count()
    for fmt in ("json", "csv"):
        assert client.get(EXPORT, params={"format": fmt}).status_code == 200
        assert (
            client.get(
                EXPORT, params={"entity_id": str(entity), "format": fmt}
            ).status_code
            == 200
        )
    assert count() == before
