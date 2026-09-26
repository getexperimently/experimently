"""`deps.get_api_key` records when a key was last used (issue #198).

The write is throttled to one per key per `LAST_USED_RESOLUTION`, and a
failure to record it never fails authentication.
"""

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import OperationalError

from backend.app.api import deps
from backend.app.models.api_key import LAST_USED_RESOLUTION, APIKey

NOW = datetime(2026, 9, 26, 12, 0, 0)


def _key(last_used_at=None) -> APIKey:
    return APIKey(
        id=uuid.uuid4(),
        key="0" * 64,
        name="k",
        is_active=True,
        user_id=uuid.uuid4(),
        last_used_at=last_used_at,
    )


def _db_returning(api_key, user):
    """A session whose two lookups return the key, then the user."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [api_key, user]
    return db


@pytest.mark.unit
@pytest.mark.regression
def test_get_api_key_records_the_use():
    api_key = MagicMock(is_valid=True, user_id=uuid.uuid4())
    user = MagicMock(is_active=True)
    db = _db_returning(api_key, user)

    assert deps.get_api_key(db=db, api_key_header="eptk_x") is user
    api_key.update_last_used.assert_called_once_with(db)


@pytest.mark.unit
def test_a_failed_write_does_not_fail_authentication():
    api_key = MagicMock(is_valid=True, user_id=uuid.uuid4())
    api_key.update_last_used.side_effect = OperationalError("UPDATE", {}, None)
    user = MagicMock(is_active=True)
    db = _db_returning(api_key, user)

    assert deps.get_api_key(db=db, api_key_header="eptk_x") is user
    db.rollback.assert_called_once()


@pytest.mark.unit
def test_an_invalid_key_records_nothing():
    api_key = MagicMock(is_valid=False)
    db = _db_returning(api_key, None)

    with pytest.raises(deps.HTTPException) as exc:
        deps.get_api_key(db=db, api_key_header="eptk_x")
    assert exc.value.status_code == 401
    api_key.update_last_used.assert_not_called()


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize(
    "last_used_at",
    [None, NOW - LAST_USED_RESOLUTION, NOW - timedelta(hours=3)],
    ids=["never", "exactly-one-window", "stale"],
)
def test_update_last_used_writes_when_null_or_stale(last_used_at):
    db = MagicMock()
    db.execute.return_value.rowcount = 1

    assert _key(last_used_at).update_last_used(db, now=NOW) is True
    db.execute.assert_called_once()
    db.commit.assert_called_once()

    params = db.execute.call_args.args[0].compile().params
    assert params["last_used_at"] == NOW
    assert params["last_used_at_1"] == NOW - LAST_USED_RESOLUTION


@pytest.mark.unit
@pytest.mark.parametrize(
    "last_used_at",
    [NOW, NOW - timedelta(seconds=59), NOW + timedelta(seconds=5)],
    ids=["just-now", "inside-window", "clock-skew-ahead"],
)
def test_update_last_used_skips_a_recent_value(last_used_at):
    db = MagicMock()

    assert _key(last_used_at).update_last_used(db, now=NOW) is False
    db.execute.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.unit
def test_update_last_used_reports_a_lost_race():
    """Another worker wrote first: the guarded UPDATE matches no row."""
    db = MagicMock()
    db.execute.return_value.rowcount = 0

    assert _key(None).update_last_used(db, now=NOW) is False


@pytest.mark.unit
def test_default_now_is_naive_utc():
    """Naive UTC, like expires_at: comparable with the stored column."""
    db = MagicMock()
    db.execute.return_value.rowcount = 1
    before = datetime.utcnow()
    _key(None).update_last_used(db)
    written = db.execute.call_args.args[0].compile().params["last_used_at"]
    assert written.tzinfo is None
    assert before <= written <= datetime.utcnow()
