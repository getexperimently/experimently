# Performance Testing Guide

This guide covers the performance and load testing framework for the experimentation platform. It explains how to run tests, interpret results, tune SLA targets, and extend the framework.

## Quick Start

```bash
# 1. Activate the virtual environment
source venv/bin/activate

# 2. Run spec/validator tests (no server needed)
export APP_ENV=test TESTING=true
python -m pytest backend/tests/performance/ -v --tb=short -p no:cov

# 3. Run a baseline load test against a running server
python backend/tests/performance/run_load_tests.py \
    --profile baseline \
    --host http://localhost:8000 \
    --users 50 \
    --duration 60s

# 4. Or start a local server automatically
python backend/tests/performance/run_load_tests.py \
    --profile baseline \
    --start-server \
    --users 50 \
    --duration 60s
```

## Test Profiles

The framework includes six test profiles, each targeting different aspects of system performance.

| Profile | Locustfile | Purpose | Typical Duration |
|---|---|---|---|
| `baseline` | `api_load_test.py` | Standard production traffic mix (80% tracking, 20% API) | 60s–5m |
| `spike` | `spike_test.py` | Sudden traffic burst (10 → 1000 → 10 users) | 2m (auto) |
| `endurance` | `endurance_test.py` | Sustained load for memory/resource leak detection | 30m |
| `crud` | `crud_load_test.py` | CRUD operations (create/update/delete experiments & flags) | 60s–5m |
| `db-stress` | `db_stress_test.py` | Database stress (concurrent writes, reads, complex queries) | 60s–5m |
| `breakpoint` | `breakpoint_test.py` | Find system limits (ramp 10 → 2000 users) | 7m (auto) |

### Running a Profile

Use the `--profile` convenience argument:

```bash
python backend/tests/performance/run_load_tests.py --profile crud --users 100 --duration 120s
python backend/tests/performance/run_load_tests.py --profile db-stress --users 200 --duration 5m
python backend/tests/performance/run_load_tests.py --profile breakpoint  # duration auto-managed by shape
```

Or specify a locustfile directly:

```bash
python backend/tests/performance/run_load_tests.py \
    --locustfile backend/tests/performance/locustfiles/crud_load_test.py \
    --users 100 --duration 120s
```

## SLA Targets

Performance targets are defined in `backend/tests/performance/specs/performance_targets.py`. Each target specifies latency percentiles (p50/p95/p99) and minimum throughput (RPS).

### Current Targets

| Target | Endpoint | Method | p50 | p95 | p99 | Min RPS |
|---|---|---|---|---|---|---|
| assign | /api/v1/tracking/assign | POST | 50ms | 200ms | 500ms | 500 |
| track | /api/v1/tracking/track | POST | 30ms | 100ms | 300ms | 1000 |
| evaluate_flag | /api/v1/feature-flags/evaluate/{key} | GET | 20ms | 80ms | 200ms | 2000 |
| batch_evaluate_flags | /api/v1/feature-flags/evaluate-batch | POST | 80ms | 300ms | 800ms | 500 |
| create_experiment | /api/v1/experiments | POST | 150ms | 400ms | 1000ms | 100 |
| update_experiment | /api/v1/experiments/{id} | PUT | 120ms | 350ms | 900ms | 100 |
| create_feature_flag | /api/v1/feature-flags | POST | 120ms | 350ms | 900ms | 150 |
| update_feature_flag | /api/v1/feature-flags/{id} | PUT | 100ms | 300ms | 800ms | 150 |
| delete_experiment | /api/v1/experiments/{id} | DELETE | 100ms | 300ms | 800ms | 100 |
| list_experiments | /api/v1/experiments | GET | 100ms | 300ms | 800ms | 200 |
| get_experiment_results | /api/v1/experiments/{id}/results | GET | 200ms | 600ms | 1500ms | 50 |
| bulk_flag_toggle | /api/v1/feature-flags/bulk-toggle | POST | 200ms | 500ms | 1200ms | 50 |
| health | /health | GET | 10ms | 30ms | 100ms | 5000 |

### Target Groups

Targets are organized into logical groups:

- **tracking**: assign, track — high-frequency SDK calls
- **evaluation**: evaluate_flag, batch_evaluate_flags — feature flag evaluation
- **crud**: create/update/delete experiments and feature flags — dashboard operations
- **analytics**: list_experiments, get_experiment_results — read-heavy queries
- **bulk_operations**: bulk_flag_toggle — batch operations
- **infrastructure**: health — health checks and monitoring

## CI Integration

Performance tests run via GitHub Actions (`.github/workflows/performance-tests.yml`):

- **Schedule**: Weekly on Monday at 02:00 UTC (baseline profile)
- **Manual dispatch**: Select any profile via the `test_type` dropdown

### Manual Trigger

