"""
Salesforce integration service.
Creates/updates Salesforce Opportunities linked to platform experiments.
All methods swallow exceptions — Salesforce failures never disrupt platform.
"""

import logging
from typing import Any, Dict, Optional

import httpx

from backend.app.models.integration_config import IntegrationConfig

logger = logging.getLogger(__name__)


class SalesforceService:
    """Manages Salesforce Opportunity lifecycle tied to experiment events."""

    LOGIN_BASE_URL = "https://login.salesforce.com"
    API_VERSION = "v57.0"

    def __init__(self, instance_url: str, client_id: str, client_secret: str):
        self._instance_url = instance_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token: Optional[str] = None

    @classmethod
    def from_config(cls, config: IntegrationConfig) -> Optional["SalesforceService"]:
        """Factory: build from IntegrationConfig.encrypted_config dict.

        Returns None if any required credential is missing.
        """
        creds = config.encrypted_config or {}
        instance_url = creds.get("instance_url")
        client_id = creds.get("client_id")
        client_secret = creds.get("client_secret")
        if not all([instance_url, client_id, client_secret]):
            return None
        return cls(instance_url, client_id, client_secret)

    def get_access_token(self) -> Optional[str]:
        """OAuth2 client credentials flow to obtain an access token.

        Returns the access_token string, or None on any failure.
        """
        try:
            response = httpx.post(
                f"{self.LOGIN_BASE_URL}/services/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                timeout=10,
            )
            response.raise_for_status()
            self._access_token = response.json().get("access_token")
            return self._access_token
        except Exception as exc:
            # Log the failure class only: the exception text can echo the
            # OAuth request/response, which may contain credentials.
            logger.warning(
                "SalesforceService OAuth login failed: %s", type(exc).__name__
            )
            return None

    def _auth_headers(self) -> Dict[str, str]:
        """Return Authorization + Content-Type headers, fetching token if needed."""
        token = self._access_token or self.get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def create_opportunity(
        self,
        name: str,
        experiment_id: str,
        hypothesis: str = "",
    ) -> Optional[str]:
        """Create a Salesforce Opportunity for an experiment.

        Returns the Salesforce Opportunity ID string, or None on failure.
        """
        try:
            response = httpx.post(
                f"{self._instance_url}/services/data/{self.API_VERSION}/sobjects/Opportunity",
                headers=self._auth_headers(),
                json={
                    "Name": name,
                    "StageName": "Prospecting",
                    "CloseDate": "2099-12-31",
                    "Description": (
                        f"Experiment ID: {experiment_id}\nHypothesis: {hypothesis}"
                    ),
                },
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("id")
        except Exception as exc:
            logger.warning("SalesforceService create_opportunity failed: %s", exc)
            return None

    def update_opportunity(
        self,
        opportunity_id: str,
        fields: Dict[str, Any],
    ) -> Optional[bool]:
        """Update an existing Opportunity with the given fields.

        Returns True on success, None on failure.
        """
        try:
            response = httpx.patch(
                f"{self._instance_url}/services/data/{self.API_VERSION}/sobjects/Opportunity/{opportunity_id}",
                headers=self._auth_headers(),
                json=fields,
                timeout=10,
            )
            response.raise_for_status()
            return True
        except Exception as exc:
            logger.warning(
                "SalesforceService update_opportunity failed for %s: %s",
                opportunity_id,
                exc,
            )
            return None

    def sync_experiment(
        self,
        experiment_id: str,
        name: str,
        hypothesis: str,
        opportunity_id: Optional[str] = None,
        results: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Create or update a Salesforce Opportunity for an experiment.

        - If no opportunity_id is given, creates a new Opportunity.
        - If opportunity_id is given and results are provided, updates it.
        Returns the opportunity_id (existing or newly created), or None on error.
        """
        if not opportunity_id:
            return self.create_opportunity(name, experiment_id, hypothesis)
        if results:
            self.update_opportunity(opportunity_id, {"Description": str(results)})
        return opportunity_id

    def get_opportunity(self, opportunity_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a Salesforce Opportunity by ID.

        Returns the opportunity dict, or None on failure.
        """
        try:
            response = httpx.get(
                f"{self._instance_url}/services/data/{self.API_VERSION}/sobjects/Opportunity/{opportunity_id}",
                headers=self._auth_headers(),
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            logger.warning(
                "SalesforceService get_opportunity failed for %s: %s",
                opportunity_id,
                exc,
            )
            return None

    def parse_webhook_event(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse a Salesforce outbound message webhook payload into a normalized dict.

        Returns a normalized event dict, or None for unrecognized / empty payloads.
        """
        try:
            event_type = payload.get("event_type") or payload.get("sObjectType")
            if not event_type:
                return None
            return {
                "event_type": event_type,
                "object_id": payload.get("id") or payload.get("sobject", {}).get("Id"),
                "changes": payload.get("changedFields", []),
            }
        except Exception as exc:
            logger.warning("SalesforceService parse_webhook_event failed: %s", exc)
            return None
