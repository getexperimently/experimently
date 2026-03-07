"""
Workspace API endpoints for EP-057: Multi-Tenant Team Workspaces.

Provides REST endpoints for workspace CRUD, member management,
invite lifecycle, and workspace-scoped API key management.
"""

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_active_user, get_db
from backend.app.models.user import User
from backend.app.models.workspace import (
    ROLE_HIERARCHY,
    Workspace,
    WorkspaceAPIKey,
    WorkspaceInvite,
    WorkspaceMember,
    WorkspaceMemberRole,
)
from backend.app.schemas.workspaces import (
    AddMemberRequest,
    CreateAPIKeyRequest,
    CreateAPIKeyResponse,
    CreateInviteRequest,
    CreateWorkspaceRequest,
    UpdateMemberRoleRequest,
    UpdateWorkspaceRequest,
    WorkspaceAPIKeyResponse,
    WorkspaceInviteResponse,
    WorkspaceMemberResponse,
    WorkspaceResponse,
    WorkspaceWithStatsResponse,
)
from backend.app.services.workspace_service import (
    AlreadyMember,
    APIKeyNotFound,
    CannotDemoteLastOwner,
    CannotRemoveLastOwner,
    InviteAlreadyAccepted,
    InviteExpired,
    InviteNotFound,
    PlanLimitExceeded,
    WorkspaceMemberNotFound,
    WorkspaceNotFound,
    WorkspaceSlugInvalid,
    WorkspaceSlugTaken,
    workspace_service,
)

router = APIRouter()

# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────


def _get_workspace_or_404(db: Session, workspace_id: uuid.UUID) -> Workspace:
    """Return workspace or raise 404."""
    try:
        return workspace_service.get_workspace(db, workspace_id)
    except WorkspaceNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _require_member(
    db: Session, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> WorkspaceMember:
    """Return the member record or raise 403."""
    member = workspace_service.get_member(db, workspace_id, user_id)
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this workspace.",
        )
    return member


def _require_role(
    db: Session,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    minimum_role: str,
) -> None:
    """Raise 403 unless the user holds at least minimum_role."""
    if not workspace_service.check_member_permission(
        db, workspace_id, user_id, minimum_role
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires {minimum_role} role or above.",
        )


