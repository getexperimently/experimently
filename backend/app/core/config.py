"""
Application settings and configuration.

This module defines settings for the application based on environment variables
and sensible defaults.
"""

import logging
import os
import warnings
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import (
    AnyHttpUrl,
    EmailStr,
    PostgresDsn,
    RedisDsn,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

logger = logging.getLogger(__name__)

# Minimum acceptable length for SECRET_KEY in non-test environments
_MIN_SECRET_KEY_LENGTH = 32

# ---------------------------------------------------------------------------
# Environment name canonicalisation
# ---------------------------------------------------------------------------
# ``ENVIRONMENT`` is the single source of truth for "which environment am I
# running in".  The canonical values are below; the legacy spellings ``dev``
# and ``prod`` (and the legacy ``APP_ENV`` variable) are still accepted but
# emit a DeprecationWarning so operators migrate their env files.

EnvironmentName = Literal["development", "test", "staging", "production"]

CANONICAL_ENVIRONMENTS: tuple = ("development", "test", "staging", "production")

# Legacy spelling -> canonical spelling.
_LEGACY_ENVIRONMENT_ALIASES: Dict[str, str] = {
    "dev": "development",
    "prod": "production",
    # The AWS demo stack (demo/setup-aws.sh, infrastructure/cdk/app.py) runs
    # with APP_ENV=demo: a public, seeded development-grade deployment.
    "demo": "development",
}

# Canonical spelling -> legacy ``APP_ENV`` spelling (mirrored back into the
# process environment for the handful of modules that still read APP_ENV).
_CANONICAL_TO_APP_ENV: Dict[str, str] = {
    "development": "dev",
    "test": "test",
    "staging": "staging",
    "production": "prod",
}

# Environments in which the dev-admin auth bypass may run at all.
BYPASS_ALLOWED_ENVIRONMENTS: tuple = ("development", "test")

# Environments that must not run with placeholder secrets or demo passwords.
HARDENED_ENVIRONMENTS: tuple = ("staging", "production")

# Placeholder secrets that ship in the repository (class defaults,
# docker-compose.yml, .env.example) or are otherwise well known.  Any secret
# equal to one of these, or starting with one of the prefixes, is refused in
# HARDENED_ENVIRONMENTS regardless of its length.
_PLACEHOLDER_SECRETS: frozenset = frozenset(
    {
        "",
        "secret",
        "changeme",
        "change-me",
        "password",
        "supersecret",
        "default-secret-key-for-testing",
        "development_secret_key_change_in_production",
        "dev-audit-key-change-in-production",
        "sso-state-secret-change-in-prod",
    }
)
_PLACEHOLDER_SECRET_PREFIXES: tuple = (
    "dev-only-",
    "dev-audit-",
    "development_secret",
    "default-secret",
    "ci-only-",
    "test-",
    "sso-state-secret-change",
)


def _secret_is_placeholder(value: str) -> bool:
    """True when *value* is a committed/well-known placeholder secret."""
    normalised = (value or "").strip().lower()
    if normalised in _PLACEHOLDER_SECRETS:
        return True
    return any(normalised.startswith(prefix) for prefix in _PLACEHOLDER_SECRET_PREFIXES)


def _hardening_required(info: ValidationInfo) -> bool:
    """Secrets must be real in staging/production unless the test suite is running."""
    environment = (info.data or {}).get("ENVIRONMENT", "development")
    is_testing = os.getenv("TESTING", "").lower() in ("1", "true", "yes")
    return not is_testing and environment in HARDENED_ENVIRONMENTS


def canonical_environment(value: Any) -> Any:
    """
    Map a raw environment string to its canonical spelling.

    ``dev`` -> ``development`` and ``prod`` -> ``production`` are accepted with
    a DeprecationWarning.  Unknown values are returned (lower-cased) untouched
    so the ``Literal`` validation on the field produces the error message.
    Non-string values are returned as-is for the same reason.
    """
    if not isinstance(value, str):
        return value
    normalised = value.strip().lower()
    if normalised in _LEGACY_ENVIRONMENT_ALIASES:
        canonical = _LEGACY_ENVIRONMENT_ALIASES[normalised]
        message = f"ENVIRONMENT={value!r} is deprecated; use ENVIRONMENT={canonical!r} instead."
        warnings.warn(message, DeprecationWarning, stacklevel=3)
        logger.warning(message)
        return canonical
    return normalised


def canonical_environment_quiet(value: str) -> str:
    """Like :func:`canonical_environment` but never warns (for comparisons)."""
    normalised = value.strip().lower()
    return _LEGACY_ENVIRONMENT_ALIASES.get(normalised, normalised)


def resolve_environment_from_process_env() -> str:
    """
    Determine the canonical environment name from the process environment.

    ``ENVIRONMENT`` wins.  The legacy ``APP_ENV`` variable is honoured as a
    fallback (with a DeprecationWarning).  When neither is set the platform
    runs as ``development``.
    """
    raw = os.environ.get("ENVIRONMENT")
    legacy = os.environ.get("APP_ENV")
    if raw:
        canonical = canonical_environment(raw)
        if legacy and canonical_environment_quiet(legacy) != canonical:
            logger.warning(
                "ENVIRONMENT=%r and APP_ENV=%r disagree; ENVIRONMENT wins. "
                "Remove APP_ENV from your configuration.",
                raw,
                legacy,
            )
        return canonical
    if legacy:
        message = (
            "APP_ENV is deprecated; set ENVIRONMENT="
            f"{canonical_environment_quiet(legacy)!r} instead."
        )
        warnings.warn(message, DeprecationWarning, stacklevel=2)
        logger.warning(message)
        return canonical_environment(legacy)
    return "development"


class Settings(BaseSettings):
    """Base settings class."""

    PROJECT_NAME: str = "Experimentation Platform"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    # Canonical environment name. Legacy ``dev``/``prod`` spellings and the
    # legacy ``APP_ENV`` variable are accepted (see module docstring above).
    ENVIRONMENT: EnvironmentName = "development"
    DEBUG: bool = False
    SECRET_KEY: str = "default-secret-key-for-testing"  # Default for testing only
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 1 hour

    # ------------------------------------------------------------------
    # Authentication provider (P0 open-core)
    # ------------------------------------------------------------------
    # ``local``  - email/password against ``users.hashed_password`` (bcrypt)
    #              issuing HS256 JWTs signed with SECRET_KEY.  Community
    #              Edition default; no AWS required.
    # ``cognito`` - AWS Cognito user pool (needs COGNITO_USER_POOL_ID and
    #              COGNITO_CLIENT_ID in the process environment).
    AUTH_PROVIDER: Literal["local", "cognito"] = "local"

    # Dev-admin bypass: every request is served as a synthetic ADMIN user
    # without credentials.  Only honoured when ENVIRONMENT is development or
    # test (see ``forbid_dev_auth_bypass_outside_dev`` below and
    # ``backend.app.api.deps.dev_auth_bypass_active``).  Never enable this on
    # a network-reachable deployment.
    DEV_AUTH_BYPASS: bool = False

    # Local-provider token and lockout policy.
    LOCAL_AUTH_TOKEN_TTL_MINUTES: int = 720  # 12 hours
    LOCAL_AUTH_MAX_FAILED_ATTEMPTS: int = 10
    LOCAL_AUTH_LOCKOUT_MINUTES: int = 15

    # ------------------------------------------------------------------
    # Enterprise licence (open-core seam; see backend/app/core/license.py)
    # ------------------------------------------------------------------
    # Offline-verified Ed25519 licence key, ``base64url(claims).base64url(sig)``.
    # Empty (the default) means Community Edition: /api/v1/edition reports
    # ``{"edition": "ce", "status": "none"}`` and every ``require_feature``
    # dependency refuses.  Never phoned home, never logged.
    EXPERIMENTLY_LICENSE_KEY: str = ""
    # PEM public key for developer licences minted by
    # ``scripts/make_dev_license.py`` (kid ``dev``).  Honoured only when
    # ENVIRONMENT is development or test, so a leaked dev key cannot unlock a
    # production deployment.
    EXPERIMENTLY_DEV_LICENSE_PUBLIC_KEY: str = ""
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []
    # CORS_ORIGINS is a plain-string list version of BACKEND_CORS_ORIGINS that
    # can also be set via env var as a comma-separated string. NoDecode stops
    # pydantic-settings from JSON-decoding the raw value so the "before"
    # validator below receives it as-is.
    CORS_ORIGINS: Annotated[List[str], NoDecode] = []

    # Database settings
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "experimentation"
    POSTGRES_PORT: str = "5432"
    POSTGRES_SCHEMA: Optional[str] = None
    DATABASE_URI: Optional[PostgresDsn] = None
    SQLALCHEMY_DATABASE_URI: Optional[PostgresDsn] = None

    # Redis settings
    REDIS_HOST: str = "localhost"
    REDIS_PORT: str = "6379"
    REDIS_PASSWORD: Optional[str] = None
    REDIS_DB: int = 0
    REDIS_URI: Optional[RedisDsn] = None

    # User settings
    FIRST_SUPERUSER: EmailStr = "admin@example.com"
    FIRST_SUPERUSER_PASSWORD: str = "admin"

    # Scheduler notification and health settings
    NOTIFICATION_WEBHOOK_URL: str = ""
    SCHEDULER_MAX_RETRIES: int = 3
    SCHEDULER_RETRY_DELAY_SECONDS: int = 60
    SCHEDULER_HISTORY_RETENTION_DAYS: int = 30

    # Slack notification settings
    SLACK_BOT_TOKEN: str = ""
    SLACK_DEFAULT_CHANNEL: str = "#platform-alerts"
    SLACK_ENABLED: bool = False

    # DynamoDB settings
    DYNAMODB_COUNTERS_TABLE: str = "experiment-counters"

    # Multi-armed bandit weight refresh cadence (Issue #22). The in-app
    # BanditSchedulerRunner recomputes BanditState weights this often.
    BANDIT_UPDATE_INTERVAL_MINUTES: int = 5

    # Background scheduler cadences (minutes). SafetyScheduler checks flag
    # error-rate/latency thresholds and auto-rolls back; RolloutScheduler
    # advances time-based rollout stages. Demos set both to 1.
    SAFETY_CHECK_INTERVAL_MINUTES: int = 5
    ROLLOUT_CHECK_INTERVAL_MINUTES: int = 15

    # Per-IP ceiling for SDK-facing endpoints (/tracking/*, flag evaluation).
    # Far above the 300/min default because one server-side SDK or NAT egress
    # can legitimately fan out thousands of assignments a minute.
    SDK_RATE_LIMIT_PER_MINUTE: int = 6000

    # Observability (read by backend/app/core/health.py, logger.py, main.py)
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Optional[Literal["json", "console"]] = (
        None  # None -> json in staging/production, console otherwise
    )
    # Days of `analysis_snapshots` and `bandit_state_history` to keep. The
    # request path writes at most one snapshot per experiment, kind and day,
    # but the bandit scheduler records every tick, so the tables still grow
    # without a purge. 0 disables the purge.
    ANALYSIS_HISTORY_RETENTION_DAYS: int = 90

    METRICS_ENABLED: bool = True
    METRICS_TOKEN: Optional[str] = (
        None  # required to read /metrics outside development/test
    )
    REDIS_REQUIRED: bool = False  # when true, /health/ready fails without Redis

    # Process model (documented: one worker per container; scheduler ticks are advisory-locked)
    WEB_CONCURRENCY: int = 1
    PORT: int = 8000

    # AWS region
    AWS_REGION: str = "us-east-1"

    # Compliance audit settings (EP-033)
    AUDIT_HMAC_KEY: str = "dev-audit-key-change-in-production"
    AUDIT_RETENTION_DAYS_SOC2: int = 365  # 12 months
    AUDIT_RETENTION_DAYS_ISO27001: int = 730  # 24 months

    # EP-050: HIPAA Compliance settings
    PHI_ENCRYPTION_KEY: Optional[str] = None
    HIPAA_ENABLED: bool = False
    HIPAA_ALLOWED_REGIONS: List[str] = ["us-east-1", "us-west-2"]
    HIPAA_AUDIT_LOG_RETENTION_YEARS: int = 6

    # Glue / ETL settings (P3-A)
    GLUE_ETL_JOB_NAME: str = "experimentation-events-etl"
    GLUE_METRICS_JOB_NAME: str = "experimentation-metrics-etl"
    GLUE_DATABASE: str = "experimentation"
    GLUE_EVENTS_TABLE: str = "raw_events"
    ATHENA_OUTPUT_BUCKET: str = "s3://experimentation-athena-results/"
    GLUE_CRAWLER_NAME: str = "experimentation-crawler"

    # Email / notification settings (EP-030)
    EMAIL_ENABLED: bool = False
    SENDGRID_API_KEY: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    EMAIL_FROM_ADDRESS: str = "platform@example.com"
    EMAIL_FROM_NAME: str = "Experimentation Platform"
    NOTIFICATION_ADMIN_EMAILS: List[str] = []

    # EP-046: LLM/AI Model Evaluation
    LLM_OPENAI_API_KEY: str = ""
    LLM_ANTHROPIC_API_KEY: str = ""
    LLM_GOOGLE_API_KEY: str = ""
    LLM_DEFAULT_JUDGE_MODEL: str = "claude-3-5-sonnet-20241022"
    LLM_MAX_TOKENS_DEFAULT: int = 1000
    LLM_TEMPERATURE_DEFAULT: float = 0.7

    # EP-041: Databricks warehouse connector
    DATABRICKS_HOST: str = ""
    DATABRICKS_HTTP_PATH: str = ""
    DATABRICKS_TOKEN: str = ""
    DATABRICKS_CATALOG: str = "main"
    DATABRICKS_SCHEMA: str = "default"
    DATABRICKS_TIMEOUT_SECONDS: int = 30

    # EP-048: ClickHouse warehouse connector
    CLICKHOUSE_HOST: str = "localhost"
    CLICKHOUSE_PORT: int = 8123  # HTTP port (9000 for native)
    CLICKHOUSE_DATABASE: str = "default"
    CLICKHOUSE_USER: str = "default"
    CLICKHOUSE_PASSWORD: str = ""
    CLICKHOUSE_SECURE: bool = False
    CLICKHOUSE_TIMEOUT_SECONDS: int = 30

    # EP-048: MySQL warehouse connector
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_DATABASE: str = ""
    MYSQL_USER: str = ""
    MYSQL_PASSWORD: str = ""
    MYSQL_TIMEOUT_SECONDS: int = 30

    # SSO / SAML / OIDC settings (EP-037)
    SSO_ENABLED: bool = True
    SAML_SP_ENTITY_ID: str = "https://experimentation-platform.example.com"
    SAML_SP_ACS_URL: str = (
        "https://experimentation-platform.example.com/auth/sso/saml/acs"
    )
    OIDC_GOOGLE_CLIENT_ID: str = ""
    OIDC_GOOGLE_CLIENT_SECRET: str = ""
    OIDC_GITHUB_CLIENT_ID: str = ""
    OIDC_GITHUB_CLIENT_SECRET: str = ""
    OIDC_MICROSOFT_CLIENT_ID: str = ""
    OIDC_MICROSOFT_CLIENT_SECRET: str = ""
    SSO_STATE_SECRET: str = "sso-state-secret-change-in-prod"

    # Cognito settings
    COGNITO_GROUP_ROLE_MAPPING: Dict[str, str] = {
        "Admins": "admin",
        "Developers": "developer",
        "Analysts": "analyst",
        "Viewers": "viewer",
    }
    COGNITO_ADMIN_GROUPS: List[str] = ["Admins", "SuperUsers"]
    SYNC_ROLES_ON_LOGIN: bool = True

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",  # Ignore unknown fields to catch typos
    )

    # ------------------------------------------------------------------
    # Environment helpers
    # ------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_staging(self) -> bool:
        return self.ENVIRONMENT == "staging"

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"

    @property
    def is_test(self) -> bool:
        return self.ENVIRONMENT == "test"

    @property
    def dev_auth_bypass_active(self) -> bool:
        """True only when the dev-admin bypass is both enabled and permitted."""
        return (
            self.DEV_AUTH_BYPASS is True
            and self.ENVIRONMENT in BYPASS_ALLOWED_ENVIRONMENTS
        )

    @field_validator("ENVIRONMENT", mode="before")
    @classmethod
    def canonicalise_environment(cls, v: Any) -> Any:
        """Accept legacy ``dev``/``prod`` spellings (with a deprecation warning)."""
        return canonical_environment(v)

    @model_validator(mode="after")
    def forbid_dev_auth_bypass_outside_dev(self) -> "Settings":
        """
        Refuse to start with DEV_AUTH_BYPASS enabled in staging/production.

        The bypass serves every request as an ADMIN without credentials; the
        only environments where that is acceptable are ``development`` and
        ``test``.  This check is deliberately NOT relaxed by ``TESTING``.
        """
        if self.DEV_AUTH_BYPASS and self.ENVIRONMENT not in BYPASS_ALLOWED_ENVIRONMENTS:
            raise ValueError(
                f"DEV_AUTH_BYPASS=true is not permitted when ENVIRONMENT={self.ENVIRONMENT!r}. "
                "The dev-admin bypass may only be enabled in development or test."
            )
        return self

    @field_validator("BACKEND_CORS_ORIGINS")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        """Parse CORS origins from string or list."""
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins_plain(cls, v: Union[str, List[str]]) -> List[str]:
        """Parse plain CORS origins list from comma-separated string or list."""
        if isinstance(v, str) and v.strip().startswith("["):
            import json

            v = json.loads(v)
        if isinstance(v, str) and v:
            return [i.strip() for i in v.split(",") if i.strip()]
        if isinstance(v, list):
            return v
        return []

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str, info: ValidationInfo) -> str:
        """
        Ensure the SECRET_KEY is sufficiently long in non-test environments.

        A short or default key in production is a critical security vulnerability.
        Tests are explicitly excluded so the test suite can run without real keys.
        """
        if _hardening_required(info):
            if _secret_is_placeholder(v) or len(v) < _MIN_SECRET_KEY_LENGTH:
                raise ValueError(
                    f"SECRET_KEY must be at least {_MIN_SECRET_KEY_LENGTH} characters "
                    "and must not be a placeholder from the repository (docker-compose.yml, "
                    ".env.example or the class default) in staging/production. "
                    'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
                )
        return v

    @field_validator("FIRST_SUPERUSER_PASSWORD")
    @classmethod
    def validate_superuser_password(cls, v: str, info: ValidationInfo) -> str:
        """Reject weak or repository-known superuser passwords in staging/production."""
        if _hardening_required(info):
            # ``Demo1234!`` is the seeded demo password and appears in the
            # public docs and docker-compose.yml; it is never acceptable
            # for a real deployment's first administrator.
            weak_defaults = {
                "admin",
                "password",
                "changeme",
                "admin123",
                "",
                "demo1234!",
            }
            if v.lower() in weak_defaults or len(v) < 8:
                raise ValueError(
                    "FIRST_SUPERUSER_PASSWORD must be at least 8 characters "
                    "and must not be a well-known or demo default in staging/production."
                )
        return v

    @field_validator("AUDIT_HMAC_KEY")
    @classmethod
    def validate_audit_hmac_key(cls, v: str, info: ValidationInfo) -> str:
        """
        Reject the dev default AUDIT_HMAC_KEY in production.

        This key signs SOC 2 / ISO 27001 compliance audit log integrity proofs
        (HMAC-SHA256). Shipping the default in prod makes all audit signatures
        forgeable and breaks compliance attestations.
        """
        if _hardening_required(info):
            if _secret_is_placeholder(v) or len(v) < _MIN_SECRET_KEY_LENGTH:
                raise ValueError(
                    f"AUDIT_HMAC_KEY must be at least {_MIN_SECRET_KEY_LENGTH} characters "
                    "and must not be the dev default in staging/production. "
                    'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
                )
        return v

    @field_validator("SSO_STATE_SECRET")
    @classmethod
    def validate_sso_state_secret(cls, v: str, info: ValidationInfo) -> str:
        """
        Reject the dev default SSO_STATE_SECRET in production.

        This secret protects the SAML/OIDC state parameter against CSRF.
        A predictable value lets an attacker forge SSO state tokens.
        """
        if _hardening_required(info):
            if _secret_is_placeholder(v) or len(v) < _MIN_SECRET_KEY_LENGTH:
                raise ValueError(
                    f"SSO_STATE_SECRET must be at least {_MIN_SECRET_KEY_LENGTH} characters "
                    "and must not be the dev default in staging/production. "
                    'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
                )
        return v

    @field_validator("DATABASE_URI", mode="before")
    @classmethod
    def assemble_database_connection(
        cls, v: Optional[str], info: ValidationInfo
    ) -> Any:
        """Assemble database connection string if not provided directly."""
        if isinstance(v, str):
            return v
        return PostgresDsn.build(
            scheme="postgresql",
            username=info.data.get("POSTGRES_USER"),
            password=info.data.get("POSTGRES_PASSWORD"),
            host=info.data.get("POSTGRES_SERVER"),
            port=int(info.data.get("POSTGRES_PORT", 5432)),
            path=info.data.get("POSTGRES_DB", ""),
        )

    @field_validator("SQLALCHEMY_DATABASE_URI", mode="before")
    @classmethod
    def assemble_db_connection(cls, v: Optional[str], info: ValidationInfo) -> Any:
        """Assemble database connection string if not provided directly."""
        if isinstance(v, str):
            return v
        # If DATABASE_URI is set, use that
        database_uri = info.data.get("DATABASE_URI")
        if database_uri:
            return database_uri
        # Otherwise build from components
        return PostgresDsn.build(
            scheme="postgresql",
            username=info.data.get("POSTGRES_USER"),
            password=info.data.get("POSTGRES_PASSWORD"),
            host=info.data.get("POSTGRES_SERVER"),
            port=int(info.data.get("POSTGRES_PORT", 5432)),
            path=info.data.get("POSTGRES_DB", ""),
        )

    @field_validator("REDIS_URI", mode="before")
    @classmethod
    def assemble_redis_connection(cls, v: Optional[str], info: ValidationInfo) -> Any:
        """Assemble Redis connection string if not provided directly."""
        if isinstance(v, str):
            return v

        # Build Redis URI components
        host = info.data.get("REDIS_HOST", "localhost")
        port = int(info.data.get("REDIS_PORT", 6379))
        password = info.data.get("REDIS_PASSWORD")

        # Construct the Redis URI
        if password:
            return f"redis://:{password}@{host}:{port}"
        return f"redis://{host}:{port}"


