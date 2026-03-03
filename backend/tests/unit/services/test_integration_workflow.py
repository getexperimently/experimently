"""
EP-034 Batch 4: End-to-end integration workflow tests.

Tests the service layer across all three integrations — Jira, Salesforce, GitHub —
covering the factory pattern, experiment lifecycle events, webhook processing, and
resilience/error handling. No real HTTP calls are made; all network I/O is mocked.
"""
import hashlib
import hmac as hmac_lib
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.app.services.integrations.jira_service import JiraService
from backend.app.services.integrations.salesforce_service import SalesforceService
from backend.app.services.integrations.github_service import GitHubService
from backend.app.models.integration_config import IntegrationConfig, IntegrationType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jira_config(is_active: bool = True, extra: dict = None):
    config = MagicMock(spec=IntegrationConfig)
    config.integration_type = IntegrationType.JIRA
    config.is_active = is_active
    base = {
        "base_url": "https://company.atlassian.net",
        "email": "admin@company.com",
        "api_token": "token123",
        "project_key": "EXP",
    }
    if extra is not None:
        base.update(extra)
    config.encrypted_config = base
    return config


def _make_salesforce_config(is_active: bool = True, extra: dict = None):
    config = MagicMock(spec=IntegrationConfig)
    config.integration_type = IntegrationType.SALESFORCE
    config.is_active = is_active
    base = {
        "instance_url": "https://myorg.salesforce.com",
        "client_id": "sf_client_id",
        "client_secret": "sf_client_secret",
    }
    if extra is not None:
        base.update(extra)
    config.encrypted_config = base
    return config


def _make_github_config(is_active: bool = True, extra: dict = None):
    config = MagicMock(spec=IntegrationConfig)
    config.integration_type = IntegrationType.GITHUB
    config.is_active = is_active
    base = {
        "token": "ghp_test_token",
        "repo_owner": "myorg",
        "repo_name": "experimentation",
        "webhook_secret": "webhook_secret_abc",
    }
    if extra is not None:
        base.update(extra)
    config.encrypted_config = base
    return config


def _make_jira_service():
    return JiraService(
        base_url="https://company.atlassian.net",
        api_token="token123",
        email="admin@company.com",
        project_key="EXP",
    )


def _make_salesforce_service():
    svc = SalesforceService(
        instance_url="https://myorg.salesforce.com",
        client_id="sf_client_id",
        client_secret="sf_client_secret",
    )
    svc._access_token = "pre_fetched_token"
    return svc


def _make_github_service(webhook_secret: str = "webhook_secret_abc"):
    return GitHubService(
        token="ghp_test_token",
        repo_owner="myorg",
        repo_name="experimentation",
        webhook_secret=webhook_secret,
    )


def _mock_httpx_post(return_json: dict, status_code: int = 201):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = return_json
    mock_resp.content = b"body"
    return mock_resp


def _mock_httpx_get(return_json: dict, status_code: int = 200):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = return_json
    return mock_resp


# ===========================================================================
# 1. IntegrationConfig Factory Pattern
# ===========================================================================

