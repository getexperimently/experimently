"""
The ``sdk:ruleset`` scope, enforced.

:func:`require_sdk_ruleset_key` is the dependency for the routes that serve
server-side local evaluation.  It is layered on ``deps.get_api_key`` (which
validates the key, its owner and records its use) and then decides on the
**presented** key itself: it re-hashes the ``X-API-Key`` header and reads that
one ``APIKey`` row, so another key of the same user carrying the scope grants
nothing.  Scope membership is :func:`backend.app.core.api_key_scopes.has_scope`
-- exact and case-sensitive after split, strip and dropping empties.

Refusals: no or unknown key -> 401 (from ``get_api_key``); a valid key without
the scope -> 403.
"""

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.core.api_key_scopes import SDK_RULESET_SCOPE, has_scope
from backend.app.core.security import hash_api_key
from backend.app.models.api_key import APIKey
from backend.app.models.user import User

#: The 403 detail for a valid key that lacks the scope.
MISSING_SCOPE_DETAIL = (
    f"This API key does not have the '{SDK_RULESET_SCOPE}' scope. Create a key "
    f"with the '{SDK_RULESET_SCOPE}' scope for server-side local evaluation."
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
    return api_key