1. Go to **Actions** → **Performance Tests** → **Run workflow**
2. Select parameters:
   - `test_type`: baseline, spike, endurance, crud, db_stress, breakpoint
   - `users`: Concurrent user count (default: 100)
   - `duration`: Test duration (default: 120s)
   - `host`: Target host (default: http://localhost:8000)
3. Click **Run workflow**

### CI Artifacts

Each run uploads:
- `locust-results-{type}-{run}`: Stats CSV with endpoint-level metrics
- `locust-history-{type}-{run}`: Per-second history CSV (for breakpoint analysis)

## Interpreting Results

### Validation Report

The runner produces a report like:

```
============================================================
PERFORMANCE TEST REPORT
============================================================
Total endpoints: 5  |  Passed: 4  |  Failed: 1
------------------------------------------------------------
[PASS] /api/v1/tracking/track
[PASS] /api/v1/tracking/assign
[PASS] /api/v1/feature-flags/evaluate/{key}
[FAIL] /api/v1/experiments
       - p95 exceeded: 450.0ms > 300ms target
       - RPS below target: 150.2 < 200 required RPS
[PASS] /health
============================================================
1 endpoint(s) failed SLA targets.
============================================================
```

### Breakpoint Analysis

When running the breakpoint profile, the enhanced report includes:

```
============================================================
BREAKPOINT ANALYSIS
============================================================
Max stable users    : 500
Breaking RPS        : 1250.3
Breaking error rate : 6.20%
Breaking p99        : 2150ms
Stages completed    : 5
Status: Degradation detected — consider scaling
============================================================
```

### Key Metrics to Watch

| Metric | What It Means | Action If Failing |
|---|---|---|
| p95 exceeded | 95th percentile latency is too high | Optimize query, add caching, scale up |
| p99 exceeded | Tail latency is too high | Check for GC pauses, connection pool limits |
| Error rate > 1% | Too many 4xx/5xx responses | Check error logs, circuit breakers |
| RPS below target | Throughput is insufficient | Scale out, optimize hot paths |

## Capacity Planning

The capacity planner (`backend/tests/performance/analyzers/capacity_planner.py`) extrapolates load test results to estimate production requirements.

```python
from backend.tests.performance.analyzers.capacity_planner import (
    estimate_capacity,
    generate_capacity_report,
)

# Endpoint RPS data from a load test run
endpoint_rps = [
    ("/api/v1/tracking/track", 850.0),
    ("/api/v1/feature-flags/evaluate/{key}", 1500.0),
    ("/api/v1/experiments", 180.0),
]

# Plan for 5000 RPS with 50% headroom
estimates = estimate_capacity(endpoint_rps, target_rps=5000)
print(generate_capacity_report(estimates))
```

The formula: `instances = ceil(target_rps * 1.5 / rps_per_instance)`

## Query Analysis

The query analyzer (`backend/tests/performance/analyzers/db_query_analyzer.py`) parses PostgreSQL `pg_stat_statements` output to identify slow queries and missing indexes.

```python
from backend.tests.performance.analyzers.db_query_analyzer import (
    analyze_slow_queries,
    generate_query_report,
)

# Analyze queries slower than 100ms
slow = analyze_slow_queries("/tmp/pg_stats.csv", threshold_ms=100.0)
print(generate_query_report(slow))
```

## Adding New Tests

### 1. Add a New SLA Target

Edit `backend/tests/performance/specs/performance_targets.py`:

```python
PERFORMANCE_TARGETS["my_endpoint"] = PerformanceTarget(
    endpoint="/api/v1/my-endpoint",
    method="POST",
    p50_ms=100,
    p95_ms=300,
    p99_ms=800,
    min_rps=200,
    description="My new endpoint",
)
```

Add it to the appropriate target group:

```python
TARGET_GROUPS["crud"].target_keys.append("my_endpoint")
```

### 2. Add a New Locustfile

Create a new file in `backend/tests/performance/locustfiles/`:

```python
from locust import HttpUser, task, between

class MyUser(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self):
        self.headers = {"X-API-Key": os.environ.get("LOAD_TEST_API_KEY", "test-api-key")}

    @task
    def my_task(self):
        self.client.get("/api/v1/my-endpoint", headers=self.headers, catch_response=True)
```

### 3. Register the Profile

Add the mapping in `run_load_tests.py`:

```python
_PROFILE_LOCUSTFILES["my-profile"] = str(_THIS_DIR / "locustfiles" / "my_test.py")
```

And in `.github/workflows/performance-tests.yml` add the option to the `test_type` choice and the `case` statement.

### 4. Write Spec Tests

Add tests in `test_specs.py` to validate the new target's SLA values are consistent with the existing targets.

## Framework Architecture

```
backend/tests/performance/
├── specs/
│   └── performance_targets.py    # SLA contracts + target groups
├── locustfiles/
│   ├── api_load_test.py          # Baseline (tracking + API mix)
│   ├── spike_test.py             # Spike (LoadTestShape 4-stage)
│   ├── endurance_test.py         # Endurance (30-min sustained)
│   ├── crud_load_test.py         # CRUD operations
│   ├── db_stress_test.py         # Database stress
│   └── breakpoint_test.py        # Breakpoint/capacity finding
├── analyzers/
│   ├── db_query_analyzer.py      # Slow query analysis
│   └── capacity_planner.py       # Instance/capacity planning
├── validators.py                 # CSV parsing, SLA validation, reports
├── run_load_tests.py             # CI orchestrator
├── test_specs.py                 # SLA spec tests
├── test_validators.py            # Validator unit tests
└── test_load_profiles.py         # Load profile structure tests
```
