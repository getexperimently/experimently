# Environment Configuration Setup Guide

This guide explains how to set up the environment configuration for Experimently.

## Overview

The platform uses Pydantic Settings to manage environment-specific configuration. The setup includes:

1. A base settings class with common configurations
2. Environment-specific settings classes (development, test, production)
3. Environment file templates for different environments
4. Logic to determine the current environment and load appropriate settings

## Setup Steps

### 1. Create Environment Files

The settings class for each environment reads its own file from the directory you start the
application in (the repository root):

| `ENVIRONMENT` | File |
|---|---|
| `development` (the default) | `.env.dev` |
| `test` | `.env.test` |
| `staging`, `production` | `.env.prod` |

Variables set in the process environment override the file. `.env.example` at the
repository root lists the variables and is a starting point. Docker Compose reads a
different file, `.env` next to `docker-compose.yml`; see
[The Docker Compose stack](docker-compose-file.md).

### 2. Environment Variables

The most important environment variables to configure:

#### Database Connection
```dotenv
POSTGRES_SERVER=localhost
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=experimentation
POSTGRES_PORT=5432
POSTGRES_SCHEMA=experimentation
```

Choose your own `POSTGRES_PASSWORD` for anything but a local database.

#### Redis Connection
```dotenv
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
```

Set `REDIS_PASSWORD` as well if your Redis requires one; the local stack's does not.

#### Application Settings
```dotenv
PROJECT_NAME="Experimently"
ENVIRONMENT=development
DEBUG=true
LOG_LEVEL=DEBUG
```

These are development values. In production, set `DEBUG=false` and `LOG_LEVEL` to `INFO`,
`WARNING` or `ERROR`.

#### Security Settings

`SECRET_KEY` signs login tokens. It must be a random string of at least 32 characters, and
staging and production refuse a shorter one or one of the placeholders in this repository.
Generate one:

```{.bash exec}
SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
echo "${#SECRET_KEY}"
```
<!-- expect: 64 -->

It prints `64`, the key's length. Put `SECRET_KEY=` followed by the key (`echo "$SECRET_KEY"`
shows it) in your environment file, next to these:

```dotenv
CORS_ORIGINS=http://localhost:3100,http://localhost:3200,http://localhost:8000
SDK_RATE_LIMIT_PER_MINUTE=6000
```

- CORS takes either of two forms. `CORS_ORIGINS` is a plain comma-separated list;
  `BACKEND_CORS_ORIGINS` must be a JSON array of URLs, such as
  `BACKEND_CORS_ORIGINS=["https://app.example.com"]`. When both are empty the development
  defaults (localhost ports 3000, 3001, 3100, 3200 and 8000) are used.
- `SDK_RATE_LIMIT_PER_MINUTE` is the per-IP ceiling for SDK traffic (`/api/v1/tracking/*`
  and flag evaluation). The default is 6000 a minute.

#### Background Jobs
```dotenv
BANDIT_UPDATE_INTERVAL_MINUTES=5
```

`BANDIT_UPDATE_INTERVAL_MINUTES` is how often multi-armed bandit weights are refreshed.

### 3. Environment Selection

The application determines which environment to use based on the `ENVIRONMENT` variable:

- If not set, defaults to `development`
- Valid values: `development`, `test`, `staging`, `production` (the older spellings `dev`
  and `prod` still work, with a deprecation warning)

Set it in your shell, in your deployment configuration, or in the environment file. In the
shell, for development:

```{.bash exec}
export ENVIRONMENT=development
```

For the others, give `test`, `staging` or `production` instead of `development`.

### 4. Production Configuration

For production deployment:

1. **Never commit production credentials to version control**
2. Use a secure method to provide the `.env.prod` file or environment variables
3. Ensure the following production values are properly set:
   - `SECRET_KEY` (generate a strong random string)
   - `POSTGRES_PASSWORD` (use a strong password)
   - `REDIS_PASSWORD` (if applicable)
   - `FIRST_SUPERUSER_PASSWORD` (for the admin user)
   - `DEBUG=false`
   - `LOG_LEVEL=WARNING` or `ERROR`

## Accessing Settings in Code

The settings are accessible throughout the application by importing the `settings` instance:

```python
from backend.app.core.config import settings

# Use settings
db_connection = settings.SQLALCHEMY_DATABASE_URI
app_name = settings.PROJECT_NAME
```

## Extending the Configuration

To add new configuration options:

1. Add the new setting to the `BaseAppSettings` class in `config.py`
2. Provide a default value
3. Override in environment-specific classes if needed
4. Update environment file templates with the new variable

Example:
```python
# In config.py
class BaseAppSettings(BaseSettings):
    # ... existing settings
    
    # New setting
    CACHE_TTL_SECONDS: int = 300  # Default 5 minutes
```

## Troubleshooting

- If settings aren't loading correctly, check that your environment file exists and has the correct format
- Verify environment variables are set correctly
- Check file permissions on the .env files
- Enable DEBUG mode to see more detailed logs
