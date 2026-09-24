# Python Virtual Environment Setup Guide

This guide outlines how to set up and configure a Python virtual environment for the Experimently project.

## The requirements layout

The `requirements/` directory already exists — you do not create it. It holds
four *profiles*, and every one of them resolves to the same pins:

```
requirements/
├── base.txt     # one line: -r ../backend/requirements.txt
├── dev.txt      # base + ipython, debugpy
├── test.txt     # base (every test dependency is already pinned in base)
└── prod.txt     # base + gunicorn
```

**`backend/requirements.txt` is the single source of truth.** It is what every
CI job and the developer venv install. `requirements/base.txt` is a single
`-r ../backend/requirements.txt` line, so the profiles cannot drift from it —
that is the whole point of the layout, and it is why this page does not list
the pins. Read the file; a copy here would be wrong within a week. An earlier
version of this page listed 43 pins as the "contents" of `base.txt`, starting
`fastapi==0.103.1` when the actual pin was `0.141.1`.

To see what is pinned:

```bash
grep -c '==' backend/requirements.txt      # how many
grep '^fastapi' backend/requirements.txt   # a specific one
```

Note that `requirements/prod.txt` is **not** what the container installs — the
image installs `backend/requirements.txt`. The prod profile is for running the
API under gunicorn outside a container.

## Python version

`.python-version` pins 3.11.10, and `pyproject.toml` sets
`requires-python = ">=3.11"`. There is no `setup.py` or `setup.cfg`. Lambda
runtimes and every CI workflow use 3.11; Python 3.9 reached end of life in
October 2025.

## Editable install

There is no `setup.py` — packaging is declared in `pyproject.toml`
(`[project] name = "experimently-platform"`, with a `[build-system]` table so
PEP 517 frontends do not fall back to the legacy setuptools path). The name is
deliberately not `experimently`: that belongs to the Python SDK under
`sdk/python/`.

```bash
pip install -e .
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

See [Editable install](#editable-install) above.

## Benefits

This virtual environment configuration provides:

1. **Isolation**: Keeps project dependencies separate from system Python
2. **Reproducibility**: Explicitly defined dependencies with pinned versions
3. **Environment Separation**: Different configurations for development, testing, and production
4. **One Source of Truth**: Every profile resolves to `backend/requirements.txt`, so CI and local venvs cannot drift
5. **One Toolchain**: ruff (format, import order, lint) is pinned in
   `backend/requirements.txt` like everything else, so the version in your venv
   is the version CI runs -- see
   [Pre-commit Hooks](pre-commit-hooks.md)
