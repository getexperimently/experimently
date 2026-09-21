# Python Virtual Environment Setup Guide

This guide outlines how to set up and configure a Python virtual environment for the Experimently project.

## Directory Structure

Create a `requirements` directory with the following files to manage dependencies across different environments:

```
requirements/
├── base.txt        # Base dependencies used in all environments
├── dev.txt         # Development dependencies
├── test.txt        # Testing dependencies
└── prod.txt        # Production dependencies
```

## Requirements Files

### Base Requirements (requirements/base.txt)

```
# API Frameworks
fastapi==0.103.1
uvicorn[standard]==0.23.2
pydantic==2.3.0
pydantic-settings==2.0.3
email-validator==2.0.0.post2
python-multipart==0.0.6
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4

# Database & ORM
sqlalchemy==2.0.20
alembic==1.12.0
psycopg2-binary==2.9.7
asyncpg==0.28.0
redis==4.6.0
boto3==1.28.40

# Utilities
python-dateutil==2.8.2
pyyaml==6.0.1
jinja2==3.1.2
tenacity==8.2.3
structlog==23.1.0
orjson==3.9.5

# Analytics
numpy==1.25.2
scipy==1.11.2
pandas==2.1.0
```

### Development Requirements (requirements/dev.txt)

```
-r base.txt

# Development Tools
black==23.7.0
isort==5.12.0
mypy==1.5.1
flake8==6.1.0
pre-commit==3.4.0

# Documentation
mkdocs==1.5.3
mkdocs-material==9.2.8
mkdocstrings==0.22.0

# Debugging
ipython==8.15.0
debugpy==1.6.7
```

### Test Requirements (requirements/test.txt)

```
-r base.txt

# Testing
pytest==7.4.2
pytest-asyncio==0.21.1
pytest-cov==4.1.0
pytest-mock==3.11.1
httpx==0.24.1
faker==19.6.2
factory-boy==3.3.0
freezegun==1.2.2
```

### Production Requirements (requirements/prod.txt)

```
-r base.txt

# Monitoring & Tracing
opentelemetry-api==1.19.0
opentelemetry-sdk==1.19.0
opentelemetry-exporter-otlp==1.19.0
prometheus-client==0.17.1

# Production WSGI server
gunicorn==21.2.0
```

## Additional Configuration Files

### Python Version File (.python-version)

For pyenv users, create a `.python-version` file:

```
3.11.8
```

### Setup.py (for Development Mode Installation)

```python
from setuptools import find_packages, setup

setup(
    name="experimently",
    version="0.1.0",
    packages=find_packages(),
    include_package_data=True,
    python_requires=">=3.11",
    install_requires=[
        # Base dependencies are read from requirements files
    ],
)
```

## Usage Instructions

### Initial Setup

There is no setup script. It is three commands, from the repository root:

```bash
python3.11 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r backend/requirements.txt
```

`backend/requirements.txt` is the single source of truth for pins, and it is
what every CI job and the developer venv install. The profile files above are
thin wrappers around it -- `requirements/base.txt` is one `-r` line -- so
`pip install -r requirements/dev.txt` gets the same pins plus the debugging
extras.

### Selecting a profile

```bash
pip install -r requirements/dev.txt    # base + ipython, debugpy
pip install -r requirements/test.txt   # base (test deps are pinned in base)
pip install -r requirements/prod.txt   # base + gunicorn
```

### Development Mode Installation

```bash
pip install -e .
```

## Benefits

This virtual environment configuration provides:

1. **Isolation**: Keeps project dependencies separate from system Python
2. **Reproducibility**: Explicitly defined dependencies with pinned versions
3. **Environment Separation**: Different configurations for development, testing, and production
4. **One Source of Truth**: Every profile resolves to `backend/requirements.txt`, so CI and local venvs cannot drift
5. **Development Tools**: Pre-configured development tools like linters and formatters