class DevSettings(Settings):
    """Development environment settings."""

    ENVIRONMENT: EnvironmentName = "development"
    LOG_LEVEL: str = (
        "INFO"  # set LOG_LEVEL=DEBUG explicitly; DEBUG makes every library chatty
    )
    CORS_ORIGINS: Annotated[List[str], NoDecode] = [
        "http://localhost:3100",
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3200",  # ShopLab demo storefront
        "http://localhost:3300",  # StreamPulse demo app
        "http://localhost:8000",
    ]
    CACHE_ENABLED: bool = False
    CACHE_CONTROL: Dict[str, Any] = {"enabled": False, "redis": None, "ttl": 3600}
    PROJECT_NAME: str = "Experimentation Platform (Development)"
    PROJECT_DESCRIPTION: str = "A platform for managing experiments and feature flags (Development Environment)"
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "experimentation"

    model_config = SettingsConfigDict(
        env_file=".env.dev", case_sensitive=True, extra="ignore"
    )


class TestSettings(Settings):
    """Test environment settings."""

    ENVIRONMENT: EnvironmentName = "test"
    ENV: str = "test"
    TESTING: bool = True
    LOG_LEVEL: str = (
        "INFO"  # set LOG_LEVEL=DEBUG explicitly; DEBUG makes every library chatty
    )
    PROJECT_NAME: str = "Experimentation Platform"
    PROJECT_DESCRIPTION: str = (
        "API for managing experiments and feature flags in test environment"
    )
    DEBUG: bool = True
    POSTGRES_SERVER: str = "localhost"  # Use localhost for testing
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "experimentation_test"
    POSTGRES_SCHEMA: str = "test_experimentation"
    CACHE_ENABLED: bool = False
    CACHE_CONTROL: Dict[str, Any] = {"enabled": False, "redis": None, "ttl": 3600}

    model_config = SettingsConfigDict(
        env_file=".env.test", case_sensitive=True, extra="ignore"
    )


