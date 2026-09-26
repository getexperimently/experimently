# Technical Guide

Detailed implementation reference for Experimently. Covers architecture, data models, key subsystems, and real-world use cases.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Client Layer                             │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Next.js UI  │  │ JavaScript   │  │ Python SDK /         │  │
│  │ (Port 3000) │  │ SDK          │  │ Direct API calls     │  │
│  └──────┬──────┘  └──────┬───────┘  └──────────┬───────────┘  │
└─────────│────────────────│─────────────────────│───────────────┘
          │                │                     │
          ▼                ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Application (Port 8000)            │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Middleware: Auth, CORS, Rate Limiting, Request Logging  │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │ /api/v1/   │  │ /api/v1/     │  │ /api/v1/              │  │
│  │ experiments│  │ feature-flags│  │ tracking / results    │  │
│  └──────┬─────┘  └──────┬───────┘  └───────────┬───────────┘  │
│         │               │                       │               │
│  ┌──────▼───────────────▼───────────────────────▼───────────┐  │
│  │                   Services Layer                          │  │
│  │  ExperimentService  FeatureFlagService  AssignmentService │  │
│  │  EventService       ResultsEngine       RulesEngine       │  │
│  └──────────────────────────────┬────────────────────────────┘  │
└─────────────────────────────────│───────────────────────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          ▼                       ▼                       ▼
  ┌──────────────┐      ┌──────────────────┐    ┌──────────────┐
  │ PostgreSQL   │      │ Redis (Cache)    │    │ AWS Lambda   │
  │ (Aurora)     │      │ (ElastiCache)    │    │ Functions    │
  └──────────────┘      └──────────────────┘    └──────────────┘
```

---

## Data Models

### Core Entities

```
Experiment
├── id (UUID PK)
├── key (unique string) ← used in tracking API
├── name, description, hypothesis
├── status: DRAFT | ACTIVE | PAUSED | COMPLETED
├── type: A_B | MULTIVARIATE | FEATURE_FLAG
├── owner_id → User
├── start_date, end_date (for scheduling)
├── targeting_rules (JSON)
├── traffic_allocation (0-100)
│
├── variants → [Variant]
│   ├── id, name
│   ├── is_control (bool)
│   ├── traffic_allocation (0-100, must sum to ≤100)
│   └── configuration (JSON — variant-specific config)
│
├── metrics → [Metric]
│   ├── id, name
│   ├── event_name ← matches Event.event_name
│   ├── metric_type: CONVERSION | REVENUE | COUNT | DURATION
│   └── is_primary (bool)
│
└── assignments → [Assignment]
    ├── user_id (string — your app's user identifier)
    ├── variant_id → Variant
    └── created_at

Event
├── id (UUID PK)
├── user_id (string)
├── event_type (string)
├── event_name (string) ← matched to Metric.event_name
├── experiment_id → Experiment (nullable)
├── feature_flag_id → FeatureFlag (nullable)
├── variant_id → Variant (nullable)
├── value (float — revenue, count, duration)
└── properties (JSON — arbitrary metadata)

FeatureFlag
├── id (UUID PK)
├── key (unique string) ← used in evaluation API
├── name, description
├── status: ACTIVE | INACTIVE | ARCHIVED
├── owner_id → User
├── rollout_percentage (0-100)
├── targeting_rules (JSON)
└── rollout_schedules → [RolloutSchedule]
    ├── stages → [RolloutStage]
    │   ├── stage_order (int)
    │   ├── target_percentage (int)
    │   ├── trigger_type: TIME_BASED | METRIC_BASED | MANUAL
    │   └── start_date

User
├── id (UUID PK)
├── username, email, full_name
├── role: ADMIN | DEVELOPER | ANALYST | VIEWER
├── is_superuser (bool)
└── is_active (bool)
```

---

## Authentication System

### Two Authentication Methods

**1. Bearer Token (JWT)**
- Used by human users in the dashboard
- Obtained via `POST /api/v1/auth/login`
- Validated against AWS Cognito (production) or local DB (development)
- Expires per `ACCESS_TOKEN_EXPIRE_MINUTES`

```bash
# Get token
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -d '{"username":"admin","password":"admin"}' \
  -H "Content-Type: application/json" | jq -r '.access_token')

