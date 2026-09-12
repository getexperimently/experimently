"""
User-owned API keys (Community Edition) — ``/api/v1/api-keys``.

Keys authenticate SDK traffic (``X-API-Key`` header on ``/tracking/*``,
flag evaluation, OpenFeature, edge bootstrap ...) as the owning user via
``deps.get_api_key``.  The plaintext secret is returned exactly once by the
create endpoint; only its SHA-256 hash is persisted (``APIKey.key``).

* ``GET /``            — the caller's keys; ADMIN may pass ``?all=true``.
* ``POST /``           — create; 201 with the plaintext ``key``.
* ``DELETE /{key_id}`` — owner or ADMIN; 204.

Workspace-scoped keys (EE) live under ``/workspaces/{id}/api-keys``.
"""

from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.core.permissions import (
    Action,
    ResourceType,
    check_permission,
    get_permission_error_message,
)
from backend.app.models.api_key import APIKey
from backend.app.models.user import User
from backend.app.schemas.api_key import (
    KEY_PREFIX_LENGTH,
    APIKeyCreate,
    APIKeyCreated,
    APIKeyRead,
)

router = APIRouter()


def _may_act_on_others_keys(user: User, action: Action) -> bool:
    """
    Whether *user* may perform *action* on keys they do not own.

    Own keys never go through this check; cross-user access is governed by
    the RBAC map (``ResourceType.API_KEY``), which grants it to ADMIN only.
    """
    return check_permission(user, ResourceType.API_KEY, action)


def _to_read(key: APIKey) -> APIKeyRead:
    scopes = [s.strip() for s in (key.scopes or "").split(",") if s.strip()]
    return APIKeyRead(
        id=key.id,
        name=key.name,
        description=key.description,
        scopes=scopes,
        is_active=bool(key.is_active),
        user_id=key.user_id,
        created_at=key.created_at,
        expires_at=key.expires_at,
        last_used_at=key.last_used_at,
    )


# Routes are registered without a trailing slash so ``POST /api/v1/api-keys``
# works from curl without following a 307; ``/api-keys/`` is redirected.
@router.get("", response_model=List[APIKeyRead])
def list_api_keys(
    all_users: bool = Query(
        False,
        alias="all",
        description="ADMIN only: list every user's keys instead of just your own",
    ),
    include_inactive: bool = Query(False, description="Include revoked keys"),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """List API keys owned by the caller (or all keys for ADMIN with ``?all=true``)."""
    query = db.query(APIKey)
    if all_users:
        if not _may_act_on_others_keys(current_user, Action.LIST):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=get_permission_error_message(ResourceType.API_KEY, Action.LIST),
            )
    else:
        query = query.filter(APIKey.user_id == current_user.id)
    if not include_inactive:
        query = query.filter(APIKey.is_active.is_(True))
    keys = query.order_by(APIKey.created_at.desc()).all()
    return [_to_read(k) for k in keys]


@router.post("", response_model=APIKeyCreated, status_code=status.HTTP_201_CREATED)
def create_api_key(
    body: APIKeyCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Create an API key for the caller.

    The response is the only place the plaintext ``key`` is ever shown; store
    it securely.  ``prefix`` (the first characters of the key) is returned so
    the key can be recognised later.
    """
    scopes = ",".join(body.scopes) if body.scopes else None
    api_key, plaintext = APIKey.create_for_user(
        db,
        user_id=current_user.id,
        name=body.name,
        description=body.description,
        scopes=scopes,
        expires_at=body.expires_at,
    )
    return APIKeyCreated(
        id=api_key.id,
        name=api_key.name,
        key=plaintext,
        prefix=plaintext[:KEY_PREFIX_LENGTH],
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_api_key(
    key_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Response:
    """Permanently delete an API key (owner or ADMIN)."""
    api_key: Optional[APIKey] = db.query(APIKey).filter(APIKey.id == key_id).first()
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    if api_key.user_id != current_user.id and not _may_act_on_others_keys(
        current_user, Action.DELETE
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=get_permission_error_message(ResourceType.API_KEY, Action.DELETE),
        )
    db.delete(api_key)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
