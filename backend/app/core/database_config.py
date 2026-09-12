# backend/app/core/database_config.py
"""
Dynamic schema configuration for database models.
"""

import logging
import os

logger = logging.getLogger(__name__)


# Add this to backend/app/core/database_config.py
def clear_schema_cache():
    """Clear the cached schema name."""
    # No-op when cache is disabled


# REMOVED @lru_cache for development to avoid caching issues with environment variables
# Re-enable in production with proper configuration management
def get_schema_name() -> str:
    """Get the schema name based on the environment."""
    # Check for truthy values, not just specific strings
    app_env = os.environ.get("APP_ENV", "")
    testing = os.environ.get("TESTING", "")

    # Only use test schema if explicitly set to test values
    if app_env == "test" or testing == "true":
        schema_name = "test_experimentation"
    else:
        schema_name = "experimentation"

    # Log only first time to avoid spam (use a module-level flag)
    if not hasattr(get_schema_name, "_logged"):
        logger.info(
            f"Using schema: {schema_name} (APP_ENV={app_env!r}, TESTING={testing!r})"
        )
        get_schema_name._logged = True

    return schema_name
