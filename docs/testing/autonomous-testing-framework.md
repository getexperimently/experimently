# Autonomous Real-World Testing Framework

**Status**: Implemented — All 6 phases operational.
**Test count**: 4,500+ platform-wide (backend ~4,000 | frontend 226 | Java SDK 86 | React SDK 98 | realistic scenarios 100+)

---

## Overview

The Experimently platform includes an autonomous testing framework that goes beyond
traditional unit and integration tests.  While the platform already has 4,500+ tests,
this framework adds:

1. **Statistically realistic data** — synthetic data that behaves like the real world,
   not just valid shapes
2. **Browser-based UI simulation** — agents that click through the dashboard as real
   users would
3. **Statistical correctness validation** — verifying that p-values, Bayesian posteriors,
   variance reduction, and traffic allocation are mathematically correct
4. **Smoke testing** — zero-mock infrastructure wiring tests catching auth, CORS,
   middleware, and router registration bugs
5. **Self-healing** — when a test fails, an agent diagnoses the root cause, writes the
   fix, and verifies it

---

## Architecture

```
┌───────────────────────────────────────────────────────────────────────────┐
│                                                                           │
│   1. GENERATE          2. SIMULATE            3. VALIDATE                │
│   data-generator       scenario-runner        validator                  │
│   agent                agent (Playwright)     agent                      │
│                                                                           │
│   4. REVIEW            5. TEST                6. AUTO-FIX                │
│   reviewer             tester                 auto-fixer                 │
│   agent                agent                  agent (if failures)        │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
```

Orchestrated by the `/autotest` skill (`.claude/commands/autotest.md`).

---

## File Layout

```
.claude/
  agents/
    reviewer.md           # Code review agent
    tester.md             # Test writing agent
    data-generator.md     # Realistic data seeding agent
    scenario-runner.md    # UI simulation agent (Playwright)
    validator.md          # Statistical correctness validator
    auto-fixer.md         # Self-healing repair agent
  commands/
    autotest.md           # /autotest orchestration skill

backend/tests/
  realistic/
    __init__.py
    data_generator.py               # Core synthetic data engine
    test_api_fuzzing.py             # Schemathesis API fuzzing
    scenarios/
      __init__.py
      ab_test_lifecycle.py          # Full A/B test lifecycle (5 tests)
      feature_flag_rollout.py       # Gradual rollout scenario (5 tests)
      statistical_edge_cases.py     # Edge case scenarios (11 tests)
      concurrent_experiments.py     # MEG + interaction testing (8 tests)
      llm_experiment_lifecycle.py   # LLM/AI model evaluation (EP-046, 30+ tests)
      bayesian_analysis.py          # Bayesian experimentation (EP-035, 25+ tests)
      variance_reduction.py         # CUPED + sequential testing (25+ tests)
      multi_tenant_isolation.py     # Workspace isolation (EP-057, 20+ tests)
    profiles/
      casual_user.py                # Casual user behavioral profile
      power_user.py                 # Power user behavioral profile
      churn_risk_user.py            # Churn risk behavioral profile
  smoke/
    __init__.py
    conftest.py
    test_wiring.py                  # Zero-mock infrastructure wiring tests (34+ tests)
    test_production.py              # Production deployment smoke tests (14 tests)

frontend/
  playwright.config.ts              # Playwright browser automation config
```

---

## Data Generator

The core engine is `backend/tests/realistic/data_generator.py`.

### What it produces

