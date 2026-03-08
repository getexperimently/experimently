# EP-059: Multi-Agent QA/UAT System

## Status: Complete

## Overview

EP-059 extends the existing EP-047 autonomous testing framework into a production-grade multi-agent QA system that covers the full testing pyramid — from unit tests through E2E browser tests, visual regression, accessibility audits, and cross-SDK contract verification.

The system is designed for a solo developer shipping commercially: every test layer that a full QA team would cover is automated through 8 specialized Claude Code agents orchestrated by the `/autotest` skill.

## Problem Statement

The Experimently platform had 4,500+ tests across unit (3,100+), integration (1,128), smoke (48+), realistic scenarios (100+), and frontend (226). However, it lacked:

- **E2E browser tests** — zero Playwright specs despite having Playwright configured
- **Visual regression testing** — UI changes were invisible to existing tests
- **Accessibility testing** — no WCAG 2.1 AA compliance verification
- **Cross-SDK contract testing** — 14+ SDKs with no automated hash parity checks
- **Consolidated QA orchestration** — agents ran sequentially with no parallel execution

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

## Implementation Details

### Phase 1: E2E Browser Tests with Playwright

**Files created:**
- `frontend/tests/e2e/pages/common.page.ts` — Shared navigation, toast, modal helpers
- `frontend/tests/e2e/pages/login.page.ts` — Login form interactions
- `frontend/tests/e2e/pages/experiments.page.ts` — Experiment list + detail pages
- `frontend/tests/e2e/pages/feature-flags.page.ts` — Feature flag management
- `frontend/tests/e2e/pages/admin.page.ts` — Admin panel pages
- `frontend/tests/e2e/fixtures/auth.fixture.ts` — Role-based authenticated page fixtures
- `frontend/tests/e2e/fixtures/data.fixture.ts` — API data seeding/cleanup
- `frontend/tests/e2e/auth.spec.ts` — Login/logout/session tests (6 tests)
- `frontend/tests/e2e/experiment-lifecycle.spec.ts` — Full experiment CRUD (5 tests)
- `frontend/tests/e2e/feature-flag.spec.ts` — Feature flag management (5 tests)
- `frontend/tests/e2e/rbac.spec.ts` — Role-based access control (6 tests)
- `frontend/tests/e2e/admin-panel.spec.ts` — Admin dashboard (6 tests)

**Page Object Model:** All E2E tests use the Page Object pattern for maintainability. Locators use semantic selectors (roles, labels, text content) — never hardcoded CSS or XPath.

**Test Fixtures:**
- `auth.fixture.ts` provides pre-authenticated pages for admin, developer, analyst, and viewer roles
- `data.fixture.ts` provides API helpers for seeding/cleaning test data

### Phase 2: Visual Regression Testing

**File created:** `frontend/tests/e2e/visual-regression.spec.ts` (~15 snapshots)

Uses Playwright's built-in `toHaveScreenshot()` with:
- 2% pixel difference tolerance for cross-environment rendering
- Desktop + mobile + tablet viewports
- Key pages: dashboard, experiments, feature flags, admin, login

**Baseline management:**
```bash
npx playwright test visual-regression --update-snapshots  # Create/update baselines
```

Baselines stored in `frontend/tests/e2e/__screenshots__/`.

### Phase 3: Cross-SDK Contract Testing

**Files created:**
- `tests/sdk-contract/golden-vectors.json` — 9 hash vectors + 2 rollout vectors
- `tests/sdk-contract/test_python_sdk.py` — 25 pytest tests
- `tests/sdk-contract/test_js_sdk.js` — 30 tests (Node.js runner)

**Algorithm verified:**
```
1. Concatenate: "{userId}:{flagKey}"
2. UTF-8 encode
3. MD5 digest (16 bytes)
4. First 4 bytes as LITTLE-ENDIAN uint32
5. Divide by 2^32 (4294967296) → [0.0, 1.0)
```

**Test coverage:**
- Hash value accuracy (tolerance: 1e-10)
- MD5 hex digest verification
- Rollout inclusion/exclusion at 3%, 5%, 50%, 100%
- Property tests: determinism, range, uniqueness, byte order

All 55 contract tests pass (25 Python + 30 JavaScript).

### Phase 4: Accessibility Testing

**File created:** `frontend/tests/e2e/accessibility.spec.ts` (~10 page audits)

Uses `@axe-core/playwright` for WCAG 2.1 AA compliance scanning:
- Critical/serious violations fail the test
- Moderate/minor issues reported as warnings
- Covers: forms, keyboard navigation, color contrast, image alt text
- Dynamic import pattern for graceful degradation when axe-core isn't installed

**Dependency added:** `@axe-core/playwright: ^4.10.0` in `frontend/package.json`

