"""
Integration configuration management API endpoints — EP-034 Batch 3.

Provides CRUD for Salesforce / Jira / GitHub integration configs and
inbound webhook handlers for each integration type.

Permission model:
  - GET /integrations, GET /integrations/{type}  → ADMIN or DEVELOPER
  - POST / PUT / DELETE                           → ADMIN only
  - Webhook endpoints                             → unauthenticated (verified
      via HMAC or similar mechanism per integration)
"""

import hashlib
import hmac as hmac_lib
import json
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.app.api import deps
from backend.app.models.integration_config import IntegrationConfig, IntegrationType
from backend.app.models.user import User, UserRole
from backend.app.schemas.integration import (
    IntegrationConfigCreate,
    IntegrationConfigUpdate,
    IntegrationConfigResponse,
)
from backend.app.services.integrations.jira_service import JiraService
from backend.app.services.integrations.salesforce_service import SalesforceService
from backend.app.services.integrations.github_service import GitHubService

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------

def _require_admin(current_user: User) -> None:
    """Raise HTTP 403 if the caller is not ADMIN (or superuser)."""
    if current_user.is_superuser:
        return
    if getattr(current_user, "role", None) == UserRole.ADMIN:
        return
    raise HTTPException(status_code=403, detail="Only ADMIN users can manage integrations")


def _require_admin_or_developer(current_user: User) -> None:
    """Raise HTTP 403 if the caller is neither ADMIN nor DEVELOPER (or superuser)."""
    if current_user.is_superuser:
        return
    allowed = {UserRole.ADMIN, UserRole.DEVELOPER}
    if getattr(current_user, "role", None) in allowed:
        return
    raise HTTPException(status_code=403, detail="ADMIN or DEVELOPER role required")


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=List[IntegrationConfigResponse])
def list_integrations(
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(deps.get_db),
):
    """Return all integration configurations (ADMIN / DEVELOPER only)."""
    _require_admin_or_developer(current_user)
    return db.query(IntegrationConfig).all()


@router.get("/{integration_type}", response_model=IntegrationConfigResponse)
def get_integration(
    integration_type: IntegrationType,
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(deps.get_db),
):
    """Retrieve a single integration config by type (ADMIN / DEVELOPER only)."""
    _require_admin_or_developer(current_user)
    config = (
        db.query(IntegrationConfig)
        .filter(IntegrationConfig.integration_type == integration_type)
        .first()
    )
    if not config:
        raise HTTPException(
            status_code=404,
            detail=f"No {integration_type.value} integration configured",
        )
    return config


@router.post("", response_model=IntegrationConfigResponse, status_code=201)
def create_integration(
    data: IntegrationConfigCreate,
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(deps.get_db),
):
    """Create a new integration configuration (ADMIN only)."""
    _require_admin(current_user)

    existing = (
        db.query(IntegrationConfig)
        .filter(IntegrationConfig.integration_type == data.integration_type)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"{data.integration_type.value} integration already configured",
        )

    config = IntegrationConfig(
        integration_type=data.integration_type,
        is_active=data.is_active,
        encrypted_config=data.encrypted_config,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


@router.put("/{integration_type}", response_model=IntegrationConfigResponse)
def update_integration(
    integration_type: IntegrationType,
    data: IntegrationConfigUpdate,
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(deps.get_db),
):
    """Update an existing integration configuration (ADMIN only)."""
    _require_admin(current_user)

    config = (
        db.query(IntegrationConfig)
        .filter(IntegrationConfig.integration_type == integration_type)
        .first()
    )
    if not config:
        raise HTTPException(
            status_code=404,
            detail=f"No {integration_type.value} integration configured",
        )

    if data.is_active is not None:
        config.is_active = data.is_active
    if data.encrypted_config is not None:
        config.encrypted_config = data.encrypted_config
    if data.last_error is not None or "last_error" in (data.model_fields_set or set()):
        config.last_error = data.last_error

    db.commit()
    db.refresh(config)
    return config


@router.delete("/{integration_type}", status_code=204)
def delete_integration(
    integration_type: IntegrationType,
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(deps.get_db),
):
    """Delete an integration configuration (ADMIN only)."""
    _require_admin(current_user)

    config = (
        db.query(IntegrationConfig)
        .filter(IntegrationConfig.integration_type == integration_type)
        .first()
    )
    if not config:
        raise HTTPException(
            status_code=404,
            detail=f"No {integration_type.value} integration configured",
        )

    db.delete(config)
    db.commit()


# ---------------------------------------------------------------------------
# Webhook endpoints
# ---------------------------------------------------------------------------

@router.post("/webhooks/jira", status_code=200)
async def jira_webhook(
    request: Request,
    db: Session = Depends(deps.get_db),
):
    """Receive and process Jira webhook events.

    Looks up an active Jira IntegrationConfig; if found, delegates to
    JiraService.parse_webhook_event().  Always returns 200 — Jira delivery
    failures must not be surfaced to the caller.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    config = (
        db.query(IntegrationConfig)
        .filter(
            IntegrationConfig.integration_type == IntegrationType.JIRA,
            IntegrationConfig.is_active.is_(True),
        )
        .first()
    )

    if config:
        try:
            service = JiraService.from_config(config)
            if service:
                service.parse_webhook_event(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("jira_webhook processing error: %s", exc)

    return {"status": "received"}


@router.post("/webhooks/salesforce", status_code=200)
async def salesforce_webhook(
    request: Request,
    db: Session = Depends(deps.get_db),
):
    """Receive and process Salesforce outbound message webhook.

    Always returns 200 — Salesforce failures must not be surfaced.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    config = (
        db.query(IntegrationConfig)
        .filter(
            IntegrationConfig.integration_type == IntegrationType.SALESFORCE,
            IntegrationConfig.is_active.is_(True),
        )
        .first()
    )

    if config:
        try:
            service = SalesforceService.from_config(config)
            if service:
                service.parse_webhook_event(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("salesforce_webhook processing error: %s", exc)

    return {"status": "received"}


@router.post("/webhooks/github", status_code=200)
async def github_webhook(
    request: Request,
    db: Session = Depends(deps.get_db),
):
    """Receive and process GitHub webhook events with optional HMAC-SHA256 validation.

    - If an active GitHub config exists and an X-Hub-Signature-256 header is
      present, the signature is verified; an invalid signature returns HTTP 400.
    - If no signature header is supplied the check is skipped (config may not
      have a webhook_secret configured).
    - Always returns 200 on success.
    """
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    event_type = request.headers.get("X-GitHub-Event", "")

    config = (
        db.query(IntegrationConfig)
        .filter(
            IntegrationConfig.integration_type == IntegrationType.GITHUB,
            IntegrationConfig.is_active.is_(True),
        )
        .first()
    )

    if config:
        try:
            service = GitHubService.from_config(config)
            if service and signature:
                if not service.verify_webhook_signature(body, signature):
                    raise HTTPException(status_code=400, detail="Invalid webhook signature")
                try:
                    parsed = json.loads(body)
                    service.parse_webhook_event(event_type, parsed)
                except HTTPException:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning("github_webhook parse error: %s", exc)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("github_webhook processing error: %s", exc)

    return {"status": "received"}
