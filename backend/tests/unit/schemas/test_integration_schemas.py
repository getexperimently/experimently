"""
Tests for integration Pydantic v2 schemas — EP-034 Batch 1.
"""
import pytest
from datetime import datetime
from uuid import uuid4


class TestIntegrationType:
    def test_enum_has_salesforce(self):
        from backend.app.schemas.integration import IntegrationType
        assert IntegrationType.SALESFORCE == "salesforce"

    def test_enum_has_jira(self):
        from backend.app.schemas.integration import IntegrationType
        assert IntegrationType.JIRA == "jira"

    def test_enum_has_github(self):
        from backend.app.schemas.integration import IntegrationType
        assert IntegrationType.GITHUB == "github"


class TestIntegrationConfigCreate:
    def test_create_valid(self):
        from backend.app.schemas.integration import IntegrationConfigCreate, IntegrationType
        obj = IntegrationConfigCreate(integration_type=IntegrationType.JIRA)
        assert obj.integration_type == IntegrationType.JIRA

    def test_create_requires_integration_type(self):
        from backend.app.schemas.integration import IntegrationConfigCreate
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            IntegrationConfigCreate()

    def test_create_rejects_invalid_type(self):
        from backend.app.schemas.integration import IntegrationConfigCreate
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            IntegrationConfigCreate(integration_type="invalid_type")

    def test_create_with_encrypted_config(self):
        from backend.app.schemas.integration import IntegrationConfigCreate, IntegrationType
        obj = IntegrationConfigCreate(
            integration_type=IntegrationType.GITHUB,
            encrypted_config={"token": "ghp_abc123"}
        )
        assert obj.encrypted_config == {"token": "ghp_abc123"}

    def test_create_is_active_defaults_false(self):
        from backend.app.schemas.integration import IntegrationConfigCreate, IntegrationType
        obj = IntegrationConfigCreate(integration_type=IntegrationType.SALESFORCE)
        assert obj.is_active is False


class TestIntegrationConfigResponse:
    def test_response_has_id_field(self):
        from backend.app.schemas.integration import IntegrationConfigResponse, IntegrationType
        obj = IntegrationConfigResponse(
            id=uuid4(),
            integration_type=IntegrationType.JIRA,
            is_active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        assert obj.id is not None

    def test_response_has_integration_type(self):
        from backend.app.schemas.integration import IntegrationConfigResponse, IntegrationType
        obj = IntegrationConfigResponse(
            id=uuid4(),
            integration_type=IntegrationType.GITHUB,
            is_active=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        assert obj.integration_type == IntegrationType.GITHUB

    def test_response_from_attributes_enabled(self):
        from backend.app.schemas.integration import IntegrationConfigResponse
        from pydantic import ConfigDict
        # Check that model_config has from_attributes=True
        config = IntegrationConfigResponse.model_config
        assert config.get("from_attributes") is True

    def test_response_has_last_sync_at(self):
        from backend.app.schemas.integration import IntegrationConfigResponse, IntegrationType
        now = datetime.utcnow()
        obj = IntegrationConfigResponse(
            id=uuid4(),
            integration_type=IntegrationType.JIRA,
            is_active=True,
            last_sync_at=now,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        assert obj.last_sync_at == now

    def test_response_has_last_error(self):
        from backend.app.schemas.integration import IntegrationConfigResponse, IntegrationType
        obj = IntegrationConfigResponse(
            id=uuid4(),
            integration_type=IntegrationType.JIRA,
            is_active=False,
            last_error="Connection timeout",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        assert obj.last_error == "Connection timeout"


class TestJiraIssueCreateRequest:
    def test_jira_issue_create_has_project_key(self):
        from backend.app.schemas.integration import JiraIssueCreateRequest
        obj = JiraIssueCreateRequest(
            project_key="PROJ",
            experiment_name="Test",
            experiment_id="exp-1",
            hypothesis="This will work",
            start_date=datetime.utcnow(),
        )
        assert obj.project_key == "PROJ"

    def test_jira_issue_create_requires_project_key(self):
        from backend.app.schemas.integration import JiraIssueCreateRequest
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            JiraIssueCreateRequest(
                experiment_name="Test",
                experiment_id="exp-1",
                hypothesis="This will work",
                start_date=datetime.utcnow(),
            )

    def test_jira_issue_create_default_issue_type(self):
        from backend.app.schemas.integration import JiraIssueCreateRequest
        obj = JiraIssueCreateRequest(
            project_key="PROJ",
            experiment_name="Test",
            experiment_id="exp-1",
            hypothesis="hyp",
            start_date=datetime.utcnow(),
        )
        assert obj.issue_type == "Task"


class TestJiraWebhookEvent:
    def test_webhook_event_has_event_type(self):
        from backend.app.schemas.integration import JiraWebhookEvent
        obj = JiraWebhookEvent(
            event_type="status_transition",
            issue_key="PROD-42",
            new_status="Done",
        )
        assert obj.event_type == "status_transition"

    def test_webhook_event_has_issue_key(self):
        from backend.app.schemas.integration import JiraWebhookEvent
        obj = JiraWebhookEvent(
            event_type="status_transition",
            issue_key="PROJ-10",
            new_status="In Progress",
        )
        assert obj.issue_key == "PROJ-10"
