"""The modules' settings, kept out of the core ``Settings`` (issue #91).

A core deployment that set ``ENVIRONMENT=production`` used to refuse to start
unless it also supplied ``AUDIT_HMAC_KEY`` and ``SSO_STATE_SECRET`` -- two
secrets only the modules read, one of which nothing read.  The fields that
only module code reads live here instead, on :class:`ModulesSettings`, which
``modules.register(hooks)`` builds and validates as its first step: a
placeholder audit key in staging or production is still refused, but by the
modules' registration, so it can only ever stop a full-profile deployment.

What lives here, by manifest group:

* group 3, signed audit: ``AUDIT_HMAC_KEY`` and its hardening validator.  The
  retention windows (``AUDIT_RETENTION_DAYS_*``) stay core -- the core
  ``AuditLogService`` reads them.
* group 2, HIPAA: ``PHI_ENCRYPTION_KEY`` and ``HIPAA_*``.
* group 4, SSO: ``SAML_SP_*`` and ``OIDC_*``.  ``SSO_ENABLED`` and
  ``SSO_STATE_SECRET`` are gone: nothing read either.
* group 6, warehouse connectors: ``DATABRICKS_*``, ``CLICKHOUSE_*``,
  ``MYSQL_*``.
* group 8, real-time counters: ``DYNAMODB_COUNTERS_TABLE``, read by
  ``DynamoDBCounterService`` when no table name is passed to it.
* group 9, ETL: ``GLUE_*`` and ``ATHENA_OUTPUT_BUCKET``.

Module code reads them as ``from modules.backend.app.settings import
settings`` -- the same shape as the core singleton, so a test patches
``<module>.settings`` exactly as before.  Core fields (``AWS_REGION``,
``SECRET_KEY``, ...) are still read from ``backend.app.core.config.settings``.

``ENVIRONMENT`` is mirrored from the core singleton rather than resolved again
from the process environment, so the two can never disagree on whether
hardening applies (the core resolver also honours the legacy ``APP_ENV``).
The dotenv file is taken from the same place
(:func:`backend.app.core.config.env_file_for_environment`), so these settings
are read from ``.env.dev``/``.env.test``/``.env.prod`` exactly as they were
while they lived on the core class.
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.app.core.config import (
    _MIN_SECRET_KEY_LENGTH,
    EnvironmentName,
    _hardening_required,
    _secret_is_placeholder,
    canonical_environment,
    env_file_for_environment,
)


class ModulesSettings(BaseSettings):
    """Settings only module code reads.  See the module docstring."""

    #: Mirrors the core ``settings.ENVIRONMENT``; declared first so the
    #: hardening validators below can read it from ``info.data``.
    ENVIRONMENT: EnvironmentName = "development"

    # Compliance audit signing (EP-033)
    AUDIT_HMAC_KEY: str = "dev-audit-key-change-in-production"

    # EP-050: HIPAA Compliance settings
    PHI_ENCRYPTION_KEY: Optional[str] = None
    HIPAA_ENABLED: bool = False
    HIPAA_ALLOWED_REGIONS: List[str] = ["us-east-1", "us-west-2"]
    HIPAA_AUDIT_LOG_RETENTION_YEARS: int = 6

    # P2-B: real-time DynamoDB counters
    DYNAMODB_COUNTERS_TABLE: str = "experiment-counters"

    # Glue / ETL settings (P3-A)
    GLUE_ETL_JOB_NAME: str = "experimentation-events-etl"
    GLUE_METRICS_JOB_NAME: str = "experimentation-metrics-etl"
    GLUE_DATABASE: str = "experimentation"
    GLUE_EVENTS_TABLE: str = "raw_events"
    ATHENA_OUTPUT_BUCKET: str = "s3://experimentation-athena-results/"
    GLUE_CRAWLER_NAME: str = "experimentation-crawler"

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
    SAML_SP_ENTITY_ID: str = "https://experimently.example.com"
    SAML_SP_ACS_URL: str = "https://experimently.example.com/auth/sso/saml/acs"
    OIDC_GOOGLE_CLIENT_ID: str = ""
    OIDC_GOOGLE_CLIENT_SECRET: str = ""
    OIDC_GITHUB_CLIENT_ID: str = ""
    OIDC_GITHUB_CLIENT_SECRET: str = ""
    OIDC_MICROSOFT_CLIENT_ID: str = ""
    OIDC_MICROSOFT_CLIENT_SECRET: str = ""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    @field_validator("ENVIRONMENT", mode="before")
    @classmethod
    def canonicalise_environment(cls, v: Any) -> Any:
        """Accept the legacy ``dev``/``prod`` spellings, as the core class does."""
        return canonical_environment(v)

    @field_validator("AUDIT_HMAC_KEY")
    @classmethod
    def validate_audit_hmac_key(cls, v: str, info: ValidationInfo) -> str:
        """
        Reject the dev default AUDIT_HMAC_KEY in staging/production.

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


def build_modules_settings() -> ModulesSettings:
    """A fresh, validated :class:`ModulesSettings` for this process.

    ``ENVIRONMENT`` comes from the core singleton (see the module docstring),
    and so does the dotenv file: ``env_file_for_environment()`` answers with
    the very file the core settings class for that environment reads
    (``.env.dev`` / ``.env.test`` / ``.env.prod``), which is the mechanism
    ``docs/getting-started/environment-setup.md`` documents for production.
    Without it every setting that moved off the core class -- AUDIT_HMAC_KEY,
    PHI_ENCRYPTION_KEY, the OIDC/SAML/HIPAA/warehouse ones -- would quietly
    stop being read from those files and fall back to its dev default.

    Raises ``pydantic.ValidationError`` when a hardened environment carries a
    placeholder secret.
    """
    from backend.app.core.config import settings as core_settings

    return ModulesSettings(
        ENVIRONMENT=core_settings.ENVIRONMENT,
        _env_file=env_file_for_environment(core_settings.ENVIRONMENT),
    )


_instance: Optional[ModulesSettings] = None


def load_modules_settings(force: bool = False) -> ModulesSettings:
    """Build the process-wide instance once (``force`` rebuilds it) and return it.

    ``modules.register(hooks)`` calls this first, so that a validation failure is
    the registration's failure -- caught and logged by ``modules_loader``, and a
    reason for the schema builders to refuse -- rather than an import-time
    crash of whichever module happened to be imported first.
    """
    global _instance
    if _instance is None or force:
        _instance = build_modules_settings()
    return _instance


def __getattr__(name: str) -> Any:
    """``from modules.backend.app.settings import settings`` -- the process-wide instance.

    Resolved lazily (PEP 562) so importing this module never builds the
    settings behind the registration's back; the modules bind the name at
    their own import, which ``register(hooks)`` triggers after it has
    validated the settings itself.
    """
    if name == "settings":
        return load_modules_settings()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ModulesSettings",
    "build_modules_settings",
    "load_modules_settings",
]
