#!/usr/bin/env bash
# =============================================================================
# Experimently — AWS Demo Environment Bootstrap
# Usage: ./demo/setup-aws.sh [--destroy]
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO_DIR="$REPO_ROOT/demo"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${BLUE}[demo-aws]${NC} $*"; }
ok()   { echo -e "${GREEN}[demo-aws]${NC} $*"; }
warn() { echo -e "${YELLOW}[demo-aws]${NC} $*"; }
err()  { echo -e "${RED}[demo-aws] ERROR:${NC} $*" >&2; }

# ---------------------------------------------------------------------------
# --destroy flag
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--destroy" ]]; then
    log "Destroying AWS demo environment..."
    export ENVIRONMENT=demo
    : "${AWS_ACCOUNT_ID:?set AWS_ACCOUNT_ID to the target AWS account id}"
    export AWS_ACCOUNT_ID
    export AWS_REGION="${AWS_REGION:-us-west-2}"

    cd "$REPO_ROOT/infrastructure"
    ENVIRONMENT=demo npx cdk destroy --all --force
    ok "Demo environment destroyed."

    # Cleanup local artifacts
    rm -f "$DEMO_DIR/.demo_api_key_aws"
    rm -f "$DEMO_DIR/cdk-demo-outputs.json"
    if [[ -f "$DEMO_DIR/.pids/simulator-aws.pid" ]]; then
        PID=$(cat "$DEMO_DIR/.pids/simulator-aws.pid" 2>/dev/null || echo "")
        [[ -n "$PID" ]] && kill "$PID" 2>/dev/null || true
        rm -f "$DEMO_DIR/.pids/simulator-aws.pid"
    fi
    exit 0
fi

# ---------------------------------------------------------------------------
# 1. Prerequisite checks
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  Experimently Demo — AWS Setup                ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
echo ""

log "Checking prerequisites..."
MISSING=()
command -v aws     >/dev/null 2>&1 || MISSING+=("aws")
command -v cdk     >/dev/null 2>&1 || MISSING+=("cdk (npm install -g aws-cdk)")
command -v node    >/dev/null 2>&1 || MISSING+=("node")
command -v python3 >/dev/null 2>&1 || MISSING+=("python3")
command -v jq      >/dev/null 2>&1 || MISSING+=("jq")

