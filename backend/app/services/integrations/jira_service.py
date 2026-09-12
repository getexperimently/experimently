"""
Jira integration service.
Creates/updates Jira issues linked to platform experiments.
All methods swallow exceptions — Jira failures never disrupt platform.
"""

import logging
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class JiraService:
    """Manages Jira issue lifecycle tied to experiment events."""

    def __init__(
        self, base_url: str, api_token: str, email: str, project_key: str = ""
    ):
        self._base_url = base_url.rstrip("/")
        self._api_token = api_token
        self._email = email
        self._project_key = project_key
        self._auth = (email, api_token)

    @classmethod
    def from_config(cls, config) -> "JiraService":
        """Factory: build from IntegrationConfig.encrypted_config dict."""
        cfg = config.encrypted_config or {}
        return cls(
            base_url=cfg.get("base_url", ""),
            api_token=cfg.get("api_token", ""),
            email=cfg.get("email", ""),
            project_key=cfg.get("project_key", ""),
        )

    def _post(self, path: str, payload: dict) -> Optional[dict]:
        url = f"{self._base_url}{path}"
        resp = httpx.post(url, json=payload, auth=self._auth, timeout=10)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def _get(self, path: str) -> Optional[dict]:
        url = f"{self._base_url}{path}"
        resp = httpx.get(url, auth=self._auth, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def create_experiment_issue(
        self,
        project_key: str,
        experiment_name: str,
        experiment_id: str,
        hypothesis: str,
        start_date: datetime,
        issue_type: str = "Task",
        platform_url: str = "",
    ) -> Optional[dict]:
        try:
            description = (
                f"*Experiment ID:* {experiment_id}\n"
                f"*Hypothesis:* {hypothesis}\n"
                f"*Start Date:* {start_date.isoformat()}\n"
            )
            if platform_url:
                description += f"*Platform Link:* {platform_url}\n"

            payload = {
                "fields": {
                    "project": {"key": project_key},
                    "summary": f"[Experiment] {experiment_name}",
                    "description": description,
                    "issuetype": {"name": issue_type},
                }
            }
            return self._post("/rest/api/3/issue", payload)
        except Exception as exc:
            logger.warning("Jira create_experiment_issue failed: %s", exc)
            return None

    def add_results_comment(
        self,
        issue_key: str,
        experiment_name: str,
        winning_variant: Optional[str],
        p_value: float,
        relative_lift: float,
        confidence_interval: tuple,
    ) -> None:
        try:
            body = (
                f"*Experiment Results: {experiment_name}*\n\n"
                f"- Winning variant: {winning_variant or 'No clear winner'}\n"
                f"- p-value: {p_value:.4f}\n"
                f"- Relative lift: {relative_lift * 100:.1f}%\n"
                f"- 95% CI: [{confidence_interval[0]:.3f}, {confidence_interval[1]:.3f}]\n"
            )
            self._post(f"/rest/api/3/issue/{issue_key}/comment", {"body": body})
        except Exception as exc:
            logger.warning("Jira add_results_comment failed for %s: %s", issue_key, exc)

    def transition_issue(self, issue_key: str, transition_id: str) -> None:
        try:
            self._post(
                f"/rest/api/3/issue/{issue_key}/transitions",
                {"transition": {"id": transition_id}},
            )
        except Exception as exc:
            logger.warning("Jira transition_issue failed for %s: %s", issue_key, exc)

    def get_issue(self, issue_key: str) -> Optional[dict]:
        try:
            return self._get(f"/rest/api/3/issue/{issue_key}")
        except Exception as exc:
            logger.warning("Jira get_issue failed for %s: %s", issue_key, exc)
            return None

    def parse_webhook_event(self, payload: dict) -> Optional[dict]:
        try:
            event_type = payload.get("webhookEvent", "")
            if event_type != "jira:issue_updated":
                return None
            issue = payload.get("issue", {})
            changelog = payload.get("changelog", {})
            status_change = next(
                (
                    item
                    for item in changelog.get("items", [])
                    if item.get("field") == "status"
                ),
                None,
            )
            if not status_change:
                return None
            return {
                "event_type": "status_transition",
                "issue_key": issue.get("key"),
                "new_status": status_change.get("toString"),
            }
        except Exception:
            return None
