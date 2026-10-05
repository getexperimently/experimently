"""The API reference pages render: their Content-Security-Policy lets them load (#817).

`SecurityHeadersMiddleware` used to send `default-src 'none'` on every
response, so `/api/v1/docs` (Swagger UI) and `/api/v1/redoc` loaded no script
and showed a blank page. The two pages now get `DOCS_CSP`, matched by exact
path; every other response keeps `default-src 'none'; frame-ancestors 'none'`.
"""

from __future__ import annotations

import base64
import hashlib
import re

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.middleware.security_middleware import API_CSP, DOCS_CSP, DOCS_PATHS

pytestmark = [pytest.mark.unit, pytest.mark.regression]

STRICT = "default-src 'none'; frame-ancestors 'none'"

# Inline <script> blocks only: no src attribute.
_INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)
_SCRIPT_SRC = re.compile(r"<script[^>]*\bsrc=\"([^\"]+)\"", re.I)
_LINK_HREF = re.compile(r"<link[^>]*\bhref=\"([^\"]+)\"", re.I)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _directives(policy: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for part in policy.split(";"):
        name, *values = part.split()
        out[name] = values
    return out


def _sha256(source: str) -> str:
    return (
        "'sha256-"
        + base64.b64encode(hashlib.sha256(source.encode()).digest()).decode()
        + "'"
    )


def _origin(url: str) -> str:
    return "/".join(url.split("/")[:3])


def test_the_docs_paths_are_exactly_the_two_pages():
    assert DOCS_PATHS == frozenset({"/api/v1/docs", "/api/v1/redoc"})
    assert API_CSP == STRICT


@pytest.mark.parametrize("path", ["/api/v1/docs", "/api/v1/redoc"])
def test_docs_page_carries_the_docs_policy(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-security-policy"] == DOCS_CSP
    # The other headers are the API's, unchanged.
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("path", ["/api/v1/docs", "/api/v1/redoc"])
def test_every_inline_script_on_the_page_is_hashed_in_script_src(client, path):
    """Recomputes the hash from the served body: a FastAPI template change fails here."""
    body = client.get(path).text
    script_src = _directives(DOCS_CSP)["script-src"]
    inline = _INLINE_SCRIPT.findall(body)
    if path == "/api/v1/docs":
        # Swagger UI's initialiser; without it this test would check nothing.
        assert len(inline) == 1, inline
    for source in inline:
        assert _sha256(source) in script_src, (
            f"{path}: an inline script's hash {_sha256(source)} is not in DOCS_CSP's "
            "script-src; update SWAGGER_INIT_SCRIPT_SHA256 in security_middleware.py"
        )


@pytest.mark.parametrize("path", ["/api/v1/docs", "/api/v1/redoc"])
def test_every_external_asset_origin_is_allowed(client, path):
    body = client.get(path).text
    policy = _directives(DOCS_CSP)
    for url in _SCRIPT_SRC.findall(body):
        assert _origin(url) in policy["script-src"], url
    for url in _LINK_HREF.findall(body):
        if url.startswith("http"):
            assert _origin(url) in policy["style-src"] + policy["img-src"], url


def test_the_docs_policy_allows_no_inline_or_eval_script():
    script_src = _directives(DOCS_CSP)["script-src"]
    assert "'unsafe-inline'" not in script_src
    assert "'unsafe-eval'" not in script_src
    assert _directives(DOCS_CSP)["default-src"] == ["'none'"]
    assert _directives(DOCS_CSP)["frame-ancestors"] == ["'none'"]


def test_the_docs_policy_names_only_the_origins_the_pages_load():
    """Each origin was seen loading in a browser; a new one is a deliberate change."""
    origins = {
        value
        for values in _directives(DOCS_CSP).values()
        for value in values
        if value.startswith("https://")
    }
    assert origins == {
        "https://cdn.jsdelivr.net",  # Swagger UI and ReDoc script and stylesheet
        "https://fonts.googleapis.com",  # ReDoc's font stylesheet
        "https://fonts.gstatic.com",  # its font files
        "https://fastapi.tiangolo.com",  # FastAPI's favicon
        "https://cdn.redoc.ly",  # ReDoc's footer logo, requested by its script
    }


@pytest.mark.parametrize(
    "path",
    [
        "/health",
        "/api/v1/experiments",  # 401 without credentials; the header is what matters
        "/api/v1/openapi.json",
        "/api/v1/no-such-route",
        "/api/v1/docs/",
        "/api/v1/docsx",
        "/api/v1/redoc/x",
        "/api/v1/redocs",
        "/docs",
        "/redoc",
    ],
)
def test_every_other_path_keeps_the_strict_policy(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.headers["content-security-policy"] == STRICT, (
        f"{path} answered {response.status_code} with "
        f"{response.headers.get('content-security-policy')!r}"
    )
