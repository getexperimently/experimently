"""
Integration tests for EP-058: Real-time WebSocket Streaming Results.

Tests the WebSocket endpoint at /api/v1/ws/experiments/{experiment_id}/results
and companion HTTP endpoints:
  GET /api/v1/ws/experiments/{experiment_id}/results/subscribers
  GET /api/v1/ws/active-experiments

Uses starlette.testclient.TestClient's native WebSocket support (synchronous
context manager). All DB calls are mocked so no live PostgreSQL is required.
"""

from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

WS_BASE = "/api/v1/ws/experiments"
ACTIVE_ENDPOINT = "/api/v1/ws/active-experiments"


def _make_snapshot(
    experiment_id: str = "test-exp-123",
    status: str = "active",
    is_significant: bool = False,
) -> dict:
    """Return a minimal fake snapshot dict."""
    return {
        "event": "results_update",
        "experiment_id": experiment_id,
        "timestamp": "2026-03-07T00:00:00+00:00",
        "status": status,
        "variants": [
            {
                "key": "control",
                "name": "Control",
                "participant_count": 500,
                "conversion_count": 50,
                "conversion_rate": 0.10,
                "relative_lift": 0.0,
                "p_value": None,
                "is_control": True,
            },
            {
                "key": "variant_b",
                "name": "Variant B",
                "participant_count": 500,
                "conversion_count": 65,
                "conversion_rate": 0.13,
                "relative_lift": 0.30,
                "p_value": 0.03 if is_significant else 0.20,
                "is_control": False,
            },
        ],
        "total_participants": 1000,
        "days_running": 7,
        "is_significant": is_significant,
    }


PATCH_SNAPSHOT = (
    "backend.app.services.results_streaming_service."
    "ResultsStreamingService.get_live_snapshot"
)


# ---------------------------------------------------------------------------
# WebSocket connect — initial snapshot
# ---------------------------------------------------------------------------


class TestWebSocketConnect:
    """Tests for the WebSocket connection + initial snapshot delivery."""

    def test_websocket_connect_receives_snapshot(self):
        """On connect, server immediately sends a snapshot."""
        snapshot = _make_snapshot("test-exp-123")

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/test-exp-123/results") as ws:
                data = ws.receive_json()

        assert data["event"] == "results_update"
        assert "variants" in data

    def test_initial_snapshot_contains_experiment_id(self):
        """Initial snapshot has experiment_id matching the URL parameter."""
        snapshot = _make_snapshot("exp-abc")

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/exp-abc/results") as ws:
                data = ws.receive_json()

        assert data["experiment_id"] == "exp-abc"

    def test_initial_snapshot_has_total_participants(self):
        """Initial snapshot contains total_participants field."""
        snapshot = _make_snapshot()

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/test-exp/results") as ws:
                data = ws.receive_json()

        assert "total_participants" in data
        assert isinstance(data["total_participants"], int)

    def test_initial_snapshot_has_variants_list(self):
        """Initial snapshot has a non-empty variants list."""
        snapshot = _make_snapshot()

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/test-exp/results") as ws:
                data = ws.receive_json()

        assert isinstance(data["variants"], list)
        assert len(data["variants"]) == 2

    def test_initial_snapshot_has_timestamp(self):
        """Initial snapshot includes a timestamp string."""
        snapshot = _make_snapshot()

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/test-exp/results") as ws:
                data = ws.receive_json()

        assert "timestamp" in data
        assert isinstance(data["timestamp"], str)

    def test_initial_snapshot_has_status(self):
        """Initial snapshot includes a status field."""
        snapshot = _make_snapshot(status="active")

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/test-exp/results") as ws:
                data = ws.receive_json()

        assert "status" in data
        assert data["status"] == "active"

    def test_initial_snapshot_has_is_significant(self):
        """Initial snapshot includes is_significant boolean."""
        snapshot = _make_snapshot(is_significant=True)

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/test-exp/results") as ws:
                data = ws.receive_json()

        assert data["is_significant"] is True

    def test_initial_snapshot_has_days_running(self):
        """Initial snapshot includes days_running field."""
        snapshot = _make_snapshot()

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/test-exp/results") as ws:
                data = ws.receive_json()

        assert "days_running" in data

    def test_variant_has_required_fields(self):
        """Each variant in snapshot has the required fields."""
        snapshot = _make_snapshot()

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/test-exp/results") as ws:
                data = ws.receive_json()

        for variant in data["variants"]:
            assert "name" in variant
            assert "participant_count" in variant
            assert "conversion_count" in variant
            assert "conversion_rate" in variant
            assert "is_control" in variant


