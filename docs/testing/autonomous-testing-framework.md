# Autonomous Testing & Multi-Agent QA System

**Epics**: EP-047 (Foundation) + EP-059 (Multi-Agent QA/UAT Extension)
**Status**: Complete — All phases operational.
**Test count**: ~4,600+ platform-wide (backend ~4,200 | frontend 226 | E2E 28 | visual 8 | a11y 10 | SDK contract 55 | Java 86 | React SDK 98 | Go 60+ | iOS 50+ | Android 60+ | Ruby 90 | PHP 69 | .NET 63 | Elixir 93)

---

## Overview

The Experimently platform includes an autonomous testing framework that covers the full testing pyramid — from unit tests through E2E browser tests, visual regression, accessibility audits, and cross-SDK contract verification. The system is designed for a solo developer shipping commercially: every test layer that a full QA team would cover is automated through 8 specialized Claude Code agents orchestrated by the `/autotest` skill.

Beyond traditional unit and integration tests, this framework adds:

1. **Statistically realistic data** — synthetic data that behaves like the real world, not just valid shapes
2. **Browser-based UI simulation** — agents that click through the dashboard as real users would
3. **Statistical correctness validation** — verifying that p-values, Bayesian posteriors, variance reduction, and traffic allocation are mathematically correct
4. **E2E browser tests** — 28 Playwright specs covering auth, experiments, feature flags, RBAC, and admin
5. **Visual regression testing** — screenshot comparison across desktop, tablet, and mobile viewports
6. **Accessibility testing** — WCAG 2.1 AA compliance scans via axe-core
7. **Cross-SDK contract testing** — golden vector hash parity across 14+ SDKs
8. **Smoke testing** — zero-mock infrastructure wiring tests catching auth, CORS, middleware, and router registration bugs
9. **Self-healing** — when a test fails, an agent diagnoses the root cause, writes the fix, and verifies it

---

## Architecture

### Agent Pipeline

```
Pre-flight checks (backend health, frontend running, DB connected)
    |
    v
Phase 1 (PARALLEL):
    data-generator ──┐
    tester (units) ──┤
                     v
Phase 2 (SEQUENTIAL, needs Phase 1 data):
    scenario-runner (E2E + visual regression)
                     |
                     v
Phase 3 (PARALLEL):
    validator ────────┐
    reviewer ─────────┤
    contract-tester ──┤
    a11y-auditor ─────┤
                      v
Phase 4 (CONDITIONAL, only if failures):
    auto-fixer
                      |
                      v
    Consolidated Report
```

### Agent Inventory

| Agent | Role | Tools |
|-------|------|-------|
| `data-generator` | Seed statistically realistic experiment data | Read, Bash, Glob, Grep |
| `tester` | Run unit/integration tests, check coverage | Read, Write, Edit, Bash, Glob, Grep |
| `scenario-runner` | E2E browser tests via Playwright + visual regression | Read, Bash, Glob, Grep, Playwright MCP |
| `validator` | Validate statistical correctness of results | Read, Bash, Glob, Grep |
| `reviewer` | Code review for correctness, security, patterns | Read, Glob, Grep, Bash |
| `contract-tester` | Cross-SDK golden vector hash parity tests | Read, Bash, Glob, Grep |
| `a11y-auditor` | WCAG 2.1 AA accessibility scans via axe-core | Read, Bash, Glob, Grep |
| `auto-fixer` | Diagnose and fix failures autonomously | Read, Write, Edit, Bash, Glob, Grep |

---

## File Layout

