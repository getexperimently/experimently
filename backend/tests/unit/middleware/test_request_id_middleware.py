"""
Unit tests for backend/app/middleware/request_id_middleware.py

Covers:
- X-Request-ID header is always present in the response
- If client sends X-Request-ID it is echoed back unchanged
- If client does not send X-Request-ID a fresh UUID is generated
- Request context is bound to the logger context
"""

import uuid

import pytest
from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.testclient import TestClient


def _make_app() -> FastAPI:
    """Return a tiny FastAPI app with RequestIDMiddleware applied."""
    from backend.app.middleware.request_id_middleware import RequestIDMiddleware

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/ping")
    async def ping():
        return {"pong": True}

    return app


def test_request_id_added_to_response_headers():
    """Response always has X-Request-ID header even without client sending one."""
    client = TestClient(_make_app())
    response = client.get("/ping")
    assert "x-request-id" in response.headers or "X-Request-ID" in response.headers


def test_new_uuid_generated_when_absent():
    """If no X-Request-ID in request, a new UUID is generated and returned."""
    client = TestClient(_make_app())
    response = client.get("/ping")

    # Locate the header (headers dict is case-insensitive in httpx)
    request_id = response.headers.get("x-request-id") or response.headers.get(
        "X-Request-ID"
    )
    assert request_id is not None

    # Must be a valid UUID
    parsed = uuid.UUID(request_id)
    assert str(parsed) == request_id.lower()


def test_existing_request_id_propagated():
    """If client sends X-Request-ID, it is echoed back unchanged."""
    client = TestClient(_make_app())
    sent_id = "my-custom-request-id-abc"
    response = client.get("/ping", headers={"X-Request-ID": sent_id})

    returned_id = response.headers.get("x-request-id") or response.headers.get(
        "X-Request-ID"
    )
    assert returned_id == sent_id


def test_different_requests_get_different_ids():
    """Two requests without X-Request-ID should receive different IDs."""
    client = TestClient(_make_app())
    r1 = client.get("/ping")
    r2 = client.get("/ping")

    id1 = r1.headers.get("x-request-id") or r1.headers.get("X-Request-ID")
    id2 = r2.headers.get("x-request-id") or r2.headers.get("X-Request-ID")
    assert id1 != id2


def test_request_id_valid_uuid_format():
    """Auto-generated request IDs should be valid UUID4 strings."""
    client = TestClient(_make_app())
    response = client.get("/ping")

    request_id = response.headers.get("x-request-id") or response.headers.get(
        "X-Request-ID"
    )
    # Should not raise
    parsed = uuid.UUID(str(request_id))
    assert parsed.version == 4


def test_bind_log_context_called(mocker):
    """bind_log_context is called with request_id, path, and method."""
    mock_bind = mocker.patch(
        "backend.app.middleware.request_id_middleware.bind_log_context"
    )

    client = TestClient(_make_app())
    client.get("/ping")

    mock_bind.assert_called_once()
    call_kwargs = mock_bind.call_args.kwargs
    assert "request_id" in call_kwargs
    assert call_kwargs["path"] == "/ping"
    assert call_kwargs["method"] == "GET"