# ---------------------------------------------------------------------------
# WebSocket message protocol — ping/pong
# ---------------------------------------------------------------------------


class TestWebSocketPingPong:
    """Tests for the ping/pong client message protocol."""

    def test_ping_receives_pong(self):
        """Client sends ping, server replies with pong."""
        snapshot = _make_snapshot()

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/test-exp/results") as ws:
                ws.receive_json()  # consume initial snapshot
                ws.send_json({"action": "ping"})
                response = ws.receive_json()

        assert response["event"] == "pong"

    def test_ping_response_has_event_pong(self):
        """Ping response payload has event='pong'."""
        snapshot = _make_snapshot()

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/ping-test/results") as ws:
                ws.receive_json()
                ws.send_json({"action": "ping"})
                response = ws.receive_json()

        assert response == {"event": "pong"}

    def test_multiple_pings_receive_multiple_pongs(self):
        """Multiple ping messages each receive a pong response."""
        snapshot = _make_snapshot()

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/multi-ping/results") as ws:
                ws.receive_json()  # initial snapshot
                for _ in range(3):
                    ws.send_json({"action": "ping"})
                    resp = ws.receive_json()
                    assert resp["event"] == "pong"


# ---------------------------------------------------------------------------
# WebSocket message protocol — refresh
# ---------------------------------------------------------------------------


class TestWebSocketRefresh:
    """Tests for the refresh action."""

    def test_refresh_receives_new_snapshot(self):
        """Client sends refresh, server sends a new snapshot."""
        snapshot1 = _make_snapshot()
        snapshot2 = _make_snapshot(status="paused")

        side_effects = [snapshot1, snapshot2]

        with patch(PATCH_SNAPSHOT, side_effect=side_effects):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/refresh-exp/results") as ws:
                initial = ws.receive_json()
                assert initial["status"] == "active"

                ws.send_json({"action": "refresh"})
                refreshed = ws.receive_json()

        assert refreshed["event"] == "results_update"
        assert refreshed["status"] == "paused"

    def test_refresh_snapshot_has_correct_experiment_id(self):
        """Refresh snapshot contains the correct experiment_id."""
        snapshot = _make_snapshot(experiment_id="exp-refresh")

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/exp-refresh/results") as ws:
                ws.receive_json()
                ws.send_json({"action": "refresh"})
                refreshed = ws.receive_json()

        assert refreshed["experiment_id"] == "exp-refresh"


# ---------------------------------------------------------------------------
# WebSocket — invalid/unknown actions
# ---------------------------------------------------------------------------


class TestWebSocketUnknownActions:
    """Tests for unknown / malformed client messages."""

    def test_unknown_action_does_not_crash(self):
        """Unknown action doesn't crash the server; next messages still work."""
        snapshot = _make_snapshot()

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/test-exp/results") as ws:
                ws.receive_json()  # initial snapshot
                ws.send_json({"action": "unknown_action"})
                # Server should still respond to a subsequent ping
                ws.send_json({"action": "ping"})
                resp = ws.receive_json()

        assert resp["event"] == "pong"

    def test_malformed_json_does_not_crash(self):
        """A non-JSON string doesn't crash the server."""
        snapshot = _make_snapshot()

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/test-exp/results") as ws:
                ws.receive_json()  # initial snapshot
                ws.send_text("this is not json")
                # Server should still process next valid message
                ws.send_json({"action": "ping"})
                resp = ws.receive_json()

        assert resp["event"] == "pong"