```
.claude/
  agents/
    reviewer.md             # Code review agent
    tester.md               # Test writing agent
    data-generator.md       # Realistic data seeding agent
    scenario-runner.md      # UI simulation agent (Playwright + visual regression)
    validator.md            # Statistical correctness validator
    auto-fixer.md           # Self-healing repair agent
    contract-tester.md      # Cross-SDK golden vector tests
    a11y-auditor.md         # WCAG 2.1 AA accessibility scans
  commands/
    autotest.md             # /autotest orchestration skill

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
  tests/e2e/
    pages/
      common.page.ts                # Shared navigation, toast, modal helpers
      login.page.ts                 # Login form interactions
      experiments.page.ts           # Experiment list + detail pages
      feature-flags.page.ts         # Feature flag management
      admin.page.ts                 # Admin panel pages
    fixtures/
      auth.fixture.ts               # Role-based authenticated page fixtures
      data.fixture.ts               # API data seeding/cleanup
    auth.spec.ts                    # Login/logout/session tests (6 tests)
    experiment-lifecycle.spec.ts    # Full experiment CRUD (5 tests)
    feature-flag.spec.ts            # Feature flag management (5 tests)
    rbac.spec.ts                    # Role-based access control (6 tests)
    admin-panel.spec.ts             # Admin dashboard (6 tests)
    visual-regression.spec.ts       # Screenshot comparisons (~8 snapshots)
    accessibility.spec.ts           # WCAG 2.1 AA audits (~10 page audits)

tests/sdk-contract/
  golden-vectors.json               # 9 hash vectors + 2 rollout vectors
  test_python_sdk.py                # 25 pytest tests
  test_js_sdk.js                    # 30 tests (Node.js runner)

.github/workflows/
  frontend-tests.yml                # E2E job with Playwright
  sdk-contract-tests.yml            # Python + JS contract test matrix
  nightly-qa.yml                    # Full test pyramid at 2 AM UTC
  pr-qa-gate.yml                    # Fast subset for PR merge gate
```

---

## Data Generator

The core engine is `backend/tests/realistic/data_generator.py`.

### What it produces

- Statistically realistic CVR data (not flat random)
- Novelty effects (day-1 spike -> steady state)
- Day-of-week patterns (weekday 1.2x vs weekend 0.7x)
- Session decay (engagement drops 15%/week)
- Outlier users (bots, whales -- lognormal value distribution)
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
# Dry run -- generate data, print summary, no API call
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

### Casual User (`backend/tests/realistic/profiles/casual_user.py`)
- 1-2 sessions/week, 3% CVR, 65% bounce rate
- Sensitive to UX complexity (treatment uplift may be negative)

### Power User (`backend/tests/realistic/profiles/power_user.py`)
- 6 sessions/week, 20% CVR, 10% bounce rate
- Early adopter -- responds positively to new features

### Churn Risk User (`backend/tests/realistic/profiles/churn_risk_user.py`)
- Declining engagement over 4 weeks (10% -> 2% CVR)
- Re-engagement boost from treatment (+15% CVR)
- Useful for holdout group and novelty effect testing

---

## Scenario Tests by Feature Area

### Core A/B Testing (`ab_test_lifecycle.py`, `statistical_edge_cases.py`)
- Full experiment lifecycle through REST API
- Statistical significance validation (z-score >= 1.96)
- Zero-variance metrics, outlier contamination
- Simpson's paradox (subgroup reversal)
- Multi-assignment detection
- Metric drift injection
- Underpowered experiment detection
- Novelty effect day-1 spike validation

### Feature Flag Rollout (`feature_flag_rollout.py`)
- Three-stage rollout schedule (10% -> 50% -> 100%)
- Monotonic percentage progression
- Session decay reduces late engagement
- Event distribution tracks rollout percentage

### Concurrent Experiments (`concurrent_experiments.py`)
- 50/50 control/treatment split balance
- Unique user IDs per variant
- Zero population overlap by default
- Event timestamps after assignment
- Mutual exclusion group API integration

### LLM/AI Model Evaluation (`llm_experiment_lifecycle.py`) -- EP-046
- **Cost estimation**: All 6 providers (OpenAI, Anthropic, Google, Cohere, Mistral, local) verified against known pricing tables, zero tokens, unknown providers, linear scaling
- **Prompt rendering**: Single/multiple variable substitution, missing variable errors, extra variable tolerance, numeric casting, static prompts
- **Variant assignment**: MD5 consistent hashing determinism, bucket distribution [0,1), 50/50 split balance (10K users, 4-sigma tolerance)
- **Evaluation statistics**: Mean, std, Welch t-test, Cohen's d, 95% CI coverage, CI width decreases with sample size
- **Provider registry**: Known providers registered, unknown raises ValueError
- **Synthetic data**: Treatment quality > control, latency improvement, rating ranges

### Bayesian Experimentation (`bayesian_analysis.py`) -- EP-035
- **Beta-Binomial posterior**: Uniform prior no-data, all-convert, no-convert, informative prior update, posterior mean convergence to observed rate
- **Credible intervals**: Coverage of posterior mean, width decreases with data, narrow CI with high confidence
- **Probability of being best**: Clear winner >99%, equal variants ~50/50, probabilities sum to 1, three-way split with dominant variant
- **Expected loss**: Near-zero for best variant, equal variants similar loss, all losses non-negative
- **Bayes Factor**: Strong evidence detection (BF > 10), no evidence with no data, Jeffreys/Kass-Raftery label categories
- **Stopping rule**: Stop when clear winner, continue when uncertain
- **Full pipeline**: `analyze()` returns all expected fields, 3-variant analysis, large sample winner identification

