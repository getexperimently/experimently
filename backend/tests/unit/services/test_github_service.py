"""
Tests for GitHubService.
All HTTP calls are mocked with unittest.mock — no real GitHub required.
"""

import hashlib
import hmac as hmac_lib
from unittest.mock import MagicMock, patch

import httpx
import pytest


class TestGitHubServiceInit:
    def test_init_with_token(self):
        """Service stores token, repo_owner, repo_name."""
        from backend.app.services.integrations.github_service import GitHubService

        svc = GitHubService(token="ghp_abc123", repo_owner="myorg", repo_name="myrepo")
        assert svc._token == "ghp_abc123"
        assert svc._owner == "myorg"
        assert svc._repo == "myrepo"

    def test_init_stores_webhook_secret(self):
        """Service stores optional webhook_secret."""
        from backend.app.services.integrations.github_service import GitHubService

        svc = GitHubService(
            token="tok",
            repo_owner="org",
            repo_name="repo",
            webhook_secret="mysecret",
        )
        assert svc._webhook_secret == "mysecret"

    def test_init_default_webhook_secret_is_empty(self):
        """webhook_secret defaults to empty string."""
        from backend.app.services.integrations.github_service import GitHubService

        svc = GitHubService(token="tok", repo_owner="org", repo_name="repo")
        assert svc._webhook_secret == ""

    def test_from_config_extracts_credentials(self):
        """from_config() reads encrypted_config."""
        from backend.app.services.integrations.github_service import GitHubService

        mock_config = MagicMock()
        mock_config.encrypted_config = {
            "token": "ghp_test_token",
            "repo_owner": "myorg",
            "repo_name": "myrepo",
            "webhook_secret": "whsecret",
        }
        svc = GitHubService.from_config(mock_config)
        assert svc is not None
        assert svc._token == "ghp_test_token"
        assert svc._owner == "myorg"
        assert svc._repo == "myrepo"
        assert svc._webhook_secret == "whsecret"

    def test_from_config_missing_token_returns_none(self):
        """Returns None if token missing."""
        from backend.app.services.integrations.github_service import GitHubService

        mock_config = MagicMock()
        mock_config.encrypted_config = {
            "repo_owner": "myorg",
            "repo_name": "myrepo",
            # token is missing
        }
        svc = GitHubService.from_config(mock_config)
        assert svc is None

    def test_from_config_missing_repo_owner_returns_none(self):
        """Returns None if repo_owner is missing."""
        from backend.app.services.integrations.github_service import GitHubService

        mock_config = MagicMock()
        mock_config.encrypted_config = {
            "token": "ghp_tok",
            "repo_name": "myrepo",
        }
        svc = GitHubService.from_config(mock_config)
        assert svc is None

    def test_from_config_none_config_returns_none(self):
        """Returns None if encrypted_config is None."""
        from backend.app.services.integrations.github_service import GitHubService

        mock_config = MagicMock()
        mock_config.encrypted_config = None
        svc = GitHubService.from_config(mock_config)
        assert svc is None


