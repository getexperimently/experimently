"""``provision_user`` refuses a sign-in that more than one account matches (#343).

The lookup is ``lower(email) = <the signed-in address>``, so two accounts whose
addresses differ only in letter case both match it.  Since #343 the database
refuses such a pair (``ix_users_email_lower``), so an integration test can no
longer build one in the shared test schema; the refusal stays as a safeguard
for a database whose index was dropped by hand, and this test pins it with the
query stubbed to return two rows.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from backend.app.models.user import User, UserRole
from modules.backend.app.models.sso_config import SSOConfig, SSOProviderType
from modules.backend.app.services import sso_service

pytestmark = [pytest.mark.unit, pytest.mark.regression]

DOMAIN = "ambiguous.example.com"


def _config() -> SSOConfig:
    return SSOConfig(
        org_name="Ambiguous Org",
        org_domain=DOMAIN,
        provider_type=SSOProviderType.SAML,
        entity_id="client-id",
        role_mapping={"admins": "admin"},
        is_enforced=False,
        is_active=True,
    )


def _account(email: str) -> User:
    return User(
        id=uuid.uuid4(),
        username=f"u_{uuid.uuid4().hex[:8]}",
        email=email,
        role=UserRole.VIEWER,
        is_active=True,
    )


def _db_returning(rows: list) -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter.return_value.limit.return_value.all.return_value = rows
    return db


def test_two_matching_accounts_are_refused_and_nothing_is_written():
    rows = [_account(f"carol@{DOMAIN}"), _account(f"Carol@{DOMAIN}")]
    db = _db_returning(rows)
    info = {"email": f"carol@{DOMAIN}", "name_id": "carol", "groups": ["admins"]}

    with pytest.raises(sso_service.SSORefusal) as exc_info:
        sso_service.provision_user(db, info, _config())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == sso_service.EMAIL_AMBIGUOUS_DETAIL
    assert exc_info.value.sso_error == sso_service.SSO_ACCOUNT
    # Neither account is handed out or changed, and nothing is created.
    db.add.assert_not_called()
    db.commit.assert_not_called()
    assert [row.role for row in rows] == [UserRole.VIEWER, UserRole.VIEWER]
    # At most two rows are asked for: enough to tell one from many.
    db.query.return_value.filter.return_value.limit.assert_called_once_with(2)


def test_one_matching_account_is_returned():
    """The control: the same stub with one row is not refused."""
    (row,) = rows = [_account(f"Carol@{DOMAIN}")]
    db = _db_returning(rows)
    info = {"email": f"carol@{DOMAIN}", "name_id": "carol", "groups": []}

    assert sso_service.provision_user(db, info, _config()) is row
    db.add.assert_not_called()
