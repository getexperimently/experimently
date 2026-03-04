#!/usr/bin/env bash
# =============================================================================
# Experimently — Local Demo Teardown
# Usage: ./demo/teardown-local.sh
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO_DIR="$REPO_ROOT/demo"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${BLUE}[demo]${NC} $*"; }
ok()   { echo -e "${GREEN}[demo]${NC} $*"; }
warn() { echo -e "${YELLOW}[demo]${NC} $*"; }

echo ""
log "Stopping Experimently demo environment..."

# ---------------------------------------------------------------------------
# 1. Kill tracked processes
# ---------------------------------------------------------------------------
PIDS_DIR="$DEMO_DIR/.pids"
if [[ -d "$PIDS_DIR" ]]; then
    for pid_file in "$PIDS_DIR"/*.pid; do
        [[ -f "$pid_file" ]] || continue
        PID=$(cat "$pid_file" 2>/dev/null || echo "")
        PROC_NAME=$(basename "$pid_file" .pid)
        if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
            log "Stopping $PROC_NAME (PID $PID)..."
            kill "$PID" 2>/dev/null || true
            # Wait up to 5 seconds for graceful shutdown
            for i in {1..5}; do
                kill -0 "$PID" 2>/dev/null || break
                sleep 1
            done
            # Force kill if still running
            kill -9 "$PID" 2>/dev/null || true
            ok "$PROC_NAME stopped."
        else
            warn "$PROC_NAME (PID ${PID:-unknown}) not running, skipping."
        fi
    done
else
    warn "No .pids directory found — nothing to kill."
fi

# ---------------------------------------------------------------------------
# 2. Stop Docker services
# ---------------------------------------------------------------------------
log "Stopping Docker services..."
cd "$REPO_ROOT"
docker-compose down
ok "Docker services stopped."

# ---------------------------------------------------------------------------
# 3. Cleanup demo artifacts
# ---------------------------------------------------------------------------
log "Cleaning up demo artifacts..."
rm -rf "$DEMO_DIR/.pids"
rm -rf "$DEMO_DIR/.logs"
rm -f  "$DEMO_DIR/.demo_api_key"
rm -f  "$DEMO_DIR/.demo_api_key_aws"
ok "Cleanup complete."

echo ""
ok "Demo environment stopped."
echo ""
