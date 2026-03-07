# Autonomous Real-World Testing Framework

**Status**: Implemented — Phase 1 (data generation) and Phase 2 (agent layer) complete.
**Phase 3** (self-healing loop) is live via the `auto-fixer` agent and `/autotest` skill.

---

## Overview

The Experimently platform includes an autonomous testing framework that goes beyond
traditional unit and integration tests.  While the platform already has 3,250+ unit tests,
API integration tests, load tests, and smoke tests, this framework adds:

1. **Statistically realistic data** — synthetic data that behaves like the real world,
   not just valid shapes
2. **Browser-based UI simulation** — agents that click through the dashboard as real
   users would
3. **Statistical correctness validation** — verifying that p-values, variance reduction,
   and traffic allocation are mathematically correct
4. **Self-healing** — when a test fails, an agent diagnoses the root cause, writes the
   fix, and verifies it

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│   1. GENERATE          2. SIMULATE            3. VALIDATE               │
│   data-generator       scenario-runner        validator                 │
│   agent                agent (Playwright)     agent                     │
│                                                                          │
│                              ▼ failure detected                         │
│                                                                          │
│   4. DIAGNOSE          5. FIX                 6. VERIFY & COMMIT        │
│   auto-fixer           auto-fixer             auto-fixer                │
│   agent                agent                  agent                     │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

Orchestrated by the `/autotest` skill (`.claude/commands/autotest.md`).

---

## File Layout

```
.claude/
  agents/
    reviewer.md           # Code review agent (pre-existing)
    tester.md             # Test writing agent (pre-existing)
    data-generator.md     # Realistic data seeding agent
    scenario-runner.md    # UI simulation agent (Playwright)
    validator.md          # Statistical correctness validator
    auto-fixer.md         # Self-healing repair agent
  commands/
    autotest.md           # /autotest orchestration skill

backend/tests/realistic/
  __init__.py
  data_generator.py             # Core synthetic data engine
  test_api_fuzzing.py           # Schemathesis API fuzzing
  scenarios/
    ab_test_lifecycle.py        # Full A/B test lifecycle
    feature_flag_rollout.py     # Gradual rollout scenario
    statistical_edge_cases.py   # Edge case scenarios
    concurrent_experiments.py   # MEG + interaction testing
  profiles/
    casual_user.py              # Casual user behavioral profile
    power_user.py               # Power user behavioral profile
    churn_risk_user.py          # Churn risk behavioral profile

frontend/
  playwright.config.ts          # Playwright browser automation config
```

---

## Data Generator

The core engine is `backend/tests/realistic/data_generator.py`.

### What it produces

