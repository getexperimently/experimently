"""
AWS Secrets Manager integration for production secret loading.

In production, sensitive configuration (database passwords, JWT secrets, API keys)
are stored in AWS Secrets Manager and loaded at application startup.

Secret naming convention:
  /{environment}/experimentation/{secret-name}

Examples:
  /prod/experimentation/db-password
  /prod/experimentation/jwt-secret
  /prod/experimentation/redis-url
  /staging/experimentation/db-password
"""
import json
import logging
import os
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)


@lru_cache(maxsize=32)
def get_secret(secret_name: str, region_name: str = "us-west-2") -> str:
    """
    Retrieve a secret value from AWS Secrets Manager.

    Results are cached in-process for the lifetime of the application
    (avoids repeated API calls on every request). To force refresh,
    clear the cache: get_secret.cache_clear().

    Args:
        secret_name: Full secret name or ARN
        region_name: AWS region

    Returns:
        Secret string value

    Raises:
        RuntimeError: If secret cannot be retrieved
    """
    try:
        import boto3
        from botocore.exceptions import ClientError

        client = boto3.client("secretsmanager", region_name=region_name)
        response = client.get_secret_value(SecretId=secret_name)

        secret = response.get("SecretString")
        if secret is None:
            # Binary secret — decode
            import base64
            secret = base64.b64decode(response["SecretBinary"]).decode("utf-8")

        # Only the secret's identifier is logged, never its value.
        logger.info("Successfully retrieved secret: %s", secret_name)  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
        return secret

    except ImportError:
        raise RuntimeError(
            "boto3 is required for Secrets Manager access. "
            "Install it with: pip install boto3"
        )
    except Exception as exc:
        # Logs the identifier and the boto error, never the secret value.
        logger.error("Failed to retrieve secret %s: %s", secret_name, exc)  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure
        raise RuntimeError(f"Could not retrieve secret '{secret_name}': {exc}") from exc


def get_secret_json(secret_name: str, region_name: str = "us-west-2") -> dict:
    """Retrieve and parse a JSON secret."""
    raw = get_secret(secret_name, region_name)
    return json.loads(raw)


def build_secret_name(key: str, environment: Optional[str] = None) -> str:
    """
    Build the standard secret name for this platform.

    Args:
        key: Secret key (e.g. 'db-password', 'jwt-secret')
        environment: Override environment (defaults to APP_ENV env var)

    Returns:
        Full secret path: /{env}/experimentation/{key}
    """
    env = environment or os.environ.get("APP_ENV", "dev")
    return f"/{env}/experimentation/{key}"