class ProdSettings(Settings):
    """Production/staging environment settings."""

    ENVIRONMENT: EnvironmentName = "production"
    PROJECT_NAME: str = "Experimentation Platform"
    PROJECT_DESCRIPTION: str = "A platform for managing experiments and feature flags"
    CACHE_ENABLED: bool = True
    CACHE_CONTROL: Dict[str, Any] = {"enabled": True, "redis": None, "ttl": 3600}

    model_config = SettingsConfigDict(
        env_file=".env.prod", case_sensitive=True, extra="ignore"
    )

    def get_db_url(self) -> str:
        """
        Get the database URL, loading from Secrets Manager if needed.

        In production with ECS, POSTGRES_PASSWORD is injected directly
        from Secrets Manager as an env var by the task definition.
        This method is a fallback for non-ECS production deployments
        where the password was not injected via env var.
        """
        if self.ENVIRONMENT == "production" and not self.POSTGRES_PASSWORD:
            try:
                from backend.app.core.secrets import build_secret_name, get_secret

                password = get_secret(build_secret_name("db-password"))
                return (
                    f"postgresql://{self.POSTGRES_USER}:{password}"
                    f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}"
                    f"/{self.POSTGRES_DB}"
                )
            except Exception:
                pass  # Fall through to standard URL construction
        return str(self.SQLALCHEMY_DATABASE_URI)


