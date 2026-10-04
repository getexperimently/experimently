"""Segments made from a list of user ids, and the member routes (#440).

Through the routes, against a real database:

* ``kind`` is ``rules`` or ``id_list``, set on create and never changed; an
  id list has no rules;
* ``POST /segments/{id}/members`` and ``/members/remove`` take 1 to 10,000
  ids of 1 to 255 characters, refuse unknown fields, and answer 422 with fixed
  text that never repeats a submitted id;
* a segment holds at most ``MAX_SEGMENT_MEMBERS`` ids, checked before anything
  is written, under ``SELECT ... FOR UPDATE`` on the segment row;
* add and remove are idempotent and answer exact counts;
* evaluate and bulk-evaluate answer an id list on ``user_context.user_id``;
* only DEVELOPER and ADMIN change members.

The audit entries (counts only) are pinned in ``test_audit_route_events.py``.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event, text

from backend.app.models.segment import Segment, SegmentKind
from backend.app.models.segment import SegmentStatus as ModelSegmentStatus
from backend.app.services import audience_service

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

COLLECTION = "/api/v1/segments"
SCHEMA = "test_experimentation"
#: Part of every submitted id in the refusal tests: never in a response.
MARKER = "member-marker-b440"

US = {
    "logical_operator": "AND",
    "groups": [
        {
            "logical_operator": "AND",
            "conditions": [
                {"attribute": "country", "operator": "equals", "value": "US"}
            ],
        }
    ],
}


def _members(segment_id: str) -> str:
    return f"{COLLECTION}/{segment_id}/members"


def _create_id_list(client, name=None) -> str:
    response = client.post(
        COLLECTION,
        json={"name": name or f"Ids {uuid.uuid4().hex[:8]}", "kind": "id_list"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _stored_count(db_session, segment_id) -> int:
    db_session.rollback()
    return db_session.execute(
        text(f"SELECT count(*) FROM {SCHEMA}.segment_members WHERE segment_id = :s"),
        {"s": segment_id},
    ).scalar()


@pytest.fixture
def stored_id_list(db_session, admin_user):
    """An id-list segment written directly, for tests whose client is not an admin."""
    made = []

    def _make(status=ModelSegmentStatus.ACTIVE):
        segment = Segment(
            name=f"Stored ids {uuid.uuid4().hex[:8]}",
            kind=SegmentKind.ID_LIST.value,
            rules=None,
            status=status,
            owner_id=admin_user.id,
        )
        db_session.add(segment)
        db_session.commit()
        made.append(segment.id)
        return str(segment.id)

    yield _make
    db_session.rollback()
    if made:
        db_session.query(Segment).filter(Segment.id.in_(made)).delete(
            synchronize_session=False
        )
        db_session.commit()


# ---------------------------------------------------------------------------
# B16: kind
# ---------------------------------------------------------------------------


def test_kind_an_id_list_is_created_without_rules(admin_client):
    response = admin_client.post(
        COLLECTION, json={"name": "Pilot customers", "kind": "id_list"}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "id_list"
    assert body["rules"] is None
    got = admin_client.get(f"{COLLECTION}/{body['id']}").json()
    assert (got["kind"], got["rules"], got["member_count"]) == ("id_list", None, 0)


def test_kind_defaults_to_rules(admin_client):
    response = admin_client.post(COLLECTION, json={"name": "US", "rules": US})
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["kind"], body["rules"]) == ("rules", US)
    got = admin_client.get(f"{COLLECTION}/{body['id']}").json()
    assert got["member_count"] is None


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"kind": "id_list", "rules": US}, "rules: an id_list segment has no rules"),
        ({"kind": "rules"}, "rules: required for a rules segment"),
        ({}, "rules: required for a rules segment"),
    ],
    ids=["id-list-with-rules", "rules-without-rules", "default-without-rules"],
)
def test_kind_and_rules_must_agree_on_create(admin_client, payload, message):
    response = admin_client.post(COLLECTION, json={"name": "Refused", **payload})
    assert response.status_code == 422, response.text
    [error] = response.json()["detail"]
    assert error["msg"] == f"Value error, {message}"


@pytest.mark.parametrize("kind", ["rules", "id_list", "anything"])
def test_kind_cannot_be_changed(admin_client, kind):
    segment_id = _create_id_list(admin_client)
    response = admin_client.put(f"{COLLECTION}/{segment_id}", json={"kind": kind})
    assert response.status_code == 422, response.text
    [error] = response.json()["detail"]
    assert error["msg"] == "Value error, kind: a segment's kind cannot be changed"
    assert admin_client.get(f"{COLLECTION}/{segment_id}").json()["kind"] == "id_list"


def test_kind_an_id_list_takes_no_rules_on_update(admin_client):
    segment_id = _create_id_list(admin_client)
    response = admin_client.put(f"{COLLECTION}/{segment_id}", json={"rules": US})
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "rules: an id_list segment has no rules"
    assert admin_client.get(f"{COLLECTION}/{segment_id}").json()["rules"] is None
    renamed = admin_client.put(f"{COLLECTION}/{segment_id}", json={"name": "Renamed"})
    assert renamed.status_code == 200, renamed.text


@pytest.mark.parametrize("route", ["members", "members/remove"])
def test_kind_member_routes_refuse_a_rules_segment(admin_client, route):
    created = admin_client.post(COLLECTION, json={"name": "US", "rules": US}).json()
    field = "add" if route == "members" else "remove"
    response = admin_client.post(
        f"{COLLECTION}/{created['id']}/{route}", json={field: ["u1"]}
    )
    assert response.status_code == 409, response.text
    verb = "added only to" if route == "members" else "removed only from"
    assert response.json()["detail"] == f"members can be {verb} an id_list segment"


@pytest.mark.parametrize("route", ["members", "members/remove"])
def test_kind_member_routes_refuse_an_archived_segment(admin_client, db_session, route):
    segment_id = _create_id_list(admin_client)
    assert admin_client.delete(f"{COLLECTION}/{segment_id}").status_code == 204
    field = "add" if route == "members" else "remove"
    response = admin_client.post(
        f"{COLLECTION}/{segment_id}/{route}", json={field: ["u1"]}
    )
    assert response.status_code == 409, response.text
    assert (
        response.json()["detail"]
        == "this segment is archived; its members cannot be changed"
    )
    assert _stored_count(db_session, segment_id) == 0


@pytest.mark.parametrize("route", ["members", "members/remove"])
def test_kind_member_routes_unknown_and_non_uuid(admin_client, route):
    field = "add" if route == "members" else "remove"
    unknown = admin_client.post(
        f"{COLLECTION}/{uuid.uuid4()}/{route}", json={field: ["u1"]}
    )
    assert unknown.status_code == 404, unknown.text
    not_uuid = admin_client.post(f"{COLLECTION}/abc/{route}", json={field: ["u1"]})
    assert not_uuid.status_code == 422, not_uuid.text


# ---------------------------------------------------------------------------
# B10, B11: request limits and unknown fields
# ---------------------------------------------------------------------------

LIMIT_CASES = [
    ([f"{MARKER}-{i}" for i in range(10_000)], None),
    ([f"{MARKER}-{i}" for i in range(10_001)], "add: at most 10,000 IDs per request"),
    ([MARKER, MARKER + "x" * (255 - len(MARKER))], None),
    (
        [MARKER, MARKER + "x" * (256 - len(MARKER))],
        "add[1]: an ID is 1 to 255 characters",
    ),
    ([MARKER, ""], "add[1]: an ID is 1 to 255 characters"),
    ([MARKER, 7], "add[1]: an ID is 1 to 255 characters"),
    ([], "add: at least 1 ID is required"),
    (MARKER, "add: a list of IDs is required"),
]
LIMIT_IDS = [
    "10000-ok",
    "10001-refused",
    "255-ok",
    "256-refused",
    "empty-id",
    "number",
    "no-ids",
    "not-a-list",
]


@pytest.mark.parametrize("ids, message", LIMIT_CASES, ids=LIMIT_IDS)
def test_request_limits(admin_client, db_session, ids, message):
    segment_id = _create_id_list(admin_client)
    response = admin_client.post(_members(segment_id), json={"add": ids})
    if message is None:
        assert response.status_code == 200, response.text[:500]
        assert response.json()["added"] == len(ids)
        return
    assert response.status_code == 422, response.text[:500]
    [error] = response.json()["detail"]
    assert error["loc"] == ["body", "add"]
    assert error["msg"] == f"Value error, {message}"
    assert MARKER not in response.text
    assert _stored_count(db_session, segment_id) == 0


@pytest.mark.parametrize(
    "ids, message",
    [
        (
            [f"{MARKER}-{i}" for i in range(10_001)],
            "remove: at most 10,000 IDs per request",
        ),
        ([MARKER, "x" * 256], "remove[1]: an ID is 1 to 255 characters"),
        ([], "remove: at least 1 ID is required"),
    ],
    ids=["10001", "256", "none"],
)
def test_request_limits_on_remove(admin_client, ids, message):
    segment_id = _create_id_list(admin_client)
    response = admin_client.post(f"{_members(segment_id)}/remove", json={"remove": ids})
    assert response.status_code == 422, response.text[:500]
    [error] = response.json()["detail"]
    assert error["msg"] == f"Value error, {message}"
    assert MARKER not in response.text


@pytest.mark.parametrize(
    "route, body",
    [
        ("members", {"ids": [MARKER]}),
        ("members", {"add": [MARKER], "remove": [MARKER]}),
        ("members/remove", {"remove": [MARKER], "add": [MARKER]}),
    ],
    ids=["wrong-key", "add-plus-extra", "remove-plus-extra"],
)
def test_unknown_fields_are_refused(admin_client, db_session, route, body):
    segment_id = _create_id_list(admin_client)
    response = admin_client.post(f"{COLLECTION}/{segment_id}/{route}", json=body)
    assert response.status_code == 422, response.text
    assert "extra_forbidden" in {e["type"] for e in response.json()["detail"]}
    assert MARKER not in response.text
    assert _stored_count(db_session, segment_id) == 0


# ---------------------------------------------------------------------------
# B12, B13: the cap, under the row lock
# ---------------------------------------------------------------------------


def test_the_segment_cap_writes_nothing(admin_client, db_session, monkeypatch):
    monkeypatch.setattr(audience_service, "MAX_SEGMENT_MEMBERS", 5)
    segment_id = _create_id_list(admin_client)
    first = admin_client.post(_members(segment_id), json={"add": ["a", "b", "c"]})
    assert first.json() == {"added": 3, "already_members": 0, "member_count": 3}

    # 4 new ids and 1 already stored: 3 + 4 = 7.
    response = admin_client.post(
        _members(segment_id), json={"add": ["a", "d", "e", "f", "g", "g"]}
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == (
        "this segment would have 7 members; a segment holds at most 5"
    )
    assert _stored_count(db_session, segment_id) == 3

    # Exactly at the cap is accepted.
    response = admin_client.post(_members(segment_id), json={"add": ["d", "e"]})
    assert response.json() == {"added": 2, "already_members": 0, "member_count": 5}


@pytest.fixture
def statements(db_session):
    engine = db_session.get_bind()
    seen: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        seen.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


def _first(seen, *needles):
    return next(
        i for i in range(len(seen)) if all(n in seen[i].upper() for n in needles)
    )


@pytest.mark.parametrize("route", ["members", "members/remove"])
def test_member_changes_lock_the_segment_row(admin_client, statements, route):
    segment_id = _create_id_list(admin_client)
    statements.clear()
    field = "add" if route == "members" else "remove"
    response = admin_client.post(
        f"{COLLECTION}/{segment_id}/{route}", json={field: ["u1", "u2"]}
    )
    assert response.status_code == 200, response.text
    lock = _first(statements, "FROM", "SEGMENTS", "FOR UPDATE")
    write = _first(
        statements,
        "INSERT INTO" if route == "members" else "DELETE FROM",
        "SEGMENT_MEMBERS",
    )
    count = _first(statements, "COUNT(", "SEGMENT_MEMBERS")
    assert lock < write, statements
    assert lock < count, statements


# ---------------------------------------------------------------------------
# B14, B15: idempotent, exact counts
# ---------------------------------------------------------------------------


def test_add_and_remove_are_idempotent(admin_client):
    segment_id = _create_id_list(admin_client)
    first = admin_client.post(_members(segment_id), json={"add": ["a", "b", "c"]})
    assert first.json() == {"added": 3, "already_members": 0, "member_count": 3}
    again = admin_client.post(_members(segment_id), json={"add": ["a", "b", "c", "a"]})
    assert again.status_code == 200, again.text
    assert again.json() == {"added": 0, "already_members": 3, "member_count": 3}

    gone = admin_client.post(f"{_members(segment_id)}/remove", json={"remove": ["z"]})
    assert gone.status_code == 200, gone.text
    assert gone.json() == {"removed": 0, "not_members": 1, "member_count": 3}
    twice = admin_client.post(
        f"{_members(segment_id)}/remove", json={"remove": ["a", "a"]}
    )
    assert twice.json() == {"removed": 1, "not_members": 0, "member_count": 2}


def test_ids_are_matched_exactly(admin_client):
    segment_id = _create_id_list(admin_client)
    admin_client.post(_members(segment_id), json={"add": ["User-1"]})
    response = admin_client.post(
        _members(segment_id), json={"add": ["user-1", " User-1", "User-1"]}
    )
    assert response.json() == {"added": 2, "already_members": 1, "member_count": 3}


def test_member_count_is_exact(admin_client, db_session):
    segment_id = _create_id_list(admin_client)
    admin_client.post(_members(segment_id), json={"add": ["a", "b", "c", "d", "e"]})
    removed = admin_client.post(
        f"{_members(segment_id)}/remove", json={"remove": ["a", "b", "q"]}
    ).json()
    stored = _stored_count(db_session, segment_id)
    assert stored == 3
    assert removed["member_count"] == stored
    assert admin_client.get(f"{COLLECTION}/{segment_id}").json()["member_count"] == 3
    listed = admin_client.get(COLLECTION, params={"limit": 200}).json()
    assert all(item["member_count"] is None for item in listed)


# ---------------------------------------------------------------------------
# B17: evaluate an id list
# ---------------------------------------------------------------------------


def test_evaluate_an_id_list(admin_client):
    segment_id = _create_id_list(admin_client)
    admin_client.post(_members(segment_id), json={"add": ["u1"]})

    def evaluate(context):
        response = admin_client.post(
            f"{COLLECTION}/{segment_id}/evaluate", json={"user_context": context}
        )
        assert response.status_code == 200, response.text
        return response.json()

    member = evaluate({"user_id": "u1", "country": "DE"})
    assert (member["is_member"], member["matched_rules"]) == (True, [])
    assert evaluate({"user_id": "u2"})["is_member"] is False
    assert evaluate({"country": "US"})["is_member"] is False
    assert evaluate({"user_id": 1})["is_member"] is False
    assert evaluate({"user_id": ["u1"]})["is_member"] is False
    assert evaluate({"user": {"user_id": "u1"}})["is_member"] is False
    assert evaluate({"user_id": "u1\x00"})["is_member"] is False

    bulk = admin_client.post(
        f"{COLLECTION}/bulk-evaluate",
        json={"user_context": {"user_id": "u1"}, "segment_ids": [segment_id]},
    )
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["memberships"] == {segment_id: True}


def test_preview_takes_rules(admin_client):
    segment_id = _create_id_list(admin_client)
    response = admin_client.post(
        f"{COLLECTION}/{segment_id}/preview",
        json={"name": "Preview", "kind": "id_list"},
    )
    assert response.status_code == 422, response.text
    assert (
        response.json()["detail"] == "rules: preview takes rules; an id_list has none"
    )


# ---------------------------------------------------------------------------
# B18: roles (non-superusers)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("route", ["members", "members/remove"])
def test_roles_analyst_cannot_change_members(
    stored_id_list, analyst_client, db_session, route
):
    segment_id = stored_id_list()
    field = "add" if route == "members" else "remove"
    response = analyst_client.post(
        f"{COLLECTION}/{segment_id}/{route}", json={field: ["u1"]}
    )
    assert response.status_code == 403, response.text
    assert _stored_count(db_session, segment_id) == 0


@pytest.mark.parametrize("route", ["members", "members/remove"])
def test_roles_viewer_cannot_change_members(
    stored_id_list, viewer_client, db_session, route
):
    segment_id = stored_id_list()
    field = "add" if route == "members" else "remove"
    response = viewer_client.post(
        f"{COLLECTION}/{segment_id}/{route}", json={field: ["u1"]}
    )
    assert response.status_code == 403, response.text


def test_roles_developer_changes_members(stored_id_list, developer_client, db_session):
    segment_id = stored_id_list()
    added = developer_client.post(_members(segment_id), json={"add": ["u1", "u2"]})
    assert added.status_code == 200, added.text
    removed = developer_client.post(
        f"{_members(segment_id)}/remove", json={"remove": ["u1"]}
    )
    assert removed.status_code == 200, removed.text
    assert _stored_count(db_session, segment_id) == 1


def test_deleting_a_segment_row_deletes_its_members(admin_client, db_session):
    """ON DELETE CASCADE: no member outlives its segment."""
    segment_id = _create_id_list(admin_client)
    admin_client.post(_members(segment_id), json={"add": ["a", "b"]})
    db_session.rollback()
    db_session.query(Segment).filter(Segment.id == uuid.UUID(segment_id)).delete(
        synchronize_session=False
    )
    db_session.commit()
    assert _stored_count(db_session, segment_id) == 0