class TestGitHubIssueOperations:
    def _make_service(self):
        from backend.app.services.integrations.github_service import GitHubService

        return GitHubService(
            token="ghp_test_token",
            repo_owner="myorg",
            repo_name="myrepo",
            webhook_secret="whsecret123",
        )

    def test_create_issue_with_experiment_data(self):
        """Creates GH issue with experiment title and hypothesis body."""
        svc = self._make_service()
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"number": 42, "id": 100042}
            mock_post.return_value = mock_resp
            svc.create_issue(
                title="[Experiment] Checkout A/B Test",
                body="Hypothesis: New checkout increases conversion",
            )
            mock_post.assert_called_once()
            _, kwargs = mock_post.call_args
            body = kwargs.get("json", {})
            assert "Checkout A/B Test" in body.get("title", "")

    def test_create_issue_returns_issue_number(self):
        """Returns issue number from response."""
        svc = self._make_service()
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"number": 99, "id": 100099}
            mock_post.return_value = mock_resp
            issue_num = svc.create_issue(title="Test Issue", body="body")
            assert issue_num == 99

    def test_create_issue_adds_experiment_label(self):
        """Includes 'experiment' label in request."""
        svc = self._make_service()
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"number": 1}
            mock_post.return_value = mock_resp
            svc.create_issue(title="Test", body="body")
            _, kwargs = mock_post.call_args
            labels = kwargs.get("json", {}).get("labels", [])
            assert "experiment" in labels

    def test_create_issue_merges_custom_labels(self):
        """Custom labels are merged with default 'experiment' label."""
        svc = self._make_service()
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"number": 1}
            mock_post.return_value = mock_resp
            svc.create_issue(
                title="Test", body="body", labels=["enhancement", "ab-test"]
            )
            _, kwargs = mock_post.call_args
            labels = kwargs.get("json", {}).get("labels", [])
            assert "experiment" in labels
            assert "enhancement" in labels
            assert "ab-test" in labels

    def test_create_issue_returns_none_on_error(self):
        """Returns None if API fails."""
        svc = self._make_service()
        with patch("httpx.post", side_effect=Exception("GitHub API error")):
            result = svc.create_issue(title="Test", body="body")
            assert result is None

    def test_create_issue_uses_correct_endpoint(self):
        """POST to /repos/{owner}/{repo}/issues."""
        svc = self._make_service()
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"number": 1}
            mock_post.return_value = mock_resp
            svc.create_issue(title="Test", body="body")
            call_url = mock_post.call_args[0][0]
            assert "myorg" in call_url
            assert "myrepo" in call_url
            assert "issues" in call_url

    def test_add_results_comment(self):
        """Posts comment to issue with results markdown."""
        svc = self._make_service()
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"id": 55555}
            mock_post.return_value = mock_resp
            svc.add_results_comment(
                issue_number=42,
                results_markdown="| Variant | Conversion |\n|---------|------------|\n| A | 5% |",
            )
            mock_post.assert_called_once()
            call_url = mock_post.call_args[0][0]
            assert "42" in call_url
            assert "comments" in call_url

    def test_add_results_comment_returns_comment_id(self):
        """Returns comment ID from response."""
        svc = self._make_service()
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"id": 77777}
            mock_post.return_value = mock_resp
            comment_id = svc.add_results_comment(
                issue_number=1, results_markdown="results"
            )
            assert comment_id == 77777

    def test_add_results_comment_returns_none_on_error(self):
        """Returns None if fails."""
        svc = self._make_service()
        with patch("httpx.post", side_effect=Exception("Network error")):
            result = svc.add_results_comment(issue_number=1, results_markdown="results")
            assert result is None

    def test_close_issue_transitions_to_closed(self):
        """PATCH /issues/{number} with state=closed."""
        svc = self._make_service()
        with patch("httpx.patch") as mock_patch:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"number": 42, "state": "closed"}
            mock_patch.return_value = mock_resp
            result = svc.close_issue(42)
            mock_patch.assert_called_once()
            _, kwargs = mock_patch.call_args
            assert kwargs.get("json", {}).get("state") == "closed"
            assert result is True

    def test_close_issue_returns_none_on_error(self):
        """Returns None if close fails."""
        svc = self._make_service()
        with patch("httpx.patch", side_effect=Exception("Timeout")):
            result = svc.close_issue(42)
            assert result is None

    def test_get_issue_returns_data(self):
        """GET /issues/{number} returns issue dict."""
        svc = self._make_service()
        with patch("httpx.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "number": 42,
                "title": "Test Issue",
                "state": "open",
            }
            mock_get.return_value = mock_resp
            result = svc.get_issue(42)
            assert result["number"] == 42
            assert result["title"] == "Test Issue"

    def test_get_issue_returns_none_on_error(self):
        """Returns None if get_issue fails."""
        svc = self._make_service()
        with patch("httpx.get", side_effect=Exception("Not found")):
            result = svc.get_issue(99999)
            assert result is None


class TestGitHubPROperations:
    def _make_service(self):
        from backend.app.services.integrations.github_service import GitHubService

        return GitHubService(
            token="ghp_test_token",
            repo_owner="myorg",
            repo_name="myrepo",
        )

    def test_add_pr_comment(self):
        """Posts experiment results as comment on a PR."""
        svc = self._make_service()
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"id": 11111}
            mock_post.return_value = mock_resp
            comment_id = svc.add_pr_comment(
                pr_number=7,
                comment="Experiment results: variant B wins with p=0.02",
            )
            mock_post.assert_called_once()
            call_url = mock_post.call_args[0][0]
            assert "7" in call_url
            assert comment_id == 11111

    def test_add_pr_comment_returns_none_on_error(self):
        """Returns None if fails."""
        svc = self._make_service()
        with patch("httpx.post", side_effect=Exception("GitHub error")):
            result = svc.add_pr_comment(pr_number=7, comment="results")
            assert result is None

    def test_add_pr_comment_posts_to_issues_endpoint(self):
        """PR comments use the /issues/{pr_number}/comments endpoint."""
        svc = self._make_service()
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"id": 1}
            mock_post.return_value = mock_resp
            svc.add_pr_comment(pr_number=15, comment="test comment")
            call_url = mock_post.call_args[0][0]
            assert "issues" in call_url
            assert "15" in call_url
            assert "comments" in call_url


