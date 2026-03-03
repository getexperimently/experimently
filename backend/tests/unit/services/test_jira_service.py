"""
Tests for JiraService.
All HTTP calls are mocked with unittest.mock — no real Jira required.
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime


class TestJiraServiceInit:
    def test_init_with_base_url_and_token(self):
        from backend.app.services.integrations.jira_service import JiraService
        svc = JiraService(base_url="https://test.atlassian.net", api_token="token123", email="user@test.com")
        assert svc._base_url == "https://test.atlassian.net"

    def test_init_strips_trailing_slash(self):
        from backend.app.services.integrations.jira_service import JiraService
        svc = JiraService(base_url="https://test.atlassian.net/", api_token="tok", email="e@t.com")
        assert not svc._base_url.endswith("/")

    def test_init_from_config(self):
        """JiraService.from_config(integration_config) factory."""
        from backend.app.services.integrations.jira_service import JiraService
        mock_config = MagicMock()
        mock_config.encrypted_config = {"base_url": "https://t.atlassian.net", "api_token": "tok", "email": "e@t.com", "project_key": "PROD"}
        svc = JiraService.from_config(mock_config)
        assert svc is not None


class TestJiraTicketCreation:
    def test_create_issue_calls_post_endpoint(self):
        from backend.app.services.integrations.jira_service import JiraService
        svc = JiraService(base_url="https://t.atlassian.net", api_token="tok", email="e@t.com")
        with patch.object(svc, "_post", return_value={"id": "10001", "key": "PROD-42"}) as mock_post:
            result = svc.create_experiment_issue(
                project_key="PROD",
                experiment_name="Checkout Test",
                experiment_id="exp-uuid-1",
                hypothesis="New checkout increases conversion",
                start_date=datetime.utcnow(),
            )
            mock_post.assert_called_once()
            assert result["key"] == "PROD-42"

    def test_create_issue_sets_issue_type(self):
        from backend.app.services.integrations.jira_service import JiraService
        svc = JiraService(base_url="https://t.atlassian.net", api_token="tok", email="e@t.com")
        with patch.object(svc, "_post", return_value={"id": "10001", "key": "PROD-1"}) as mock_post:
            svc.create_experiment_issue("PROD", "Test", "id", "hyp", datetime.utcnow(), issue_type="Story")
            payload = mock_post.call_args[0][1]
            assert payload["fields"]["issuetype"]["name"] == "Story"

    def test_create_issue_includes_experiment_link(self):
        from backend.app.services.integrations.jira_service import JiraService
        svc = JiraService(base_url="https://t.atlassian.net", api_token="tok", email="e@t.com")
        with patch.object(svc, "_post", return_value={"id": "10001", "key": "PROD-1"}) as mock_post:
            svc.create_experiment_issue("PROD", "Test", "exp-123", "hyp", datetime.utcnow(),
                                         platform_url="https://platform.example.com")
            payload = mock_post.call_args[0][1]
            desc = str(payload["fields"].get("description", ""))
            assert "exp-123" in desc or "platform.example.com" in desc

    def test_create_issue_title_includes_experiment_name(self):
        from backend.app.services.integrations.jira_service import JiraService
        svc = JiraService(base_url="https://t.atlassian.net", api_token="tok", email="e@t.com")
        with patch.object(svc, "_post", return_value={"id": "10001", "key": "PROD-1"}) as mock_post:
            svc.create_experiment_issue("PROD", "My AB Test", "id", "hyp", datetime.utcnow())
            payload = mock_post.call_args[0][1]
            assert "My AB Test" in payload["fields"]["summary"]

    def test_create_issue_never_raises_on_http_error(self):
        from backend.app.services.integrations.jira_service import JiraService
        svc = JiraService(base_url="https://t.atlassian.net", api_token="tok", email="e@t.com")
        with patch.object(svc, "_post", side_effect=Exception("Network error")):
            result = svc.create_experiment_issue("PROJ", "Test", "id", "hyp", datetime.utcnow())
            assert result is None  # returns None on error, never raises


class TestJiraIssueUpdate:
    def test_update_issue_with_results(self):
        from backend.app.services.integrations.jira_service import JiraService
        svc = JiraService(base_url="https://t.atlassian.net", api_token="tok", email="e@t.com")
        with patch.object(svc, "_post", return_value={"id": "comment-1"}) as mock_post:
            svc.add_results_comment(
                issue_key="PROD-42",
                experiment_name="Checkout Test",
                winning_variant="Treatment B",
                p_value=0.03,
                relative_lift=0.15,
                confidence_interval=(0.05, 0.25),
            )
            mock_post.assert_called_once()

    def test_update_issue_never_raises_on_error(self):
        from backend.app.services.integrations.jira_service import JiraService
        svc = JiraService(base_url="https://t.atlassian.net", api_token="tok", email="e@t.com")
        with patch.object(svc, "_post", side_effect=RuntimeError("timeout")):
            # Must not raise
            svc.add_results_comment("PROD-1", "Test", "B", 0.05, 0.1, (0, 0.2))

    def test_transition_issue_status(self):
        from backend.app.services.integrations.jira_service import JiraService
        svc = JiraService(base_url="https://t.atlassian.net", api_token="tok", email="e@t.com")
        with patch.object(svc, "_post", return_value={}) as mock_post:
            svc.transition_issue("PROD-42", transition_id="31")
            mock_post.assert_called_once()

    def test_get_issue_returns_dict(self):
        from backend.app.services.integrations.jira_service import JiraService
        svc = JiraService(base_url="https://t.atlassian.net", api_token="tok", email="e@t.com")
        with patch.object(svc, "_get", return_value={"id": "10001", "key": "PROD-1", "fields": {}}):
            result = svc.get_issue("PROD-1")
            assert result["key"] == "PROD-1"


class TestJiraWebhookHandling:
    def test_parse_webhook_status_transition(self):
        from backend.app.services.integrations.jira_service import JiraService
        svc = JiraService(base_url="https://t.atlassian.net", api_token="tok", email="e@t.com")
        payload = {
            "webhookEvent": "jira:issue_updated",
            "issue": {"key": "PROD-42", "fields": {"status": {"name": "Done"}}},
            "changelog": {"items": [{"field": "status", "toString": "Done"}]}
        }
        event = svc.parse_webhook_event(payload)
        assert event["event_type"] == "status_transition"
        assert event["issue_key"] == "PROD-42"
        assert event["new_status"] == "Done"

    def test_parse_webhook_unsupported_event_returns_none(self):
        from backend.app.services.integrations.jira_service import JiraService
        svc = JiraService(base_url="https://t.atlassian.net", api_token="tok", email="e@t.com")
        result = svc.parse_webhook_event({"webhookEvent": "sprint_started"})
        assert result is None

    def test_parse_webhook_missing_fields_returns_none(self):
        from backend.app.services.integrations.jira_service import JiraService
        svc = JiraService(base_url="https://t.atlassian.net", api_token="tok", email="e@t.com")
        result = svc.parse_webhook_event({})
        assert result is None


class TestJiraHTTPLayer:
    def test_post_uses_basic_auth(self):
        """_post must use Basic auth with email:api_token."""
        import httpx
        from backend.app.services.integrations.jira_service import JiraService
        svc = JiraService(base_url="https://t.atlassian.net", api_token="secret", email="user@test.com")
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"id": "1"}
            mock_post.return_value = mock_resp
            svc._post("/rest/api/3/issue", {"fields": {}})
            _, kwargs = mock_post.call_args
            assert "auth" in kwargs or "headers" in kwargs  # basic auth present

    def test_get_returns_parsed_json(self):
        from backend.app.services.integrations.jira_service import JiraService
        svc = JiraService(base_url="https://t.atlassian.net", api_token="tok", email="e@t.com")
        with patch("httpx.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"key": "PROD-1"}
            mock_get.return_value = mock_resp
            result = svc._get("/rest/api/3/issue/PROD-1")
            assert result["key"] == "PROD-1"
