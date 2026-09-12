"""
Unit tests for ``ENVIRONMENT`` canonicalisation and the auth-provider settings
(P0 open-core: backend/app/core/config.py).

Covers:
- canonical values, legacy ``dev``/``prod`` aliases (with DeprecationWarning),
  rejection of unknown values
- ``APP_ENV`` fallback and ``ENVIRONMENT`` precedence for the singleton
  selection (run in a subprocess so the module import is fresh)
- ``AUTH_PROVIDER`` / ``DEV_AUTH_BYPASS`` defaults and the production guard
- the ``dev_auth_bypass_active`` helper in ``deps``
"""

import os
import subprocess
import sys
import warnings
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from backend.app.core.config import (
    BYPASS_ALLOWED_ENVIRONMENTS,
    CANONICAL_ENVIRONMENTS,
    DevSettings,
    ProdSettings,
    Settings,
    TestSettings,
    canonical_environment,
    resolve_environment_from_process_env,
)

pytestmark = pytest.mark.unit

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))


def _clean_env(**overrides):
    """Environment for subprocess checks: no ENVIRONMENT/APP_ENV unless given."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("ENVIRONMENT", "APP_ENV", "DEV_AUTH_BYPASS", "TESTING", "SECRET_KEY")
    }
    env["PYTHONPATH"] = REPO_ROOT
    env.update(overrides)
    return env


def _run(code: str, **env_overrides) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=_clean_env(**env_overrides),
        capture_output=True,
        text=True,
        timeout=120,
    )


# ---------------------------------------------------------------------------
# canonical_environment
# ---------------------------------------------------------------------------


class TestCanonicalEnvironment:
    @pytest.mark.parametrize("value", CANONICAL_ENVIRONMENTS)
    def test_canonical_values_pass_through_without_warning(self, value):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert canonical_environment(value) == value

    @pytest.mark.parametrize("legacy,expected", [("dev", "development"), ("prod", "production")])
    def test_legacy_aliases_map_with_deprecation_warning(self, legacy, expected):
        with pytest.warns(DeprecationWarning, match="deprecated"):
            assert canonical_environment(legacy) == expected

    @pytest.mark.parametrize(
        "raw,expected", [("  Development ", "development"), ("PROD", "production")]
    )
    def test_whitespace_and_case_are_normalised(self, raw, expected):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            assert canonical_environment(raw) == expected

    def test_non_string_is_returned_unchanged(self):
        assert canonical_environment(None) is None
        assert canonical_environment(3) == 3

    def test_canonical_set_matches_contract(self):
        assert set(CANONICAL_ENVIRONMENTS) == {"development", "test", "staging", "production"}
        assert set(BYPASS_ALLOWED_ENVIRONMENTS) == {"development", "test"}


# ---------------------------------------------------------------------------
# Settings.ENVIRONMENT field
# ---------------------------------------------------------------------------


class TestSettingsEnvironmentField:
    def test_default_is_development(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ENVIRONMENT", None)
            assert Settings(_env_file=None).ENVIRONMENT == "development"

    @pytest.mark.parametrize("value", CANONICAL_ENVIRONMENTS)
    def test_accepts_every_canonical_value(self, value):
        assert Settings(_env_file=None, ENVIRONMENT=value).ENVIRONMENT == value

    def test_legacy_prod_kwarg_is_canonicalised(self):
        with pytest.warns(DeprecationWarning):
            s = Settings(_env_file=None, ENVIRONMENT="prod")
        assert s.ENVIRONMENT == "production"
        assert s.is_production is True

    def test_legacy_dev_kwarg_is_canonicalised(self):
        with pytest.warns(DeprecationWarning):
            s = Settings(_env_file=None, ENVIRONMENT="dev")
        assert s.ENVIRONMENT == "development"
        assert s.is_development is True

    def test_unknown_value_is_rejected(self):
        with pytest.raises(ValidationError, match="development"):
            Settings(_env_file=None, ENVIRONMENT="bogus")

    def test_legacy_env_var_is_canonicalised(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "prod"}):
            with pytest.warns(DeprecationWarning):
                s = Settings(_env_file=None)
        assert s.ENVIRONMENT == "production"

    def test_subclass_defaults_are_canonical(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ENVIRONMENT", None)
            assert DevSettings(_env_file=None).ENVIRONMENT == "development"
            assert TestSettings(_env_file=None).ENVIRONMENT == "test"
            assert (
                ProdSettings(
                    _env_file=None, SECRET_KEY="a" * 64, FIRST_SUPERUSER_PASSWORD="StrongProd1!"
                ).ENVIRONMENT
                == "production"
            )

    def test_production_validators_still_fire_on_canonical_value(self, monkeypatch):
        monkeypatch.delenv("TESTING", raising=False)
        with pytest.raises(ValidationError, match="SECRET_KEY"):
            Settings(_env_file=None, ENVIRONMENT="production", SECRET_KEY="changeme")

    def test_production_validators_fire_on_legacy_prod_value(self, monkeypatch):
        monkeypatch.delenv("TESTING", raising=False)
        with pytest.warns(DeprecationWarning):
            with pytest.raises(ValidationError, match="SECRET_KEY"):
                Settings(_env_file=None, ENVIRONMENT="prod", SECRET_KEY="changeme")

    def test_helper_properties(self):
        assert Settings(_env_file=None, ENVIRONMENT="test").is_test
        assert Settings(_env_file=None, ENVIRONMENT="staging").is_staging

    def test_demo_alias_maps_to_development(self):
        """demo/setup-aws.sh and the CDK demo stack run with APP_ENV=demo."""
        with pytest.warns(DeprecationWarning):
            assert Settings(_env_file=None, ENVIRONMENT="demo").ENVIRONMENT == "development"


# ---------------------------------------------------------------------------
# Placeholder secrets are refused in staging as well as production
# ---------------------------------------------------------------------------

_STRONG = {
    "SECRET_KEY": "b" * 64,
    "AUDIT_HMAC_KEY": "c" * 64,
    "SSO_STATE_SECRET": "d" * 64,
    "FIRST_SUPERUSER_PASSWORD": "Str0ng-Passw0rd",
}

# The values that ship in the repository: class defaults, docker-compose.yml,
# .env.example, the demo seed password.
_COMMITTED_PLACEHOLDERS = [
    ("SECRET_KEY", "default-secret-key-for-testing"),
    ("SECRET_KEY", "dev-only-change-me-9f1c7b2e4a6d8e0f1a2b3c4d5e6f7a8b"),
    ("SECRET_KEY", "development_secret_key_change_in_production"),
    ("SECRET_KEY", "DEV-ONLY-" + "x" * 60),
    ("AUDIT_HMAC_KEY", "dev-audit-key-change-in-production"),
    ("SSO_STATE_SECRET", "sso-state-secret-change-in-prod"),
    ("FIRST_SUPERUSER_PASSWORD", "Demo1234!"),
    ("FIRST_SUPERUSER_PASSWORD", "admin"),
]


class TestHardenedSecrets:
    @pytest.mark.parametrize("env", ["staging", "production"])
    @pytest.mark.parametrize("field,value", _COMMITTED_PLACEHOLDERS)
    def test_committed_placeholders_are_refused(self, env, field, value, monkeypatch):
        monkeypatch.delenv("TESTING", raising=False)
        kwargs = dict(_STRONG, ENVIRONMENT=env)
        kwargs[field] = value
        with pytest.raises(ValidationError, match=field):
            Settings(_env_file=None, **kwargs)

    @pytest.mark.parametrize("env", ["staging", "production"])
    def test_class_defaults_are_refused(self, env, monkeypatch):
        monkeypatch.delenv("TESTING", raising=False)
        with pytest.raises(ValidationError) as excinfo:
            Settings(_env_file=None, ENVIRONMENT=env)
        text = str(excinfo.value)
        for field in ("SECRET_KEY", "AUDIT_HMAC_KEY", "SSO_STATE_SECRET", "FIRST_SUPERUSER_PASSWORD"):
            assert field in text

    @pytest.mark.parametrize("env", ["staging", "production"])
    def test_real_secrets_are_accepted(self, env, monkeypatch):
        monkeypatch.delenv("TESTING", raising=False)
        assert Settings(_env_file=None, ENVIRONMENT=env, **_STRONG).ENVIRONMENT == env

    @pytest.mark.parametrize("env", ["development", "test"])
    def test_placeholders_are_fine_outside_hardened_environments(self, env, monkeypatch):
        monkeypatch.delenv("TESTING", raising=False)
        assert Settings(_env_file=None, ENVIRONMENT=env).ENVIRONMENT == env

    def test_testing_flag_relaxes_but_never_the_bypass_rule(self, monkeypatch):
        monkeypatch.setenv("TESTING", "true")
        Settings(_env_file=None, ENVIRONMENT="production")  # placeholders tolerated
        with pytest.raises(ValidationError, match="DEV_AUTH_BYPASS"):
            Settings(_env_file=None, ENVIRONMENT="production", DEV_AUTH_BYPASS=True)


# ---------------------------------------------------------------------------
# resolve_environment_from_process_env
# ---------------------------------------------------------------------------


class TestResolveFromProcessEnv:
    def test_defaults_to_development(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ENVIRONMENT", None)
            os.environ.pop("APP_ENV", None)
            assert resolve_environment_from_process_env() == "development"

    def test_app_env_fallback_warns(self):
        with patch.dict(os.environ, {"APP_ENV": "test"}, clear=False):
            os.environ.pop("ENVIRONMENT", None)
            with pytest.warns(DeprecationWarning, match="APP_ENV is deprecated"):
                assert resolve_environment_from_process_env() == "test"

    def test_app_env_prod_alias(self):
        with patch.dict(os.environ, {"APP_ENV": "prod"}, clear=False):
            os.environ.pop("ENVIRONMENT", None)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                assert resolve_environment_from_process_env() == "production"

    def test_environment_wins_over_app_env(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "staging", "APP_ENV": "test"}, clear=False):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                assert resolve_environment_from_process_env() == "staging"


# ---------------------------------------------------------------------------
# Module import (fresh interpreter): singleton selection + APP_ENV mirror
# ---------------------------------------------------------------------------


class TestModuleImportSelection:
    """Each case imports backend.app.core.config in a subprocess."""

    CODE = (
        "from backend.app.core.config import settings; import os; "
        "print(type(settings).__name__, settings.ENVIRONMENT, os.environ.get('APP_ENV'))"
    )

    def test_app_env_production_selects_prod_settings(self):
        proc = _run(self.CODE, APP_ENV="production", TESTING="true")
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.split() == ["ProdSettings", "production", "production"]

    def test_app_env_prod_legacy_alias(self):
        proc = _run(self.CODE, APP_ENV="prod", TESTING="true")
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.split()[:2] == ["ProdSettings", "production"]

    def test_app_env_test_selects_test_settings(self):
        proc = _run(self.CODE, APP_ENV="test", TESTING="true")
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.split() == ["TestSettings", "test", "test"]

    def test_environment_test_mirrors_app_env_for_legacy_readers(self):
        proc = _run(self.CODE, ENVIRONMENT="test", TESTING="true")
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.split() == ["TestSettings", "test", "test"]

    def test_environment_development_selects_dev_settings(self):
        proc = _run(self.CODE, ENVIRONMENT="development")
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.split() == ["DevSettings", "development", "dev"]

    def test_environment_staging_uses_prod_settings_but_keeps_name(self):
        proc = _run(self.CODE, ENVIRONMENT="staging", TESTING="true")
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.split()[:2] == ["ProdSettings", "staging"]

    def test_no_env_defaults_to_development(self):
        proc = _run(self.CODE)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.split()[:2] == ["DevSettings", "development"]

    def test_unknown_environment_refuses_to_import(self):
        proc = _run("import backend.app.core.config", ENVIRONMENT="bogus")
        assert proc.returncode != 0
        assert "development" in proc.stderr  # Literal error lists the allowed values

    def test_bypass_in_production_refuses_to_import(self):
        proc = _run(
            "import backend.app.core.config",
            ENVIRONMENT="production",
            DEV_AUTH_BYPASS="true",
            TESTING="true",  # disable the other prod validators: the bypass guard must fire on its own
        )
        assert proc.returncode != 0
        assert "DEV_AUTH_BYPASS" in proc.stderr

    def test_bypass_in_production_refuses_without_testing_too(self):
        proc = _run(
            "import backend.app.core.config", ENVIRONMENT="production", DEV_AUTH_BYPASS="true"
        )
        assert proc.returncode != 0

    def test_weak_secret_key_in_production_refuses_to_boot(self):
        proc = _run(
            "import backend.app.core.config",
            ENVIRONMENT="production",
            SECRET_KEY="changeme-in-prod",
        )
        assert proc.returncode != 0
        assert "SECRET_KEY" in proc.stderr

    def test_compose_defaults_in_production_refuse_to_boot(self):
        proc = _run(
            "import backend.app.core.config",
            ENVIRONMENT="production",
            SECRET_KEY="dev-only-change-me-9f1c7b2e4a6d8e0f1a2b3c4d5e6f7a8b",
            FIRST_SUPERUSER_PASSWORD="Demo1234!",
        )
        assert proc.returncode != 0
        assert "SECRET_KEY" in proc.stderr
        assert "FIRST_SUPERUSER_PASSWORD" in proc.stderr

    def test_app_env_demo_boots_as_development(self):
        proc = _run(
            "from backend.app.core.config import settings; print(settings.ENVIRONMENT)",
            APP_ENV="demo",
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "development"

    def test_bypass_in_test_is_accepted(self):
        proc = _run(
            "from backend.app.core.config import settings; print(settings.dev_auth_bypass_active)",
            ENVIRONMENT="test",
            DEV_AUTH_BYPASS="true",
            TESTING="true",
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "True"


# ---------------------------------------------------------------------------
# AUTH_PROVIDER / DEV_AUTH_BYPASS
# ---------------------------------------------------------------------------


class TestAuthSettings:
    def test_defaults(self):
        with patch.dict(os.environ, {}, clear=False):
            for key in ("AUTH_PROVIDER", "DEV_AUTH_BYPASS", "ENVIRONMENT"):
                os.environ.pop(key, None)
            s = Settings(_env_file=None)
        assert s.AUTH_PROVIDER == "local"
        assert s.DEV_AUTH_BYPASS is False
        assert s.LOCAL_AUTH_TOKEN_TTL_MINUTES == 720
        assert s.LOCAL_AUTH_MAX_FAILED_ATTEMPTS == 10
        assert s.LOCAL_AUTH_LOCKOUT_MINUTES == 15
        assert s.dev_auth_bypass_active is False

    def test_auth_provider_rejects_unknown(self):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, AUTH_PROVIDER="ldap")

    def test_cognito_provider_accepted(self):
        assert Settings(_env_file=None, AUTH_PROVIDER="cognito").AUTH_PROVIDER == "cognito"

    @pytest.mark.parametrize("env", ["development", "test"])
    def test_bypass_allowed_in_dev_and_test(self, env):
        s = Settings(_env_file=None, ENVIRONMENT=env, DEV_AUTH_BYPASS=True)
        assert s.dev_auth_bypass_active is True

    @pytest.mark.parametrize("env", ["staging", "production"])
    def test_bypass_rejected_in_staging_and_production(self, env, monkeypatch):
        # TESTING=true must NOT relax this guard.
        monkeypatch.setenv("TESTING", "true")
        with pytest.raises(ValidationError, match="DEV_AUTH_BYPASS"):
            Settings(_env_file=None, ENVIRONMENT=env, DEV_AUTH_BYPASS=True, SECRET_KEY="a" * 64)

    def test_bypass_false_in_production_is_fine(self):
        s = Settings(
            _env_file=None,
            ENVIRONMENT="production",
            DEV_AUTH_BYPASS=False,
            SECRET_KEY="a" * 64,
            FIRST_SUPERUSER_PASSWORD="StrongProd1!",
            AUDIT_HMAC_KEY="b" * 64,
            SSO_STATE_SECRET="c" * 64,
        )
        assert s.dev_auth_bypass_active is False


class TestDepsBypassHelper:
    """``deps.dev_auth_bypass_active`` reads the singleton at call time."""

    def test_true_only_with_both_conditions(self, monkeypatch):
        from backend.app.api import deps

        monkeypatch.setattr(deps.settings, "DEV_AUTH_BYPASS", True)
        monkeypatch.setattr(deps.settings, "ENVIRONMENT", "test")
        assert deps.dev_auth_bypass_active() is True

        monkeypatch.setattr(deps.settings, "ENVIRONMENT", "production")
        assert deps.dev_auth_bypass_active() is False

        monkeypatch.setattr(deps.settings, "ENVIRONMENT", "development")
        monkeypatch.setattr(deps.settings, "DEV_AUTH_BYPASS", False)
        assert deps.dev_auth_bypass_active() is False

    def test_truthy_non_bool_does_not_unlock(self, monkeypatch):
        from backend.app.api import deps

        monkeypatch.setattr(deps.settings, "DEV_AUTH_BYPASS", "true")
        monkeypatch.setattr(deps.settings, "ENVIRONMENT", "development")
        assert deps.dev_auth_bypass_active() is False

    def test_mock_settings_never_unlock(self):
        """A MagicMock settings object (used by legacy tests) must not enable the bypass."""
        from backend.app.api import deps

        with patch("backend.app.api.deps.settings", MagicMock()):
            assert deps.dev_auth_bypass_active() is False