### CUPED & Sequential Testing (`variance_reduction.py`) -- EP-021, Issue #21
- **CUPED theta**: Perfect correlation theta=1, zero variance covariate theta=0, uncorrelated theta~0, negative correlation theta=-1
- **CUPED adjustment**: Variance reduction with correlated covariate, mean preservation after adjustment
- **Full CUPED pipeline**: Variance reduction percentage positive, detects treatment lift, no false positive with identical groups, 95% CI contains true effect
- **Winsorization**: Clips outliers above percentile, preserves normal values
- **mSPRT**: Significant results can stop, no difference does not stop, lambda ratio increases with more data, evidence strength populated
- **Always-valid CI**: Contains zero when no effect, excludes zero with strong effect, positive width
- **Alpha spending**: O'Brien-Fleming boundaries decrease over looks, Pocock boundaries roughly constant, cumulative alpha <= total
- **Evidence trajectory**: Length matches input, sample sizes increase
- **Long-running risk**: At-risk detection when over expected duration, not at-risk when on track, risk ratio computed correctly

### Multi-Tenant Workspaces (`multi_tenant_isolation.py`) -- EP-057
- **Model integrity**: Required columns present on Workspace, WorkspaceMember, WorkspaceInvite, WorkspaceAPIKey models
- **Plan limits**: FREE < PRO < ENTERPRISE hierarchy, specific FREE plan values (10 experiments, 50 flags, 5 members, 3 API keys)
- **Role hierarchy**: VIEWER < ANALYST < DEVELOPER < ADMIN < OWNER ordering, all 5 roles represented
- **Slug validation**: Unique constraint, index for lookups
- **Invite lifecycle**: Token format (64 hex), expiry detection, acceptance detection
- **API key properties**: Prefix format (`ep_live_`), expiry detection, validity requires active + not expired
- **Service exceptions**: 14 exception types defined, proper hierarchy
- **Data isolation**: Unique constraint on (workspace_id, user_id), default scopes follow least-privilege

---

## Smoke Tests

### Infrastructure Wiring (`test_wiring.py`)

Zero-mock tests that catch the class of bugs where authentication is mocked in unit tests but the real app has wiring issues. Uses `FastAPI.TestClient` with the real app -- no dependency overrides.

| Category | Tests | What It Catches |
|----------|-------|-----------------|
| Database columns | 10 | Migration gaps -- model columns not in actual tables |
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

## E2E Browser Tests (Playwright)

28 Playwright specs using the Page Object Model pattern for maintainability. All locators use semantic selectors (roles, labels, text content) -- never hardcoded CSS or XPath.

**Spec files:**

| Spec | Tests | Coverage |
|------|-------|----------|
| `auth.spec.ts` | 6 | Login, logout, session management |
| `experiment-lifecycle.spec.ts` | 5 | Full experiment CRUD |
| `feature-flag.spec.ts` | 5 | Feature flag management |
| `rbac.spec.ts` | 6 | Role-based access control |
| `admin-panel.spec.ts` | 6 | Admin dashboard |

**Test fixtures:**
- `auth.fixture.ts` provides pre-authenticated pages for admin, developer, analyst, and viewer roles
- `data.fixture.ts` provides API helpers for seeding/cleaning test data

```bash
cd frontend
npx playwright test                              # All E2E tests
npx playwright test auth                         # Auth tests only
npx playwright test experiment-lifecycle         # Experiment lifecycle
npx playwright test --headed                     # Show browser
npx playwright test --ui                         # Interactive mode
npx playwright show-report                       # View HTML report
```

---

## Visual Regression Testing

**File:** `frontend/tests/e2e/visual-regression.spec.ts` (~8 snapshots)

Uses Playwright's built-in `toHaveScreenshot()` with:
- 2% pixel difference tolerance for cross-environment rendering
- Desktop + mobile + tablet viewports
- Key pages: dashboard, experiments, feature flags, admin, login

**Baseline management:**
```bash
cd frontend
npm run test:visual                              # Run visual comparisons
npm run test:visual:update                       # Update baselines
npx playwright test visual-regression --update-snapshots  # Create/update baselines
```

Baselines stored in `frontend/tests/e2e/__screenshots__/`.

---

## Accessibility Testing

**File:** `frontend/tests/e2e/accessibility.spec.ts` (~10 page audits)