- Statistically realistic CVR data (not flat random)
- Novelty effects (day-1 spike → steady state)
- Day-of-week patterns (weekday 1.2× vs weekend 0.7×)
- Session decay (engagement drops 15%/week)
- Outlier users (bots, whales — lognormal value distribution)
- Intentional edge cases (multi-assignment bugs, metric drift, Simpson's paradox)

### Pre-built scenarios

| Scenario | Users | Control CVR | Treatment CVR | Z-score |
|----------|-------|-------------|---------------|---------|
| `ab_test_lifecycle` | 1,000 | 8% | 9.5% | ~2.2 (significant) |
| `feature_flag_rollout` | 2,000 | 5% | 5.1% | ~0.4 (not significant) |
| `novelty_effect` | 1,500 | 10% | 11% + spike | ~1.9 (marginal) |
| `statistical_edge_cases` | 3,000 | 6% | 7.2% | ~2.8 (significant) |
| `concurrent_experiments` | 5,000 | 7% | 8.2% | ~3.5 (significant) |

### CLI usage

```bash
# Dry run — generate data, print summary, no API call
source venv/bin/activate
python backend/tests/realistic/data_generator.py --scenario ab_test_lifecycle --dry-run

# Seed into running platform
python backend/tests/realistic/data_generator.py \
  --scenario ab_test_lifecycle \
  --api-url http://localhost:8000 \
  --token <JWT>

# All scenarios
python backend/tests/realistic/data_generator.py --scenario all --dry-run
```

---

## User Behavioral Profiles

Three behavioral profiles model different user segments:

### Casual User (`profiles/casual_user.py`)
- 1–2 sessions/week, 3% CVR, 65% bounce rate
- Sensitive to UX complexity (treatment uplift may be negative)

### Power User (`profiles/power_user.py`)
- 6 sessions/week, 20% CVR, 10% bounce rate
- Early adopter — responds positively to new features

### Churn Risk User (`profiles/churn_risk_user.py`)
- Declining engagement over 4 weeks (10% → 2% CVR)
- Re-engagement boost from treatment (+15% CVR)
- Useful for holdout group and novelty effect testing

---

## Agents

### `data-generator` agent
Invoked when you need realistic scenario data.  Calls the data generator,
optionally seeds the API, and returns a summary of what was created.

### `scenario-runner` agent
Walks through the dashboard UI using Playwright MCP.  Validates UI state
at each step and cross-checks against the backend API.

### `validator` agent
Verifies statistical correctness of results: p-values, CUPED variance reduction,
MAB traffic allocation, and sequential testing signals.

### `auto-fixer` agent
When tests fail: reads the error, traces the root cause, writes the minimal fix,
verifies it passes, and commits it.  Stops if the fix is ambiguous or large.

---

## The `/autotest` Skill

One command to run the full autonomous loop:

```
/autotest [scenario_name or "all"]
```

Execution order:
1. `data-generator` — seed realistic data
2. `scenario-runner` — validate UI behavior
3. `validator` — check statistical correctness
4. `reviewer` — review recent code changes
5. `tester` — verify test coverage
6. `auto-fixer` — repair any failures found

Produces a consolidated pass/fail report.

---

## API Fuzzing

`backend/tests/realistic/test_api_fuzzing.py` uses Schemathesis to automatically
generate adversarial inputs for every endpoint in the OpenAPI spec.

```bash
# Install schemathesis
pip install schemathesis

# Run against running platform
RUN_FUZZING=1 python -m pytest backend/tests/realistic/test_api_fuzzing.py -v
```

Validates:
- No endpoint returns 500 for schema-valid inputs
- Invalid inputs produce 422, not 500
- Response bodies conform to declared schemas
- No internal details leaked in error responses

---

## Playwright Setup

The browser automation layer uses `@playwright/mcp` as an MCP server.

### Install Playwright

```bash
cd frontend
npm install --save-dev @playwright/test
npx playwright install chromium
```

### Register Playwright MCP (Claude Code settings)

Add to `.mcp.json` or Claude Code MCP configuration:

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@latest"],
      "env": {
        "PLAYWRIGHT_HEADLESS": "true"
      }
    }
  }
}
```

### Run Playwright tests directly

```bash
cd frontend
npx playwright test           # headless
npx playwright test --headed  # with browser window
npx playwright test --ui      # interactive mode
```

---

## Running the Full Suite

```bash
# 1. Start the platform
docker-compose up -d

# 2. Activate venv
source venv/bin/activate

# 3. Verify data generator works
python backend/tests/realistic/data_generator.py --scenario ab_test_lifecycle --dry-run

# 4. Run existing unit tests (should still be green)
export APP_ENV=test TESTING=true
python -m pytest backend/tests/unit/ -p no:cov -q

# 5. Run scenario tests (offline — no API needed)
python -m pytest backend/tests/realistic/scenarios/ -v

# 6. Run API fuzzing (requires running platform)
RUN_FUZZING=1 python -m pytest backend/tests/realistic/test_api_fuzzing.py -v

# 7. Run full /autotest loop
/autotest ab_test_lifecycle
```

---

## Success Metrics

| Metric | Target | Status |
|--------|--------|--------|
| Scenario coverage | 5+ real-world scenarios | ✅ 5 scenarios implemented |
| Data realism | p < 0.05 at correct sample size | ✅ z-scores validated |
| User profiles | 3+ behavioral archetypes | ✅ casual, power, churn risk |
| Agent coverage | data-gen, scenario-runner, validator, auto-fixer | ✅ all 4 implemented |
| API fuzzing | Zero-maintenance adversarial testing | ✅ Schemathesis integration |
| Orchestration | Single `/autotest` command | ✅ skill implemented |
