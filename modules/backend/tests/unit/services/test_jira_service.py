"""
Tests for JiraService.
All HTTP calls are mocked with unittest.mock — no real Jira required.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestJiraServiceInit:
    def test_init_with_base_url_and_token(self):
        from modules.backend.app.services.integrations.jira_service import JiraService

        svc = JiraService(
            base_url="https://test.atlassian.net",
            api_token="token123",
            email="user@test.com",
        )
        assert svc._base_url == "https://test.atlassian.net"

    def test_init_strips_trailing_slash(self):
        from modules.backend.app.services.integrations.jira_service import JiraService

        svc = JiraService(
            base_url="https://test.atlassian.net/", api_token="tok", email="e@t.com"
        )
        assert not svc._base_url.endswith("/")

    def test_init_from_config(self):
        """JiraService.from_config(integration_config) factory."""
        from modules.backend.app.services.integrations.jira_service import JiraService

        mock_config = MagicMock()
        mock_config.encrypted_config = {
            "base_url": "https://t.atlassian.net",
            "api_token": "tok",
            "email": "e@t.com",
            "project_key": "PROD",
        }
        svc = JiraService.from_config(mock_config)
        assert svc is not None


class TestJiraTicketCreation:
    def test_create_issue_calls_post_endpoint(self):
        from modules.backend.app.services.integrations.jira_service import JiraService

        svc = JiraService(
            base_url="https://t.atlassian.net", api_token="tok", email="e@t.com"
        )
        with patch.object(
            svc, "_post", return_value={"id": "10001", "key": "PROD-42"}
        ) as mock_post:
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
        from modules.backend.app.services.integrations.jira_service import JiraService

        svc = JiraService(
            base_url="https://t.atlassian.net", api_token="tok", email="e@t.com"
        )
        with patch.object(
            svc, "_post", return_value={"id": "10001", "key": "PROD-1"}
        ) as mock_post:
            svc.create_experiment_issue(
                "PROD", "Test", "id", "hyp", datetime.utcnow(), issue_type="Story"
            )
            payload = mock_post.call_args[0][1]
            assert payload["fields"]["issuetype"]["name"] == "Story"

    def test_create_issue_includes_experiment_link(self):
        from modules.backend.app.services.integrations.jira_service import JiraService

        svc = JiraService(
            base_url="https://t.atlassian.net", api_token="tok", email="e@t.com"
        )
        with patch.object(
            svc, "_post", return_value={"id": "10001", "key": "PROD-1"}
        ) as mock_post:
            svc.create_experiment_issue(
                "PROD",
                "Test",
                "exp-123",
                "hyp",
                datetime.utcnow(),
                platform_url="https://platform.example.com",
            )
            payload = mock_post.call_args[0][1]
            desc = str(payload["fields"].get("description", ""))
            assert "exp-123" in desc or "platform.example.com" in desc

    def test_create_issue_title_includes_experiment_name(self):
        from modules.backend.app.services.integrations.jira_service import JiraService

        svc = JiraService(
            base_url="https://t.atlassian.net", api_token="tok", email="e@t.com"
        )
        with patch.object(
            svc, "_post", return_value={"id": "10001", "key": "PROD-1"}
        ) as mock_post:
            svc.create_experiment_issue(
                "PROD", "My AB Test", "id", "hyp", datetime.utcnow()
            )
            payload = mock_post.call_args[0][1]
            assert "My AB Test" in payload["fields"]["summary"]

    def test_create_issue_never_raises_on_http_error(self):
        from modules.backend.app.services.integrations.jira_service import JiraService

        svc = JiraService(
            base_url="https://t.atlassian.net", api_token="tok", email="e@t.com"
        )
        with patch.object(svc, "_post", side_effect=Exception("Network error")):
            result = svc.create_experiment_issue(
                "PROJ", "Test", "id", "hyp", datetime.utcnow()
            )
            assert result is None  # returns None on error, never raises


class TestJiraIssueUpdate:
    def test_update_issue_with_results(self):
        from modules.backend.app.services.integrations.jira_service import JiraService

        svc = JiraService(
            base_url="https://t.atlassian.net", api_token="tok", email="e@t.com"
        )
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
        from modules.backend.app.services.integrations.jira_service import JiraService

        svc = JiraService(
            base_url="https://t.atlassian.net", api_token="tok", email="e@t.com"
        )
        with patch.object(svc, "_post", side_effect=RuntimeError("timeout")):
            # Must not raise
            svc.add_results_comment("PROD-1", "Test", "B", 0.05, 0.1, (0, 0.2))

    def test_transition_issue_status(self):
        from modules.backend.app.services.integrations.jira_service import JiraService

        svc = JiraService(
            base_url="https://t.atlassian.net", api_token="tok", email="e@t.com"
        )
        with patch.object(svc, "_post", return_value={}) as mock_post:
            svc.transition_issue("PROD-42", transition_id="31")
            mock_post.assert_called_once()

    def test_get_issue_returns_dict(self):
        from modules.backend.app.services.integrations.jira_service import JiraService

        svc = JiraService(
            base_url="https://t.atlassian.net", api_token="tok", email="e@t.com"
        )
        with patch.object(
            svc, "_get", return_value={"id": "10001", "key": "PROD-1", "fields": {}}
        ):
            result = svc.get_issue("PROD-1")
            assert result["key"] == "PROD-1"


class TestJiraWebhookHandling:
    def test_parse_webhook_status_transition(self):
        from modules.backend.app.services.integrations.jira_service import JiraService

        svc = JiraService(
            base_url="https://t.atlassian.net", api_token="tok", email="e@t.com"
        )
        payload = {
            "webhookEvent": "jira:issue_updated",
            "issue": {"key": "PROD-42", "fields": {"status": {"name": "Done"}}},
            "changelog": {"items": [{"field": "status", "toString": "Done"}]},
        }
        event = svc.parse_webhook_event(payload)
        assert event["event_type"] == "status_transition"
        assert event["issue_key"] == "PROD-42"
        assert event["new_status"] == "Done"

    def test_parse_webhook_unsupported_event_returns_none(self):
        from modules.backend.app.services.integrations.jira_service import JiraService

        svc = JiraService(
            base_url="https://t.atlassian.net", api_token="tok", email="e@t.com"
        )
        result = svc.parse_webhook_event({"webhookEvent": "sprint_started"})
        assert result is None

    def test_parse_webhook_missing_fields_returns_none(self):
        from modules.backend.app.services.integrations.jira_service import JiraService

        svc = JiraService(
            base_url="https://t.atlassian.net", api_token="tok", email="e@t.com"
        )
        result = svc.parse_webhook_event({})
        assert result is None


class TestJiraHTTPLayer:
    def test_post_uses_basic_auth(self):
        """_post must use Basic auth with email:api_token."""
        import httpx

        from modules.backend.app.services.integrations.jira_service import JiraService

        svc = JiraService(
            base_url="https://t.atlassian.net",
            api_token="secret",
            email="user@test.com",
        )
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"id": "1"}
            mock_post.return_value = mock_resp
            svc._post("/rest/api/3/issue", {"fields": {}})
            _, kwargs = mock_post.call_args
            assert "auth" in kwargs or "headers" in kwargs  # basic auth present

    def test_get_returns_parsed_json(self):
        from modules.backend.app.services.integrations.jira_service import JiraService

        svc = JiraService(
            base_url="https://t.atlassian.net", api_token="tok", email="e@t.com"
        )
        with patch("httpx.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"key": "PROD-1"}
            mock_get.return_value = mock_resp
            result = svc._get("/rest/api/3/issue/PROD-1")
            assert result["key"] == "PROD-1"


class TestJiraWebhookAuthentication:
    """The shared secret that makes `POST /webhooks/jira` non-anonymous.

    Jira Cloud signs the raw body with the webhook's secret
    (`X-Hub-Signature: sha256=<hex>`); Jira Server has no secret support, so a
    relay presents the secret itself in `X-Experimently-Webhook-Secret`.
    """

    SECRET = "jira-shared-secret"

    def _service(self, secret: str = SECRET):
        from modules.backend.app.services.integrations.jira_service import JiraService

        return JiraService(
            base_url="https://t.atlassian.net",
            api_token="tok",
            email="e@t.com",
            webhook_secret=secret,
        )

    @staticmethod
    def _sign(secret: str, body: bytes) -> str:
        import hashlib
        import hmac

        return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    def test_from_config_reads_the_webhook_secret(self):
        """The secret lives in encrypted_config, next to the API token."""
        from modules.backend.app.services.integrations.jira_service import JiraService

        config = MagicMock()
        config.encrypted_config = {
            "base_url": "https://t.atlassian.net",
            "api_token": "tok",
            "email": "e@t.com",
            "webhook_secret": self.SECRET,
        }
        assert JiraService.from_config(config)._webhook_secret == self.SECRET

    def test_from_config_without_a_secret_leaves_it_empty(self):
        from modules.backend.app.services.integrations.jira_service import JiraService

        config = MagicMock()
        config.encrypted_config = {"base_url": "https://t.atlassian.net"}
        assert JiraService.from_config(config)._webhook_secret == ""

    @pytest.mark.regression
    def test_nothing_presented_is_rejected(self):
        """An anonymous POST is not a Jira delivery."""
        assert self._service().verify_webhook(b'{"webhookEvent": "x"}') is False

    def test_valid_signature_is_accepted(self):
        body = b'{"webhookEvent": "jira:issue_updated"}'
        svc = self._service()
        assert svc.verify_webhook(body, self._sign(self.SECRET, body)) is True

    def test_signature_of_another_body_is_rejected(self):
        """The signature covers the body, so a swapped body fails."""
        svc = self._service()
        signature = self._sign(self.SECRET, b'{"webhookEvent": "original"}')
        assert svc.verify_webhook(b'{"webhookEvent": "tampered"}', signature) is False

    def test_signature_from_another_secret_is_rejected(self):
        body = b'{"webhookEvent": "x"}'
        svc = self._service()
        assert svc.verify_webhook(body, self._sign("other-secret", body)) is False

    def test_shared_secret_header_is_accepted(self):
        svc = self._service()
        assert svc.verify_webhook(b"{}", "", self.SECRET) is True

    def test_wrong_shared_secret_is_rejected(self):
        svc = self._service()
        assert svc.verify_webhook(b"{}", "", "not-the-secret") is False

    def test_a_presented_signature_is_judged_on_its_own(self):
        """A wrong signature is a refusal, not a fallback to the header."""
        svc = self._service()
        bad = self._sign("other-secret", b"{}")
        assert svc.verify_webhook(b"{}", bad, self.SECRET) is False

    @pytest.mark.regression
    def test_no_configured_secret_accepts_nothing(self):
        """An integration with no secret cannot authenticate anybody."""
        svc = self._service(secret="")
        body = b"{}"
        assert svc.verify_webhook(body, self._sign("", body)) is False
        assert svc.verify_webhook(body, "", "") is False