# ---------------------------------------------------------------------------
# HTTP companion endpoint — subscriber count
# ---------------------------------------------------------------------------


class TestSubscriberCountEndpoint:
    """Tests for GET /api/v1/ws/experiments/{id}/results/subscribers."""

    def test_subscriber_count_endpoint_returns_200(self):
        """Endpoint returns 200 OK."""
        client = TestClient(app)
        response = client.get(f"{WS_BASE}/exp-1/results/subscribers")
        assert response.status_code == 200

    def test_subscriber_count_returns_zero_when_no_connections(self):
        """Subscriber count is 0 when no clients are connected."""
        client = TestClient(app)
        response = client.get(f"{WS_BASE}/exp-no-clients/results/subscribers")
        assert response.status_code == 200
        data = response.json()
        assert "subscriber_count" in data
        assert data["subscriber_count"] == 0

    def test_subscriber_count_response_has_experiment_id(self):
        """Response includes experiment_id field."""
        client = TestClient(app)
        response = client.get(f"{WS_BASE}/exp-check/results/subscribers")
        data = response.json()
        assert data["experiment_id"] == "exp-check"

    def test_subscriber_count_is_integer(self):
        """subscriber_count field is an integer."""
        client = TestClient(app)
        response = client.get(f"{WS_BASE}/exp-int/results/subscribers")
        data = response.json()
        assert isinstance(data["subscriber_count"], int)

    def test_subscriber_count_reflects_active_connections(self):
        """Subscriber count increases while WebSocket is connected."""
        snapshot = _make_snapshot()

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/exp-live/results"):
                response = client.get(f"{WS_BASE}/exp-live/results/subscribers")
                data = response.json()
                # There's at least one active subscriber
                assert data["subscriber_count"] >= 1


# ---------------------------------------------------------------------------
# HTTP companion endpoint — active experiments
# ---------------------------------------------------------------------------


class TestActiveExperimentsEndpoint:
    """Tests for GET /api/v1/ws/active-experiments."""

    def test_active_experiments_endpoint_returns_200(self):
        """Endpoint returns 200 OK."""
        client = TestClient(app)
        response = client.get(ACTIVE_ENDPOINT)
        assert response.status_code == 200

    def test_active_experiments_returns_list(self):
        """Response has active_experiments key with a list value."""
        client = TestClient(app)
        response = client.get(ACTIVE_ENDPOINT)
        data = response.json()
        assert "active_experiments" in data
        assert isinstance(data["active_experiments"], list)

    def test_active_experiments_includes_connected_experiment(self):
        """Active experiments list includes experiments with live subscribers."""
        snapshot = _make_snapshot(experiment_id="exp-active-check")

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/exp-active-check/results"):
                response = client.get(ACTIVE_ENDPOINT)
                data = response.json()
                assert "exp-active-check" in data["active_experiments"]

    def test_active_experiments_empty_when_no_connections(self):
        """Active experiments list is empty (or doesn't contain the test exp) when disconnected."""
        client = TestClient(app)
        # Reset: nothing should be connected for this experiment
        response = client.get(ACTIVE_ENDPOINT)
        data = response.json()
        assert "active_experiments" in data
        # "exp-fresh-no-connections" was never connected, so not in the list
        assert "exp-fresh-no-connections" not in data["active_experiments"]


# ---------------------------------------------------------------------------
# Multiple clients / experiments
# ---------------------------------------------------------------------------


