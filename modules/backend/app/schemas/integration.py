"""
Pydantic v2 schemas for third-party integration configuration — EP-034 Batch 1.
"""

import enum
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class IntegrationType(str, enum.Enum):
    SALESFORCE = "salesforce"
    JIRA = "jira"
    GITHUB = "github"


# ---------------------------------------------------------------------------
# Integration Config schemas
# ---------------------------------------------------------------------------


class IntegrationConfigCreate(BaseModel):
    """Payload for creating a new integration config."""

    integration_type: IntegrationType
    is_active: bool = False
    encrypted_config: Optional[Dict[str, Any]] = None


class IntegrationConfigUpdate(BaseModel):
    """Payload for updating an existing integration config."""

    is_active: Optional[bool] = None
    encrypted_config: Optional[Dict[str, Any]] = None
    last_error: Optional[str] = None


class IntegrationConfigResponse(BaseModel):
    """Response schema for an integration config record."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    integration_type: IntegrationType
    is_active: bool
    encrypted_config: Optional[Dict[str, Any]] = None
    last_sync_at: Optional[datetime] = None
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Jira-specific schemas
# ---------------------------------------------------------------------------


class JiraIssueCreateRequest(BaseModel):
    """Request body for creating a Jira issue linked to an experiment."""

    project_key: str
    experiment_name: str
    experiment_id: str
    hypothesis: str
    start_date: datetime
    issue_type: str = "Task"
    platform_url: Optional[str] = None


class JiraWebhookEvent(BaseModel):
    """Parsed Jira webhook event."""

    event_type: str
    issue_key: str
    new_status: Optional[str] = None
    raw_payload: Optional[Dict[str, Any]] = None
