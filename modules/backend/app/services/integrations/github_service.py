"""
GitHub integration service.
Creates/updates GitHub issues and adds comments linked to platform experiments.
All methods swallow exceptions — GitHub failures never disrupt platform.
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

from modules.backend.app.models.integration_config import IntegrationConfig
from modules.backend.app.services.integrations import webhook_auth

logger = logging.getLogger(__name__)


class GitHubService:
    """Manages GitHub issue lifecycle tied to experiment events."""

    API_BASE = "https://api.github.com"

    def __init__(
        self,
        token: str,
        repo_owner: str,
        repo_name: str,
        webhook_secret: str = "",
    ):
        self._token = token
        self._owner = repo_owner
        self._repo = repo_name
        self._webhook_secret = webhook_secret

    @classmethod
    def from_config(cls, config: IntegrationConfig) -> Optional["GitHubService"]:
        """Factory: build from IntegrationConfig.encrypted_config dict.

        Returns None if any required credential is missing.
        """
        creds = config.encrypted_config or {}
        token = creds.get("token")
        owner = creds.get("repo_owner")
        repo = creds.get("repo_name")
        if not all([token, owner, repo]):
            return None
        return cls(token, owner, repo, creds.get("webhook_secret", ""))

    def _headers(self) -> Dict[str, str]:
        """Return standard GitHub API request headers."""
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _repo_url(self, path: str) -> str:
        """Build a full URL for the configured repo."""
        return f"{self.API_BASE}/repos/{self._owner}/{self._repo}{path}"

    def create_issue(
        self,
        title: str,
        body: str,
        labels: Optional[List[str]] = None,
    ) -> Optional[int]:
        """Create a GitHub issue. Always adds the 'experiment' label.

        Returns the issue number, or None on failure.
        """
        try:
            all_labels = ["experiment"] + (labels or [])
            response = httpx.post(
                self._repo_url("/issues"),
                headers=self._headers(),
                json={"title": title, "body": body, "labels": all_labels},
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("number")
        except Exception as exc:
            logger.warning("GitHubService create_issue failed: %s", exc)
            return None

    def add_results_comment(
        self,
        issue_number: int,
        results_markdown: str,
    ) -> Optional[int]:
        """Post experiment results as a comment on a GitHub issue.

        Returns the comment ID, or None on failure.
        """
        try:
            response = httpx.post(
                self._repo_url(f"/issues/{issue_number}/comments"),
                headers=self._headers(),
                json={"body": results_markdown},
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("id")
        except Exception as exc:
            logger.warning(
                "GitHubService add_results_comment failed for issue %s: %s",
                issue_number,
                exc,
            )
            return None

    def add_pr_comment(self, pr_number: int, comment: str) -> Optional[int]:
        """Post a comment on a GitHub pull request.

        Uses the /issues/{pr_number}/comments endpoint (PRs are issues in the API).
        Returns the comment ID, or None on failure.
        """
        try:
            response = httpx.post(
                self._repo_url(f"/issues/{pr_number}/comments"),
                headers=self._headers(),
                json={"body": comment},
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("id")
        except Exception as exc:
            logger.warning(
                "GitHubService add_pr_comment failed for PR %s: %s",
                pr_number,
                exc,
            )
            return None

    def close_issue(self, issue_number: int) -> Optional[bool]:
        """Close a GitHub issue by setting state=closed.

        Returns True on success, None on failure.
        """
        try:
            response = httpx.patch(
                self._repo_url(f"/issues/{issue_number}"),
                headers=self._headers(),
                json={"state": "closed"},
                timeout=10,
            )
            response.raise_for_status()
            return True
        except Exception as exc:
            logger.warning(
                "GitHubService close_issue failed for issue %s: %s",
                issue_number,
                exc,
            )
            return None

    def get_issue(self, issue_number: int) -> Optional[Dict[str, Any]]:
        """Fetch issue details by issue number.

        Returns the issue dict, or None on failure.
        """
        try:
            response = httpx.get(
                self._repo_url(f"/issues/{issue_number}"),
                headers=self._headers(),
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            logger.warning(
                "GitHubService get_issue failed for issue %s: %s",
                issue_number,
                exc,
            )
            return None

    def verify_webhook_signature(
        self, payload_body: bytes, signature_header: str
    ) -> bool:
        """Verify a GitHub webhook X-Hub-Signature-256 HMAC-SHA256 header.

        Returns True if the signature is valid, False otherwise — including
        when no ``webhook_secret`` is configured, because an integration that
        cannot check a signature must not accept one.  GitHub always signs, so
        this is the only form accepted here; the shared-secret header the other
        two providers may use is not.

        The endpoint does not call this: it reads ``webhook_secret``
        off the config and calls ``webhook_auth`` directly, because
        ``from_config`` needs outbound credentials an inbound delivery
        does not have (see the webhook section of
        ``api/v1/endpoints/integrations.py``).  Kept for a caller that
        already holds a service.
        """
        return webhook_auth.verify_signature(
            self._webhook_secret, payload_body, signature_header
        )

    def parse_webhook_event(
        self, event_type: str, payload: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Parse a GitHub webhook event into a normalized structure.

        Supported event types:
        - "issues" with actions: opened, closed, labeled
        - "pull_request" with action: closed + merged=True

        Returns a normalized event dict, or None for unrecognized events.
        """
        try:
            if event_type == "issues":
                action = payload.get("action")
                issue = payload.get("issue")
                if not issue:
                    return None
                if action in ("opened", "closed", "labeled"):
                    return {
                        "event_type": f"issue_{action}",
                        "issue_number": issue["number"],
                        "title": issue["title"],
                        "state": issue["state"],
                    }
            elif event_type == "pull_request":
                pr = payload.get("pull_request", {})
                if payload.get("action") == "closed" and pr.get("merged"):
                    return {
                        "event_type": "pr_merged",
                        "pr_number": pr["number"],
                        "title": pr["title"],
                        "merged_at": pr.get("merged_at"),
                    }
            return None
        except Exception as exc:
            logger.warning("GitHubService parse_webhook_event failed: %s", exc)
            return None