### Phase 5: Agent Orchestration Upgrade

**Files modified/created:**
- `.claude/commands/autotest.md` — Rewritten with parallel phases, conditional logic, 8-agent pipeline
- `.claude/agents/contract-tester.md` — New agent for cross-SDK golden vector tests
- `.claude/agents/a11y-auditor.md` — New agent for WCAG 2.1 AA accessibility scans
- `.claude/agents/scenario-runner.md` — Updated with visual regression + network validation steps

**Key improvements:**
- Parallel execution in Phases 1 and 3 (2-4 agents simultaneously)
- Conditional Phase 4 (auto-fixer only runs if failures detected)
- Pre-flight environment checks before any agent launches
- Consolidated report format with per-phase status

### Phase 6: CI Workflows

**Files created/modified:**
- `.github/workflows/frontend-tests.yml` — Added E2E job with Playwright
- `.github/workflows/sdk-contract-tests.yml` — Python + JS contract test matrix
- `.github/workflows/nightly-qa.yml` — Full test pyramid at 2 AM UTC
- `.github/workflows/pr-qa-gate.yml` — Fast subset for PR merge gate

**Nightly QA pipeline:** unit → integration → smoke → E2E → visual → a11y → contract
**PR gate:** unit + smoke + frontend + SDK contracts + E2E (fast subset)

## Running the Tests

### E2E Browser Tests
```bash
cd frontend
npx playwright test                              # All E2E tests
npx playwright test auth                         # Auth tests only
npx playwright test experiment-lifecycle         # Experiment lifecycle
npx playwright test --headed                     # Show browser
npx playwright test --ui                         # Interactive mode
npx playwright show-report                       # View HTML report
```

### Visual Regression
```bash
cd frontend
npm run test:visual                              # Run visual comparisons
npm run test:visual:update                       # Update baselines
```

### Accessibility Audit
```bash
cd frontend
npm run test:a11y                                # Run a11y scans
```

### SDK Contract Tests
```bash
# Python
source venv/bin/activate
python -m pytest tests/sdk-contract/test_python_sdk.py -v

# JavaScript
node tests/sdk-contract/test_js_sdk.js
```

### Full Autonomous Pipeline
```bash
/autotest                          # Default: ab_test_lifecycle
/autotest all                      # All scenarios
/autotest feature_flag_rollout     # Specific scenario
```

## Test Coverage After EP-059

| Layer | Before | After |
|-------|--------|-------|
| Unit tests | 3,100+ | 3,100+ (unchanged) |
| Integration tests | 1,128 | 1,128 (unchanged) |
| Smoke tests | 48+ | 48+ (unchanged) |
| Realistic scenario tests | 100+ | 100+ (unchanged) |
| Frontend component tests | 226 | 226 (unchanged) |
| **E2E browser tests** | **0** | **~28 tests** |
| **Visual regression** | **0** | **~8 snapshots** |
| **Accessibility audits** | **0** | **~10 page audits** |
| **SDK contract tests** | **0** | **55 tests (25 Python + 30 JS)** |
| API fuzzing | Schemathesis | Schemathesis (unchanged) |
| **Total** | **~4,500** | **~4,600 + visual/a11y** |

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

## Files Created/Modified

### New Files (21)
```
frontend/tests/e2e/pages/common.page.ts
frontend/tests/e2e/pages/login.page.ts
frontend/tests/e2e/pages/experiments.page.ts
frontend/tests/e2e/pages/feature-flags.page.ts
frontend/tests/e2e/pages/admin.page.ts
frontend/tests/e2e/fixtures/auth.fixture.ts
frontend/tests/e2e/fixtures/data.fixture.ts
frontend/tests/e2e/auth.spec.ts
frontend/tests/e2e/experiment-lifecycle.spec.ts
frontend/tests/e2e/feature-flag.spec.ts
frontend/tests/e2e/rbac.spec.ts
frontend/tests/e2e/admin-panel.spec.ts
frontend/tests/e2e/visual-regression.spec.ts
frontend/tests/e2e/accessibility.spec.ts
tests/sdk-contract/golden-vectors.json
tests/sdk-contract/test_python_sdk.py
tests/sdk-contract/test_js_sdk.js
.claude/agents/contract-tester.md
.claude/agents/a11y-auditor.md
.github/workflows/sdk-contract-tests.yml
.github/workflows/nightly-qa.yml
.github/workflows/pr-qa-gate.yml
```

### Modified Files (4)
```
frontend/package.json                    — Added @axe-core/playwright, test scripts
.github/workflows/frontend-tests.yml    — Added E2E job
.claude/commands/autotest.md             — Rewritten with 8-agent pipeline
.claude/agents/scenario-runner.md        — Added visual regression + network validation
```
