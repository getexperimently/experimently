"""`Settings.dashboard_origins`: where an SSO sign-in may send the browser back.

C2b spec-v3 §2: the dashboard's origins are not the CORS list (that one also
names the demo apps and any site running an SDK). They are `DASHBOARD_ORIGINS`,
then `PUBLIC_BASE_URL`'s origin, then -- in development only -- the two
localhost dashboards; normalised with `normalise_origin`. The primary one is
the first `DASHBOARD_ORIGINS` entry, else `PUBLIC_BASE_URL`'s origin.
"""

from __future__ import annotations

import pytest

from backend.app.core import config
from backend.app.core.config import (
    DevSettings,
    ProdSettings,
    TestSettings,
    dashboard_origins_warning,
)

pytestmark = [pytest.mark.unit]

PROD_SECRET = "p" * 64


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    for name in ("DASHBOARD_ORIGINS", "PUBLIC_BASE_URL", "ALLOWED_HOSTS"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def logged(monkeypatch):
    """What config.py logs, by level. (The unit conftest patches getLogger, so
    caplog sees nothing; the existing CORS tests capture the same way.)"""
    lines = {"error": [], "warning": []}
    for level in lines:
        monkeypatch.setattr(
            config.logger,
            level,
            lambda msg, *args, _level=level: lines[_level].append(msg % args),
        )
    return lines


def _prod(**kwargs):
    return ProdSettings(
        ENVIRONMENT=kwargs.pop("ENVIRONMENT", "production"),
        SECRET_KEY=PROD_SECRET,
        _env_file=None,
        **kwargs,
    )


def test_development_accepts_the_two_local_dashboards_and_nothing_else():
    s = DevSettings(_env_file=None)
    assert s.dashboard_origins == ["http://localhost:3000", "http://localhost:3100"]
    assert s.primary_dashboard_origin is None
    # The demo apps are CORS origins, never dashboard origins.
    assert "http://localhost:3200" in s.cors_allowed_origins
    assert "http://localhost:3200" not in s.dashboard_origins


@pytest.mark.parametrize("environment", ["test", "staging", "production"])
def test_no_default_dashboard_origin_outside_development(environment):
    s = (
        TestSettings(_env_file=None)
        if environment == "test"
        else _prod(ENVIRONMENT=environment, PUBLIC_BASE_URL=None, ALLOWED_HOSTS=["x"])
    )
    assert s.dashboard_origins == []
    assert s.primary_dashboard_origin is None


def test_public_base_url_is_a_dashboard_origin_and_the_primary_one():
    s = TestSettings(PUBLIC_BASE_URL="https://App.Example.com/", _env_file=None)
    assert s.dashboard_origins == ["https://app.example.com"]
    assert s.primary_dashboard_origin == "https://app.example.com"


def test_the_first_dashboard_origins_entry_is_primary():
    s = TestSettings(
        PUBLIC_BASE_URL="https://api.example.com",
        DASHBOARD_ORIGINS="https://app.example.com/, https://other.example.com:8443",
        _env_file=None,
    )
    assert s.dashboard_origins == [
        "https://app.example.com",
        "https://other.example.com:8443",
        "https://api.example.com",
    ]
    assert s.primary_dashboard_origin == "https://app.example.com"


def test_dashboard_origins_takes_a_json_array():
    s = TestSettings(DASHBOARD_ORIGINS='["https://app.example.com"]', _env_file=None)
    assert s.dashboard_origins == ["https://app.example.com"]


@pytest.mark.parametrize(
    "value",
    ["*", "https://app.example.com/path", "app.example.com", "https://a.example.com?x"],
)
def test_an_entry_that_is_not_an_origin_is_dropped_with_an_error(value, logged):
    s = TestSettings(DASHBOARD_ORIGINS=value, _env_file=None)
    assert s.dashboard_origins == []
    assert any("DASHBOARD_ORIGINS entry" in line for line in logged["error"])


def test_malformed_json_does_not_stop_the_settings_loading(logged):
    s = TestSettings(DASHBOARD_ORIGINS="[not json", _env_file=None)
    assert s.dashboard_origins == []
    assert any("not valid JSON" in line for line in logged["error"])


# ---------------------------------------------------------------------------
# EM3: the startup warning for the `api.` hedge
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize("environment", ["staging", "production"])
def test_an_api_host_with_no_dashboard_origins_warns_at_startup(environment, logged):
    _prod(ENVIRONMENT=environment, PUBLIC_BASE_URL="https://api.example.com")
    warnings = [w for w in logged["warning"] if "DASHBOARD_ORIGINS is empty" in w]
    assert len(warnings) == 1, logged


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "PUBLIC_BASE_URL": "https://api.example.com",
            "DASHBOARD_ORIGINS": "https://app.example.com",
        },
        {"PUBLIC_BASE_URL": "https://app.example.com"},
        {"PUBLIC_BASE_URL": "https://apiary.example.com"},
    ],
)
def test_no_warning_when_the_dashboard_origin_is_known(kwargs, logged):
    s = _prod(**kwargs)
    assert dashboard_origins_warning(s) is None
    assert not any("DASHBOARD_ORIGINS is empty" in w for w in logged["warning"])


@pytest.mark.parametrize("cls", [DevSettings, TestSettings])
def test_no_warning_outside_staging_and_production(cls, logged):
    s = cls(PUBLIC_BASE_URL="https://api.example.com", _env_file=None)
    assert dashboard_origins_warning(s) is None
    assert not any("DASHBOARD_ORIGINS is empty" in w for w in logged["warning"])
