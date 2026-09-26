"""The CORS allow-list is a list of origins as a browser sends them (#126).

`BACKEND_CORS_ORIGINS` was `List[AnyHttpUrl]`, which renders every entry with
a trailing slash (`http://localhost:3000/`). Starlette compares `Origin`
exactly, and no browser sends the slash, so the setting matched nothing. One
malformed entry also failed validation and stopped the API starting.

Every other input keeps today's output exactly: these tests pin it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.app.core.config import (
    DEFAULT_CORS_ORIGINS,
    DevSettings,
    ProdSettings,
    Settings,
    TestSettings,
    normalise_origin,
)

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[4]


def _today(settings) -> list:
    """main.py's derivation before this change, for the inputs that worked."""
    origins = [str(o) for o in settings.BACKEND_CORS_ORIGINS]
    if not origins:
        origins = [o for o in settings.CORS_ORIGINS if o]
    if not origins:
        origins = list(DEFAULT_CORS_ORIGINS)
    return origins


@pytest.fixture(autouse=True)
def _no_cors_env(monkeypatch):
    for name in ("BACKEND_CORS_ORIGINS", "CORS_ORIGINS"):
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# normalise_origin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("http://localhost:3000", "http://localhost:3000"),
        ("http://localhost:3000/", "http://localhost:3000"),
        ("  https://App.Example.COM  ", "https://app.example.com"),
        ("https://app.example.com:443", "https://app.example.com"),
        ("http://app.example.com:80/", "http://app.example.com"),
        ("https://app.example.com:8443", "https://app.example.com:8443"),
        ("HTTP://X:80", "http://x"),
        ("*", "*"),
    ],
)
def test_an_origin_is_normalised_to_what_a_browser_sends(value, expected):
    assert normalise_origin(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "localhost:3000",
        "ftp://example.com",
        "https://",
        "https://app.example.com/path",
        "https://app.example.com/?q=1",
        "https://app.example.com/#x",
        "https://user@app.example.com",
        "https://user:pw@app.example.com",
        "https://app.example.com:notaport",
        "https://app.example.com:99999",
        "https://app .example.com",
        None,
    ],
)
def test_anything_else_is_not_an_origin(value):
    assert normalise_origin(value) is None


# ---------------------------------------------------------------------------
# The allow-list: unchanged where it worked, fixed where it did not
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cls", [DevSettings, TestSettings, ProdSettings])
def test_with_neither_setting_the_output_is_unchanged(cls):
    settings = cls.model_construct()
    settings.BACKEND_CORS_ORIGINS = []
    settings.CORS_ORIGINS = cls.model_fields["CORS_ORIGINS"].default
    assert settings.cors_allowed_origins == _today(settings)


@pytest.mark.parametrize(
    "raw",
    [
        "http://localhost:3100,http://localhost:3200",
        "*",
        # .env.example and docker-compose.yml's defaults, verbatim
        "http://localhost:3100,http://localhost:3200,http://localhost:3300,http://localhost:8000",
        "http://localhost:3000,http://localhost:3100,http://localhost:3200,http://localhost:3300",
    ],
)
def test_cors_origins_output_is_unchanged(monkeypatch, raw):
    monkeypatch.setenv("CORS_ORIGINS", raw)
    settings = Settings(_env_file=None)
    assert settings.cors_allowed_origins == _today(settings)


@pytest.mark.regression
def test_backend_cors_origins_entries_lose_the_trailing_slash(monkeypatch):
    monkeypatch.setenv(
        "BACKEND_CORS_ORIGINS",
        '["http://localhost:3000/", "https://App.Example.com:443"]',
    )
    settings = Settings(_env_file=None)
    assert settings.cors_allowed_origins == [
        "http://localhost:3000",
        "https://app.example.com",
    ]


def test_backend_cors_origins_takes_the_comma_form_too(monkeypatch):
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", "http://a.example, http://b.example")
    assert Settings(_env_file=None).cors_allowed_origins == [
        "http://a.example",
        "http://b.example",
    ]


def test_an_entry_that_is_not_an_origin_is_dropped_with_an_error(monkeypatch):
    from backend.app.core import config

    errors = []
    monkeypatch.setattr(
        config.logger, "error", lambda msg, *args: errors.append(msg % args)
    )
    monkeypatch.setenv(
        "CORS_ORIGINS", "http://localhost:3100,https://app.example.com/dashboard"
    )
    origins = Settings(_env_file=None).cors_allowed_origins
    assert origins == ["http://localhost:3100"]
    assert any("not an origin" in e and "/dashboard" in e for e in errors), errors


def test_a_list_of_only_bad_entries_falls_through_as_if_unset(monkeypatch):
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", '["not a url"]')
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3200")
    assert Settings(_env_file=None).cors_allowed_origins == ["http://localhost:3200"]


def test_main_passes_the_normalised_list_to_cors():
    from backend.app import main
    from backend.app.core.config import settings

    assert main.cors_origins == settings.cors_allowed_origins


# ---------------------------------------------------------------------------
# Through the real app, in a fresh process (main.py reads settings at import)
# ---------------------------------------------------------------------------

_PROBE = """
import json, sys
from fastapi.testclient import TestClient
from backend.app.main import app
client = TestClient(app)
out = {"live": client.get("/health/live").status_code}
for origin in json.loads(sys.argv[1]):
    r = client.options("/api/v1/experiments/", headers={
        "Origin": origin, "Access-Control-Request-Method": "GET"})
    out[origin] = r.headers.get("access-control-allow-origin")
print("RESULT " + json.dumps(out))
"""


def _probe(env_extra: dict, origins: list) -> dict:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("BACKEND_CORS_ORIGINS", "CORS_ORIGINS")
    }
    env.update({"APP_ENV": "test", "TESTING": "true", "ENVIRONMENT": "test"})
    env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, json.dumps(origins)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    line = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    assert line, f"probe failed (exit {proc.returncode}):\n{proc.stderr[-3000:]}"
    return json.loads(line[-1][len("RESULT ") :])


@pytest.mark.regression
def test_a_backend_cors_origins_entry_with_a_slash_gets_allow_origin():
    result = _probe(
        {"BACKEND_CORS_ORIGINS": '["http://localhost:3000/"]'},
        ["http://localhost:3000", "http://localhost:3999"],
    )
    assert result["http://localhost:3000"] == "http://localhost:3000"
    assert result["http://localhost:3999"] is None


def test_a_malformed_entry_does_not_stop_the_api_starting():
    result = _probe(
        {"BACKEND_CORS_ORIGINS": '["::not a url::", "http://localhost:3000"]'},
        ["http://localhost:3000"],
    )
    assert result["live"] == 200  # liveness: the app started; needs no database
    assert result["http://localhost:3000"] == "http://localhost:3000"
