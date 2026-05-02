"""
Application settings and configuration.

This module defines settings for the application based on environment variables
and sensible defaults.
"""

import os
import secrets
from typing import Any, Dict, List, Optional, Union
from pydantic import field_validator, model_validator, AnyHttpUrl, EmailStr, PostgresDsn, RedisDsn, ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict

# Minimum acceptable length for SECRET_KEY in non-test environments
_MIN_SECRET_KEY_LENGTH = 32


class Settings(BaseSettings):
    """Base settings class."""

    PROJECT_NAME: str = "Experimentation Platform"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "dev"
    DEBUG: bool = False
    SECRET_KEY: str = "default-secret-key-for-testing"  # Default for testing only
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 1 hour
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []
    # CORS_ORIGINS is a plain-string list version of BACKEND_CORS_ORIGINS that
    # can also be set via env var as a comma-separated string.
    CORS_ORIGINS: List[str] = []

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

    # AWS region
    AWS_REGION: str = "us-east-1"

    # Compliance audit settings (EP-033)
    AUDIT_HMAC_KEY: str = "dev-audit-key-change-in-production"
    AUDIT_RETENTION_DAYS_SOC2: int = 365    # 12 months
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
    SAML_SP_ACS_URL: str = "https://experimentation-platform.example.com/auth/sso/saml/acs"
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
        "Viewers": "viewer"
    }
    COGNITO_ADMIN_GROUPS: List[str] = ["Admins", "SuperUsers"]
    SYNC_ROLES_ON_LOGIN: bool = True

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore"  # Ignore unknown fields to catch typos
    )

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
        environment = (info.data or {}).get("ENVIRONMENT", "dev")
        is_testing = os.getenv("TESTING", "").lower() in ("1", "true", "yes")
        if not is_testing and environment == "prod":
            weak_defaults = {
                "default-secret-key-for-testing",
                "secret",
                "changeme",
                "password",
                "supersecret",
            }
            if v in weak_defaults or len(v) < _MIN_SECRET_KEY_LENGTH:
                raise ValueError(
                    f"SECRET_KEY must be at least {_MIN_SECRET_KEY_LENGTH} characters "
                    "and must not be a well-known default value in production. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
                )
        return v

    @field_validator("FIRST_SUPERUSER_PASSWORD")
    @classmethod
    def validate_superuser_password(cls, v: str, info: ValidationInfo) -> str:
        """Reject weak default superuser passwords in production."""
        environment = (info.data or {}).get("ENVIRONMENT", "dev")
        is_testing = os.getenv("TESTING", "").lower() in ("1", "true", "yes")
        if not is_testing and environment == "prod":
            weak_defaults = {"admin", "password", "changeme", "admin123", ""}
            if v in weak_defaults or len(v) < 8:
                raise ValueError(
                    "FIRST_SUPERUSER_PASSWORD must be at least 8 characters "
                    "and must not be a well-known default in production."
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
        environment = (info.data or {}).get("ENVIRONMENT", "dev")
        is_testing = os.getenv("TESTING", "").lower() in ("1", "true", "yes")
        if not is_testing and environment == "prod":
            weak_defaults = {"dev-audit-key-change-in-production", "", "changeme"}
            if v in weak_defaults or len(v) < _MIN_SECRET_KEY_LENGTH:
                raise ValueError(
                    f"AUDIT_HMAC_KEY must be at least {_MIN_SECRET_KEY_LENGTH} characters "
                    "and must not be the dev default in production. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
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
        environment = (info.data or {}).get("ENVIRONMENT", "dev")
        is_testing = os.getenv("TESTING", "").lower() in ("1", "true", "yes")
        if not is_testing and environment == "prod":
            weak_defaults = {"sso-state-secret-change-in-prod", "", "changeme"}
            if v in weak_defaults or len(v) < _MIN_SECRET_KEY_LENGTH:
                raise ValueError(
                    f"SSO_STATE_SECRET must be at least {_MIN_SECRET_KEY_LENGTH} characters "
                    "and must not be the dev default in production. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
                )
        return v

    @field_validator("DATABASE_URI", mode="before")
    @classmethod
    def assemble_database_connection(cls, v: Optional[str], info: ValidationInfo) -> Any:
        """Assemble database connection string if not provided directly."""
        if isinstance(v, str):
            return v
        return PostgresDsn.build(
            scheme="postgresql",
            username=info.data.get("POSTGRES_USER"),
            password=info.data.get("POSTGRES_PASSWORD"),
            host=info.data.get("POSTGRES_SERVER"),
            port=int(info.data.get("POSTGRES_PORT", 5432)),
            path=info.data.get('POSTGRES_DB', ''),
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
            path=info.data.get('POSTGRES_DB', ''),
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

    ENVIRONMENT: str = "dev"
    LOG_LEVEL: str = "DEBUG"
    CORS_ORIGINS: List[str] = ["http://localhost:3100", "http://localhost:3000", "http://localhost:3001", "http://localhost:8000"]
    CACHE_ENABLED: bool = False
    CACHE_CONTROL: Dict[str, Any] = {"enabled": False, "redis": None, "ttl": 3600}
    PROJECT_NAME: str = "Experimentation Platform (Development)"
    PROJECT_DESCRIPTION: str = "A platform for managing experiments and feature flags (Development Environment)"
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "experimentation"

    model_config = SettingsConfigDict(env_file=".env.dev", case_sensitive=True, extra="ignore")


class TestSettings(Settings):
    """Test environment settings."""

    ENV: str = "test"
    TESTING: bool = True
    LOG_LEVEL: str = "DEBUG"
    PROJECT_NAME: str = "Experimentation Platform"
    PROJECT_DESCRIPTION: str = "API for managing experiments and feature flags in test environment"
    DEBUG: bool = True
    POSTGRES_SERVER: str = "localhost"  # Use localhost for testing
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "experimentation_test"
    POSTGRES_SCHEMA: str = "test_experimentation"
    CACHE_ENABLED: bool = False
    CACHE_CONTROL: Dict[str, Any] = {"enabled": False, "redis": None, "ttl": 3600}

    model_config = SettingsConfigDict(env_file=".env.test", case_sensitive=True, extra="ignore")


class ProdSettings(Settings):
    """Production environment settings."""

    ENVIRONMENT: str = "prod"
    PROJECT_NAME: str = "Experimentation Platform"
    PROJECT_DESCRIPTION: str = "A platform for managing experiments and feature flags"
    CACHE_ENABLED: bool = True
    CACHE_CONTROL: Dict[str, Any] = {"enabled": True, "redis": None, "ttl": 3600}

    model_config = SettingsConfigDict(env_file=".env.prod", case_sensitive=True, extra="ignore")

    def get_db_url(self) -> str:
        """
        Get the database URL, loading from Secrets Manager if needed.

        In production with ECS, POSTGRES_PASSWORD is injected directly
        from Secrets Manager as an env var by the task definition.
        This method is a fallback for non-ECS production deployments
        where the password was not injected via env var.
        """
        if self.ENVIRONMENT == "prod" and not self.POSTGRES_PASSWORD:
            try:
                from backend.app.core.secrets import get_secret, build_secret_name
                password = get_secret(build_secret_name("db-password"))
                return (
                    f"postgresql://{self.POSTGRES_USER}:{password}"
                    f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}"
                    f"/{self.POSTGRES_DB}"
                )
            except Exception:
                pass  # Fall through to standard URL construction
        return str(self.SQLALCHEMY_DATABASE_URI)


# Select settings based on environment
environment = os.getenv("APP_ENV", "dev").lower()

if environment == "prod":
    settings = ProdSettings()
elif environment == "test":
    settings = TestSettings()
else:
    settings = DevSettings()

# Make settings accessible at module level
__all__ = ["settings", "Settings", "DevSettings", "TestSettings", "ProdSettings"]
