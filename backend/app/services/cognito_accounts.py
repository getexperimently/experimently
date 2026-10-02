"""Find the account a Cognito sign-in belongs to.

Under ``AUTH_PROVIDER=cognito`` every authenticated request resolves the
caller's Cognito identity to one ``users`` row. The key is the Cognito user ID
(the ``sub`` attribute), stored on the row as ``external_id = "cognito:<sub>"``.
The ``cognito:`` prefix keeps these values apart from the identity-provider
subjects single sign-on stores in the same column.

The cases, evaluated in order (every refusal is decided before anything is
written):

== ========================================================= =====================
#  Case                                                      Outcome
== ========================================================= =====================
0  ``sub`` absent or blank                                   refuse ``no_sub``
1  a row has ``external_id = cognito:<sub>``                 that row; its role
                                                             follows the token's
                                                             groups when
                                                             ``SYNC_ROLES_ON_LOGIN``
2  the username names a row with a password                  refuse
                                                             ``local_password``
3  the username names a row with another ``external_id``     refuse
                                                             ``linked_elsewhere``
4  the username names a row with neither                     refuse
                                                             ``legacy_unlinked``
5  the identity has no email address                         refuse ``no_email``
6  another row holds the address, in any letter case         refuse ``email_taken``
7  otherwise                                                 create the row, role
                                                             from the groups
8  the create's commit fails                                 roll back, look the
                                                             ID up once more:
                                                             that row, or refuse
                                                             ``commit_failed``
== ========================================================= =====================

An account that existed before its first Cognito sign-in is used only once an
administrator has linked it by setting its ``external_id``; nothing here links
a row by username or email. A row's username, email and name are never
rewritten from Cognito.
"""

import logging
from typing import Any, Mapping, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.cognito import map_cognito_groups_to_role, should_be_superuser
from backend.app.core.config import settings
from backend.app.models.user import User, UserRole

#: The record of a refused Cognito sign-in -- the same logger the token check
#: in ``auth_service`` writes to. Its ``reason`` field is one of the codes below.
sign_in_logger = logging.getLogger("backend.app.auth.cognito_sign_in")

EXTERNAL_ID_PREFIX = "cognito:"

REASON_NO_SUB = "no_sub"
REASON_LOCAL_PASSWORD = "local_password"
REASON_LINKED_ELSEWHERE = "linked_elsewhere"
REASON_LEGACY_UNLINKED = "legacy_unlinked"
REASON_NO_EMAIL = "no_email"
REASON_EMAIL_TAKEN = "email_taken"
REASON_COMMIT_FAILED = "commit_failed"


class CognitoSignInRefused(Exception):
    """A Cognito identity that is not resolved to an account.

    The caller answers it with the generic 401 and records it with
    :func:`log_sign_in_refused`; the reason never reaches the response.
    """

    def __init__(
        self,
        reason: str,
        *,
        cognito_username: Optional[str] = None,
        sub: Optional[str] = None,
        row_id: Any = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.cognito_username = cognito_username
        self.sub = sub
        self.row_id = row_id


def log_sign_in_refused(refusal: CognitoSignInRefused) -> None:
    """Record a refused sign-in: reason, Cognito username, sub and the id of
    the row the identity was refused for (no email address)."""
    sign_in_logger.warning(
        "Cognito sign-in refused (%s): username=%s sub=%s row_id=%s",
        refusal.reason,
        refusal.cognito_username,
        refusal.sub,
        refusal.row_id,
        extra={
            "reason": refusal.reason,
            "cognito_username": refusal.cognito_username,
            "sub": refusal.sub,
            "row_id": str(refusal.row_id) if refusal.row_id is not None else None,
        },
    )


def cognito_external_id(sub: str) -> str:
    """The ``users.external_id`` value for the Cognito user ``sub``."""
    return f"{EXTERNAL_ID_PREFIX}{sub}"


def _role_from_groups(groups: list) -> Tuple[UserRole, bool]:
    is_superuser = should_be_superuser(groups)
    role = UserRole.ADMIN if is_superuser else map_cognito_groups_to_role(groups)
    return role, is_superuser


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def resolve_cognito_user(db: Session, user_data: Mapping[str, Any]) -> User:
    """Return the account for a Cognito identity, creating it on first sign-in.

    ``user_data`` is what ``CognitoAuthService.get_user_with_groups`` returns:
    ``{"username", "attributes": {"sub", "email"?, ...}, "groups": [...]}``.

    Raises :class:`CognitoSignInRefused` with the session left unchanged --
    the caller rolls back before answering.
    """
    username = user_data.get("username")
    attributes = user_data.get("attributes") or {}
    sub = _text(attributes.get("sub"))

    def refuse(reason: str, row_id: Any = None) -> CognitoSignInRefused:
        return CognitoSignInRefused(
            reason, cognito_username=username, sub=sub or None, row_id=row_id
        )

    # 0. Without the Cognito user ID there is nothing to key the account on.
    if not sub:
        raise refuse(REASON_NO_SUB)
    external_id = cognito_external_id(sub)
    role, is_superuser = _role_from_groups(list(user_data.get("groups") or []))

    # 1. The account linked to this Cognito user.
    user = db.query(User).filter(User.external_id == external_id).first()
    if user is not None:
        if settings.SYNC_ROLES_ON_LOGIN and (
            user.role != role or user.is_superuser != is_superuser
        ):
            user.role = role
            user.is_superuser = is_superuser
            db.commit()
            db.refresh(user)
        return user

    # 2-4. An account already uses this username but is not linked to this
    # Cognito user: it is used only after an administrator links it.
    namesake = db.query(User).filter(User.username == username).first()
    if namesake is not None:
        if namesake.hashed_password:
            raise refuse(REASON_LOCAL_PASSWORD, namesake.id)
        if namesake.external_id:
            raise refuse(REASON_LINKED_ELSEWHERE, namesake.id)
        raise refuse(REASON_LEGACY_UNLINKED, namesake.id)

    # 5. Every account has an email address.
    email = _text(attributes.get("email"))
    if not email:
        raise refuse(REASON_NO_EMAIL)

    # 6. An address belongs to one account, whatever its letter case. The
    # account is never linked by email.
    holder = db.query(User.id).filter(func.lower(User.email) == email.lower()).first()
    if holder is not None:
        raise refuse(REASON_EMAIL_TAKEN, holder.id)

    # 7. A new account, linked to this Cognito user from the start.
    full_name = (
        f"{_text(attributes.get('given_name'))} {_text(attributes.get('family_name'))}"
    ).strip()
    user = User(
        username=username,
        email=email,
        full_name=full_name,
        is_active=True,
        role=role,
        is_superuser=is_superuser,
        external_id=external_id,
    )
    db.add(user)
    try:
        db.commit()
    except SQLAlchemyError:
        # 8. Most likely a concurrent first sign-in of the same identity
        # created the row first: use it if it is there.
        db.rollback()
        user = db.query(User).filter(User.external_id == external_id).first()
        if user is None:
            raise refuse(REASON_COMMIT_FAILED) from None
        return user
    db.refresh(user)
    return user
