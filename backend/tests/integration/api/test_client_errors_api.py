"""
Integration tests for the client error reporting API
(``POST /api/v1/tracking/errors`` and ``/tracking/errors/batch``).

The endpoints resolve ``feature_flag_key`` / ``experiment_key`` to ids and
persist ``ErrorLog`` rows that safety monitoring reads. Every test removes the
rows it created (same cleanup pattern as ``test_tracking_api.py``).
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.api.v1.endpoints.client_errors import (
    METADATA_MAX_BYTES,
    STACK_TRACE_MAX_BYTES,
)
from backend.app.models.experiment import Experiment, ExperimentStatus
from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.models.metrics.metric import ErrorLog
from backend.tests.integration.helpers import unique_flag_key


@pytest.fixture
def flag(db_session, make_feature_flag):
    """An ACTIVE flag; its error rows and the flag itself are removed afterwards."""
    created = make_feature_flag(
        key=unique_flag_key("errors"),
        name="Errors Flag",
        status=FeatureFlagStatus.ACTIVE,
        rollout_percentage=25,
    )
    yield created
    db_session.rollback()
    db_session.query(ErrorLog).filter(ErrorLog.feature_flag_id == created.id).delete()
    db_session.query(FeatureFlag).filter(FeatureFlag.id == created.id).delete()
    db_session.commit()


@pytest.fixture
def experiment(db_session, make_experiment):
    suffix = uuid.uuid4().hex[:8]
    created = make_experiment(
        name=f"Errors experiment {suffix}",
        key=f"errors-exp-{suffix}",
        status=ExperimentStatus.ACTIVE,
    )
    yield created
    db_session.rollback()
    db_session.query(ErrorLog).filter(
        ErrorLog.request_data["experiment_id"].astext == str(created.id)
    ).delete(synchronize_session=False)
    db_session.query(Experiment).filter(Experiment.id == created.id).delete()
    db_session.commit()


def _user() -> str:
    return f"device-{uuid.uuid4().hex[:10]}"


def _rows(db_session, flag):
    return (
        db_session.query(ErrorLog)
        .filter(ErrorLog.feature_flag_id == flag.id)
        .order_by(ErrorLog.timestamp)
        .all()
    )


class TestReportError:
    def test_writes_row_with_resolved_flag_id(self, admin_client, db_session, flag):
        user_id = _user()
        body = {
            "feature_flag_key": flag.key,
            "user_id": user_id,
            "error_type": "crash",
            "message": "NullPointerException in PlayerV2Fragment",
            "metadata": {
                "os": "Android",
                "os_version": "12.0.0",
                "device_model": "Galaxy S10",
            },
        }
        resp = admin_client.post("/api/v1/tracking/errors", json=body)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["feature_flag_id"] == str(flag.id)
        assert data["experiment_id"] is None
        assert data["error_type"] == "crash"
        assert data["user_id"] == user_id
        assert uuid.UUID(data["id"])

        db_session.expire_all()
        rows = _rows(db_session, flag)
        assert len(rows) == 1
        row = rows[0]
        assert str(row.id) == data["id"]
        assert row.feature_flag_id == flag.id
        assert row.user_id == user_id
        assert row.error_type == "crash"
        assert row.message == "NullPointerException in PlayerV2Fragment"
        assert row.meta_data == body["metadata"]
        assert row.request_data["feature_flag_key"] == flag.key
        assert row.request_data["source"] == "client"
        # defaulted to "now" (naive UTC column)
        assert abs((datetime.utcnow() - row.timestamp).total_seconds()) < 60

    def test_client_timestamp_is_kept_in_metadata(self, admin_client, db_session, flag):
        when = datetime(2026, 3, 1, 10, 30, tzinfo=timezone(timedelta(hours=2)))
        resp = admin_client.post(
            "/api/v1/tracking/errors",
            json={
                "feature_flag_key": flag.key,
                "error_type": "crash",
                "message": "boom",
                "metadata": {"os": "Android"},
                "timestamp": when.isoformat(),
            },
        )
        assert resp.status_code == 201, resp.text
        db_session.expire_all()
        row = _rows(db_session, flag)[0]
        assert row.meta_data["os"] == "Android"
        assert datetime.fromisoformat(row.meta_data["client_timestamp"]) == when
        assert abs((datetime.utcnow() - row.timestamp).total_seconds()) < 60

    def test_experiment_key_is_resolved_into_request_data(
        self, admin_client, db_session, flag, experiment
    ):
        resp = admin_client.post(
            "/api/v1/tracking/errors",
            json={
                "feature_flag_key": flag.key,
                "experiment_key": experiment.key,
                "error_type": "api_error",
                "message": "500 from /checkout",
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["experiment_id"] == str(experiment.id)
        db_session.expire_all()
        row = _rows(db_session, flag)[0]
        assert row.request_data["experiment_key"] == experiment.key
        assert row.request_data["experiment_id"] == str(experiment.id)

    def test_experiment_only_report(self, admin_client, db_session, experiment):
        resp = admin_client.post(
            "/api/v1/tracking/errors",
            json={
                "experiment_key": experiment.key,
                "error_type": "js_error",
                "message": "x",
            },
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["feature_flag_id"] is None
        assert data["experiment_id"] == str(experiment.id)

    def test_long_message_is_truncated_to_column_width(
        self, admin_client, db_session, flag
    ):
        resp = admin_client.post(
            "/api/v1/tracking/errors",
            json={
                "feature_flag_key": flag.key,
                "error_type": "crash",
                "message": "x" * 5000,
            },
        )
        assert resp.status_code == 201, resp.text
        db_session.expire_all()
        assert len(_rows(db_session, flag)[0].message) == 1000

    def test_unknown_flag_key_returns_404(self, admin_client):
        resp = admin_client.post(
            "/api/v1/tracking/errors",
            json={
                "feature_flag_key": unique_flag_key("missing"),
                "error_type": "crash",
                "message": "x",
            },
        )
        assert resp.status_code == 404, resp.text

    def test_unknown_experiment_key_returns_404(self, admin_client, flag):
        resp = admin_client.post(
            "/api/v1/tracking/errors",
            json={
                "feature_flag_key": flag.key,
                "experiment_key": f"missing-{uuid.uuid4().hex}",
                "error_type": "crash",
                "message": "x",
            },
        )
        assert resp.status_code == 404, resp.text

    def test_missing_both_keys_returns_422(self, admin_client):
        resp = admin_client.post(
            "/api/v1/tracking/errors",
            json={"user_id": _user(), "error_type": "crash", "message": "x"},
        )
        assert resp.status_code == 422, resp.text

    @pytest.mark.parametrize("missing", ["error_type", "message"])
    def test_missing_required_field_returns_422(self, admin_client, flag, missing):
        body = {"feature_flag_key": flag.key, "error_type": "crash", "message": "x"}
        body.pop(missing)
        resp = admin_client.post("/api/v1/tracking/errors", json=body)
        assert resp.status_code == 422, resp.text

    def test_requires_api_key(self, flag):
        from fastapi.testclient import TestClient

        from backend.app.main import app

        app.dependency_overrides.clear()
        with TestClient(app) as anonymous:
            resp = anonymous.post(
                "/api/v1/tracking/errors",
                json={
                    "feature_flag_key": flag.key,
                    "error_type": "crash",
                    "message": "x",
                },
            )
        assert resp.status_code == 401


class TestReportErrorsBatch:
    def test_batch_writes_rows_and_counts(self, admin_client, db_session, flag):
        users = [_user() for _ in range(3)]
        resp = admin_client.post(
            "/api/v1/tracking/errors/batch",
            json={
                "errors": [
                    {
                        "feature_flag_key": flag.key,
                        "user_id": user,
                        "error_type": "crash",
                        "message": f"crash for {user}",
                        "metadata": {"os": "Android"},
                    }
                    for user in users
                ]
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success_count": 3, "failure_count": 0, "errors": None}

        db_session.expire_all()
        rows = _rows(db_session, flag)
        assert {row.user_id for row in rows} == set(users)
        assert all(row.feature_flag_id == flag.id for row in rows)

    def test_batch_reports_unknown_keys_per_item(self, admin_client, db_session, flag):
        resp = admin_client.post(
            "/api/v1/tracking/errors/batch",
            json={
                "errors": [
                    {
                        "feature_flag_key": flag.key,
                        "error_type": "crash",
                        "message": "ok",
                    },
                    {
                        "feature_flag_key": unique_flag_key("missing"),
                        "error_type": "crash",
                        "message": "bad",
                    },
                    {
                        "feature_flag_key": flag.key,
                        "error_type": "crash",
                        "message": "ok 2",
                    },
                ]
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["success_count"] == 2
        assert data["failure_count"] == 1
        assert len(data["errors"]) == 1
        assert data["errors"][0]["index"] == 1
        assert "not found" in data["errors"][0]["error"]

        db_session.expire_all()
        assert len(_rows(db_session, flag)) == 2

    def test_batch_item_without_keys_is_422(self, admin_client, flag):
        resp = admin_client.post(
            "/api/v1/tracking/errors/batch",
            json={"errors": [{"error_type": "crash", "message": "x"}]},
        )
        assert resp.status_code == 422, resp.text

    def test_empty_batch_is_422(self, admin_client):
        resp = admin_client.post("/api/v1/tracking/errors/batch", json={"errors": []})
        assert resp.status_code == 422, resp.text

    def test_batch_over_limit_is_413(self, admin_client, flag):
        resp = admin_client.post(
            "/api/v1/tracking/errors/batch",
            json={
                "errors": [
                    {
                        "feature_flag_key": flag.key,
                        "error_type": "crash",
                        "message": "x",
                    }
                    for _ in range(101)
                ]
            },
        )
        assert resp.status_code == 413, resp.text


def _post_one(client, path, report):
    if path.endswith("/batch"):
        resp = client.post(path, json={"errors": [report]})
        assert resp.status_code == 200, resp.text
        assert resp.json()["success_count"] == 1, resp.text
    else:
        resp = client.post(path, json=report)
        assert resp.status_code == 201, resp.text
    return resp


_PATHS = ["/api/v1/tracking/errors", "/api/v1/tracking/errors/batch"]


@pytest.mark.regression
class TestStoredErrorReports:
    """What is stored for a report: the receive time and bounded sizes."""

    @pytest.mark.parametrize("path", _PATHS)
    def test_stored_timestamp_is_the_receive_time(
        self, admin_client, db_session, flag, path
    ):
        """A client-sent timestamp is kept in metadata; the row is timed on receipt."""
        sent = datetime.now(timezone.utc) + timedelta(days=3)
        before = datetime.utcnow()
        resp = _post_one(
            admin_client,
            path,
            {
                "feature_flag_key": flag.key,
                "error_type": "crash",
                "message": "boom",
                "timestamp": sent.isoformat(),
            },
        )
        after = datetime.utcnow()

        db_session.expire_all()
        row = _rows(db_session, flag)[0]
        assert (
            before - timedelta(seconds=5)
            <= row.timestamp
            <= after + timedelta(seconds=5)
        )
        assert datetime.fromisoformat(row.meta_data["client_timestamp"]) == sent
        if not path.endswith("/batch"):
            assert datetime.fromisoformat(resp.json()["timestamp"]) == row.timestamp

    @pytest.mark.parametrize("path", _PATHS)
    def test_stack_trace_is_cut_to_the_byte_limit(
        self, admin_client, db_session, flag, path
    ):
        """An oversized stack trace is stored as a prefix within the byte limit."""
        # Three bytes per character in UTF-8, so the character count alone
        # would pass a character limit of the same number.
        stack_trace = "\u20ac" * STACK_TRACE_MAX_BYTES
        _post_one(
            admin_client,
            path,
            {
                "feature_flag_key": flag.key,
                "error_type": "crash",
                "message": "boom",
                "stack_trace": stack_trace,
            },
        )

        db_session.expire_all()
        stored = _rows(db_session, flag)[0].stack_trace
        size = len(stored.encode("utf-8"))
        assert STACK_TRACE_MAX_BYTES - 3 < size <= STACK_TRACE_MAX_BYTES
        assert stack_trace.startswith(stored)

    def test_stack_trace_within_the_limit_is_unchanged(
        self, admin_client, db_session, flag
    ):
        """A stack trace within the limit is stored as sent."""
        stack_trace = "at PlayerV2Fragment.onCreate(PlayerV2Fragment.kt:42)\n" * 10
        _post_one(
            admin_client,
            "/api/v1/tracking/errors",
            {
                "feature_flag_key": flag.key,
                "error_type": "crash",
                "message": "boom",
                "stack_trace": stack_trace,
            },
        )
        db_session.expire_all()
        assert _rows(db_session, flag)[0].stack_trace == stack_trace

    @pytest.mark.parametrize("path", _PATHS)
    def test_oversized_metadata_is_replaced_by_a_marker(
        self, admin_client, db_session, flag, path
    ):
        """Metadata over the byte limit is stored as a marker with its size."""
        metadata = {"os": "Android", "dump": "\u00e9" * (METADATA_MAX_BYTES // 2 + 64)}
        sent = datetime.now(timezone.utc)
        _post_one(
            admin_client,
            path,
            {
                "feature_flag_key": flag.key,
                "error_type": "crash",
                "message": "boom",
                "metadata": metadata,
                "timestamp": sent.isoformat(),
            },
        )

        db_session.expire_all()
        stored = _rows(db_session, flag)[0].meta_data
        assert stored["metadata_truncated"] is True
        assert stored["metadata_bytes"] > METADATA_MAX_BYTES
        assert "dump" not in stored
        assert datetime.fromisoformat(stored["client_timestamp"]) == sent
        encoded = json.dumps(stored, separators=(",", ":"), ensure_ascii=False)
        assert len(encoded.encode("utf-8")) <= METADATA_MAX_BYTES