Uses `@axe-core/playwright` for WCAG 2.1 AA compliance scanning:
- Critical/serious violations fail the test
- Moderate/minor issues reported as warnings
- Covers: forms, keyboard navigation, color contrast, image alt text
- Dynamic import pattern for graceful degradation when axe-core isn't installed

**Dependency:** `@axe-core/playwright: ^4.10.0` in `frontend/package.json`

```bash
cd frontend
npm run test:a11y                                # Run a11y scans
```

---

## Cross-SDK Contract Testing

Verifies that all SDKs produce identical hashing results using golden vectors as the canonical source of truth.

**Files:**
- `tests/sdk-contract/golden-vectors.json` -- 9 hash vectors + 2 rollout vectors
- `tests/sdk-contract/test_python_sdk.py` -- 25 pytest tests
- `tests/sdk-contract/test_js_sdk.js` -- 30 tests (Node.js runner)

**Algorithm verified:**
```
1. Concatenate: "{userId}:{flagKey}"
2. UTF-8 encode
3. MD5 digest (16 bytes)
4. First 4 bytes as LITTLE-ENDIAN uint32
5. Divide by 2^32 (4294967296) -> [0.0, 1.0)
```

**Test coverage:**
- Hash value accuracy (tolerance: 1e-10)
- MD5 hex digest verification
- Rollout inclusion/exclusion at 3%, 5%, 50%, 100%
- Property tests: determinism, range, uniqueness, byte order

All 55 contract tests pass (25 Python + 30 JavaScript).

```bash
# Python
source venv/bin/activate
python -m pytest tests/sdk-contract/test_python_sdk.py -v

# JavaScript
node tests/sdk-contract/test_js_sdk.js
```

---

## API Fuzzing

`backend/tests/realistic/test_api_fuzzing.py` uses Schemathesis to automatically generate adversarial inputs for every endpoint in the OpenAPI spec.

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

## The `/autotest` Skill

One command to run the full autonomous loop:

```
/autotest [scenario_name or "all"]
```