class TestIntegrationConfigFactory:
    """JiraService.from_config, SalesforceService.from_config, GitHubService.from_config."""

    # --- Jira ---

    def test_jira_service_from_active_config(self):
        """JiraService.from_config() returns a service when config has all required fields."""
        config = _make_jira_config(is_active=True)
        service = JiraService.from_config(config)
        assert service is not None
        assert isinstance(service, JiraService)

    def test_jira_service_from_config_stores_credentials(self):
        """Service built from config stores base_url, email, project_key correctly."""
        config = _make_jira_config()
        service = JiraService.from_config(config)
        assert service._base_url == "https://company.atlassian.net"
        assert service._email == "admin@company.com"
        assert service._project_key == "EXP"

    def test_jira_service_from_config_with_empty_config_returns_instance(self):
        """JiraService.from_config() still builds an instance from an empty dict
        (JiraService does not validate required fields at construction time — all
        fields default to empty strings, which is acceptable for unit testing)."""
        config = MagicMock(spec=IntegrationConfig)
        config.encrypted_config = {}
        service = JiraService.from_config(config)
        # JiraService does not guard against empty fields — it builds with defaults
        assert service is not None
        assert isinstance(service, JiraService)

    def test_jira_service_from_none_encrypted_config(self):
        """JiraService.from_config() tolerates None encrypted_config (defaults to empty dict)."""
        config = MagicMock(spec=IntegrationConfig)
        config.encrypted_config = None
        service = JiraService.from_config(config)
        # JiraService accepts None and treats it like {}
        assert service is not None

    # --- Salesforce ---

    def test_salesforce_service_from_active_config(self):
        """SalesforceService.from_config() returns a service for a complete config."""
        config = _make_salesforce_config(is_active=True)
        service = SalesforceService.from_config(config)
        assert service is not None
        assert isinstance(service, SalesforceService)

    def test_salesforce_service_from_config_stores_credentials(self):
        """Service built from config stores instance_url and client creds."""
        config = _make_salesforce_config()
        service = SalesforceService.from_config(config)
        assert service._instance_url == "https://myorg.salesforce.com"
        assert service._client_id == "sf_client_id"
        assert service._client_secret == "sf_client_secret"

    def test_salesforce_service_from_config_missing_fields_returns_none(self):
        """SalesforceService.from_config() returns None when required fields absent."""
        config = MagicMock(spec=IntegrationConfig)
        config.encrypted_config = {"instance_url": "https://myorg.salesforce.com"}
        service = SalesforceService.from_config(config)
        assert service is None

    def test_salesforce_service_from_none_config_returns_none(self):
        """SalesforceService.from_config() returns None when encrypted_config is None."""
        config = MagicMock(spec=IntegrationConfig)
        config.encrypted_config = None
        service = SalesforceService.from_config(config)
        assert service is None

    # --- GitHub ---

    def test_github_service_from_active_config(self):
        """GitHubService.from_config() returns a service for a complete config."""
        config = _make_github_config(is_active=True)
        service = GitHubService.from_config(config)
        assert service is not None
        assert isinstance(service, GitHubService)

    def test_github_service_from_config_stores_credentials(self):
        """Service built from config stores token, owner, repo, and webhook_secret."""
        config = _make_github_config()
        service = GitHubService.from_config(config)
        assert service._token == "ghp_test_token"
        assert service._owner == "myorg"
        assert service._repo == "experimentation"
        assert service._webhook_secret == "webhook_secret_abc"

    def test_github_service_from_config_missing_token_returns_none(self):
        """GitHubService.from_config() returns None when token is missing."""
        config = MagicMock(spec=IntegrationConfig)
        config.encrypted_config = {"repo_owner": "myorg", "repo_name": "experimentation"}
        service = GitHubService.from_config(config)
        assert service is None

    def test_github_service_from_config_missing_repo_owner_returns_none(self):
        """GitHubService.from_config() returns None when repo_owner is missing."""
        config = MagicMock(spec=IntegrationConfig)
        config.encrypted_config = {"token": "ghp_tok", "repo_name": "experimentation"}
        service = GitHubService.from_config(config)
        assert service is None

    def test_github_service_from_none_config_returns_none(self):
        """GitHubService.from_config() returns None when encrypted_config is None."""
        config = MagicMock(spec=IntegrationConfig)
        config.encrypted_config = None
        service = GitHubService.from_config(config)
        assert service is None

    def test_all_three_services_can_be_built_from_valid_configs(self):
        """All three services can be instantiated from their respective valid configs."""
        jira = JiraService.from_config(_make_jira_config())
        sf = SalesforceService.from_config(_make_salesforce_config())
        gh = GitHubService.from_config(_make_github_config())
        assert jira is not None
        assert sf is not None
        assert gh is not None


# ===========================================================================
# 2. Experiment Lifecycle Integration
# ===========================================================================

