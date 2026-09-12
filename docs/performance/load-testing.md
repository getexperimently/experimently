# Load Testing — Experimentation Platform

## Overview

The load testing framework uses [Locust](https://locust.io/) to validate that the
experimentation platform API meets its SLA (Service Level Agreement) performance targets
under realistic and extreme traffic conditions.

Three test types are provided:

| Test | Script | Purpose | Duration |
|------|--------|---------|----------|
| Baseline | `api_load_test.py` | Normal production-like traffic | 60–120s |
| Spike | `spike_test.py` | Sudden traffic burst (10 → 1000 users) | 120s |
| Endurance | `endurance_test.py` | Sustained load, memory/leak detection | 30 min |

---

## Performance SLA Targets

These targets are defined in `backend/tests/performance/specs/performance_targets.py`
and serve as the authoritative contracts for API performance.

| Endpoint | Method | p50 | p95 | p99 | Min RPS |
|----------|--------|-----|-----|-----|---------|
| `POST /api/v1/tracking/assign` | POST | < 50ms | < 200ms | < 500ms | > 500 |
| `POST /api/v1/tracking/track` | POST | < 30ms | < 100ms | < 300ms | > 1000 |
| `GET /api/v1/feature-flags/evaluate/{key}` | GET | < 20ms | < 80ms | < 200ms | > 2000 |
| `GET /api/v1/experiments` | GET | < 100ms | < 300ms | < 800ms | > 200 |
| `GET /health` | GET | < 10ms | < 30ms | < 100ms | > 5000 |

A test **passes** when all of the following hold simultaneously:
- p50, p95, and p99 response times are at or below the target thresholds
- Error rate is at or below 1%
- Achieved RPS meets or exceeds the minimum target

---

## File Structure

```
backend/tests/performance/
├── __init__.py
├── specs/
│   ├── __init__.py
│   └── performance_targets.py    # SLA contract definitions
├── validators.py                  # Result parsing and SLA validation logic
├── test_specs.py                  # Unit tests for SLA specs
├── test_validators.py             # Unit tests for validators
├── run_load_tests.py              # CI runner script
└── locustfiles/
    ├── __init__.py
    ├── api_load_test.py           # Baseline load test
    ├── spike_test.py              # Spike test with LoadTestShape
    └── endurance_test.py          # 30-minute endurance test
```

---

## Running Load Tests Locally

### Prerequisites

```bash
# Activate the virtual environment
source /Users/ashishmarkanday/github/experimentation-platform/venv/bin/activate

# Ensure dependencies are installed (includes locust==2.17.0)
pip install -r backend/requirements.txt

# Start the backend API server (in a separate terminal)
# from the repository root
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

### Option A: Locust Web UI (interactive)

```bash
cd /Users/ashishmarkanday/github/experimentation-platform

# Baseline test
locust -f backend/tests/performance/locustfiles/api_load_test.py \
       --host http://localhost:8000

# Spike test
locust -f backend/tests/performance/locustfiles/spike_test.py \
       --host http://localhost:8000

# Endurance test
locust -f backend/tests/performance/locustfiles/endurance_test.py \
       --host http://localhost:8000
```

Then open `http://localhost:8089` in your browser, configure the number of users
and spawn rate, and click **Start swarming**.

### Option B: Headless mode (no browser)

```bash
cd /Users/ashishmarkanday/github/experimentation-platform

# Baseline — 50 users, 60 seconds
locust -f backend/tests/performance/locustfiles/api_load_test.py \
       --headless \
       --users 50 \
       --spawn-rate 10 \
       --run-time 60s \
       --host http://localhost:8000 \
       --csv /tmp/locust_baseline

# Results are written to:
#   /tmp/locust_baseline_stats.csv
#   /tmp/locust_baseline_stats_history.csv
#   /tmp/locust_baseline_failures.csv
```

### Option C: CI runner (validates SLAs automatically)

```bash
cd /Users/ashishmarkanday/github/experimentation-platform
source venv/bin/activate

python backend/tests/performance/run_load_tests.py \
    --host http://localhost:8000 \
    --users 50 \
    --spawn-rate 10 \
    --duration 60s

# Exit code 0 = all SLAs met
# Exit code 1 = SLA violation(s) detected
```

The runner can also start a local server automatically:

```bash
python backend/tests/performance/run_load_tests.py \
    --start-server \
    --server-port 8001 \
    --users 50 \
    --duration 60s
```

---

## Understanding Test Types

### Baseline (`api_load_test.py`)

Simulates normal production traffic with two user classes:

- **TrackingUser** (80% of load, weight=8): Calls `POST /tracking/track` (3x) and
  `POST /tracking/assign` (1x) with short waits (10–50ms between tasks)
- **APIUser** (20% of load, weight=2): Calls `GET /experiments`, `GET /feature-flags/evaluate/{key}`,
  and `GET /health` with longer waits (0.5–2s between tasks)

**Use for**: Verifying baseline SLA compliance before a release.

### Spike (`spike_test.py`)

Uses `LoadTestShape` to drive a four-stage traffic profile:

| Stage | Duration | Users | Spawn Rate |
|-------|----------|-------|------------|
| Baseline | 0–30s | 10 | 10/s |
| Spike ramp | 30–60s | 1000 | 100/s |
| Sustain peak | 60–90s | 1000 | 1/s |
| Recovery | 90–120s | 10 | 100/s |

**Use for**: Detecting connection pool exhaustion, circuit breaker triggers, and
latency spikes during sudden traffic bursts.

### Endurance (`endurance_test.py`)

Runs 100 concurrent users with realistic task weights for 30 minutes.
Logs a metrics snapshot every 5 minutes to detect gradual degradation.

**Use for**: Detecting memory leaks, DB connection pool leaks, and performance
regression that only manifests after extended operation.

---

## Reading the Results CSV

Locust produces three CSV files when run with `--csv <prefix>`:

| File | Content |
|------|---------|
| `<prefix>_stats.csv` | Aggregate per-endpoint statistics (p50, p95, p99, RPS) |
| `<prefix>_stats_history.csv` | Time-series stats sampled every 2 seconds |
| `<prefix>_failures.csv` | Details of any failed requests |

### Key columns in `_stats.csv`

| Column | Description |
|--------|-------------|
| `Type` | HTTP method (GET, POST, …) |
| `Name` | Endpoint path |
| `Request Count` | Total requests sent |
| `Failure Count` | Number of 4xx/5xx responses |
| `50%` | p50 response time in ms |
| `95%` | p95 response time in ms |
| `99%` | p99 response time in ms |
| `Requests/s` | Average RPS during the test |

The last row (`Aggregated`) is a summary across all endpoints — the validators
skip this row automatically.

---

## Interpreting CI Results

The `run_load_tests.py` runner produces a structured report after each run:

```
============================================================
PERFORMANCE TEST REPORT
============================================================
Total endpoints: 5  |  Passed: 4  |  Failed: 1
------------------------------------------------------------
[PASS] /health
[PASS] /api/v1/tracking/track
[PASS] /api/v1/feature-flags/evaluate/{key}
[PASS] /api/v1/experiments
[FAIL] /api/v1/tracking/assign
       - p95 exceeded: 245.0ms > 200ms target
       - RPS below target: 420.3 < 500 required RPS
============================================================
1 endpoint(s) failed SLA targets.
============================================================
```

**If a test fails**:
1. Check the `_stats.csv` artifact uploaded by the CI workflow
2. Compare against the SLA targets in `performance_targets.py`
3. Look at the `_stats_history.csv` for time-series degradation
4. Check `_failures.csv` for error details

---

## Updating SLA Targets

SLA targets are defined in:
```
backend/tests/performance/specs/performance_targets.py
```

To add a new endpoint target:

```python
PERFORMANCE_TARGETS["batch_evaluate"] = PerformanceTarget(
    endpoint="/api/v1/feature-flags/evaluate-batch",
    method="POST",
    p50_ms=40,
    p95_ms=150,
    p99_ms=400,
    min_rps=800,
    description="Batch feature flag evaluation",
)
```

After updating targets, run the spec unit tests to verify consistency:

```bash
source venv/bin/activate
python -m pytest backend/tests/performance/test_specs.py -v
```

To update an existing target (e.g., after a performance improvement):

1. Update the values in `performance_targets.py`
2. Run the spec tests to verify `p50 < p95 < p99` still holds
3. Create a git commit documenting the new SLA
4. Trigger the CI workflow to validate the new targets against the live system

---

## Adding Load Tests for New Endpoints

1. Add a `PerformanceTarget` entry in `performance_targets.py`
2. Write spec tests in `test_specs.py` covering the new target
3. Add a `@task` method to the appropriate user class in `api_load_test.py`
4. Run the validator unit tests to confirm everything works
5. Trigger a CI baseline run to establish a performance baseline

---

## Running Unit Tests for the Load Test Framework

```bash
source venv/bin/activate
export APP_ENV=test TESTING=true

# Test the SLA spec definitions
python -m pytest backend/tests/performance/test_specs.py -v

# Test the validators (percentile calculations, SLA checks, CSV parsing, reporting)
python -m pytest backend/tests/performance/test_validators.py -v

# Run both together
python -m pytest backend/tests/performance/test_specs.py \
                 backend/tests/performance/test_validators.py -v
```

All 43 unit tests should pass without a running database or API server.