- Statistically realistic CVR data (not flat random)
- Novelty effects (day-1 spike → steady state)
- Day-of-week patterns (weekday 1.2x vs weekend 0.7x)
- Session decay (engagement drops 15%/week)
- Outlier users (bots, whales — lognormal value distribution)
- Intentional edge cases (multi-assignment bugs, metric drift, Simpson's paradox)

### Pre-built scenarios

| Scenario | Users | Control CVR | Treatment CVR | Notes |
|----------|-------|-------------|---------------|-------|
| `ab_test_lifecycle` | 6,000 | 8% | 9.5% | Day-of-week; 18.75% relative lift |
| `feature_flag_rollout` | 4,000 | 5% | 5.1% | Session decay; not significant |
| `novelty_effect` | 6,000 | 10% | 12% | 3-day novelty spike |
| `statistical_edge_cases` | 8,000 | 6% | 7.2% | All 4 edge cases injected |
| `concurrent_experiments` | 8,000 | 7% | 8.2% | Audience overlap testing |

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

## Scenario Tests by Feature Area

### Core A/B Testing (`ab_test_lifecycle.py`, `statistical_edge_cases.py`)
- Full experiment lifecycle through REST API
- Statistical significance validation (z-score ≥ 1.96)
- Zero-variance metrics, outlier contamination
- Simpson's paradox (subgroup reversal)
- Multi-assignment detection
- Metric drift injection
- Underpowered experiment detection
- Novelty effect day-1 spike validation

### Feature Flag Rollout (`feature_flag_rollout.py`)
- Three-stage rollout schedule (10% → 50% → 100%)
- Monotonic percentage progression
- Session decay reduces late engagement
- Event distribution tracks rollout percentage

### Concurrent Experiments (`concurrent_experiments.py`)
- 50/50 control/treatment split balance
- Unique user IDs per variant
- Zero population overlap by default
- Event timestamps after assignment
- Mutual exclusion group API integration

### LLM/AI Model Evaluation (`llm_experiment_lifecycle.py`) — EP-046
- **Cost estimation**: All 6 providers (OpenAI, Anthropic, Google, Cohere, Mistral, local)
  verified against known pricing tables, zero tokens, unknown providers, linear scaling
- **Prompt rendering**: Single/multiple variable substitution, missing variable errors,
  extra variable tolerance, numeric casting, static prompts
- **Variant assignment**: MD5 consistent hashing determinism, bucket distribution [0,1),
  50/50 split balance (10K users, 4-sigma tolerance)
- **Evaluation statistics**: Mean, std, Welch t-test, Cohen's d, 95% CI coverage,
  CI width decreases with sample size
- **Provider registry**: Known providers registered, unknown raises ValueError
- **Synthetic data**: Treatment quality > control, latency improvement, rating ranges

### Bayesian Experimentation (`bayesian_analysis.py`) — EP-035
- **Beta-Binomial posterior**: Uniform prior no-data, all-convert, no-convert,
  informative prior update, posterior mean convergence to observed rate
- **Credible intervals**: Coverage of posterior mean, width decreases with data,
  narrow CI with high confidence
- **Probability of being best**: Clear winner >99%, equal variants ~50/50,
  probabilities sum to 1, three-way split with dominant variant
- **Expected loss**: Near-zero for best variant, equal variants similar loss,
  all losses non-negative
- **Bayes Factor**: Strong evidence detection (BF > 10), no evidence with no data,
  Jeffreys/Kass-Raftery label categories
- **Stopping rule**: Stop when clear winner, continue when uncertain
- **Full pipeline**: `analyze()` returns all expected fields, 3-variant analysis,
  large sample winner identification

### CUPED & Sequential Testing (`variance_reduction.py`) — EP-021, Issue #21
- **CUPED theta**: Perfect correlation θ=1, zero variance covariate θ=0,
  uncorrelated θ≈0, negative correlation θ=-1
- **CUPED adjustment**: Variance reduction with correlated covariate,
  mean preservation after adjustment
- **Full CUPED pipeline**: Variance reduction percentage positive,
  detects treatment lift, no false positive with identical groups,
  95% CI contains true effect
- **Winsorization**: Clips outliers above percentile, preserves normal values
- **mSPRT**: Significant results can stop, no difference does not stop,
  lambda ratio increases with more data, evidence strength populated
- **Always-valid CI**: Contains zero when no effect, excludes zero with strong effect,
  positive width
- **Alpha spending**: O'Brien-Fleming boundaries decrease over looks,
  Pocock boundaries roughly constant, cumulative alpha ≤ total
- **Evidence trajectory**: Length matches input, sample sizes increase
- **Long-running risk**: At-risk detection when over expected duration,
  not at-risk when on track, risk ratio computed correctly

### Multi-Tenant Workspaces (`multi_tenant_isolation.py`) — EP-057
- **Model integrity**: Required columns present on Workspace, WorkspaceMember,
  WorkspaceInvite, WorkspaceAPIKey models
- **Plan limits**: FREE < PRO < ENTERPRISE hierarchy, specific FREE plan values
  (10 experiments, 50 flags, 5 members, 3 API keys)
- **Role hierarchy**: VIEWER < ANALYST < DEVELOPER < ADMIN < OWNER ordering,
  all 5 roles represented
- **Slug validation**: Unique constraint, index for lookups
- **Invite lifecycle**: Token format (64 hex), expiry detection, acceptance detection
- **API key properties**: Prefix format (`ep_live_`), expiry detection,
  validity requires active + not expired
- **Service exceptions**: 14 exception types defined, proper hierarchy
- **Data isolation**: Unique constraint on (workspace_id, user_id),
  default scopes follow least-privilege

---

## Smoke Tests

### Infrastructure Wiring (`test_wiring.py`)

Zero-mock tests that catch the class of bugs where authentication is mocked in
unit tests but the real app has wiring issues. Uses `FastAPI.TestClient` with
the real app — no dependency overrides.

| Category | Tests | What It Catches |
|----------|-------|-----------------|
| Database columns | 10 | Migration gaps — model columns not in actual tables |
| CORS headers | 6 | Missing CORSMiddleware, wrong allowed origins |
| Auth wiring | 8 | Duplicate oauth2_scheme, 500 instead of 401, dev bypass failures |
| Security headers | 3 | Missing SecurityHeadersMiddleware (X-Frame-Options, X-Content-Type-Options) |
| App startup | 8 | Circular imports, missing routers, duplicate routes |
| Service imports | 8 | Bayesian, CUPED, sequential, MAB, LLM, workspace services importable |
| Model imports | 7 | Table names, column structure, enum completeness |
| New feature endpoints | 5 | Bayesian, sequential, CUPED, compliance, integration routers registered |

### Production Smoke (`test_production.py`)

Runs against a live deployment URL to verify critical user journeys:

| Category | Tests | What It Validates |
|----------|-------|-------------------|
| Health checks | 4 | Liveness, readiness, security headers |
| Auth endpoints | 3 | Login endpoint exists, auth required on protected routes |
| Experiments API | 2 | List experiments, valid JSON responses |
| Feature flags API | 2 | List flags, tracking API reachable |
| Tracking API | 3 | Assign/track endpoints, results API |
| Rate limiting | 1 | Rate limit middleware active |

```bash
# Run against local dev
source venv/bin/activate && export APP_ENV=test TESTING=true
python -m pytest backend/tests/smoke/test_wiring.py -v

# Run against deployed environment
SMOKE_TEST_API_URL=https://api.prod.example.com \
SMOKE_TEST_TOKEN=<jwt> \
SMOKE_TEST_API_KEY=<key> \
python -m pytest backend/tests/smoke/test_production.py -v
```

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
MAB traffic allocation, Bayesian posteriors, and sequential testing signals.

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

Produces a consolidated pass/fail report with per-phase status.

### Available scenarios

```
/autotest ab_test_lifecycle         # Standard A/B test
/autotest feature_flag_rollout      # Gradual rollout mechanics
/autotest statistical_edge_cases    # Pathological edge cases
/autotest concurrent_experiments    # Mutual exclusion + overlap
/autotest all                       # Run everything
```

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

### Playwright configuration

`frontend/playwright.config.ts` settings:
- **testDir**: `./tests/e2e`
- **Workers**: 1 (sequential — scenarios share state)
- **Browser**: Chromium only (Desktop Chrome preset)
- **Timeouts**: 15s per action, 30s navigation
- **Reporting**: HTML report + list reporter; screenshots and video on failure
- **Auto-server**: Starts `npm run dev` with 60s timeout

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
export APP_ENV=test TESTING=true

# 3. Run smoke tests (no DB required)
python -m pytest backend/tests/smoke/test_wiring.py -v

# 4. Verify data generator works
python backend/tests/realistic/data_generator.py --scenario ab_test_lifecycle --dry-run

# 5. Run existing unit tests (should still be green)
python -m pytest backend/tests/unit/ -p no:cov -q

# 6. Run all realistic scenario tests (offline — no API needed)
python -m pytest backend/tests/realistic/scenarios/ -v

# 7. Run API fuzzing (requires running platform)
RUN_FUZZING=1 python -m pytest backend/tests/realistic/test_api_fuzzing.py -v

# 8. Run production smoke tests (requires running platform)
python -m pytest backend/tests/smoke/test_production.py -v

# 9. Run full /autotest loop
/autotest ab_test_lifecycle
```

---

## Test Coverage by Epic

| Epic | Feature | Realistic Tests | Smoke Tests | Unit/Integration Tests |
|------|---------|----------------|-------------|----------------------|
| EP-001 | Enhanced Rules Engine | — | — | 131+ tests |
| EP-021 | Sequential Testing | `variance_reduction.py` (12 tests) | Service import check | 293 tests |
| #21 | CUPED Variance Reduction | `variance_reduction.py` (10 tests) | Endpoint check | 78 tests |
| #22 | Multi-Armed Bandit | — | Service import check | 110 tests |
| EP-035 | Bayesian Experimentation | `bayesian_analysis.py` (25 tests) | Endpoint check | 104 tests |
| EP-046 | LLM Model Evaluation | `llm_experiment_lifecycle.py` (30 tests) | Model + router checks | 135 tests |
| EP-057 | Multi-Tenant Workspaces | `multi_tenant_isolation.py` (20 tests) | Model + router checks | 88 tests |
| EP-033 | Compliance Audit | — | Endpoint check | 236 tests |
| EP-034 | Third-Party Integrations | — | Endpoint check | 203 tests |
| EP-036 | Split URL Testing | — | — | 129 tests |

---

## Success Metrics

| Metric | Target | Status |
|--------|--------|--------|
| Scenario coverage | 5+ real-world scenarios | 5 data gen + 4 feature scenarios |
| Data realism | p < 0.05 at correct sample size | z-scores validated |
| User profiles | 3+ behavioral archetypes | casual, power, churn risk |
| Agent coverage | data-gen, scenario-runner, validator, auto-fixer | all 6 agents implemented |
| API fuzzing | Zero-maintenance adversarial testing | Schemathesis integration |
| Orchestration | Single `/autotest` command | skill implemented |
| Smoke tests | Zero-mock infrastructure validation | 55+ wiring + production tests |
| New feature coverage | Realistic tests for all major epics | LLM, Bayesian, CUPED, sequential, workspace |
| Statistical validation | Bayesian, CUPED, mSPRT correctness | mathematical properties verified |