class TestExperimentLifecycleIntegration:
    """Full workflow: experiment starts → third-party action → experiment completes → follow-up."""

    def test_jira_issue_created_for_new_experiment(self):
        """create_experiment_issue() creates a Jira issue and returns the response dict."""
        service = _make_jira_service()
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_httpx_post({"id": "10001", "key": "EXP-123"})
            result = service.create_experiment_issue(
                project_key="EXP",
                experiment_name="Checkout A/B Test",
                experiment_id="exp-001",
                hypothesis="Simplified checkout increases conversions",
                start_date=datetime(2025, 1, 1),
            )
            assert result is not None
            assert result["key"] == "EXP-123"
            mock_post.assert_called_once()

    def test_jira_issue_summary_contains_experiment_name(self):
        """Issue summary contains the experiment name prefixed with [Experiment]."""
        service = _make_jira_service()
        with patch.object(service, "_post", return_value={"id": "10001", "key": "EXP-1"}) as mock_post:
            service.create_experiment_issue(
                project_key="EXP",
                experiment_name="My AB Test",
                experiment_id="exp-abc",
                hypothesis="hypothesis text",
                start_date=datetime.utcnow(),
            )
            payload = mock_post.call_args[0][1]
            assert "My AB Test" in payload["fields"]["summary"]

    def test_jira_results_comment_added_on_completion(self):
        """add_results_comment() posts a structured results comment to an existing issue."""
        service = _make_jira_service()
        with patch.object(service, "_post", return_value={"id": "comment-99"}) as mock_post:
            service.add_results_comment(
                issue_key="EXP-123",
                experiment_name="Checkout A/B Test",
                winning_variant="Treatment B",
                p_value=0.03,
                relative_lift=0.12,
                confidence_interval=(0.04, 0.20),
            )
            mock_post.assert_called_once()
            call_path, call_payload = mock_post.call_args[0]
            assert "EXP-123" in call_path
            assert "comment" in call_path
            # Verify the comment body contains key result fields
            assert "Treatment B" in call_payload["body"]
            assert "0.0300" in call_payload["body"]  # p_value formatted to 4dp

    def test_jira_transition_issue_after_experiment_completes(self):
        """transition_issue() moves the Jira issue to Done when experiment completes."""
        service = _make_jira_service()
        with patch.object(service, "_post", return_value={}) as mock_post:
            service.transition_issue(issue_key="EXP-123", transition_id="31")
            mock_post.assert_called_once()
            call_path, call_payload = mock_post.call_args[0]
            assert "EXP-123" in call_path
            assert call_payload["transition"]["id"] == "31"

    def test_salesforce_opportunity_created_for_new_experiment(self):
        """sync_experiment() creates a Salesforce Opportunity when no opportunity_id given."""
        service = _make_salesforce_service()
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_httpx_post({"id": "006NEWID", "success": True})
            result = service.sync_experiment(
                experiment_id="exp-001",
                name="Checkout A/B Test",
                hypothesis="Simplified checkout increases conversions",
            )
            assert result == "006NEWID"

    def test_salesforce_opportunity_updated_with_results(self):
        """sync_experiment() updates an existing Opportunity when results are available."""
        service = _make_salesforce_service()
        with patch("httpx.patch") as mock_patch:
            mock_patch.return_value = _mock_httpx_post({}, status_code=204)
            result = service.sync_experiment(
                experiment_id="exp-001",
                name="Checkout A/B Test",
                hypothesis="Hypothesis",
                opportunity_id="006EXISTING",
                results={"winner": "B", "p_value": 0.03},
            )
            mock_patch.assert_called_once()
            assert result == "006EXISTING"

    def test_github_issue_created_for_experiment(self):
        """create_issue() creates a GitHub issue with the experiment label."""
        service = _make_github_service()
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_httpx_post({"number": 42, "id": 100042})
            issue_number = service.create_issue(
                title="[Experiment] Checkout A/B Test",
                body="Hypothesis: Simplified checkout increases conversions",
            )
            assert issue_number == 42
            _, kwargs = mock_post.call_args
            labels = kwargs.get("json", {}).get("labels", [])
            assert "experiment" in labels

    def test_github_results_comment_posted_to_issue(self):
        """add_results_comment() posts results markdown to the experiment GitHub issue."""
        service = _make_github_service()
        results_md = "## Results\n\n| Variant | Conversion |\n|---------|------------|\n| B | 8.2% |"
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_httpx_post({"id": 55555})
            comment_id = service.add_results_comment(
                issue_number=42,
                results_markdown=results_md,
            )
            assert comment_id == 55555
            call_url = mock_post.call_args[0][0]
            assert "42" in call_url
            assert "comments" in call_url

    def test_github_pr_comment_with_results_summary(self):
        """add_pr_comment() posts an experiment summary on the associated pull request."""
        service = _make_github_service()
        with patch("httpx.post") as mock_post:
            mock_post.return_value = _mock_httpx_post({"id": 66666})
            comment_id = service.add_pr_comment(
                pr_number=15,
                comment="Experiment results: Variant B wins with p=0.02, +12% lift",
            )
            assert comment_id == 66666
            call_url = mock_post.call_args[0][0]
            assert "15" in call_url

    def test_github_issue_closed_after_experiment_ends(self):
        """close_issue() marks the experiment's GitHub issue as closed."""
        service = _make_github_service()
        with patch("httpx.patch") as mock_patch:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"number": 42, "state": "closed"}
            mock_patch.return_value = mock_resp
            result = service.close_issue(42)
            assert result is True
            _, kwargs = mock_patch.call_args
            assert kwargs.get("json", {}).get("state") == "closed"