class TestGitHubWebhook:
    def _make_service(self, webhook_secret="test_webhook_secret"):
        from backend.app.services.integrations.github_service import GitHubService

        return GitHubService(
            token="ghp_test",
            repo_owner="myorg",
            repo_name="myrepo",
            webhook_secret=webhook_secret,
        )

    def test_parse_webhook_event_issue_opened(self):
        """Handles issues event with action=opened."""
        svc = self._make_service()
        payload = {
            "action": "opened",
            "issue": {
                "number": 42,
                "title": "[Experiment] Checkout Test",
                "state": "open",
            },
        }
        event = svc.parse_webhook_event("issues", payload)
        assert event is not None
        assert event["event_type"] == "issue_opened"
        assert event["issue_number"] == 42

    def test_parse_webhook_event_issue_closed(self):
        """Handles issues event with action=closed."""
        svc = self._make_service()
        payload = {
            "action": "closed",
            "issue": {
                "number": 10,
                "title": "Some Issue",
                "state": "closed",
            },
        }
        event = svc.parse_webhook_event("issues", payload)
        assert event is not None
        assert event["event_type"] == "issue_closed"
        assert event["state"] == "closed"

    def test_parse_webhook_event_pr_merged(self):
        """Handles pull_request closed+merged event."""
        svc = self._make_service()
        payload = {
            "action": "closed",
            "pull_request": {
                "number": 55,
                "title": "Merge experiment feature",
                "merged": True,
                "merged_at": "2024-01-15T10:00:00Z",
            },
        }
        event = svc.parse_webhook_event("pull_request", payload)
        assert event is not None
        assert event["event_type"] == "pr_merged"
        assert event["pr_number"] == 55
        assert event["merged_at"] == "2024-01-15T10:00:00Z"

    def test_parse_webhook_event_pr_not_merged_returns_none(self):
        """pull_request closed but not merged returns None."""
        svc = self._make_service()
        payload = {
            "action": "closed",
            "pull_request": {
                "number": 55,
                "title": "Closed PR",
                "merged": False,
                "merged_at": None,
            },
        }
        event = svc.parse_webhook_event("pull_request", payload)
        assert event is None

    def test_parse_webhook_event_unsupported_returns_none(self):
        """Returns None for unrecognized events."""
        svc = self._make_service()
        result = svc.parse_webhook_event("deployment", {"action": "created"})
        assert result is None

    def test_parse_webhook_event_never_raises(self):
        """parse_webhook_event() never raises even on malformed payload."""
        svc = self._make_service()
        # Malformed payload missing 'issue' key
        result = svc.parse_webhook_event("issues", {"action": "opened"})
        # Should return None without raising
        assert result is None

    def test_verify_webhook_signature(self):
        """Validates X-Hub-Signature-256 HMAC-SHA256."""
        secret = "test_webhook_secret"
        svc = self._make_service(webhook_secret=secret)
        payload_body = b'{"action": "opened"}'
        expected_sig = (
            "sha256="
            + hmac_lib.new(secret.encode(), payload_body, hashlib.sha256).hexdigest()
        )
        result = svc.verify_webhook_signature(payload_body, expected_sig)
        assert result is True

    def test_verify_webhook_signature_invalid_returns_false(self):
        """Returns False for tampered payload."""
        svc = self._make_service(webhook_secret="test_webhook_secret")
        payload_body = b'{"action": "opened"}'
        tampered_sig = (
            "sha256=0000000000000000000000000000000000000000000000000000000000000000"
        )
        result = svc.verify_webhook_signature(payload_body, tampered_sig)
        assert result is False

    def test_verify_webhook_signature_no_secret_returns_false(self):
        """Returns False when no webhook_secret configured."""
        from backend.app.services.integrations.github_service import GitHubService

        svc = GitHubService(token="tok", repo_owner="org", repo_name="repo")
        result = svc.verify_webhook_signature(b"payload", "sha256=abc")
        assert result is False

    def test_verify_webhook_signature_missing_sha256_prefix_returns_false(self):
        """Returns False if header doesn't start with sha256=."""
        svc = self._make_service()
        result = svc.verify_webhook_signature(b"payload", "sha1=abc123")
        assert result is False