# Use token
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/experiments
```

**2. API Key**
- Used by SDKs and server-to-server tracking calls
- Static key, stored hashed in DB
- Passed via `X-API-Key` header
- Required for all `/api/v1/tracking/*` endpoints

```bash
curl -H "X-API-Key: your-key" \
  -X POST http://localhost:8000/api/v1/tracking/assign \
  -d '{"user_id":"u1","experiment_key":"my-exp","context":{}}'
```

### Role-Based Access Control (RBAC)

| Role | Create | Update | Delete | View |
|------|--------|--------|--------|------|
| ADMIN | All | All | All | All |
| DEVELOPER | Experiments, Flags | Own experiments; any flag | Own experiments; any flag | All |
| ANALYST | None | None | None | All |
| VIEWER | None | None | None | Approved experiments; all flags |

Feature flags are governed by role, not ownership: the owner is recorded but does not
decide access.

Permission checks in code (both return a bool; the caller raises the 403):

```python
from backend.app.core.permissions import (
    Action,
    ResourceType,
    can_act_on_feature_flag,
    check_permission,
)

# a role's permission on a resource type
if not check_permission(current_user, ResourceType.EXPERIMENT, Action.UPDATE):
    raise HTTPException(status_code=403, detail="Not enough permissions")

# a particular feature flag
if not can_act_on_feature_flag(current_user, flag.owner_id, Action.DELETE):
    raise HTTPException(status_code=403, detail="Not enough permissions")
```

---

## Rules Engine

The rules engine evaluates targeting rules to determine if a user should be included in an experiment or feature flag.

### Rule Structure

```json
{
  "operator": "AND",
  "rules": [
    {
      "attribute": "country",
      "operator": "IN",
      "value": ["US", "CA", "GB"]
    },
    {
      "attribute": "user_age",
      "operator": "GREATER_THAN",
      "value": 18
    },
    {
      "attribute": "plan",
      "operator": "EQUALS",
      "value": "premium"
    }
  ]
}
```

### Supported Operators (20+)

| Category | Operators |
|----------|-----------|
| Equality | `EQUALS`, `NOT_EQUALS` |
| Comparison | `GREATER_THAN`, `LESS_THAN`, `GREATER_THAN_OR_EQUAL`, `LESS_THAN_OR_EQUAL` |
| String | `CONTAINS`, `NOT_CONTAINS`, `STARTS_WITH`, `ENDS_WITH`, `REGEX` |
| Array | `IN`, `NOT_IN`, `CONTAINS_ANY`, `CONTAINS_ALL` |
| Existence | `EXISTS`, `NOT_EXISTS` |
| Versioning | `SEMVER_GT`, `SEMVER_LT`, `SEMVER_EQ` |
| Geo | `GEO_DISTANCE` |
| Time | `TIME_IN_WINDOW` |
| JSON | `JSON_PATH` |
| Logic | `AND`, `OR`, `NOT` |

### Performance

- Compilation cache: LRU cache, 10,000 entries
- Evaluation cache: thread-safe LRU with TTL (default: 300s)
- Throughput: 125,000+ simple evaluations/second
- Batch evaluation: 1,000 users in <5 seconds

```python
from backend.app.services.rules_evaluation_service import RulesEvaluationService

service = RulesEvaluationService(
    cache_size=1000,
    cache_ttl_seconds=300,
    metrics_window=1000,
)

# Single evaluation
result = await service.evaluate_rules_cached(
    rules=targeting_rules,
    context={"country": "US", "user_age": 25, "plan": "premium"},
)

# Batch evaluation
results = await service.batch_evaluate(
    users=[{"user_id": "u1", "country": "US"}, ...],
    rules=targeting_rules,
)
```

---

## Assignment Algorithm

When a user calls `/api/v1/tracking/assign`:

1. **Rules check**: Evaluate targeting rules against user context
2. **Traffic split**: Hash `user_id + experiment_id` → deterministic bucket (0-99)
3. **Variant selection**: Assign to variant based on cumulative traffic allocations
4. **Persistence**: Save assignment to `assignments` table
5. **Idempotency**: Same user always gets same variant (deterministic hash)

```
User "user-123" + Experiment "homepage-test"
     ↓
Hash → bucket 47
     ↓
Traffic allocation: Control 0-49 (50%), Treatment 50-99 (50%)
     ↓
bucket 47 → Control variant
```

This means:
- Assignment is **sticky** — user gets same variant on all subsequent calls
- Consistent across devices (same user_id = same variant)
- No session dependency

---

## Results Engine

The analytics results engine (`backend/app/services/analysis_service.py`) computes:

### Statistical Methods

**Conversion metrics (Z-test):**
- Null hypothesis: control and treatment have equal conversion rates
- Test statistic: z = (p1 - p2) / SE
- Two-tailed p-value for significance testing

**Continuous metrics (T-test):**
- Welch's t-test for unequal variances
- Effect size: Cohen's d

**Multiple comparisons correction:**
- Bonferroni correction (default)
- Benjamini-Hochberg (FDR) available

### REST Endpoints

```
GET  /api/v1/results/{id}             # Full results with p-values, CIs, effect sizes
GET  /api/v1/results/{id}/daily       # Daily time-series per variant
GET  /api/v1/results/{id}/sample-size # Sample size adequacy + power
POST /api/v1/results/{id}/invalidate-cache
```

### Sample Size Calculation

Required sample size per variant:

```
n = 2 * ((z_α/2 + z_β)² * p(1-p)) / δ²

Where:
  z_α/2 = z-score for confidence level (1.96 for 95%)
  z_β   = z-score for power (0.84 for 80%)
  p     = baseline conversion rate
  δ     = minimum detectable effect (MDE)
```

Default: 95% confidence, 80% power, 5% MDE.

---

## Lambda Functions

Three AWS Lambda functions handle real-time operations:

### 1. Assignment Lambda (`backend/lambda/assignment/`)

- Triggered by: API Gateway (tracking API)
- Purpose: High-throughput variant assignment
- DynamoDB for fast assignment storage
- Falls back to REST API for rules evaluation

### 2. Event Processor Lambda (`backend/lambda/event_processor/`)

- Triggered by: Kinesis Data Stream
- Purpose: Process event stream, aggregate metrics
- Feeds data into OpenSearch for analytics
- Handles deduplication and late-arriving events

### 3. Feature Flag Evaluation Lambda (`backend/lambda/feature_flag_evaluation/`)

- Triggered by: API Gateway (evaluation API)
- Purpose: Sub-10ms feature flag evaluation at scale
- 71 tests covering the handler, the cache and the evaluation path
- Local Redis cache for rule compilation

---

## Background Schedulers

Five background jobs start with the API process (`lifespan` in `backend/app/main.py`):

| Scheduler | Default cycle | Responsibility |
|-----------|---------------|----------------|
| Experiment scheduler | 15 min | Starts/stops experiments at `start_date` / `end_date` |
| Rollout scheduler | 15 min | Advances feature-flag rollout stages |
| Metrics scheduler | 15 min | Aggregates raw metrics |
| Safety monitor | 5 min | Checks per-flag safety thresholds, triggers rollbacks |
| Bandit scheduler | `BANDIT_UPDATE_INTERVAL_MINUTES` (5) | Recomputes multi-armed bandit weights (DynamoDB counters → PostgreSQL fallback) |

### Experiment Scheduler (every 15 min)

Transitions experiments based on `start_date`/`end_date`:
- `DRAFT` + `start_date ≤ now` → `ACTIVE`
- `ACTIVE` + `end_date ≤ now` → `COMPLETED`

```python
# API: schedule an experiment
PUT /api/v1/experiments/{id}/schedule
{
  "start_date": "2026-04-01T00:00:00Z",
  "end_date": "2026-04-15T23:59:59Z"
}
```

### Rollout Scheduler (every 15 min)

Advances feature flag rollout stages:
- Activates `TIME_BASED` stages once their `start_date` has passed (a stage never starts early, even
  when the previous stage has completed)
- Completes an `IN_PROGRESS` stage after its `trigger_configuration.duration` hours (default 24)
- Updates `rollout_percentage` on FeatureFlag
- Transitions stage status: `PENDING → IN_PROGRESS → COMPLETED`

### Safety Monitor (every 5 min)

Monitors active feature flags that have an enabled safety configuration:
- Reads error metrics from `error_logs` and latency metrics from `raw_metrics`
- Compares each configured metric against its thresholds
- Rolls the flag back to its `rollback_percentage` when a critical threshold is breached
- Records a `SafetyRollbackRecord`

```python
# Configure safety for a feature flag
POST /api/v1/safety/feature-flags/{feature_flag_id}/config
{
  "enabled": true,
  "metrics": {
    "error_rate": {"warning_threshold": 0.02, "critical_threshold": 0.05, "comparison_type": "greater_than"},
    "p95_latency": {"warning_threshold": 300, "critical_threshold": 500, "comparison_type": "greater_than"}
  },
  "rollback_percentage": 0
}
```

### Bandit Scheduler (every `BANDIT_UPDATE_INTERVAL_MINUTES`)

Recomputes variant weights for multi-armed bandit experiments and persists them in `bandit_state`;
`POST /api/v1/tracking/assign` routes new users by those weights. See
[Multi-Armed Bandit](../api/multi-armed-bandit.md).

---

## Caching Architecture

### Two-Level Cache

**Level 1: Application Cache (in-process)**
- Rules compilation: LRU(10,000) — compiled rule ASTs
- Evaluation results: LRU(1,000) with 300s TTL

**Level 2: Redis Cache**
- Feature flag state: 60s TTL
- User assignments: 3600s TTL
- Session tokens: per `ACCESS_TOKEN_EXPIRE_MINUTES`

### Cache Invalidation

```bash
# Invalidate results cache for an experiment
POST /api/v1/results/{id}/invalidate-cache

# Force fresh feature flag state
GET /api/v1/feature-flags/evaluate/{flag_key}?skip_cache=true
```

---

## Database Schema

Schema: `experimentation` (set via `POSTGRES_SCHEMA` env var)

### Key Tables

```sql
-- All tables are in the `experimentation` schema
experimentation.users
experimentation.experiments
experimentation.variants
experimentation.metrics
experimentation.assignments      -- User-variant assignment log
experimentation.events           -- Tracking events
experimentation.feature_flags
experimentation.rollout_schedules
experimentation.rollout_stages
experimentation.safety_settings
experimentation.safety_rollback_records
experimentation.audit_logs       -- Change audit trail
```

### Unique Constraints

- `experiments.key` — unique per tenant
- `feature_flags.key` — unique per tenant
- `assignments(experiment_id, user_id)` — one variant per user per experiment
- `variants` traffic allocation: 0 ≤ x ≤ 100

---

## Migration Workflow

```bash
# 1. Modify model in backend/app/models/
# 2. Generate migration
cd /path/to/project
source venv/bin/activate
export POSTGRES_DB=experimentation POSTGRES_SCHEMA=experimentation
python -m alembic -c backend/app/db/alembic.ini revision --autogenerate -m "add feature column"

# 3. Review generated file
# backend/app/db/migrations/versions/xxxx_add_feature_column.py
# Verify: down_revision, column types, schema prefix

# 4. Apply
python -m alembic -c backend/app/db/alembic.ini upgrade heads

# 5. Verify
python -m alembic -c backend/app/db/alembic.ini current
```

---

## API Design Conventions

### Versioning

All API routes are prefixed with `/api/v1/`. Future versions will use `/api/v2/`.

### Response Envelope

Success responses return the resource directly (no envelope):
```json
{"id": "...", "name": "...", "status": "ACTIVE"}
```

Error responses follow RFC 7807:
```json
{"detail": "Not enough permissions"}
```

Paginated list responses:
```json
{
  "items": [...],
  "total": 100,
  "page": 1,
  "size": 20
}
```

### Status Codes

| Code | When |
|------|------|
| 200 | GET, PUT success |
| 201 | POST (create) success |
| 204 | DELETE success |
| 400 | Validation error |
| 401 | Missing/invalid authentication |
| 403 | Authenticated but insufficient permissions |
| 404 | Resource not found |
| 409 | Conflict (duplicate key, invalid state transition) |
| 422 | Unprocessable entity (Pydantic validation failure) |

---

## Use Cases

### Use Case 1: A/B Test a Checkout Flow

**Scenario:** Engineering wants to test a simplified 2-step checkout vs the current 4-step flow.

**Implementation:**

```python
# Step 1: Create experiment
POST /api/v1/experiments
{
  "name": "Simplified Checkout Test",
  "key": "checkout-simplified",
  "type": "A_B",
  "targeting_rules": {
    "operator": "AND",
    "rules": [
      {"attribute": "country", "operator": "IN", "value": ["US"]},
      {"attribute": "account_age_days", "operator": "GREATER_THAN", "value": 7}
    ]
  },
  "variants": [
    {"name": "Control (4-step)", "is_control": true, "traffic_allocation": 50},
    {"name": "Treatment (2-step)", "is_control": false, "traffic_allocation": 50}
  ],
  "metrics": [
    {"name": "Purchase Complete", "event_name": "purchase_complete", "metric_type": "CONVERSION", "is_primary": true},
    {"name": "Revenue", "event_name": "purchase_complete", "metric_type": "REVENUE", "is_primary": false}
  ]
}
```

```javascript
// Step 2: In your frontend checkout page
const { variant_name } = await assignUser('user-123', 'checkout-simplified', {
  country: 'US',
  account_age_days: user.daysOnPlatform,
});

if (variant_name === 'Treatment (2-step)') {
  renderSimplifiedCheckout();
} else {
  renderCurrentCheckout();
}

// Step 3: Track conversion
await trackEvent('purchase_complete', 'user-123', 'checkout-simplified', {
  value: orderTotal,
  metadata: { order_id: orderId },
});
```

---

### Use Case 2: Gradual Feature Flag Rollout

**Scenario:** Ship a new recommendation engine to 5% → 25% → 100% over 3 weeks.

```python
# Step 1: Create flag
POST /api/v1/feature-flags
{"key": "new-recommendations", "name": "New Recommendation Engine", "rollout_percentage": 0}

# Step 2: Create rollout schedule
POST /api/v1/rollout-schedules
{
  "feature_flag_id": "FLAG_ID",
  "name": "Recommendation Engine Rollout",
  "stages": [
    {"stage_order": 1, "target_percentage": 5,   "trigger_type": "TIME_BASED", "start_date": "2026-04-01T00:00:00Z"},
    {"stage_order": 2, "target_percentage": 25,  "trigger_type": "TIME_BASED", "start_date": "2026-04-08T00:00:00Z"},
    {"stage_order": 3, "target_percentage": 100, "trigger_type": "MANUAL"}
  ]
}

# Step 3: Activate the schedule
POST /api/v1/rollout-schedules/SCHEDULE_ID/activate
```

The background scheduler automatically advances stages at the specified times. Stage 3 requires manual advancement:

```bash
POST /api/v1/rollout-schedules/stages/STAGE3_ID/advance
```

---

### Use Case 3: Targeting High-Value Users

**Scenario:** Only run an experiment for users on a paid plan, in the US/EU, who have been active in the last 30 days.

```json
{
  "targeting_rules": {
    "operator": "AND",
    "rules": [
      {"attribute": "plan", "operator": "IN", "value": ["pro", "enterprise"]},
      {"attribute": "country", "operator": "IN", "value": ["US", "GB", "DE", "FR"]},
      {"attribute": "days_since_last_login", "operator": "LESS_THAN", "value": 30},
      {
        "operator": "OR",
        "rules": [
          {"attribute": "lifetime_value", "operator": "GREATER_THAN", "value": 100},
          {"attribute": "subscription_months", "operator": "GREATER_THAN", "value": 6}
        ]
      }
    ]
  }
}
```

Pass user attributes in the context:
```javascript
await assignUser(userId, 'premium-feature-test', {
  plan: user.subscriptionPlan,
  country: user.countryCode,
  days_since_last_login: user.daysSinceLastLogin,
  lifetime_value: user.ltv,
  subscription_months: user.subscriptionMonths,
});
```

---

### Use Case 4: Safety-Gated Feature Flag

**Scenario:** New payment provider integration with auto-rollback if error rate > 2%.

```python
# Create flag
POST /api/v1/feature-flags
{"key": "new-payment-provider", "rollout_percentage": 5}

# Configure safety monitoring
POST /api/v1/safety/feature-flags/{feature_flag_id}/config
{
  "feature_flag_id": "FLAG_ID",
  "max_error_rate": 0.02,     # 2% error rate triggers rollback
  "max_latency_p99": 2000,    # 2s p99 latency threshold
  "window_seconds": 300,      # Monitor over 5-minute windows
  "auto_rollback": true,
  "rollback_percentage": 0    # Roll back to 0% on trigger
}

# Track errors in your payment service
POST /api/v1/tracking/track
{
  "event_type": "payment_error",
  "user_id": "user-123",
  "feature_flag_key": "new-payment-provider",
  "value": 1
}
```

The safety monitor automatically sets `rollout_percentage=0` and creates a rollback record if the error threshold is breached.

---

## Performance Characteristics

| Operation | Throughput | Latency (p99) |
|-----------|-----------|---------------|
| Variant assignment (cached) | 50,000 req/s | <5ms |
| Feature flag evaluation | 100,000 req/s | <3ms |
| Event tracking | 10,000 events/s | <20ms |
| Batch tracking (100 events) | 1,000 batches/s | <50ms |
| Rules evaluation (simple) | 125,000 ops/s | <1ms |
| Results computation | 10 exps/s | <200ms |

---

## Infrastructure (AWS)

| Service | Usage |
|---------|-------|
| ECS Fargate | API container hosting |
| Aurora PostgreSQL | Primary database |
| ElastiCache Redis | Caching layer |
| Kinesis Data Streams | Event ingestion |
| Lambda | Real-time assignment + evaluation |
| Cognito | User authentication |
| CloudWatch | Monitoring + alerting |
| Secrets Manager | Credentials storage |

The dashboard is not yet deployed by the CDK (#69): no stack hosts it, and
nothing creates CloudFront or an S3 bucket for it. In Docker Compose and in the
`frontend/Dockerfile` image it is served by nginx, which also proxies `/api/` to
the API.

---

## Monitoring & Observability

### Key Metrics (CloudWatch)

- `api.request.duration` — p50, p95, p99 per endpoint
- `rules.evaluation.duration` — rules engine latency
- `assignment.throughput` — assignments per second
- `event.ingestion.rate` — events per second
- `feature_flag.evaluation.rate` — evaluations per second
- `db.query.duration` — query latency
- `cache.hit_rate` — cache efficiency

### Log Structure

All logs follow structured JSON format:

```json
{
  "timestamp": "2026-03-01T10:00:00Z",
  "level": "INFO",
  "service": "experimentation-api",
  "request_id": "req-abc123",
  "user_id": "user-456",
  "endpoint": "/api/v1/tracking/assign",
  "duration_ms": 12,
  "experiment_key": "homepage-test",
  "variant": "Treatment"
}
```

### Dashboards

- Overview: http://localhost:8000/docs#/monitoring
- CloudWatch: `/experimentation-platform/api` log group
- Health: http://localhost:8000/health
