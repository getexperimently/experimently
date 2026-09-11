#!/usr/bin/env bash
set -euo pipefail

# Deterministic backend test runner for local and CI use.
#
# Usage:
#   scripts/run-backend-tests.sh release
#   EP_TEST_PROFILE=compose scripts/run-backend-tests.sh all
#
# Modes:
#   unit        Run unit tests only
#   integration Run integration tests only
#   smoke       Run smoke wiring checks only
#   release     Run release gate backend checks (unit + smoke)
#   all         Run unit + integration + smoke

MODE="${1:-release}"
PROFILE="${EP_TEST_PROFILE:-external}" # external | compose

if [[ "${PROFILE}" == "compose" ]]; then
  # --wait blocks until the services' healthchecks pass, so the schema
  # bootstrap below never races Postgres' first-start initialisation.
  docker compose -f docker-compose.test.yml up -d --wait postgres-test redis-test
  trap 'docker compose -f docker-compose.test.yml down --remove-orphans >/dev/null 2>&1 || true' EXIT
  export POSTGRES_PORT="${POSTGRES_PORT:-5433}"
  export REDIS_PORT="${REDIS_PORT:-6380}"
else
  export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
  export REDIS_PORT="${REDIS_PORT:-6379}"
fi

export APP_ENV=test
export TESTING=true
export POSTGRES_SERVER="${POSTGRES_SERVER:-localhost}"
export POSTGRES_USER="${POSTGRES_USER:-postgres}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
export POSTGRES_DB="${POSTGRES_DB:-experimentation_test}"
export POSTGRES_SCHEMA="${POSTGRES_SCHEMA:-experimentation}"
export REDIS_HOST="${REDIS_HOST:-localhost}"
export REDIS_DB="${REDIS_DB:-0}"

if [[ -f "venv/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source venv/bin/activate
fi

# Ensure deterministic schema bootstrap across local/CI environments.
python - <<'PY'
from sqlalchemy import create_engine, text
import os

url = (
    f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
    f"@{os.environ['POSTGRES_SERVER']}:{os.environ['POSTGRES_PORT']}/{os.environ['POSTGRES_DB']}"
)
schema = os.environ.get("POSTGRES_SCHEMA", "experimentation")
engine = create_engine(url)
with engine.begin() as conn:
    conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
print(f"Schema ensured: {schema}")
PY

run_unit() {
  python -m pytest backend/tests/unit -q
}

run_integration() {
  python -m pytest backend/tests/integration -q
}

run_smoke() {
  python -m pytest backend/tests/smoke/test_wiring.py -q
}

case "${MODE}" in
  unit)
    run_unit
    ;;
  integration)
    run_integration
    ;;
  smoke)
    run_smoke
    ;;
  release)
    run_unit
    run_smoke
    ;;
  all)
    run_unit
    run_integration
    run_smoke
    ;;
  *)
    echo "Unknown mode: ${MODE}" >&2
    echo "Expected one of: unit, integration, smoke, release, all" >&2
    exit 2
    ;;
esac
