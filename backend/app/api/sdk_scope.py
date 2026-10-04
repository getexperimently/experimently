"""
The ``sdk:ruleset`` scope, enforced.

:func:`require_sdk_ruleset_key` is the dependency for the server-side SDK
routes: the flag ruleset for local evaluation (``GET /api/v1/sdk/ruleset``),
the local evaluation counts (``POST /api/v1/tracking/evaluations``) and batch
assignment (``POST /api/v1/tracking/assign/batch``).  It is layered on
``deps.get_api_key`` (which validates the key, its owner and records its use)
and then decides on the **presented** key itself: it re-hashes the
``X-API-Key`` header and reads that one ``APIKey`` row, so another key of the
same user carrying the scope grants nothing.  Scope membership is
:func:`backend.app.core.api_key_scopes.has_scope` -- exact and case-sensitive
after split, strip and dropping empties.

The scope takes effect only while the key's owner can change feature flags
(``check_permission(owner, FEATURE_FLAG, UPDATE)``: ADMIN, DEVELOPER or a
superuser).  That is also who can change experiments
(``backend/tests/unit/core/test_flag_and_experiment_update_roles.py`` pins
the two equal for every role), which batch assignment relies on.  It is
checked on every request, so it follows role changes.  The owner is the
presented key's own ``user_id``, read from the database, not whatever
``get_api_key`` returned.

Refusals: no or unknown key -> 401 (from ``get_api_key``); a valid key without
the scope -> 403; a scoped key whose owner cannot change feature flags -> 403.
The two 403 texts are the same on every route.
"""

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.core.api_key_scopes import SDK_RULESET_SCOPE, has_scope
from backend.app.core.permissions import Action, ResourceType, check_permission
from backend.app.core.security import hash_api_key
from backend.app.models.api_key import APIKey
from backend.app.models.user import User

#: The 403 detail for a valid key that lacks the scope.
MISSING_SCOPE_DETAIL = (
    f"This API key does not have the '{SDK_RULESET_SCOPE}' scope. Create a key "
    f"with the '{SDK_RULESET_SCOPE}' scope for server-side SDK use."
)

#: The 403 detail for a scoped key whose owner cannot change feature flags.
OWNER_ROLE_DETAIL = (
    "This key's owner can no longer change feature flags or experiments, so the "
    "key is refused for server-side SDK use."
)


def require_sdk_ruleset_key(
    db: Session = Depends(deps.get_db),
    api_key_header: str = Depends(deps.API_KEY_HEADER),
    _owner: User = Depends(deps.get_api_key),
) -> APIKey:
    """Return the presented ``APIKey`` row if it carries ``sdk:ruleset``."""
    if not api_key_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key missing",
            headers={"WWW-Authenticate": "APIKey"},
        )
    api_key = (
        db.query(APIKey).filter(APIKey.key == hash_api_key(api_key_header)).first()
    )
    if api_key is None or not api_key.is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
            headers={"WWW-Authenticate": "APIKey"},
        )
    if not has_scope(api_key.scopes, SDK_RULESET_SCOPE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=MISSING_SCOPE_DETAIL
        )
    owner = db.query(User).filter(User.id == api_key.user_id).first()
    if (
        owner is None
        or not owner.is_active
        or not check_permission(owner, ResourceType.FEATURE_FLAG, Action.UPDATE)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=OWNER_ROLE_DETAIL
        )
    return api_key