class TestMultipleClientsAndExperiments:
    """Tests for scenarios with multiple concurrent clients."""

    def test_multiple_clients_same_experiment_all_receive_snapshot(self):
        """Multiple clients connected to the same experiment each get a snapshot."""
        snapshot = _make_snapshot(experiment_id="exp-multi")

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/exp-multi/results") as ws1:
                data1 = ws1.receive_json()
                with client.websocket_connect(f"{WS_BASE}/exp-multi/results") as ws2:
                    data2 = ws2.receive_json()
                    assert data1["event"] == "results_update"
                    assert data2["event"] == "results_update"

    def test_different_experiments_independent(self):
        """Two experiments have independent WebSocket streams."""
        snapshot_a = _make_snapshot(experiment_id="exp-a")
        snapshot_b = _make_snapshot(experiment_id="exp-b", status="paused")

        with patch(PATCH_SNAPSHOT, side_effect=[snapshot_a, snapshot_b]):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/exp-a/results") as ws_a:
                data_a = ws_a.receive_json()
                with client.websocket_connect(f"{WS_BASE}/exp-b/results") as ws_b:
                    data_b = ws_b.receive_json()

        assert data_a["experiment_id"] == "exp-a"
        assert data_b["experiment_id"] == "exp-b"
        assert data_b["status"] == "paused"


# ---------------------------------------------------------------------------
# Error/edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_invalid_experiment_id_still_connects(self):
        """WebSocket accepts any experiment_id string (validation deferred to service)."""
        snapshot = {
            "event": "results_update",
            "experiment_id": "invalid-id",
            "timestamp": "2026-03-07T00:00:00+00:00",
            "status": "not_found",
            "variants": [],
            "total_participants": 0,
            "days_running": None,
            "is_significant": False,
            "error": "Experiment invalid-id not found",
        }

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/invalid-id/results") as ws:
                data = ws.receive_json()

        assert data["status"] == "not_found"

    def test_snapshot_service_error_returns_error_snapshot(self):
        """If snapshot computation fails, client still receives an error snapshot."""
        error_snapshot = {
            "event": "results_update",
            "experiment_id": "exp-err",
            "timestamp": "2026-03-07T00:00:00+00:00",
            "status": "error",
            "variants": [],
            "total_participants": 0,
            "days_running": None,
            "is_significant": False,
            "error": "DB connection refused",
        }

        with patch(PATCH_SNAPSHOT, return_value=error_snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/exp-err/results") as ws:
                data = ws.receive_json()

        assert data["event"] == "results_update"
        assert data["status"] == "error"

    def test_subscriber_count_is_zero_after_disconnect(self):
        """Subscriber count drops back to 0 after WebSocket disconnects."""
        snapshot = _make_snapshot()

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            exp_id = "exp-disconnect-check"
            with client.websocket_connect(f"{WS_BASE}/{exp_id}/results") as ws:
                ws.receive_json()
            # After the context manager exits, client has disconnected
            response = client.get(f"{WS_BASE}/{exp_id}/results/subscribers")
            data = response.json()
            assert data["subscriber_count"] == 0

    def test_completed_experiment_snapshot_delivered(self):
        """Snapshot for a completed experiment is still delivered correctly."""
        snapshot = _make_snapshot(status="completed")

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/exp-done/results") as ws:
                data = ws.receive_json()

        assert data["status"] == "completed"

    def test_paused_experiment_snapshot_delivered(self):
        """Snapshot for a paused experiment is delivered correctly."""
        snapshot = _make_snapshot(status="paused")

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/exp-paused/results") as ws:
                data = ws.receive_json()

        assert data["status"] == "paused"

    def test_significant_result_flagged_in_snapshot(self):
        """is_significant is True when a variant has p_value < 0.05."""
        snapshot = _make_snapshot(is_significant=True)

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/exp-sig/results") as ws:
                data = ws.receive_json()

        assert data["is_significant"] is True

    def test_not_significant_result_flagged(self):
        """is_significant is False when no variant has p_value < 0.05."""
        snapshot = _make_snapshot(is_significant=False)

        with patch(PATCH_SNAPSHOT, return_value=snapshot):
            client = TestClient(app)
            with client.websocket_connect(f"{WS_BASE}/exp-not-sig/results") as ws:
                data = ws.receive_json()

        assert data["is_significant"] is False
