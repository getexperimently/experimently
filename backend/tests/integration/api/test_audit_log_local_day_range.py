"""The audit log page's date range answers for the browser's local days (#665).

The dashboard's date pickers hold calendar days and the table shows each
entry in the browser's local time. ``frontend/src/utils/auditDates.ts`` turns
"From D1, To D2" into ``from_date`` = local midnight starting D1 and
``to_date`` = local midnight starting the day after D2, each sent as
``Date.toISOString()`` (UTC, millisecond precision, ``Z``). ``dashboard_bounds``
below builds the same two strings for a named zone, so the API is asked
exactly what a browser in that zone would ask.

Before #665 the page sent ``start_date``/``end_date``, which the API does not
read: every range answered every entry. A bare rename (sending the day itself
as ``from_date``/``to_date``) would refuse a one-day range with 400, because
``to_date <= from_date``, and would cut the To day off at its first instant.

``to_date`` is inclusive (``<=``), so an entry stamped exactly at the next
local midnight is counted in the range. That one instant is accepted.
"""

import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from backend.app.main import app
from backend.app.models.audit_log import ActionType, AuditLog, EntityType
from backend.app.models.user import User, UserRole
from backend.tests.integration.conftest import HASHED_PASSWORD, make_client_for_user

pytestmark = [pytest.mark.integration, pytest.mark.regression]

DAY = date(2031, 3, 14)

# West and east of UTC, a half-hour and a 45-minute offset, and UTC itself.
ZONES = ["America/Los_Angeles", "Asia/Kolkata", "Pacific/Chatham", "UTC"]


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _local(zone: str, day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=ZoneInfo(zone))


def _iso_like_browser(moment: datetime) -> str:
    """``Date.prototype.toISOString``: UTC, three decimals, ``Z``."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def dashboard_bounds(zone: str, first: date, last: date) -> dict:
    """What ``localDayRange(first, last)`` sends from a browser in *zone*."""
    return {
        "from_date": _iso_like_browser(_local(zone, first, 0)),
        "to_date": _iso_like_browser(_local(zone, last + timedelta(days=1), 0)),
    }


@pytest.fixture
def actor(db_session: Session) -> User:
    """A fresh user whose entries no other test writes, so ``user_id`` isolates them."""
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"audit_day_{suffix}",
        email=f"audit_day_{suffix}@int.test",
        hashed_password=HASHED_PASSWORD,
        is_active=True,
        is_superuser=False,
        role=UserRole.DEVELOPER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _entry(db: Session, user: User, label: str, stamp: datetime) -> None:
    db.add(
        AuditLog(
            user_id=user.id,
            user_email=user.email,
            action_type=ActionType.TOGGLE_ENABLE.value,
            entity_type=EntityType.FEATURE_FLAG.value,
            entity_id=uuid.uuid4(),
            entity_name="day-range-flag",
            reason=label,
            timestamp=stamp,
        )
    )


@pytest.mark.parametrize("zone", ZONES)
def test_a_one_day_range_is_that_whole_local_day(db_session, admin_user, actor, zone):
    next_day = DAY + timedelta(days=1)
    stamps = {
        "previous-23:59": _local(zone, DAY - timedelta(days=1), 23, 59),
        "day-00:00": _local(zone, DAY, 0, 0),
        "day-12:00": _local(zone, DAY, 12, 0),
        "day-23:00": _local(zone, DAY, 23, 0),
        "next-00:30": _local(zone, next_day, 0, 30),
    }
    for label, stamp in stamps.items():
        _entry(db_session, actor, label, stamp)
    db_session.commit()

    client = make_client_for_user(db_session, admin_user)
    response = client.get(
        "/api/v1/audit-logs/",
        params={
            "user_id": str(actor.id),
            "limit": 1000,
            **dashboard_bounds(zone, DAY, DAY),
        },
    )

    assert response.status_code == 200, response.text
    returned = {item["reason"] for item in response.json()["items"]}
    assert returned == {"day-00:00", "day-12:00", "day-23:00"}


@pytest.mark.parametrize("zone", ZONES)
def test_a_range_ends_after_the_last_hour_of_the_to_day(
    db_session, admin_user, actor, zone
):
    first, last = DAY, DAY + timedelta(days=2)
    stamps = {
        "first-00:00": _local(zone, first, 0, 0),
        "last-23:00": _local(zone, last, 23, 0),
        "after-00:30": _local(zone, last + timedelta(days=1), 0, 30),
    }
    for label, stamp in stamps.items():
        _entry(db_session, actor, label, stamp)
    db_session.commit()

    client = make_client_for_user(db_session, admin_user)
    response = client.get(
        "/api/v1/audit-logs/",
        params={
            "user_id": str(actor.id),
            "limit": 1000,
            **dashboard_bounds(zone, first, last),
        },
    )

    assert response.status_code == 200, response.text
    returned = {item["reason"] for item in response.json()["items"]}
    assert returned == {"first-00:00", "last-23:00"}


def test_the_bounds_also_parse_with_an_explicit_offset(db_session, admin_user, actor):
    """The API compares instants, so ``-07:00`` and ``Z`` forms agree."""
    zone = "America/Los_Angeles"
    _entry(db_session, actor, "day-23:00", _local(zone, DAY, 23, 0))
    _entry(
        db_session, actor, "next-00:30", _local(zone, DAY + timedelta(days=1), 0, 30)
    )
    db_session.commit()

    client = make_client_for_user(db_session, admin_user)
    response = client.get(
        "/api/v1/audit-logs/",
        params={
            "user_id": str(actor.id),
            "from_date": _local(zone, DAY, 0).isoformat(),
            "to_date": _local(zone, DAY + timedelta(days=1), 0).isoformat(),
        },
    )

    assert response.status_code == 200, response.text
    assert {item["reason"] for item in response.json()["items"]} == {"day-23:00"}