# ---------------------------------------------------------------------------
# Select the settings class from the canonical environment name
# ---------------------------------------------------------------------------
# ``ENVIRONMENT`` (canonical) wins; legacy ``APP_ENV`` is honoured with a
# deprecation warning.  The resolved value is passed explicitly so the chosen
# class always reports the canonical name (``APP_ENV=prod`` -> ``production``).
#: Whether the deployment named its environment at all.  Captured *before*
#: the legacy ``APP_ENV`` mirror below, which would otherwise make an
#: undeclared process indistinguishable from a declared development one to
#: anything that reads ``os.environ`` afterwards -- and the licence verifier
#: has to treat "nothing declared" as production (``core/license.py``).
ENVIRONMENT_DECLARED: bool = bool(
    (os.environ.get("ENVIRONMENT") or "").strip()
    or (os.environ.get("APP_ENV") or "").strip()
)

_resolved_environment = resolve_environment_from_process_env()

# Mirror the legacy spelling back into APP_ENV for modules that still read it
# directly (schema selection, rate-limiter enablement, bandit scheduler ...).
os.environ.setdefault(
    "APP_ENV", _CANONICAL_TO_APP_ENV.get(_resolved_environment, _resolved_environment)
)

if _resolved_environment in ("production", "staging"):
    settings = ProdSettings(ENVIRONMENT=_resolved_environment)
elif _resolved_environment == "test":
    settings = TestSettings(ENVIRONMENT=_resolved_environment)
else:
    settings = DevSettings(ENVIRONMENT=_resolved_environment)

# Make settings accessible at module level
__all__ = [
    "BYPASS_ALLOWED_ENVIRONMENTS",
    "CANONICAL_ENVIRONMENTS",
    "DevSettings",
    "EnvironmentName",
    "ProdSettings",
    "Settings",
    "TestSettings",
    "canonical_environment",
    "resolve_environment_from_process_env",
    "settings",
]