if [[ ${#MISSING[@]} -gt 0 ]]; then
    err "Missing required tools: ${MISSING[*]}"
    exit 1
fi
ok "All prerequisites present."

# ---------------------------------------------------------------------------
# 2. AWS credentials check
# ---------------------------------------------------------------------------
log "Verifying AWS credentials..."
CALLER_IDENTITY=$(aws sts get-caller-identity 2>/dev/null || echo "")
if [[ -z "$CALLER_IDENTITY" ]]; then
    err "AWS credentials not configured. Run 'aws configure' or set AWS_PROFILE."
    exit 1
fi
ACTUAL_ACCOUNT=$(echo "$CALLER_IDENTITY" | jq -r '.Account')
ok "AWS credentials OK (account: $ACTUAL_ACCOUNT)."

# ---------------------------------------------------------------------------
# 3. Environment variables
# ---------------------------------------------------------------------------
export ENVIRONMENT=demo
# Target account comes from the environment (never hard-coded); default to the
# account the active credentials belong to.
export AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$ACTUAL_ACCOUNT}"
export AWS_REGION="${AWS_REGION:-us-west-2}"

if [[ "$ACTUAL_ACCOUNT" != "$AWS_ACCOUNT_ID" ]]; then
    warn "Active AWS account ($ACTUAL_ACCOUNT) differs from target ($AWS_ACCOUNT_ID)."
    warn "Set AWS_PROFILE or credentials for the correct account to continue."
    read -r -p "Continue anyway? [y/N] " CONFIRM
    [[ "${CONFIRM,,}" == "y" ]] || exit 1
fi

mkdir -p "$DEMO_DIR/.pids" "$DEMO_DIR/.logs"

# ---------------------------------------------------------------------------
# 4. Install CDK dependencies
# ---------------------------------------------------------------------------
log "Installing CDK dependencies..."
cd "$REPO_ROOT/infrastructure"
npm install -q

# ---------------------------------------------------------------------------
# 5. CDK Bootstrap (idempotent)
# ---------------------------------------------------------------------------
log "Bootstrapping CDK (account=$AWS_ACCOUNT_ID, region=$AWS_REGION)..."
npx cdk bootstrap "aws://$AWS_ACCOUNT_ID/$AWS_REGION" \
    --cloudformation-execution-policies arn:aws:iam::aws:policy/AdministratorAccess

# ---------------------------------------------------------------------------
# 6. CDK Deploy
# ---------------------------------------------------------------------------
log "Deploying demo stacks (this takes 15-20 min on first run)..."
ENVIRONMENT=demo npx cdk deploy --all \
    --require-approval never \
    --outputs-file "$DEMO_DIR/cdk-demo-outputs.json"
ok "CDK deployment complete."

# ---------------------------------------------------------------------------
# 7. Extract API URL from outputs
# ---------------------------------------------------------------------------
DEMO_API_URL=$(jq -r '
    .["experimentation-fargate-demo"].ApiUrl //
    .["experimentation-fargate-demo"].LoadBalancerDnsName //
    empty
' "$DEMO_DIR/cdk-demo-outputs.json" 2>/dev/null || echo "")

if [[ -z "$DEMO_API_URL" ]]; then
    # Try to find any output containing a URL
    DEMO_API_URL=$(jq -r '[.. | strings | select(startswith("http"))] | first' \
        "$DEMO_DIR/cdk-demo-outputs.json" 2>/dev/null || echo "")
fi

if [[ -z "$DEMO_API_URL" ]]; then
    err "Could not determine API URL from CDK outputs. Check $DEMO_DIR/cdk-demo-outputs.json"
    err "Set DEMO_API_URL manually and re-run the remaining steps."
    exit 1
fi

# Ensure URL has http scheme
[[ "$DEMO_API_URL" == http* ]] || DEMO_API_URL="https://$DEMO_API_URL"
ok "Demo API URL: $DEMO_API_URL"

# ---------------------------------------------------------------------------
# 8. Wait for API health check
# ---------------------------------------------------------------------------
log "Waiting for API to be healthy (up to 5 min)..."
MAX_WAIT=300
WAITED=0
until curl -sf "$DEMO_API_URL/health" >/dev/null 2>&1; do
    WAITED=$((WAITED + 5))
    if [[ $WAITED -ge $MAX_WAIT ]]; then
        err "API did not become healthy within ${MAX_WAIT}s."
        exit 1
    fi
    echo -n "."
    sleep 5
done
echo ""
ok "API is healthy."

# ---------------------------------------------------------------------------
# 9. Run database migration ECS task
# ---------------------------------------------------------------------------
log "Running database migrations via ECS task..."

# Get cluster and task definition from outputs
CLUSTER_NAME=$(jq -r '
    .["experimentation-migrations-demo"].ClusterName //
    .["experimentation-compute-demo"].ClusterName //
    "demo-cluster"
' "$DEMO_DIR/cdk-demo-outputs.json" 2>/dev/null || echo "demo-cluster")

TASK_DEF=$(jq -r '
    .["experimentation-migrations-demo"].MigrationTaskDefinition //
    "MigrationTask"
' "$DEMO_DIR/cdk-demo-outputs.json" 2>/dev/null || echo "MigrationTask")

SUBNET=$(jq -r '
    .["experimentation-vpc-demo"].PublicSubnet1Id //
    empty
' "$DEMO_DIR/cdk-demo-outputs.json" 2>/dev/null || echo "")

SECURITY_GROUP=$(jq -r '
    .["experimentation-fargate-demo"].EcsSecurityGroupId //
    empty
' "$DEMO_DIR/cdk-demo-outputs.json" 2>/dev/null || echo "")

if [[ -n "$SUBNET" && -n "$SECURITY_GROUP" ]]; then
    TASK_ARN=$(aws ecs run-task \
        --cluster "$CLUSTER_NAME" \
        --task-definition "$TASK_DEF" \
        --launch-type FARGATE \
        --network-configuration "awsvpcConfiguration={subnets=[$SUBNET],securityGroups=[$SECURITY_GROUP],assignPublicIp=ENABLED}" \
        --region "$AWS_REGION" \
        --query "tasks[0].taskArn" \
        --output text 2>/dev/null || echo "")

    if [[ -n "$TASK_ARN" && "$TASK_ARN" != "None" ]]; then
        log "Migration task started: $TASK_ARN"
        log "Waiting for migration to complete..."
        aws ecs wait tasks-stopped \
            --cluster "$CLUSTER_NAME" \
            --tasks "$TASK_ARN" \
            --region "$AWS_REGION" || true
        ok "Migration task completed."
    else
        warn "Could not start migration task — skipping (migrations may already be applied)."
    fi
else
    warn "Could not determine network config — skipping ECS migration task."
    warn "Run migrations manually if needed."
fi

# ---------------------------------------------------------------------------
# 10. Seed demo data
# ---------------------------------------------------------------------------
log "Seeding demo data..."
if [[ ! -d "$REPO_ROOT/venv" ]]; then
    python3 -m venv "$REPO_ROOT/venv"
fi
source "$REPO_ROOT/venv/bin/activate"
pip install -r "$REPO_ROOT/backend/requirements.txt" -q

python "$REPO_ROOT/backend/scripts/seed_demo_data.py" --api-url "$DEMO_API_URL"
ok "Demo data seeded."

# ---------------------------------------------------------------------------
# 11. Create demo API key
# ---------------------------------------------------------------------------
log "Creating demo API key via API..."
API_KEY_RESPONSE=$(curl -sf -X POST "$DEMO_API_URL/api/v1/auth/demo-login" \
    -H "Content-Type: application/json" \
    -d '{"email":"admin@demo.com","password":"Demo1234!"}' 2>/dev/null || echo "{}")
TOKEN=$(echo "$API_KEY_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token',''))" 2>/dev/null || echo "")

DEMO_API_KEY="demo-aws-fallback-key"
if [[ -n "$TOKEN" ]]; then
    KEY_RESPONSE=$(curl -sf -X POST "$DEMO_API_URL/api/v1/api-keys" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $TOKEN" \
        -d '{"name":"demo-simulator-aws","description":"AWS demo simulator key","scopes":"read,write"}' \
        2>/dev/null || echo "{}")
    DEMO_API_KEY=$(echo "$KEY_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('key',d.get('api_key','demo-aws-fallback-key')))" 2>/dev/null || echo "demo-aws-fallback-key")
fi

echo "$DEMO_API_KEY" > "$DEMO_DIR/.demo_api_key_aws"
ok "API key saved to demo/.demo_api_key_aws"

# ---------------------------------------------------------------------------
# 12. Start live event simulator (background)
# ---------------------------------------------------------------------------
log "Starting live event simulator (rate=2 events/sec)..."
source "$REPO_ROOT/venv/bin/activate"
nohup python "$REPO_ROOT/backend/scripts/simulate_live_events.py" \
    --api-url "$DEMO_API_URL" \
    --api-key "$DEMO_API_KEY" \
    --rate 2 \
    > "$DEMO_DIR/.logs/simulator-aws.log" 2>&1 &
echo $! > "$DEMO_DIR/.pids/simulator-aws.pid"
ok "Simulator started (PID $(cat "$DEMO_DIR/.pids/simulator-aws.pid"))"

# ---------------------------------------------------------------------------
# 13. Success banner
# ---------------------------------------------------------------------------
echo ""
echo -e "${GREEN}${BOLD}╔═════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║  Experimently Demo — AWS Ready!                 ║${NC}"
echo -e "${GREEN}${BOLD}║                                                 ║${NC}"
echo -e "${GREEN}${BOLD}║  API:      ${DEMO_API_URL}${NC}"
echo -e "${GREEN}${BOLD}║  API Docs: ${DEMO_API_URL}/docs${NC}"
echo -e "${GREEN}${BOLD}║  Admin:    admin@demo.com                       ║${NC}"
echo -e "${GREEN}${BOLD}║  Password: Demo1234!                            ║${NC}"
echo -e "${GREEN}${BOLD}║                                                 ║${NC}"
echo -e "${GREEN}${BOLD}║  Simulator: demo/.logs/simulator-aws.log        ║${NC}"
echo -e "${GREEN}${BOLD}║  Teardown:  ./demo/setup-aws.sh --destroy       ║${NC}"
echo -e "${GREEN}${BOLD}╚═════════════════════════════════════════════════╝${NC}"
echo ""
echo "CDK outputs: $DEMO_DIR/cdk-demo-outputs.json"
echo ""