# ===========================================================================
# 3. Webhook Processing Workflow
# ===========================================================================

class TestWebhookProcessingWorkflow:
    """Webhooks from each service are parsed into normalized events."""

    def test_jira_webhook_issue_updated_event(self):
        """parse_webhook_event() extracts a status_transition event from Jira payload."""
        service = _make_jira_service()
        payload = {
            "webhookEvent": "jira:issue_updated",
            "issue": {"key": "EXP-123", "fields": {"status": {"name": "In Progress"}}},
            "changelog": {
                "items": [{"field": "status", "fromString": "Open", "toString": "In Progress"}]
            },
        }
        result = service.parse_webhook_event(payload)
        assert result is not None
        assert result["event_type"] == "status_transition"
        assert result["issue_key"] == "EXP-123"
        assert result["new_status"] == "In Progress"

    def test_jira_webhook_non_update_event_returns_none(self):
        """parse_webhook_event() returns None for events other than jira:issue_updated."""
        service = _make_jira_service()
        result = service.parse_webhook_event({"webhookEvent": "sprint_started"})
        assert result is None

    def test_jira_webhook_update_without_status_change_returns_none(self):
        """parse_webhook_event() returns None when changelog has no status change."""
        service = _make_jira_service()
        payload = {
            "webhookEvent": "jira:issue_updated",
            "issue": {"key": "EXP-1"},
            "changelog": {"items": [{"field": "assignee", "toString": "Alice"}]},
        }
        result = service.parse_webhook_event(payload)
        assert result is None

    def test_jira_webhook_empty_payload_returns_none(self):
        """parse_webhook_event() returns None for an empty payload dict."""
        service = _make_jira_service()
        result = service.parse_webhook_event({})
        assert result is None

    def test_salesforce_webhook_opportunity_event(self):
        """SalesforceService.parse_webhook_event() normalizes an Opportunity update."""
        service = _make_salesforce_service()
        payload = {
            "event_type": "Opportunity",
            "id": "006TESTID",
            "changedFields": ["StageName", "CloseDate"],
        }
        result = service.parse_webhook_event(payload)
        assert result is not None
        assert result["event_type"] == "Opportunity"
        assert result["object_id"] == "006TESTID"
        assert "StageName" in result["changes"]

    def test_salesforce_webhook_with_sobject_type(self):
        """parse_webhook_event() also recognises sObjectType field."""
        service = _make_salesforce_service()
        payload = {
            "sObjectType": "Opportunity",
            "sobject": {"Id": "006ALTID"},
            "changedFields": ["Name"],
        }
        result = service.parse_webhook_event(payload)
        assert result is not None
        assert result["event_type"] == "Opportunity"
        assert result["object_id"] == "006ALTID"

    def test_salesforce_webhook_empty_payload_returns_none(self):
        """parse_webhook_event() returns None when no recognisable event_type."""
        service = _make_salesforce_service()
        result = service.parse_webhook_event({})
        assert result is None

    def test_github_webhook_with_valid_signature(self):
        """verify_webhook_signature() accepts a correct HMAC-SHA256 signature."""
        secret = "webhook_secret_abc"
        service = _make_github_service(webhook_secret=secret)
        body = b'{"action": "opened", "issue": {"number": 1}}'
        signature = "sha256=" + hmac_lib.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        assert service.verify_webhook_signature(body, signature) is True

    def test_github_webhook_with_invalid_signature(self):
        """verify_webhook_signature() rejects a tampered payload."""
        service = _make_github_service()
        body = b'{"action": "opened"}'
        tampered_sig = "sha256=" + "0" * 64
        assert service.verify_webhook_signature(body, tampered_sig) is False

    def test_github_webhook_with_no_secret_returns_false(self):
        """verify_webhook_signature() returns False when no webhook_secret is configured."""
        service = GitHubService(
            token="ghp_tok",
            repo_owner="org",
            repo_name="repo",
            # webhook_secret intentionally omitted — defaults to ""
        )
        body = b'{"action": "opened"}'
        sig = "sha256=abc"
        assert service.verify_webhook_signature(body, sig) is False

    def test_github_webhook_issue_opened_event(self):
        """parse_webhook_event() normalizes an issues/opened event."""
        service = _make_github_service()
        payload = {
            "action": "opened",
            "issue": {"number": 42, "title": "[Experiment] AB Test", "state": "open"},
        }
        result = service.parse_webhook_event("issues", payload)
        assert result is not None
        assert result["event_type"] == "issue_opened"
        assert result["issue_number"] == 42

    def test_github_webhook_pr_merged_event(self):
        """parse_webhook_event() normalizes a pull_request merged event."""
        service = _make_github_service()
        payload = {
            "action": "closed",
            "pull_request": {
                "number": 7,
                "title": "Deploy experiment feature",
                "merged": True,
                "merged_at": "2025-01-15T10:00:00Z",
            },
        }
        result = service.parse_webhook_event("pull_request", payload)
        assert result is not None
        assert result["event_type"] == "pr_merged"
        assert result["pr_number"] == 7

    def test_github_webhook_unsupported_event_returns_none(self):
        """parse_webhook_event() returns None for unrecognized event types."""
        service = _make_github_service()
        result = service.parse_webhook_event("deployment", {"action": "created"})
        assert result is None