Execution order follows the 4-phase pipeline described in [Architecture](#architecture):
1. **Phase 1 (parallel):** `data-generator` seeds data + `tester` runs unit tests
2. **Phase 2 (sequential):** `scenario-runner` runs E2E + visual regression
3. **Phase 3 (parallel):** `validator` + `reviewer` + `contract-tester` + `a11y-auditor`
4. **Phase 4 (conditional):** `auto-fixer` runs only if failures detected

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

## CI Workflows

| Workflow | Trigger | Pipeline |
|----------|---------|----------|
| `frontend-tests.yml` | Push/PR | Frontend unit tests + E2E Playwright |
| `sdk-contract-tests.yml` | Push/PR | Python + JS contract test matrix |
| `nightly-qa.yml` | Cron (2 AM UTC) | Full pyramid: unit -> integration -> smoke -> E2E -> visual -> a11y -> contract |
| `pr-qa-gate.yml` | PR | Fast subset: unit + smoke + frontend + SDK contracts + E2E |

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
- **Workers**: 1 (sequential -- scenarios share state)
- **Browser**: Chromium only (Desktop Chrome preset)
- **Timeouts**: 15s per action, 30s navigation
- **Reporting**: HTML report + list reporter; screenshots and video on failure
- **Auto-server**: Starts `npm run dev` with 60s timeout

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

# 6. Run all realistic scenario tests (offline -- no API needed)
python -m pytest backend/tests/realistic/scenarios/ -v

# 7. Run frontend tests
cd frontend && npm test && cd ..

# 8. Run E2E browser tests
cd frontend && npx playwright test && cd ..

# 9. Run visual regression
cd frontend && npm run test:visual && cd ..

# 10. Run accessibility audits
cd frontend && npm run test:a11y && cd ..

# 11. Run SDK contract tests
python -m pytest tests/sdk-contract/test_python_sdk.py -v
node tests/sdk-contract/test_js_sdk.js

# 12. Run API fuzzing (requires running platform)
RUN_FUZZING=1 python -m pytest backend/tests/realistic/test_api_fuzzing.py -v

# 13. Run production smoke tests (requires running platform)
python -m pytest backend/tests/smoke/test_production.py -v

# 14. Run full /autotest loop
/autotest ab_test_lifecycle
```

---

## Test Coverage Summary

### By Test Layer

| Layer | Count | Source |
|-------|-------|--------|
| Backend unit tests | 3,100+ | `backend/tests/unit/` |
| Backend integration tests | 1,128 | `backend/tests/integration/` |
| Smoke tests | 48+ | `backend/tests/smoke/` |
| Realistic scenario tests | 100+ | `backend/tests/realistic/scenarios/` |
| Frontend component tests | 226 | `frontend/src/tests/` |
| E2E browser tests | ~28 | `frontend/tests/e2e/*.spec.ts` |
| Visual regression snapshots | ~8 | `frontend/tests/e2e/visual-regression.spec.ts` |
| Accessibility audits | ~10 | `frontend/tests/e2e/accessibility.spec.ts` |
| SDK contract tests | 55 | `tests/sdk-contract/` (25 Python + 30 JS) |
| API fuzzing | Schemathesis | `backend/tests/realistic/test_api_fuzzing.py` |
| **Total** | **~4,600+** | |

### By Epic

| Epic | Feature | Realistic Tests | Smoke Tests | Unit/Integration Tests |
|------|---------|----------------|-------------|----------------------|
| EP-001 | Enhanced Rules Engine | -- | -- | 131+ tests |
| EP-021 | Sequential Testing | `variance_reduction.py` (12 tests) | Service import check | 293 tests |
| #21 | CUPED Variance Reduction | `variance_reduction.py` (10 tests) | Endpoint check | 78 tests |
| #22 | Multi-Armed Bandit | -- | Service import check | 110 tests |
| EP-035 | Bayesian Experimentation | `bayesian_analysis.py` (25 tests) | Endpoint check | 104 tests |
| EP-046 | LLM Model Evaluation | `llm_experiment_lifecycle.py` (30 tests) | Model + router checks | 135 tests |
| EP-057 | Multi-Tenant Workspaces | `multi_tenant_isolation.py` (20 tests) | Model + router checks | 88 tests |
| EP-033 | Compliance Audit | -- | Endpoint check | 236 tests |
| EP-034 | Third-Party Integrations | -- | Endpoint check | 203 tests |
| EP-036 | Split URL Testing | -- | -- | 129 tests |

---

## Design Decisions

### Why Playwright (not Cypress or Nova Act)

| Option | Verdict | Reasoning |
|--------|---------|-----------|
| **Playwright** | **Selected** | Already configured, built-in visual comparison, axe-core integration, MCP for Claude agents, runs in CI natively |
| Amazon Nova Act | Not selected | Early-stage, requires AWS credentials, no CI support, better for exploratory testing |
| Cypress | Not selected | Would require replacing existing config, no MCP integration |

### Why Claude Code Agents (not standalone frameworks)

The 8-agent architecture provides capabilities no standalone framework offers:
- **auto-fixer**: Reads failures, understands root cause, writes fixes
- **data-generator**: Creates statistically realistic data with known properties
- **scenario-runner**: Cross-checks UI state against API state
- **validator**: Verifies mathematical correctness of experiment results
- **contract-tester**: Ensures all SDKs produce identical hashing results
- **a11y-auditor**: Categorizes violations with remediation guidance

### Golden Vectors as Source of Truth

The `golden-vectors.json` file is the canonical source for cross-SDK hash verification. Any new SDK must pass all vectors before being merged. The file contains:
- 9 hash vectors with expected normalized values and MD5 hex digests
- 2 rollout vectors with inclusion/exclusion at different percentages
- Algorithm documentation embedded in the JSON

---

## Success Metrics

| Metric | Target | Status |
|--------|--------|--------|
| Scenario coverage | 5+ real-world scenarios | 5 data gen + 4 feature scenarios |
| Data realism | p < 0.05 at correct sample size | z-scores validated |
| User profiles | 3+ behavioral archetypes | casual, power, churn risk |
| Agent coverage | 8 specialized agents | all 8 implemented |
| E2E browser tests | Full CRUD + RBAC | 28 Playwright specs |
| Visual regression | Key pages across viewports | 8 snapshots |
| Accessibility | WCAG 2.1 AA compliance | 10 page audits |
| SDK contract parity | All SDKs produce identical hashes | 55 golden vector tests |
| API fuzzing | Zero-maintenance adversarial testing | Schemathesis integration |
| Orchestration | Single `/autotest` command | 4-phase pipeline |
| Smoke tests | Zero-mock infrastructure validation | 48+ wiring + production tests |
| New feature coverage | Realistic tests for all major epics | LLM, Bayesian, CUPED, sequential, workspace |
| Statistical validation | Bayesian, CUPED, mSPRT correctness | mathematical properties verified |
| CI automation | Nightly full pyramid + PR gate | 4 workflow files |
