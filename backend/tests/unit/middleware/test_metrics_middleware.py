"""
Unit tests for backend/app/middleware/metrics_middleware.py

Covers:
- normalize_path: UUID replacement, no-op for non-UUIDs, multiple UUIDs
- PrometheusMetricsMiddleware records metrics on successful requests
- Status code and duration are forwarded correctly
"""

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.responses import JSONResponse

# ---------------------------------------------------------------------------
# normalize_path tests (pure function — no side-effects)
# ---------------------------------------------------------------------------


def test_normalize_path_replaces_uuid():
    from backend.app.middleware.prometheus_metrics_middleware import normalize_path

    path = "/api/v1/experiments/550e8400-e29b-41d4-a716-446655440000/results"
    result = normalize_path(path)
    assert result == "/api/v1/experiments/{id}/results"


def test_normalize_path_leaves_non_uuid_intact():
    from backend.app.middleware.prometheus_metrics_middleware import normalize_path

    path = "/api/v1/feature-flags/evaluate/my-feature-key"
    result = normalize_path(path)
    assert result == "/api/v1/feature-flags/evaluate/my-feature-key"


def test_normalize_path_multiple_uuids():
    from backend.app.middleware.prometheus_metrics_middleware import normalize_path

    path = (
        "/api/v1/users/550e8400-e29b-41d4-a716-446655440000"
        "/experiments/660e8400-e29b-41d4-a716-446655440001"
    )
    result = normalize_path(path)
    assert result == "/api/v1/users/{id}/experiments/{id}"


def test_normalize_path_no_uuid():
    from backend.app.middleware.prometheus_metrics_middleware import normalize_path

    path = "/api/v1/health"
    assert normalize_path(path) == "/api/v1/health"


def test_normalize_path_root():
    from backend.app.middleware.prometheus_metrics_middleware import normalize_path

    assert normalize_path("/") == "/"


# ---------------------------------------------------------------------------
# PrometheusMetricsMiddleware integration-style tests (in-process)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metrics_middleware_records_on_success(mocker):
    """record_request is called once for a successful response."""
    mock_record = mocker.patch(
        "backend.app.middleware.prometheus_metrics_middleware.record_request"
    )

    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"pong": True}

    from backend.app.middleware.prometheus_metrics_middleware import PrometheusMetricsMiddleware

    app.add_middleware(PrometheusMetricsMiddleware)
    client = TestClient(app)

    response = client.get("/ping")
    assert response.status_code == 200

    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args.kwargs
    assert call_kwargs["status_code"] == 200
    assert call_kwargs["duration"] > 0
    assert call_kwargs["method"] == "GET"


@pytest.mark.asyncio
async def test_metrics_middleware_records_404(mocker):
    """record_request is called even when the route is not found (404)."""
    mock_record = mocker.patch(
        "backend.app.middleware.prometheus_metrics_middleware.record_request"
    )

    app = FastAPI()
    from backend.app.middleware.prometheus_metrics_middleware import PrometheusMetricsMiddleware

    app.add_middleware(PrometheusMetricsMiddleware)
    client = TestClient(app)

    response = client.get("/nonexistent-route")
    assert response.status_code == 404

    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args.kwargs
    assert call_kwargs["status_code"] == 404


@pytest.mark.asyncio
async def test_metrics_middleware_normalizes_uuid_path(mocker):
    """Paths with UUIDs are normalised before being passed to record_request."""
    mock_record = mocker.patch(
        "backend.app.middleware.prometheus_metrics_middleware.record_request"
    )

    app = FastAPI()

    @app.get("/api/v1/experiments/{experiment_id}")
    async def get_experiment(experiment_id: str):
        return {"id": experiment_id}

    from backend.app.middleware.prometheus_metrics_middleware import PrometheusMetricsMiddleware

    app.add_middleware(PrometheusMetricsMiddleware)
    client = TestClient(app)

    client.get("/api/v1/experiments/550e8400-e29b-41d4-a716-446655440000")

    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args.kwargs
    assert call_kwargs["endpoint"] == "/api/v1/experiments/{id}"


@pytest.mark.asyncio
async def test_metrics_middleware_records_post(mocker):
    """POST requests are tracked correctly."""
    mock_record = mocker.patch(
        "backend.app.middleware.prometheus_metrics_middleware.record_request"
    )

    app = FastAPI()

    @app.post("/api/v1/events")
    async def create_event():
        return {"created": True}

    from backend.app.middleware.prometheus_metrics_middleware import PrometheusMetricsMiddleware

    app.add_middleware(PrometheusMetricsMiddleware)
    client = TestClient(app)

    response = client.post("/api/v1/events", json={})
    assert response.status_code == 200

    mock_record.assert_called_once()
    assert mock_record.call_args.kwargs["method"] == "POST"