# ===========================================================================
# 4. Error Handling + Resilience
# ===========================================================================

class TestIntegrationResilience:
    """Services swallow errors and return None — they never disrupt the platform."""

    def test_jira_network_error_on_create_issue_returns_none(self):
        """JiraService.create_experiment_issue() returns None on connection error."""
        service = _make_jira_service()
        with patch("httpx.post", side_effect=ConnectionError("timeout")):
            result = service.create_experiment_issue(
                project_key="EXP",
                experiment_name="Test",
                experiment_id="exp-1",
                hypothesis="hyp",
                start_date=datetime.utcnow(),
            )
            assert result is None

    def test_jira_network_error_on_add_results_comment_does_not_raise(self):
        """JiraService.add_results_comment() swallows exceptions and returns None."""
        service = _make_jira_service()
        with patch("httpx.post", side_effect=ConnectionError("timeout")):
            # Must not raise
            result = service.add_results_comment(
                issue_key="EXP-1",
                experiment_name="Test",
                winning_variant=None,
                p_value=0.05,
                relative_lift=0.1,
                confidence_interval=(0.0, 0.2),
            )
            # add_results_comment returns None implicitly
            assert result is None

    def test_jira_from_config_with_empty_fields_still_builds_service(self):
        """JiraService.from_config() builds an instance even with empty field values
        (validation is deferred to call-time, not construction time)."""
        config = MagicMock(spec=IntegrationConfig)
        config.encrypted_config = {}
        service = JiraService.from_config(config)
        # JiraService does not validate at construction; service object is returned
        assert service is not None

    def test_salesforce_auth_failure_on_create_opportunity_returns_none(self):
        """SalesforceService.create_opportunity() returns None when auth POST fails."""
        service = SalesforceService(
            instance_url="https://myorg.salesforce.com",
            client_id="bad_id",
            client_secret="bad_secret",
        )
        with patch("httpx.post", side_effect=Exception("401 Unauthorized")):
            result = service.create_opportunity(
                name="Test Opp",
                experiment_id="exp-1",
                hypothesis="hyp",
            )
            assert result is None

    def test_salesforce_http_error_on_update_opportunity_returns_none(self):
        """SalesforceService.update_opportunity() returns None on HTTP error."""
        service = _make_salesforce_service()
        with patch("httpx.patch", side_effect=Exception("503 Service Unavailable")):
            result = service.update_opportunity(
                opportunity_id="006TESTID",
                fields={"StageName": "Closed Won"},
            )
            assert result is None

    def test_salesforce_from_config_with_empty_encrypted_config_returns_none(self):
        """SalesforceService.from_config() returns None when encrypted_config is empty."""
        config = MagicMock(spec=IntegrationConfig)
        config.encrypted_config = {}
        service = SalesforceService.from_config(config)
        assert service is None

    def test_github_api_error_on_create_issue_returns_none(self):
        """GitHubService.create_issue() returns None on GitHub API error."""
        service = _make_github_service()
        with patch("httpx.post", side_effect=Exception("GitHub API error: 422")):
            result = service.create_issue(title="Test", body="body")
            assert result is None

    def test_github_api_error_on_add_results_comment_returns_none(self):
        """GitHubService.add_results_comment() returns None when the comment POST fails."""
        service = _make_github_service()
        with patch("httpx.post", side_effect=Exception("Network timeout")):
            result = service.add_results_comment(
                issue_number=42,
                results_markdown="## Results",
            )
            assert result is None

    def test_github_api_error_on_pr_comment_returns_none(self):
        """GitHubService.add_pr_comment() returns None on network error."""
        service = _make_github_service()
        with patch("httpx.post", side_effect=Exception("Connection reset")):
            result = service.add_pr_comment(pr_number=7, comment="results")
            assert result is None

    def test_github_from_config_with_empty_encrypted_config_returns_none(self):
        """GitHubService.from_config() returns None when all required fields are absent."""
        config = MagicMock(spec=IntegrationConfig)
        config.encrypted_config = {}
        service = GitHubService.from_config(config)
        assert service is None

    def test_jira_get_issue_network_error_returns_none(self):
        """JiraService.get_issue() returns None on a network error."""
        service = _make_jira_service()
        with patch("httpx.get", side_effect=ConnectionError("DNS failure")):
            result = service.get_issue("EXP-1")
            assert result is None

    def test_salesforce_get_opportunity_network_error_returns_none(self):
        """SalesforceService.get_opportunity() returns None on network error."""
        service = _make_salesforce_service()
        with patch("httpx.get", side_effect=ConnectionError("timeout")):
            result = service.get_opportunity("006TESTID")
            assert result is None

    def test_github_get_issue_network_error_returns_none(self):
        """GitHubService.get_issue() returns None on network error."""
        service = _make_github_service()
        with patch("httpx.get", side_effect=Exception("Connection refused")):
            result = service.get_issue(42)
            assert result is None

    def test_jira_webhook_parse_never_raises_on_malformed_payload(self):
        """JiraService.parse_webhook_event() never raises on a deeply malformed payload."""
        service = _make_jira_service()
        # list instead of dict — completely wrong type handled internally
        result = service.parse_webhook_event({None: None, "webhookEvent": None})
        # Should return None, not raise
        assert result is None

    def test_salesforce_webhook_parse_never_raises_on_null_event(self):
        """SalesforceService.parse_webhook_event() returns None for None-valued event_type."""
        service = _make_salesforce_service()
        result = service.parse_webhook_event({"event_type": None})
        assert result is None

    def test_github_webhook_parse_never_raises_on_missing_issue_key(self):
        """GitHubService.parse_webhook_event() returns None when issue key absent."""
        service = _make_github_service()
        # 'issues' event but no 'issue' key in payload
        result = service.parse_webhook_event("issues", {"action": "opened"})
        assert result is None
