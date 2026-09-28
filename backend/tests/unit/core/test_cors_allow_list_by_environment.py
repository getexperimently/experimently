"""Which browser origins the API allows, by environment (#130).

Development and test keep the localhost defaults when neither CORS setting is
given, so a local dashboard and the demo apps work out of the box (and CI's
cross-origin sign-in job, which runs with ENVIRONMENT=test, keeps working).
Staging and production allow no other origin unless one is configured: their
dashboard is served from the API's own origin and needs none. A configured
DASHBOARD_ORIGINS entry is always allowed. Credentials are never allowed
cross-origin, whatever the list says.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.middleware.cors import CORSMiddleware

from backend.app.core.config import (
    DEFAULT_CORS_ORIGINS,
    DevSettings,
    ProdSettings,
    TestSettings,
    cors_start_up_messages,
    dashboard_origins_warning,
)

pytestmark = [pytest.mark.unit]

PROD_SECRET = "p" * 64

LOCALHOST_DEFAULTS = [
    "http://localhost:3100",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3200",
    "http://localhost:3300",
]


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    # TESTING: the suite exports it, and Settings refuses it with a staging or
    # production environment, which `_hardened` builds.
    for name in (
        "BACKEND_CORS_ORIGINS",
        "CORS_ORIGINS",
        "DASHBOARD_ORIGINS",
        "PUBLIC_BASE_URL",
        "ALLOWED_HOSTS",
        "TESTING",
    ):
        monkeypatch.delenv(name, raising=False)


def _hardened(environment: str = "production", **kwargs) -> ProdSettings:
    return ProdSettings(
        ENVIRONMENT=environment,
        SECRET_KEY=PROD_SECRET,
        FIRST_SUPERUSER_PASSWORD="Str0ng-first-admin",
        PUBLIC_BASE_URL=kwargs.pop("PUBLIC_BASE_URL", "https://app.example.com"),
        _env_file=None,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Nothing configured
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize("environment", ["staging", "production"])
def test_a_staging_or_production_api_allows_no_origin_it_was_not_given(environment):
    assert _hardened(environment).cors_allowed_origins == []


def test_the_localhost_defaults_are_the_five_local_apps():
    assert list(DEFAULT_CORS_ORIGINS) == LOCALHOST_DEFAULTS


def test_test_keeps_the_local_defaults():
    assert TestSettings(_env_file=None).cors_allowed_origins == LOCALHOST_DEFAULTS


def test_development_keeps_its_own_defaults():
    # DevSettings sets CORS_ORIGINS itself: the five apps plus the API's port.
    assert DevSettings(_env_file=None).cors_allowed_origins == [
        *LOCALHOST_DEFAULTS,
        "http://localhost:8000",
    ]


def test_development_with_the_setting_emptied_falls_back_to_the_defaults():
    settings = DevSettings(CORS_ORIGINS="", _env_file=None)
    assert settings.cors_allowed_origins == LOCALHOST_DEFAULTS


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_public_base_url_is_not_added(environment):
    settings = _hardened(environment, PUBLIC_BASE_URL="https://api.example.com")
    assert settings.cors_allowed_origins == []


# ---------------------------------------------------------------------------
# Configured
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_a_configured_origin_is_the_whole_list(environment):
    settings = _hardened(environment, CORS_ORIGINS="https://shop.example.com")
    assert settings.cors_allowed_origins == ["https://shop.example.com"]


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_a_dashboard_on_its_own_host_is_allowed(environment):
    settings = _hardened(
        environment,
        PUBLIC_BASE_URL="https://api.staging.example.com",
        DASHBOARD_ORIGINS="https://app.staging.example.com",
    )
    assert settings.cors_allowed_origins == ["https://app.staging.example.com"]


def test_dashboard_origins_are_added_after_cors_origins_once_each():
    settings = _hardened(
        CORS_ORIGINS="https://shop.example.com,https://app.example.com",
        DASHBOARD_ORIGINS="https://app.example.com,https://admin.example.com",
    )
    assert settings.cors_allowed_origins == [
        "https://shop.example.com",
        "https://app.example.com",
        "https://admin.example.com",
    ]


def test_dashboard_origins_are_added_in_test_too():
    settings = TestSettings(DASHBOARD_ORIGINS="http://localhost:4000", _env_file=None)
    assert settings.cors_allowed_origins == [
        *LOCALHOST_DEFAULTS,
        "http://localhost:4000",
    ]


def test_a_wildcard_in_dashboard_origins_is_not_added():
    settings = _hardened(DASHBOARD_ORIGINS="*")
    assert settings.cors_allowed_origins == []


@pytest.mark.parametrize(
    "env",
    [
        {"CORS_ORIGINS": "*"},
        {"CORS_ORIGINS": " * "},
        {"BACKEND_CORS_ORIGINS": '["*"]'},
        {"BACKEND_CORS_ORIGINS": '["https://app.example.com", "*"]'},
        {"BACKEND_CORS_ORIGINS": '["not a url"]', "CORS_ORIGINS": "*"},
    ],
)
def test_a_wildcard_however_spelled_is_kept(monkeypatch, env):
    """Kept, not refused: the start-up WARNING below names it."""
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert "*" in _hardened().cors_allowed_origins


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_credentials_are_never_allowed_cross_origin():
    from backend.app.main import app

    (cors,) = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert cors.kwargs["allow_credentials"] is False, cors.kwargs


# ---------------------------------------------------------------------------
# What the operator is told at start-up
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_start_up_names_an_empty_list(environment):
    assert cors_start_up_messages(_hardened(environment)) == [
        (
            logging.INFO,
            f"CORS allow-list ({environment}): none: same-origin only. To let a "
            "site on another origin call this API from a browser, add its "
            "origin to CORS_ORIGINS.",
        )
    ]


def test_start_up_names_the_effective_list():
    settings = _hardened(
        CORS_ORIGINS="https://shop.example.com",
        DASHBOARD_ORIGINS="https://app.example.com",
    )
    assert cors_start_up_messages(settings) == [
        (
            logging.INFO,
            "CORS allow-list (production): https://shop.example.com, "
            "https://app.example.com. To let a site on another origin call this "
            "API from a browser, add its origin to CORS_ORIGINS.",
        )
    ]


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_start_up_warns_about_a_wildcard(environment):
    messages = cors_start_up_messages(_hardened(environment, CORS_ORIGINS="*"))
    assert [level for level, _ in messages] == [logging.INFO, logging.WARNING]
    assert messages[1][1] == (
        "The CORS allow-list contains '*', so every website can call this API "
        "from a browser (without credentials, which are never allowed "
        "cross-origin). List the sites that need access in CORS_ORIGINS instead."
    )


@pytest.mark.parametrize(
    "settings",
    [
        lambda: DevSettings(CORS_ORIGINS="*", _env_file=None),
        lambda: TestSettings(_env_file=None),
    ],
    ids=["development", "test"],
)
def test_development_and_test_log_nothing(settings):
    assert cors_start_up_messages(settings()) == []


# ---------------------------------------------------------------------------
# The `api.` host with no DASHBOARD_ORIGINS
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_the_api_host_warning_names_both_settings(environment):
    message = dashboard_origins_warning(
        _hardened(environment, PUBLIC_BASE_URL="https://api.example.com")
    )
    assert message == (
        "PUBLIC_BASE_URL=https://api.example.com looks like the API's own origin "
        "and DASHBOARD_ORIGINS is empty, so no dashboard origin is known: SSO "
        "sign-in from the dashboard will be refused (400), and a browser refuses "
        "the dashboard's API calls unless its origin is in CORS_ORIGINS. Set "
        "DASHBOARD_ORIGINS to the dashboard's origin, e.g. https://app.example.com "
        "(it is added to the CORS allow-list too), or at least add that origin "
        "to CORS_ORIGINS."
    )
