"""
Tests for SalesforceService.
All HTTP calls are mocked with unittest.mock — no real Salesforce required.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest


class TestSalesforceServiceInit:
    def test_init_with_credentials(self):
        """Service stores instance_url, client_id, client_secret."""
        from backend.app.services.integrations.salesforce_service import (
            SalesforceService,
        )

        svc = SalesforceService(
            instance_url="https://myorg.salesforce.com",
            client_id="client123",
            client_secret="secret456",
        )
        assert svc._instance_url == "https://myorg.salesforce.com"
        assert svc._client_id == "client123"
        assert svc._client_secret == "secret456"

    def test_init_strips_trailing_slash(self):
        """Trailing slash is removed from instance_url."""
        from backend.app.services.integrations.salesforce_service import (
            SalesforceService,
        )

        svc = SalesforceService(
            instance_url="https://myorg.salesforce.com/",
            client_id="c",
            client_secret="s",
        )
        assert not svc._instance_url.endswith("/")

    def test_from_config_extracts_credentials(self):
        """from_config(integration_config) reads encrypted_config dict."""
        from backend.app.services.integrations.salesforce_service import (
            SalesforceService,
        )

        mock_config = MagicMock()
        mock_config.encrypted_config = {
            "instance_url": "https://myorg.salesforce.com",
            "client_id": "cid",
            "client_secret": "csecret",
        }
        svc = SalesforceService.from_config(mock_config)
        assert svc is not None
        assert svc._instance_url == "https://myorg.salesforce.com"
        assert svc._client_id == "cid"
        assert svc._client_secret == "csecret"

    def test_from_config_missing_credentials_returns_none(self):
        """Returns None if required fields missing from config."""
        from backend.app.services.integrations.salesforce_service import (
            SalesforceService,
        )

        mock_config = MagicMock()
        mock_config.encrypted_config = {
            "instance_url": "https://myorg.salesforce.com",
            # client_id and client_secret are missing
        }
        svc = SalesforceService.from_config(mock_config)
        assert svc is None

    def test_from_config_none_config_returns_none(self):
        """Returns None if encrypted_config is None."""
        from backend.app.services.integrations.salesforce_service import (
            SalesforceService,
        )

        mock_config = MagicMock()
        mock_config.encrypted_config = None
        svc = SalesforceService.from_config(mock_config)
        assert svc is None


class TestSalesforceOAuth:
    def test_get_access_token_makes_oauth_request(self):
        """POST to /services/oauth2/token with client credentials grant."""
        from backend.app.services.integrations.salesforce_service import (
            SalesforceService,
        )

        svc = SalesforceService(
            instance_url="https://myorg.salesforce.com",
            client_id="cid",
            client_secret="csecret",
        )
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "access_token": "tok123",
                "instance_url": "https://myorg.salesforce.com",
            }
            mock_post.return_value = mock_resp
            token = svc.get_access_token()
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            # Verify URL contains oauth2/token
            assert "oauth2/token" in call_args[0][0] or "oauth2/token" in str(call_args)

    def test_get_access_token_returns_token_string(self):
        """Returns access_token from response JSON."""
        from backend.app.services.integrations.salesforce_service import (
            SalesforceService,
        )

        svc = SalesforceService(
            instance_url="https://myorg.salesforce.com",
            client_id="cid",
            client_secret="csecret",
        )
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"access_token": "my_token_abc"}
            mock_post.return_value = mock_resp
            token = svc.get_access_token()
            assert token == "my_token_abc"

    def test_get_access_token_returns_none_on_error(self):
        """Returns None if request fails (never raises)."""
        from backend.app.services.integrations.salesforce_service import (
            SalesforceService,
        )

        svc = SalesforceService(
            instance_url="https://myorg.salesforce.com",
            client_id="cid",
            client_secret="csecret",
        )
        with patch("httpx.post", side_effect=Exception("Connection refused")):
            token = svc.get_access_token()
            assert token is None

    def test_get_access_token_sends_client_credentials(self):
        """Sends grant_type=client_credentials with client_id and client_secret."""
        from backend.app.services.integrations.salesforce_service import (
            SalesforceService,
        )

        svc = SalesforceService(
            instance_url="https://myorg.salesforce.com",
            client_id="my_client_id",
            client_secret="my_client_secret",
        )
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"access_token": "tok"}
            mock_post.return_value = mock_resp
            svc.get_access_token()
            _, kwargs = mock_post.call_args
            data = kwargs.get("data", {})
            assert data.get("grant_type") == "client_credentials"
            assert data.get("client_id") == "my_client_id"
            assert data.get("client_secret") == "my_client_secret"


class TestSalesforceExperimentSync:
    def _make_service(self):
        from backend.app.services.integrations.salesforce_service import (
            SalesforceService,
        )

        svc = SalesforceService(
            instance_url="https://myorg.salesforce.com",
            client_id="cid",
            client_secret="csecret",
        )
        svc._access_token = "pre_fetched_token"
        return svc

    def test_create_opportunity_with_experiment_data(self):
        """Creates Salesforce Opportunity with experiment name, hypothesis."""
        svc = self._make_service()
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"id": "006xx000001XYZABC", "success": True}
            mock_post.return_value = mock_resp
            svc.create_opportunity(
                name="Checkout A/B Test",
                experiment_id="exp-uuid-1",
                hypothesis="New checkout increases conversion",
            )
            mock_post.assert_called_once()
            _, kwargs = mock_post.call_args
            body = kwargs.get("json", {})
            assert "Checkout A/B Test" in body.get("Name", "")

    def test_create_opportunity_returns_opportunity_id(self):
        """Returns SF opportunity ID from response."""
        svc = self._make_service()
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"id": "006TESTID", "success": True}
            mock_post.return_value = mock_resp
            opp_id = svc.create_opportunity("Test", "exp-1", "hyp")
            assert opp_id == "006TESTID"

    def test_create_opportunity_returns_none_on_error(self):
        """Returns None if API fails."""
        svc = self._make_service()
        with patch("httpx.post", side_effect=Exception("Salesforce down")):
            result = svc.create_opportunity("Test", "exp-1", "hyp")
            assert result is None

    def test_create_opportunity_includes_hypothesis(self):
        """Opportunity description contains hypothesis and experiment ID."""
        svc = self._make_service()
        with patch("httpx.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.json.return_value = {"id": "006ABC", "success": True}
            mock_post.return_value = mock_resp
            svc.create_opportunity("Test", "exp-xyz", "Reduce friction in checkout")
            _, kwargs = mock_post.call_args
            body = kwargs.get("json", {})
            description = body.get("Description", "")
            assert "exp-xyz" in description
            assert "Reduce friction in checkout" in description

    def test_update_opportunity_with_results(self):
        """Updates existing opportunity with experiment results."""
        svc = self._make_service()
        with patch("httpx.patch") as mock_patch:
            mock_resp = MagicMock()
            mock_resp.status_code = 204
            mock_patch.return_value = mock_resp
            result = svc.update_opportunity(
                opportunity_id="006TESTID",
                fields={"Description": "Results: variant B won"},
            )
            mock_patch.assert_called_once()
            assert result is True

    def test_update_opportunity_returns_none_on_error(self):
        """Returns None if update fails."""
        svc = self._make_service()
        with patch("httpx.patch", side_effect=Exception("Timeout")):
            result = svc.update_opportunity("006TESTID", {"Description": "results"})
            assert result is None

    def test_sync_experiment_creates_if_no_opportunity_id(self):
        """sync_experiment() creates if no opportunity_id."""
        svc = self._make_service()
        with patch.object(
            svc, "create_opportunity", return_value="006NEW"
        ) as mock_create:
            result = svc.sync_experiment(
                experiment_id="exp-1",
                name="Test",
                hypothesis="hyp",
            )
            mock_create.assert_called_once()
            assert result == "006NEW"

    def test_sync_experiment_updates_if_opportunity_id_exists(self):
        """sync_experiment() updates if opportunity_id already exists."""
        svc = self._make_service()
        with patch.object(svc, "update_opportunity", return_value=True) as mock_update:
            result = svc.sync_experiment(
                experiment_id="exp-1",
                name="Test",
                hypothesis="hyp",
                opportunity_id="006EXISTING",
                results={"winner": "B"},
            )
            mock_update.assert_called_once()
            assert result == "006EXISTING"

    def test_get_opportunity_fields(self):
        """get_opportunity() fetches opportunity details."""
        svc = self._make_service()
        with patch("httpx.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "Id": "006TESTID",
                "Name": "Test Opportunity",
                "StageName": "Prospecting",
            }
            mock_get.return_value = mock_resp
            result = svc.get_opportunity("006TESTID")
            assert result["Id"] == "006TESTID"
            assert result["Name"] == "Test Opportunity"

    def test_get_opportunity_returns_none_on_error(self):
        """Returns None if get_opportunity fails."""
        svc = self._make_service()
        with patch("httpx.get", side_effect=Exception("Network error")):
            result = svc.get_opportunity("006TESTID")
            assert result is None

    def test_parse_webhook_event_opportunity_updated(self):
        """parse_webhook_event() handles outbound message with status changes."""
        from backend.app.services.integrations.salesforce_service import (
            SalesforceService,
        )

        svc = SalesforceService("https://myorg.salesforce.com", "c", "s")
        payload = {
            "event_type": "Opportunity",
            "id": "006TESTID",
            "changedFields": ["StageName", "CloseDate"],
        }
        event = svc.parse_webhook_event(payload)
        assert event is not None
        assert event["event_type"] == "Opportunity"
        assert event["object_id"] == "006TESTID"

    def test_parse_webhook_event_unsupported_returns_none(self):
        """Returns None for unrecognized event types (empty payload)."""
        from backend.app.services.integrations.salesforce_service import (
            SalesforceService,
        )

        svc = SalesforceService("https://myorg.salesforce.com", "c", "s")
        result = svc.parse_webhook_event({})
        assert result is None

    def test_parse_webhook_event_never_raises(self):
        """parse_webhook_event() never raises even on malformed payload."""
        from backend.app.services.integrations.salesforce_service import (
            SalesforceService,
        )

        svc = SalesforceService("https://myorg.salesforce.com", "c", "s")
        # Even None or weird types should not raise
        result = svc.parse_webhook_event({"event_type": None})
        # As long as it doesn't raise, we're good; result can be None
        # (None event_type → returns None)
        assert result is None