def _member_to_response(member: WorkspaceMember) -> WorkspaceMemberResponse:
    """Serialize a WorkspaceMember, hydrating user fields if loaded."""
    username = None
    email = None
    if member.user is not None:
        username = member.user.username
        email = member.user.email
    return WorkspaceMemberResponse(
        workspace_id=str(member.workspace_id),
        user_id=str(member.user_id),
        role=member.role.value,
        joined_at=member.joined_at,
        username=username,
        email=email,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Workspace CRUD
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: CreateWorkspaceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Create a new workspace. The authenticated user becomes the OWNER."""
    try:
        workspace = workspace_service.create_workspace(
            db=db,
            name=payload.name,
            slug=payload.slug,
            owner_id=current_user.id,
            plan=payload.plan,
            description=payload.description,
        )
    except WorkspaceSlugInvalid as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except WorkspaceSlugTaken as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return WorkspaceResponse(
        id=str(workspace.id),
        name=workspace.name,
        slug=workspace.slug,
        description=workspace.description,
        plan=workspace.plan.value,
        is_active=workspace.is_active,
        max_experiments=workspace.max_experiments,
        max_feature_flags=workspace.max_feature_flags,
        max_members=workspace.max_members,
        max_api_keys=workspace.max_api_keys,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )


@router.get("/", response_model=List[WorkspaceResponse])
def list_my_workspaces(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List all workspaces the current user belongs to."""
    workspaces = workspace_service.list_user_workspaces(db, current_user.id)
    return [
        WorkspaceResponse(
            id=str(w.id),
            name=w.name,
            slug=w.slug,
            description=w.description,
            plan=w.plan.value,
            is_active=w.is_active,
            max_experiments=w.max_experiments,
            max_feature_flags=w.max_feature_flags,
            max_members=w.max_members,
            max_api_keys=w.max_api_keys,
            created_at=w.created_at,
            updated_at=w.updated_at,
        )
        for w in workspaces
    ]


@router.get("/{workspace_id}", response_model=WorkspaceWithStatsResponse)
def get_workspace(
    workspace_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get workspace details and stats. Caller must be a member."""
    workspace = _get_workspace_or_404(db, workspace_id)
    _require_member(db, workspace_id, current_user.id)

    try:
        stats = workspace_service.get_workspace_stats(db, workspace_id)
    except Exception:
        stats = None

    return WorkspaceWithStatsResponse(
        id=str(workspace.id),
        name=workspace.name,
        slug=workspace.slug,
        description=workspace.description,
        plan=workspace.plan.value,
        is_active=workspace.is_active,
        max_experiments=workspace.max_experiments,
        max_feature_flags=workspace.max_feature_flags,
        max_members=workspace.max_members,
        max_api_keys=workspace.max_api_keys,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
        member_count=stats.member_count if stats else 0,
        experiment_count=stats.experiment_count if stats else 0,
        flag_count=stats.flag_count if stats else 0,
        api_key_count=stats.api_key_count if stats else 0,
    )


@router.put("/{workspace_id}", response_model=WorkspaceResponse)
def update_workspace(
    workspace_id: uuid.UUID = Path(...),
    payload: UpdateWorkspaceRequest = ...,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Update workspace. Requires ADMIN role or above."""
    _get_workspace_or_404(db, workspace_id)
    _require_role(db, workspace_id, current_user.id, "ADMIN")

    workspace = workspace_service.update_workspace(
        db,
        workspace_id,
        payload.model_dump(exclude_none=True),
    )
    return WorkspaceResponse(
        id=str(workspace.id),
        name=workspace.name,
        slug=workspace.slug,
        description=workspace.description,
        plan=workspace.plan.value,
        is_active=workspace.is_active,
        max_experiments=workspace.max_experiments,
        max_feature_flags=workspace.max_feature_flags,
        max_members=workspace.max_members,
        max_api_keys=workspace.max_api_keys,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(
    workspace_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Delete workspace. Requires OWNER role."""
    _get_workspace_or_404(db, workspace_id)
    _require_role(db, workspace_id, current_user.id, "OWNER")
    workspace_service.delete_workspace(db, workspace_id)


# ─────────────────────────────────────────────────────────────────────────────
# Members
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{workspace_id}/members", response_model=List[WorkspaceMemberResponse])
def list_members(
    workspace_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List workspace members. Any member may call this."""
    _get_workspace_or_404(db, workspace_id)
    _require_member(db, workspace_id, current_user.id)
    members = workspace_service.list_members(db, workspace_id)
    return [_member_to_response(m) for m in members]


@router.post(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_member(
    workspace_id: uuid.UUID = Path(...),
    payload: AddMemberRequest = ...,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Add an existing user as a workspace member. Requires ADMIN role."""
    _get_workspace_or_404(db, workspace_id)
    _require_role(db, workspace_id, current_user.id, "ADMIN")

    try:
        user_uuid = uuid.UUID(payload.user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid user_id UUID format.",
        )

    try:
        member = workspace_service.add_member(
            db,
            workspace_id=workspace_id,
            user_id=user_uuid,
            role=payload.role,
            invited_by=current_user.id,
        )
    except AlreadyMember as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except PlanLimitExceeded as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    return _member_to_response(member)


@router.put(
    "/{workspace_id}/members/{user_id}",
    response_model=WorkspaceMemberResponse,
)
def update_member_role(
    workspace_id: uuid.UUID = Path(...),
    user_id: uuid.UUID = Path(...),
    payload: UpdateMemberRoleRequest = ...,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Change a member's role. Requires ADMIN role."""
    _get_workspace_or_404(db, workspace_id)
    _require_role(db, workspace_id, current_user.id, "ADMIN")

    try:
        member = workspace_service.update_member_role(
            db, workspace_id, user_id, payload.role
        )
    except WorkspaceMemberNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except CannotDemoteLastOwner as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    return _member_to_response(member)


@router.delete(
    "/{workspace_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_member(
    workspace_id: uuid.UUID = Path(...),
    user_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Remove a member. ADMIN+ can remove anyone; members can remove themselves."""
    _get_workspace_or_404(db, workspace_id)

    is_self = current_user.id == user_id
    is_admin = workspace_service.check_member_permission(
        db, workspace_id, current_user.id, "ADMIN"
    )
    if not is_self and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires ADMIN role or above to remove other members.",
        )

    try:
        workspace_service.remove_member(db, workspace_id, user_id)
    except WorkspaceMemberNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except CannotRemoveLastOwner as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )


# ─────────────────────────────────────────────────────────────────────────────
# Invites
# ─────────────────────────────────────────────────────────────────────────────


@router.post(
    "/{workspace_id}/invites",
    response_model=WorkspaceInviteResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_invite(
    workspace_id: uuid.UUID = Path(...),
    payload: CreateInviteRequest = ...,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Send a workspace invite by email. Requires ADMIN role."""
    _get_workspace_or_404(db, workspace_id)
    _require_role(db, workspace_id, current_user.id, "ADMIN")

    invite = workspace_service.create_invite(
        db,
        workspace_id=workspace_id,
        email=payload.email,
        role=payload.role,
        invited_by=current_user.id,
    )
    return WorkspaceInviteResponse(
        id=str(invite.id),
        workspace_id=str(invite.workspace_id),
        email=invite.email,
        role=invite.role.value,
        token=invite.token,
        expires_at=invite.expires_at,
        accepted_at=invite.accepted_at,
    )


@router.get("/invites/{token}", response_model=WorkspaceInviteResponse)
def get_invite(
    token: str = Path(...),
    db: Session = Depends(get_db),
):
    """Get invite info by token. Public endpoint — no auth required."""
    try:
        invite = workspace_service.get_invite_by_token(db, token)
    except InviteNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return WorkspaceInviteResponse(
        id=str(invite.id),
        workspace_id=str(invite.workspace_id),
        email=invite.email,
        role=invite.role.value,
        token=invite.token,
        expires_at=invite.expires_at,
        accepted_at=invite.accepted_at,
    )


@router.post(
    "/invites/{token}/accept",
    response_model=WorkspaceMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def accept_invite(
    token: str = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Accept a workspace invite. The current user is added as a member."""
    try:
        member = workspace_service.accept_invite(db, token, current_user.id)
    except InviteNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InviteExpired as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except InviteAlreadyAccepted as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except (AlreadyMember, PlanLimitExceeded) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )

    return _member_to_response(member)


# ─────────────────────────────────────────────────────────────────────────────
# API Keys
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/{workspace_id}/api-keys",
    response_model=List[WorkspaceAPIKeyResponse],
)
def list_api_keys(
    workspace_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """List workspace API keys. Requires ADMIN role."""
    _get_workspace_or_404(db, workspace_id)
    _require_role(db, workspace_id, current_user.id, "ADMIN")

    keys = workspace_service.list_api_keys(db, workspace_id)
    return [
        WorkspaceAPIKeyResponse(
            id=str(k.id),
            name=k.name,
            key_prefix=k.key_prefix,
            scopes=k.scopes or [],
            is_active=k.is_active,
            last_used_at=k.last_used_at,
            expires_at=k.expires_at,
            created_at=k.created_at,
        )
        for k in keys
    ]


@router.post(
    "/{workspace_id}/api-keys",
    response_model=CreateAPIKeyResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_api_key(
    workspace_id: uuid.UUID = Path(...),
    payload: CreateAPIKeyRequest = ...,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Create a workspace API key. Plaintext key is returned exactly once."""
    _get_workspace_or_404(db, workspace_id)
    _require_role(db, workspace_id, current_user.id, "ADMIN")

    try:
        api_key, plaintext = workspace_service.create_api_key(
            db,
            workspace_id=workspace_id,
            name=payload.name,
            scopes=payload.scopes,
            expires_at=payload.expires_at,
        )
    except PlanLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )

    return CreateAPIKeyResponse(
        id=str(api_key.id),
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        key=plaintext,
        scopes=api_key.scopes or [],
        created_at=api_key.created_at,
    )


@router.delete(
    "/{workspace_id}/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_api_key(
    workspace_id: uuid.UUID = Path(...),
    key_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Revoke (deactivate) a workspace API key. Requires ADMIN role."""
    _get_workspace_or_404(db, workspace_id)
    _require_role(db, workspace_id, current_user.id, "ADMIN")

    try:
        workspace_service.revoke_api_key(db, key_id)
    except APIKeyNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "/{workspace_id}/api-keys/{key_id}/rotate",
    response_model=CreateAPIKeyResponse,
    status_code=status.HTTP_201_CREATED,
)
def rotate_api_key(
    workspace_id: uuid.UUID = Path(...),
    key_id: uuid.UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Rotate a workspace API key. Old key is revoked; new plaintext is returned once."""
    _get_workspace_or_404(db, workspace_id)
    _require_role(db, workspace_id, current_user.id, "ADMIN")

    try:
        new_key, plaintext = workspace_service.rotate_api_key(db, key_id)
    except APIKeyNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return CreateAPIKeyResponse(
        id=str(new_key.id),
        name=new_key.name,
        key_prefix=new_key.key_prefix,
        key=plaintext,
        scopes=new_key.scopes or [],
        created_at=new_key.created_at,
    )
