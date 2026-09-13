#!/usr/bin/env bash
# =========================================================================
# Experimently API container entrypoint.
#
#   1. Wait for PostgreSQL (POSTGRES_SERVER/POSTGRES_PORT) to accept connections.
#   2. RUN_MIGRATIONS=true (default)  ->  python -m backend.app.db.bootstrap
#      (creates the schema on a fresh database, `alembic upgrade heads` otherwise).
#   3. SEED=<comma list of demo,shoplab,streampulse,sdk-contract>  ->  run the
#      matching backend/scripts/seed_*.py once. Completed seeds are recorded in
#      the `seed_markers` table (backend/scripts/seed_markers.py) so a restart
#      of the container does not re-seed. SEED_FORCE=true re-runs them.
#   4. exec "$@" — by default uvicorn; `--workers ${WEB_CONCURRENCY:-1}` and the
#      proxy flags are appended when the command is uvicorn and the caller did
#      not pass them explicitly.
#
# Every step can be skipped: RUN_MIGRATIONS=false, SEED= (empty),
# WAIT_FOR_DB=false. The script runs with `set -euo pipefail`: a failed
# bootstrap or seed stops the container instead of starting a half-initialised
# API.
# =========================================================================
set -euo pipefail

log() { printf '[entrypoint] %s\n' "$*" >&2; }

cd /app

: "${POSTGRES_SERVER:=${POSTGRES_HOST:-localhost}}"
: "${POSTGRES_PORT:=5432}"
: "${POSTGRES_USER:=postgres}"
: "${POSTGRES_DB:=experimentation}"
: "${WAIT_FOR_DB:=true}"
: "${DB_WAIT_TIMEOUT:=120}"
: "${RUN_MIGRATIONS:=true}"
: "${SEED:=}"
: "${SEED_FORCE:=false}"
: "${WEB_CONCURRENCY:=1}"
export POSTGRES_SERVER POSTGRES_PORT POSTGRES_USER POSTGRES_DB

# -------------------------------------------------------------------------
# 0. OpenSSL CPU-feature probe (arm64 under some hypervisors)
#
# The OpenSSL statically linked into the `cryptography` wheel selects assembly
# code paths from the CPU flags the kernel advertises. Some arm64 VMs (Docker
# Desktop on Apple M4, for one) advertise SVE/SME that the guest cannot
# execute, and the import dies with SIGILL (exit 132). Probe once; if it
# crashes, tell OpenSSL to skip the optimised paths for this process tree.
# -------------------------------------------------------------------------
if [ -z "${OPENSSL_armcap:-}" ]; then
    if ! python -c "from cryptography.hazmat.bindings._rust import openssl" >/dev/null 2>&1; then
        log "cryptography's OpenSSL crashed on this CPU; setting OPENSSL_armcap=0 (asm optimisations off)"
        export OPENSSL_armcap=0
    fi
fi

# -------------------------------------------------------------------------
# 1. Wait for the database
# -------------------------------------------------------------------------
wait_for_db() {
    local deadline=$(( $(date +%s) + DB_WAIT_TIMEOUT ))
    log "waiting for PostgreSQL at ${POSTGRES_SERVER}:${POSTGRES_PORT} (timeout ${DB_WAIT_TIMEOUT}s)"
    while true; do
        if command -v pg_isready >/dev/null 2>&1; then
            if pg_isready -q -h "$POSTGRES_SERVER" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB"; then
                break
            fi
        else
            # Fallback when postgresql-client is not installed: a raw TCP probe.
            if python - "$POSTGRES_SERVER" "$POSTGRES_PORT" <<'PY'
import socket, sys
try:
    socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=2).close()
except OSError:
    sys.exit(1)
PY
            then
                break
            fi
        fi
        if [ "$(date +%s)" -ge "$deadline" ]; then
            log "PostgreSQL did not become ready within ${DB_WAIT_TIMEOUT}s"
            exit 1
        fi
        sleep 1
    done
    log "PostgreSQL is ready"
}

if [ "$WAIT_FOR_DB" = "true" ]; then
    wait_for_db
fi

# -------------------------------------------------------------------------
# 2. Schema bootstrap / migrations
# -------------------------------------------------------------------------
if [ "$RUN_MIGRATIONS" = "true" ]; then
    log "running database bootstrap (python -m backend.app.db.bootstrap)"
    python -m backend.app.db.bootstrap
else
    log "RUN_MIGRATIONS=${RUN_MIGRATIONS}: skipping bootstrap"
fi

# -------------------------------------------------------------------------
# 3. Seeds (once, tracked in the seed_markers table)
# -------------------------------------------------------------------------
seed_script_for() {
    case "$1" in
        demo)          echo "backend/scripts/seed_demo_data.py" ;;
        shoplab)       echo "backend/scripts/seed_shoplab.py" ;;
        streampulse)   echo "backend/scripts/seed_streampulse.py" ;;
        sdk-contract)  echo "backend/scripts/seed_sdk_contract.py" ;;
        *)             echo "" ;;
    esac
}

if [ -n "$SEED" ]; then
    IFS=',' read -r -a seeds <<< "$SEED"
    for raw in "${seeds[@]}"; do
        name="$(echo "$raw" | tr -d '[:space:]')"
        [ -z "$name" ] && continue
        script="$(seed_script_for "$name")"
        if [ -z "$script" ]; then
            log "unknown seed '${name}' (expected one of demo, shoplab, streampulse, sdk-contract)"
            exit 1
        fi
        if [ "$SEED_FORCE" != "true" ] && python -m backend.scripts.seed_markers check "$name"; then
            log "seed '${name}' already applied; skipping (SEED_FORCE=true to re-run)"
            continue
        fi
        log "applying seed '${name}' (${script})"
        python "$script"
        python -m backend.scripts.seed_markers mark "$name"
        log "seed '${name}' recorded"
    done
fi

# -------------------------------------------------------------------------
# 4. Hand over to the server
# -------------------------------------------------------------------------
if [ "$#" -eq 0 ]; then
    set -- uvicorn backend.app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
fi

if [ "$1" = "uvicorn" ]; then
    has_workers=false
    for arg in "$@"; do
        case "$arg" in
            --workers|--workers=*) has_workers=true ;;
        esac
    done
    if [ "$has_workers" = "false" ]; then
        set -- "$@" --workers "$WEB_CONCURRENCY"
    fi
    set -- "$@" --proxy-headers --forwarded-allow-ips="*" --no-server-header
fi

log "starting: $*"
exec "$@"
