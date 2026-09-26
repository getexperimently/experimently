"""A failed OIDC token exchange or userinfo call tells the browser nothing about it.

The callback is reachable by anyone: an unauthenticated caller can start a login
for a state and then call back with a garbage code. The failure used to be
answered with the exception's text -- the identity provider's
``error_description`` verbatim, the token URL, connection errors naming internal
hosts, and, from a provider that echoes the request's ``Authorization`` header
into its error, the Basic credentials. Now the answer is a fixed message plus at
most the provider's standard OAuth ``error`` code.

Driven against a real HTTP server standing in for the provider, through the
``requests`` branch and, where authlib is installed (the full image and CI's
Module Tests), the authlib branch the image runs.
"""

from __future__ import annotations

import http.server
import json
import threading
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from modules.backend.app.models.sso_config import SSOConfig, SSOProviderType
from modules.backend.app.services import sso_service

pytestmark = [pytest.mark.unit, pytest.mark.regression]

MARKER = "MARKER-must-not-reach-the-browser"


class _Provider(http.server.BaseHTTPRequestHandler):
    """Every call fails; the failure text carries the marker and the credentials."""

    mode = "error"

    def _fail(self):
        echoed = self.headers.get("Authorization", "")
        if self.mode == "error":
            body = json.dumps(
                {
                    "error": "invalid_grant",
                    "error_description": f"{MARKER} request had {echoed} at {self.path}",
                }
            ).encode()
            self.send_response(400)
        elif self.mode == "bad-code":
            body = json.dumps({"error": f"<script>{MARKER}</script>"}).encode()
            self.send_response(400)
        elif self.mode == "redirect":
            body = b""
            self.send_response(307)
            self.send_header("Location", "http://127.0.0.1:1/elsewhere")
        else:  # a server error with a free-text body
            body = f"{MARKER} internal failure {echoed}".encode()
            self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_POST = _fail
    do_GET = _fail

    def log_message(self, *args):  # keep test output quiet
        pass


@pytest.fixture
def provider():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()


def _config(server) -> SSOConfig:
    cfg = MagicMock(spec=SSOConfig)
    cfg.provider_type = SSOProviderType.OKTA
    cfg.entity_id = "client-id"
    cfg.client_secret = "client-secret-value"
    cfg.sso_url = f"http://127.0.0.1:{server.server_port}"
    return cfg


BRANCHES = [
    pytest.param(False, id="requests"),
    pytest.param(True, id="authlib"),
]


def _branch(monkeypatch, use_authlib):
    if use_authlib:
        pytest.importorskip("authlib")
        if not sso_service._AUTHLIB_AVAILABLE:
            pytest.skip("authlib not importable by the service")
    else:
        monkeypatch.setattr(sso_service, "_AUTHLIB_AVAILABLE", False)


def _refusal(coroutine) -> HTTPException:
    import asyncio

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(coroutine)
    return excinfo.value


def _assert_opaque(detail: str, server) -> None:
    assert MARKER not in detail, detail
    assert "Basic " not in detail and "client-secret-value" not in detail, detail
    assert str(server.server_port) not in detail, (
        f"the provider's address leaked: {detail}"
    )


@pytest.mark.parametrize("use_authlib", BRANCHES)
@pytest.mark.parametrize("mode", ["error", "server-error"])
def test_a_failed_exchange_is_reported_without_its_text(
    provider, monkeypatch, use_authlib, mode
):
    _branch(monkeypatch, use_authlib)
    _Provider.mode = mode
    refusal = _refusal(
        sso_service.exchange_oidc_code(
            _config(provider), "garbage-code", "https://app/cb", code_verifier="v" * 43
        )
    )
    assert refusal.status_code == 400
    _assert_opaque(refusal.detail, provider)
    assert refusal.detail.startswith("OIDC token exchange failed")
    if mode == "error":
        assert refusal.detail == "OIDC token exchange failed (invalid_grant)"


@pytest.mark.parametrize("use_authlib", BRANCHES)
def test_an_error_code_that_is_not_one_is_dropped(provider, monkeypatch, use_authlib):
    _branch(monkeypatch, use_authlib)
    _Provider.mode = "bad-code"
    refusal = _refusal(
        sso_service.exchange_oidc_code(
            _config(provider), "garbage-code", "https://app/cb", code_verifier="v" * 43
        )
    )
    assert refusal.detail == "OIDC token exchange failed"


def test_the_token_request_does_not_follow_a_redirect(provider, monkeypatch):
    """A redirected POST would re-send the client secret to wherever it points."""
    _branch(monkeypatch, False)
    _Provider.mode = "redirect"
    refusal = _refusal(
        sso_service.exchange_oidc_code(
            _config(provider), "garbage-code", "https://app/cb", code_verifier="v" * 43
        )
    )
    assert refusal.detail == "OIDC token exchange failed"


@pytest.mark.parametrize("use_authlib", BRANCHES)
@pytest.mark.parametrize("mode", ["error", "server-error"])
def test_a_failed_userinfo_call_is_reported_without_its_text(
    provider, monkeypatch, use_authlib, mode
):
    _branch(monkeypatch, use_authlib)
    _Provider.mode = mode
    refusal = _refusal(
        sso_service.get_oidc_user_info(_config(provider), "an-access-token")
    )
    assert refusal.status_code == 400
    _assert_opaque(refusal.detail, provider)
    assert refusal.detail.startswith("OIDC userinfo fetch failed")


def test_an_unreachable_provider_is_not_named(monkeypatch):
    _branch(monkeypatch, False)
    cfg = MagicMock(spec=SSOConfig)
    cfg.provider_type = SSOProviderType.OKTA
    cfg.entity_id = "client-id"
    cfg.client_secret = "client-secret-value"
    cfg.sso_url = "http://127.0.0.1:1"
    refusal = _refusal(
        sso_service.exchange_oidc_code(
            cfg, "code", "https://app/cb", code_verifier="v" * 43
        )
    )
    assert refusal.detail == "OIDC token exchange failed"
