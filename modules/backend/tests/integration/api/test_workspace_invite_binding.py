"""A workspace invite can be accepted only by the account it was sent to (#265).

``POST /api/v1/workspaces/invites/{token}/accept`` compares the accepting
account's stored email with the invite's stored email: both present, ASCII
after trimming, equal after lower-casing. Anything else is 403 with code
``invite_email_mismatch`` and a fixed message that names neither address, for
every account including a superuser, and before the expiry and
already-accepted checks.

Invites and users are written straight to the database where the test needs a
value the API would not produce (a non-ASCII character, surrounding spaces, a
missing email), so the rule is pinned on the values as stored, not only on
what ``EmailStr`` lets through.
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional

import pytest
from sqlalchemy.orm import Session

from backend.app.main import app
from backend.app.models.user import User, UserRole
from backend.tests.integration.conftest import make_client_for_user
from modules.backend.app.models.workspace import (
    WorkspaceInvite,
    WorkspaceMember,
    WorkspaceMemberRole,
)
from modules.backend.app.services.workspace_service import (
    INVITE_EMAIL_MISMATCH_CODE,
    INVITE_EMAIL_MISMATCH_MESSAGE,
    workspace_service,
)

HASHED_PASSWORD = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW"
KELVIN_SIGN = "K"  # lower-cases to ASCII "k"

MISMATCH = {
    "detail": {
        "code": INVITE_EMAIL_MISMATCH_CODE,
        "message": INVITE_EMAIL_MISMATCH_MESSAGE,
    }
}

NON_SUPERUSER_ROLES = [
    UserRole.ADMIN,
    UserRole.DEVELOPER,
    UserRole.ANALYST,
    UserRole.VIEWER,
]

pytestmark = pytest.mark.integration


def _user(
    db: Session,
    email: Optional[str],
    role: UserRole = UserRole.VIEWER,
    is_superuser: bool = False,
) -> User:
    user = User(
        username=f"inv_{uuid.uuid4().hex[:10]}",
        email=email,
        full_name="Invite Binding",
        hashed_password=HASHED_PASSWORD,
        is_active=True,
        is_superuser=is_superuser,
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _unique(local: str = "kim") -> str:
    return f"{local}.{uuid.uuid4().hex[:8]}@corp-example.com"


@pytest.fixture
def owner(db_session: Session) -> User:
    return _user(db_session, _unique("owner"), UserRole.ADMIN)


@pytest.fixture
def workspace(db_session: Session, owner: User):
    suffix = uuid.uuid4().hex[:8]
    return workspace_service.create_workspace(
        db_session, name=f"Bind {suffix}", slug=f"bind-{suffix}", owner_id=owner.id
    )


def _invite(
    db: Session, workspace, owner: User, email: str, role: str = "DEVELOPER"
) -> WorkspaceInvite:
    """An invite stored with ``email`` exactly as given (no EmailStr)."""
    return workspace_service.create_invite(
        db, workspace_id=workspace.id, email=email, role=role, invited_by=owner.id
    )


def _accept(db: Session, user: User, token: str):
    client = make_client_for_user(db, user)
    try:
        return client.post(f"/api/v1/workspaces/invites/{token}/accept")
    finally:
        app.dependency_overrides.clear()


def _state(db: Session, invite: WorkspaceInvite, user: User):
    """(accepted_at, is a member) read fresh from the database."""
    db.expire_all()
    accepted_at = (
        db.query(WorkspaceInvite.accepted_at)
        .filter(WorkspaceInvite.id == invite.id)
        .scalar()
    )
    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == invite.workspace_id,
            WorkspaceMember.user_id == user.id,
        )
        .first()
    )
    return accepted_at, member is not None


# ── The invited address joins ───────────────────────────────────────────────


@pytest.mark.parametrize("role", NON_SUPERUSER_ROLES, ids=lambda r: r.name)
def test_the_invited_address_joins_with_the_invited_role(
    db_session, owner, workspace, role
):
    email = _unique()
    invitee = _user(db_session, email, role)
    invite = _invite(db_session, workspace, owner, email, "ANALYST")

    resp = _accept(db_session, invitee, invite.token)

    assert resp.status_code == 201, resp.text
    assert resp.json()["role"] == WorkspaceMemberRole.ANALYST.value
    assert resp.json()["user_id"] == str(invitee.id)


def test_a_superuser_who_is_the_invitee_joins(db_session, owner, workspace):
    email = _unique()
    invitee = _user(db_session, email, UserRole.ADMIN, is_superuser=True)
    invite = _invite(db_session, workspace, owner, email)

    assert _accept(db_session, invitee, invite.token).status_code == 201


@pytest.mark.parametrize(
    "invited, stored",
    [
        ("Kim.{s}@Corp-Example.com", "kim.{s}@corp-example.com"),
        ("kim.{s}@corp-example.com", "KIM.{s}@CORP-EXAMPLE.COM"),
        ("  Kim.{s}@corp-example.com ", "kim.{s}@Corp-Example.com"),
    ],
    ids=["invite-mixed-case", "account-upper-case", "surrounding-spaces"],
)
def test_the_address_is_compared_without_case(
    db_session, owner, workspace, invited, stored
):
    s = uuid.uuid4().hex[:8]
    invitee = _user(db_session, stored.format(s=s))
    invite = _invite(db_session, workspace, owner, invited.format(s=s))

    resp = _accept(db_session, invitee, invite.token)

    assert resp.status_code == 201, resp.text


# ── Every other account is refused ──────────────────────────────────────────


@pytest.mark.regression
@pytest.mark.parametrize(
    "role, is_superuser",
    [(r, False) for r in NON_SUPERUSER_ROLES] + [(UserRole.ADMIN, True)],
    ids=[r.name for r in NON_SUPERUSER_ROLES] + ["superuser"],
)
def test_another_account_cannot_accept(
    db_session, owner, workspace, role, is_superuser
):
    """403 with the fixed body; the invite stays usable by the invitee."""
    invited = _unique()
    invitee = _user(db_session, invited)
    other = _user(db_session, _unique("other"), role, is_superuser)
    invite = _invite(db_session, workspace, owner, invited, "ADMIN")

    resp = _accept(db_session, other, invite.token)

    assert resp.status_code == 403, resp.text
    assert resp.json() == MISMATCH
    assert invited not in resp.text
    assert other.email not in resp.text
    assert _state(db_session, invite, other) == (None, False)

    # The refusal did not use the invite up.
    assert _accept(db_session, invitee, invite.token).status_code == 201


@pytest.mark.regression
def test_an_account_with_no_email_cannot_accept(db_session, owner, workspace):
    no_email = _user(db_session, None, UserRole.DEVELOPER)
    invite = _invite(db_session, workspace, owner, _unique())

    resp = _accept(db_session, no_email, invite.token)

    assert resp.status_code == 403, resp.text
    assert resp.json() == MISMATCH
    assert _state(db_session, invite, no_email) == (None, False)


@pytest.mark.regression
@pytest.mark.parametrize(
    "invited, stored",
    [
        ("kim.{s}@corp-example.com", KELVIN_SIGN + "im.{s}@corp-example.com"),
        (KELVIN_SIGN + "im.{s}@corp-example.com", "kim.{s}@corp-example.com"),
        ("kim.{s}@kite-example.com", "kim.{s}@" + KELVIN_SIGN + "ite-example.com"),
    ],
    ids=["account-local-part", "invite-local-part", "account-domain"],
)
def test_a_look_alike_address_is_not_the_invited_one(
    db_session, owner, workspace, invited, stored
):
    """A non-ASCII character that lower-cases to ASCII does not match.

    ``"\\u212a".lower() == "k"``, so lower-casing before the ASCII check would
    accept these. Both values are the raw stored strings.
    """
    s = uuid.uuid4().hex[:8]
    look_alike = _user(db_session, stored.format(s=s))
    invite = _invite(db_session, workspace, owner, invited.format(s=s))
    assert invited.format(s=s).lower() == stored.format(s=s).lower()

    resp = _accept(db_session, look_alike, invite.token)

    assert resp.status_code == 403, resp.text
    assert resp.json() == MISMATCH


@pytest.mark.regression
def test_an_alias_is_a_different_address(db_session, owner, workspace):
    s = uuid.uuid4().hex[:8]
    alias = _user(db_session, f"kim+work.{s}@corp-example.com")
    invite = _invite(db_session, workspace, owner, f"kim.{s}@corp-example.com")

    resp = _accept(db_session, alias, invite.token)

    assert resp.status_code == 403, resp.text


# ── Order of the refusals ───────────────────────────────────────────────────


@pytest.mark.regression
def test_the_address_is_checked_before_expiry_and_prior_acceptance(
    db_session, owner, workspace
):
    """Unknown 404; wrong account 403; expired 400; already accepted 409."""
    invited = _unique()
    invitee = _user(db_session, invited)
    other = _user(db_session, _unique("other"))

    assert _accept(db_session, other, "no-such-token").status_code == 404

    expired = _invite(db_session, workspace, owner, invited)
    expired.expires_at = datetime.utcnow() - timedelta(hours=1)
    db_session.commit()
    assert _accept(db_session, other, expired.token).json() == MISMATCH
    assert _accept(db_session, invitee, expired.token).status_code == 400

    used = _invite(db_session, workspace, owner, invited)
    assert _accept(db_session, invitee, used.token).status_code == 201
    assert _accept(db_session, other, used.token).json() == MISMATCH
    assert _accept(db_session, invitee, used.token).status_code == 409


# ── Creating an invite ──────────────────────────────────────────────────────


@pytest.mark.regression
@pytest.mark.parametrize(
    "email",
    [
        "not-an-address",
        "kim@",
        "@corp-example.com",
        "",
        "   ",
        "kim@@corp-example.com",
        "kim@corp@example.com",
        "kim smith@corp-example.com",
        KELVIN_SIGN + "im@corp-example.com",
        "k" * 244 + "@example.com",
        123,
        None,
    ],
    ids=[
        "no-at",
        "no-domain",
        "no-local-part",
        "empty",
        "blank",
        "double-at",
        "two-ats",
        "space",
        "non-ascii",
        "256-chars",
        "number",
        "null",
    ],
)
def test_an_invite_needs_a_valid_ascii_address(db_session, owner, workspace, email):
    client = make_client_for_user(db_session, owner)
    try:
        resp = client.post(
            f"/api/v1/workspaces/{workspace.id}/invites",
            json={"email": email, "role": "VIEWER"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422, resp.text
    assert (
        db_session.query(WorkspaceInvite).filter_by(workspace_id=workspace.id).count()
        == 0
    )


def test_an_invite_created_through_the_api_is_accepted_by_its_address(
    db_session, owner, workspace
):
    s = uuid.uuid4().hex[:8]
    client = make_client_for_user(db_session, owner)
    try:
        resp = client.post(
            f"/api/v1/workspaces/{workspace.id}/invites",
            json={"email": f"Kim.{s}@Corp-Example.COM", "role": "VIEWER"},
        )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 201, resp.text

    invitee = _user(db_session, f"kim.{s}@corp-example.com")
    assert _accept(db_session, invitee, resp.json()["token"]).status_code == 201


def _create_through_api(db: Session, owner: User, workspace, email: str):
    client = make_client_for_user(db, owner)
    try:
        return client.post(
            f"/api/v1/workspaces/{workspace.id}/invites",
            json={"email": email, "role": "VIEWER"},
        )
    finally:
        app.dependency_overrides.clear()


def test_the_longest_accepted_address_is_255_characters(db_session, owner, workspace):
    email = "k" * 243 + "@example.com"
    assert len(email) == 255
    resp = _create_through_api(db_session, owner, workspace, email)
    assert resp.status_code == 201, resp.text


def test_an_address_is_stored_trimmed(db_session, owner, workspace):
    s = uuid.uuid4().hex[:8]
    resp = _create_through_api(db_session, owner, workspace, f"  kim.{s}@corp.local ")
    assert resp.status_code == 201, resp.text
    assert resp.json()["email"] == f"kim.{s}@corp.local"


@pytest.mark.regression
@pytest.mark.parametrize(
    "domain",
    ["corp.local", "int.test", "home.arpa", "intranet"],
    ids=["local", "test", "home-arpa", "bare-host"],
)
def test_a_special_use_domain_can_be_invited_and_accept(
    db_session, owner, workspace, domain
):
    """Accounts on special-use domains (SSO can provision them) can be invited."""
    email = f"kim.{uuid.uuid4().hex[:8]}@{domain}"
    invitee = _user(db_session, email, UserRole.DEVELOPER)

    resp = _create_through_api(db_session, owner, workspace, email)
    assert resp.status_code == 201, resp.text
    assert resp.json()["email"] == email

    accepted = _accept(db_session, invitee, resp.json()["token"])
    assert accepted.status_code == 201, accepted.text


def test_the_accept_route_documents_its_403_body():
    """The 403 in the OpenAPI document has the typed body's schema."""
    spec = app.openapi()
    op = spec["paths"]["/api/v1/workspaces/invites/{token}/accept"]["post"]
    ref = op["responses"]["403"]["content"]["application/json"]["schema"]["$ref"]
    body = spec["components"]["schemas"][ref.rsplit("/", 1)[-1]]
    detail_ref = body["properties"]["detail"]["$ref"]
    detail = spec["components"]["schemas"][detail_ref.rsplit("/", 1)[-1]]
    assert body["required"] == ["detail"]
    assert set(detail["properties"]) == {"code", "message"}
    assert sorted(detail["required"]) == ["code", "message"]
