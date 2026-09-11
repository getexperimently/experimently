# Testing Strategy Audit — September 2026

Audited at `feat/streampulse-demo` (HEAD `a0e042d`, plus the uncommitted eligibility work in
`backend/tests/integration/api/test_tracking_api.py`). Counts come from
`pytest --collect-only -q -o addopts="" -p no:cacheprovider <dir>` and targeted runs on
2026-09-11 with Postgres on `localhost:5432`. `demo/streampulse/**` and
`backend/scripts/seed_streampulse.py` were excluded (in flight).

## Status of the P0 items

Applied on the same branch as this audit (2026-09-11):

- **P0-1 done** — `integration-tests.yml` no longer passes `-m "integration and requires_db"`; the
  required check now runs all 1,462 integration tests.
- **P0-4 done** — the required `Unit Tests` job runs the 301 Lambda tests (one invocation per
  function directory, since each defines its own `tests.conftest`).
- P0-2, P0-3, P0-5, P0-6 and everything under P1/P2 are open.

## Executive summary

1. **The required `integration-tests` check silently drops 39% of the integration suite.**
   `integration-tests.yml` runs `-m "integration and requires_db"`; 24 of 53 files carry
   neither marker, so **892 of 1458** tests run and **566 are deselected** — including every
   regression test written this week for the tracking API, results engine, bandits, and
   mutual-exclusion/holdout (`test_tracking_api.py`, `test_conversion_event_matching.py`,
   `test_bandit_scheduler_db.py`, `test_experiments_api.py`, `test_experiments_lifecycle_api.py`,
   `auth/*`). Those files gate nothing today; they only run in the non-required, path-filtered
   `backend-tests.yml` and in nightly.
2. **~1,500 SDK unit tests across 16 SDKs run in no workflow.** No job executes `npm test`,
   `pytest`, `go test`, `mvn test`, `dotnet test`, `rspec`, `phpunit`, `mix test`,
   `flutter test`, `swift test` or Gradle under `sdk/`. Only the live contract smoke (10 SDKs)
   and the two golden-vector scripts gate. The React SDK — the one that shipped calling
   non-existent endpoints — has neither a golden-vector test nor a live-contract entry.
3. **301 Lambda tests under `backend/lambda/**/tests` run nowhere** (`backend/pytest.ini`
   `testpaths = tests`; no workflow references them). The assignment/event-processor/flag
   evaluation hot paths in Lambda are tested only by mocks and only on a developer laptop.
4. **The suite never executes a migration.** Tests build the schema with
   `Base.metadata.create_all` (`backend/tests/conftest.py:225`); the five real Alembic tests in
   `backend/tests/unit/models/test_alembic_migration.py` are `@pytest.mark.skip`; there is no
   `compare_metadata`/`alembic check`; `check_and_fix_db.py` and `bootstrap.py` are untested.
5. **"Smoke" means "the app imports and routes exist", not "a deployed environment works."**
   `smoke/test_wiring.py` (55 tests, real app, no DB writes) is what the required "Smoke Tests"
   check runs; `smoke/test_production.py` (15 tests) is skipped everywhere except
   `deploy-prod.yml`. Nothing on a PR drives the public API end to end through a running server
   except the SDK live contract.
6. **Browser E2E, visual and a11y run only nightly, can't fail meaningfully, and target a
   `/login` page that does not exist.** 47 Playwright tests + 8 visual + 9 a11y; visual has no
   committed baselines; the a11y job is `|| true`; `data.fixture.ts` seeding is dead code;
   18 of 26 Next.js pages have zero tests of any kind.
7. **Schedulers are tested only against mocks.** No test seeds rows and observes a real
   `process_*` tick for the experiment, rollout, metrics or safety schedulers; the bandit
   scheduler is the sole exception (`test_bandit_scheduler_db.py`, itself excluded from the
   required gate by item 1).
8. **Test hygiene undermines trust in green.** Three competing pytest configs (root
   `pytest.ini`, `backend/pytest.ini`, `pyproject.toml`); `db_session` never truncates; 132
   `app.dependency_overrides.clear()` sites; the root `client` fixture shares one
   `test@example.com` user across the whole session; coverage is uploaded from a non-required
   job with no threshold; `backend/tests/performance` hangs when collected in the same session
   as DB layers (locust/gevent monkey-patch) but passes alone.

---

## 1. Inventory

| Layer | Location | Files | Tests | Framework | Needs | Mocks / notes |
|---|---|---|---|---|---|---|
| Backend unit | `backend/tests/unit/` | 178 | **3,867** | pytest, `asyncio_mode=auto` (backend/pytest.ini) | Postgres (many "unit" files use real `db_session`, e.g. `unit/api/test_feature_flags.py`, `unit/services/test_workspace_service.py`) | `MagicMock`/`patch` for DB in most service tests; `moto` for Cognito/DynamoDB |
| Backend integration | `backend/tests/integration/` (api/ auth/ database/ services/ workflows/) | 53 | **1,458** (892 with CI marker filter) | pytest | Postgres; `auth/*` needs moto only | 10 files are mock-only or hybrid (see §3.2); `auth/*` 91 pass on this branch |
| Backend smoke | `backend/tests/smoke/` | 2 | **70** (55 pass, 15 skip offline) | pytest | `test_wiring.py`: real app, no DB overrides; `test_production.py`: live server via `SMOKE_TEST_API_URL/_TOKEN/_API_KEY` | none |
| Backend contract | `backend/tests/contract/` | 1 (+3 JSON schemas) | **14** | pytest + jsonschema | Postgres | own engine; duplicates `DictLikeCacheControl` |
| Backend e2e (API-level) | `backend/tests/e2e/` | 2 | **20** | pytest | Postgres | own NullPool engine; API journeys only, no browser |
| Backend realistic | `backend/tests/realistic/` (1 `test_*.py` + 8 scenario modules via custom `pytest_collect_file`) | 9 | **152** (133 pass offline, 19 skip) | pytest (+schemathesis, not installed) | offline part: none; 12 scenario tests need `RUN_REALISTIC=1` + live server; 7 fuzz tests need `RUN_FUZZING=1` + schemathesis | schemathesis absent from `backend/requirements.txt` |
| Backend performance | `backend/tests/performance/` | 3 pytest + 6 locustfiles + runner | **71** (all pass alone) | pytest; Locust | pytest part: locust importable; Locust part: live server | hangs when collected with DB layers in one session |
| Lambda (in-tree) | `backend/lambda/{assignment,event_processor,feature_flag_evaluation,shared}/tests` | 19 | **301** | pytest | none (boto3 patched; moto installed but unused) | `events/tests`, `feature_flags/tests` empty; Glue script untested |
| Lambda (backend tree) | `backend/tests/unit/lambda/` | 3 | 84 | pytest | none | runs with unit suite |
| Frontend unit | `frontend/src/tests/**` | 63 | **552** | Jest 30 + RTL + jsdom | node | recharts mocked; fetch mocked per test; `collectCoverageFrom` excludes `src/pages` |
| Frontend E2E | `frontend/tests/e2e/*.spec.ts` (5 journeys) | 5 | 30 (+10 conditional `test.skip`) | Playwright 1.63, chromium, workers=1 | Next on :3100, backend on :8000, Chromium | no seeding used; specs self-skip when UI missing |
| Frontend visual | `tests/e2e/visual-regression.spec.ts` | 1 | 8 | Playwright `toHaveScreenshot` | as above | **0 baseline PNGs committed** |
| Frontend a11y | `tests/e2e/accessibility.spec.ts` | 1 | 9 | `@axe-core/playwright` | as above | fails only on critical/serious; CI step is `\|\| true` |
| SDK unit (16 SDKs) | `sdk/*` | 55 | **~1,477** (js 76, react 218, react-native 119, edge 101, openfeature 47, python 71, openfeature-python 57, java 107, go 51, ios 71, android 78, ruby 109, php 88, dotnet 89, elixir 125, flutter 70) | jest / pytest / JUnit5+Mockito / go test / XCTest / JUnit+mockk / RSpec / PHPUnit / xUnit / ExUnit / flutter_test | per-SDK toolchain | HTTP mocked in every SDK (fetch stubs, MockWebServer, httptest, WebMock, MockURLProtocol, FakeTransport) |
| SDK golden vectors | `tests/sdk-contract/{golden-vectors.json,test_python_sdk.py,test_js_sdk.js}` | 3 | 8 pytest + 1 node script; 9 hash + 2 rollout vectors | pytest / node assert | none | hashing is now "utility only" per README — bucketing is server-side |
| SDK live contract | `tests/sdk-contract/live/run_live_contract.py` | 1 | 13 SDKs in `MANIFEST`, 10 run in CI | subprocess runner over each SDK's `contract_smoke` | uvicorn + Postgres + Redis, `backend/scripts/seed_sdk_contract.py`, all toolchains | asserts assign/evaluate/track/fan-out shape; **react, react-native, android absent from MANIFEST**; ios/elixir/flutter never run in CI |
| Infrastructure | `infrastructure/tests/test_vpc_stack.py` (+`backend/tests/unit/infrastructure/test_split_url_distribution.py`) | 1 (+1) | 4 (+15) | pytest + `aws_cdk.assertions` | python + Node (jsii) | 1 of 14 stack modules in `infrastructure/cdk/stacks/` asserted; no snapshots |
| Demo (ShopLab) | `demo/shoplab/src/__tests__` (9), `demo/shoplab/simulator/test_traffic.py` | 10 | 41 jest + 12 pytest | Jest / pytest | node / python | SDK and router mocked; `traffic.py` needs live backend + `.api_key`; **no CI** |
| MCP | `backend/app/api/v1/endpoints/mcp.py` (manifest only) | — | 4 (`unit/api/test_ai_design_endpoints.py`) | pytest | none | no tool-execution transport exists |
| Scripts | `backend/scripts/{seed_demo_data,seed_sdk_contract,seed_shoplab,simulate_live_events}.py`, `backend/app/db/bootstrap.py`, root `check_and_fix_db.py` | 6 | **0** | — | Postgres | `seed_sdk_contract.py` executed by pr-qa-gate; the rest never run in CI |
| Agentic QA | `.claude/agents/*.md` (8), `.claude/commands/autotest.md` | 9 | n/a | Claude agents + Playwright MCP | live stack | run nowhere in CI; `scenario-runner` expects creds that differ from `auth.fixture.ts` and `DEMO_GUIDE.md` |

Backend total collected: **5,652**. Observed offline pass/skip: smoke 55/15, contract+e2e 34/0,
realistic 133/19, performance 71/0, integration/auth 91/0.

---

## 2. CI map

21 active workflows (+ `issue-triage.yml.example`). Required checks: Release Gate Summary,
Security Scan Summary, Unit Tests, Smoke Tests, Frontend Tests, SDK Contract Tests, SDK Live
Contract, integration-tests.

| Workflow | Trigger | Path filter | Check name(s) | What runs | Required? |
|---|---|---|---|---|---|
| `pr-qa-gate.yml` | PR→main | none | Unit Tests; Smoke Tests; Frontend Tests; SDK Contract Tests; SDK Live Contract | `pytest backend/tests/unit -p no:cov -x`; `pytest backend/tests/smoke`; Jest + `next build`; golden vectors; live contract `--strict` for 10 SDKs (pg15 + redis7, `seed_sdk_contract.py`, uvicorn) | **yes (all 5)** |
| `integration-tests.yml` | PR→main, push main | none | integration-tests | pg15-alpine + redis7; `bootstrap.py`; `pytest integration/ -m "integration and requires_db"`; `e2e/ -m e2e`; `contract/ -m contract` | **yes** — but marker filter drops 566 tests |
| `release-gate.yml` | PR→main, dispatch | none | Backend Gate (Unit + Smoke); Frontend Gate; Security Gate (Bandit + Gitleaks); **Release Gate Summary** | compose pg 5433 / redis 6380; `scripts/run-backend-tests.sh release` = unit + `smoke/test_wiring.py`; Jest+build; `bandit -ll` + gitleaks | **yes (summary)**; summary fails on any non-`success` (`release-gate.yml:93-107`) |
| `security-scan.yml` | PR→main, push main/develop, weekly Mon 08:00 | none | Python Security Scan; Frontend Security Scan; Semgrep SAST; Secret Detection; Container Security Scan; **Security Scan Summary** | bandit `-ll`; pip-audit (`continue-on-error: true`); `npm audit --audit-level=high` (`continue-on-error: true`); semgrep `--error`; gitleaks; trivy HIGH/CRITICAL | **yes (summary)** — summary ignores `frontend-security` and only checks `== "failure"` (cancelled passes) |
| `backend-tests.yml` | PR→main, push main | `backend/**`, `requirements*.txt` | test; Test Results - Python 3.11 | pg14, no redis; `pytest unit integration smoke contract e2e --cov=backend.app`; codecov upload (`fail_ci_if_error: false`, no token) | no — the only job that runs the whole DB-backed suite and the only coverage producer |
| `frontend-tests.yml` | PR→main, push main | `frontend/**` | Build & Test | Jest + build | no (name differs from required "Frontend Tests") |
| `sdk-contract-tests.yml` | PR→main, push main | `tests/sdk-contract/**`, `sdk/**`, `backend/lambda/shared/consistent_hash.py` | Python/JavaScript SDK Contract Tests | golden vectors only | no (duplicate of pr-qa-gate job) |
| `cognito-integration-tests.yml` | PR/push all branches | PR: `backend/app/**` | cognito-integration | `pytest integration/auth -m "not slow"` (moto) | no |
| `advanced-toggle-tests.yml`, `etl-tests.yml`, `realtime-counters-tests.yml`, `scheduler-tests.yml`, `segments-tests.yml` | PR/push all | PR: `backend/app/**` | test / Run ETL unit tests / Run real-time counter unit tests / Run Scheduler Enhancement Tests / Audience Segmentation Unit Tests | 3–6 hand-picked unit files each, no services | no — all are subsets of "Unit Tests" |
| `infrastructure-tests.yml` | PR→main, push main, dispatch | `infrastructure/**` | CDK Stack Tests (Python) | `pytest infrastructure/tests -o addopts=""` (1 file) | no |
| `nightly-qa.yml` | cron `0 2 * * *`, dispatch | none | Unit Tests; Integration Tests; Smoke Tests; SDK Contract Tests; Frontend Unit Tests; E2E Browser Tests; Accessibility Audit | pg15, no redis; **unfiltered** `integration/`; uvicorn :8000 + `npm run dev` :3100 + `npx playwright test` (whole dir); a11y `\|\| true`; **no seeding** | schedule only |
| `performance-tests.yml` | cron `0 2 * * 1` (weekly), dispatch | none | Run <type> load test | pg14 + redis7; bootstrap; uvicorn; `run_load_tests.py` (exits 1 on SLA breach) | schedule only |
| `deploy.yml`, `deploy-dev.yml`, `deploy-prod.yml`, `db-migrate.yml`, `rollback.yml` | push main / dispatch | — | Deploy…, Run Database Migration | CDK deploy; `alembic upgrade head` in ECS; `deploy-prod` re-runs unit + `integration/database` + `integration/api` + post-deploy `smoke/` with `SMOKE_TEST_API_URL` | no |

**Layers that exist but run nowhere:** all 16 SDK unit suites; `backend/lambda/**/tests` (301);
`backend/tests/realistic/` (incl. schemathesis fuzzing); `backend/tests/performance/test_*.py`
(71 pytest specs — only the Locust files run weekly); `demo/shoplab` tests (53); Alembic
upgrade/downgrade/drift checks; `backend/scripts/seed_demo_data.py`/`seed_shoplab.py`;
`check_and_fix_db.py`.

**Only nightly/weekly:** unfiltered integration suite; Playwright e2e/visual/a11y; Locust.

**Run but gate nothing:** `backend-tests.yml` (the one job with coverage + full DB suite),
the five topic workflows, `cognito-integration-tests.yml`, `sdk-contract-tests.yml`,
`frontend-tests.yml`, `infrastructure-tests.yml`, nightly `Accessibility Audit` (`|| true`),
`frontend-security` (`continue-on-error` and unchecked by the summary), pip-audit.

**Environment drift across jobs:** Postgres 14 / 15 / 15-alpine; `POSTGRES_HOST` vs
`POSTGRES_SERVER`; `POSTGRES_SCHEMA` set to `experimentation`, `test_experimentation` and
`experimentation_test` in different jobs; the required Unit/Smoke jobs start no Redis while
`release-gate` runs the same tests with Redis on 6380. `conftest.py` overrides DB name and
schema anyway, so the pre-created schemas in `backend-tests.yml` are dead steps.

---

## 3. Gap analysis

### 3.1 Smoke

- `smoke/test_wiring.py` (55 tests, 8 classes: DatabaseColumns, CORSWiring, AuthWiring,
  SecurityHeaders, AppStartup, ServiceImports, ModelImports, NewFeatureEndpoints) is a
  **wiring** test: real app, real middleware, no DB writes, no auth. It catches import
  errors, missing routes, 500-instead-of-401. It does not catch a dead tracking API or a
  results 500 because it never sends an authenticated request with data.
- `smoke/test_production.py` (15 tests) is the only deployed-environment smoke. It is skipped
  everywhere except `deploy-prod.yml` post-deploy; 6 of its 15 tests are `requests.get` on
  `/health` and list endpoints; `test_results_api_reachable` accepts `200/404/401`;
  `test_rate_limit_headers_present` asserts only `status_code == 200`. No test posts an
  assignment or event and reads it back.
- There is no staging/dev smoke after `deploy-dev.yml` / `deploy.yml`.

### 3.2 Integration (DB-backed coverage)

Endpoint modules with **no** DB-backed test (any of `db_session`, `admin_client`, root
`client`): `auth.py`, `users.py`, `admin.py`, `events.py`, `metrics.py`, `export.py`,
`realtime_counters.py`, `etl.py`, `scheduler_health.py`, `mutual_exclusion_groups.py`,
`global_holdout.py`, `bandit.py`, `interactions.py`, `ai_design.py`, `mcp.py`,
`experiment_wizard.py`, `warehouse.py`, `notifications.py`, `warehouse_databricks.py`,
`warehouse_clickhouse.py`, `warehouse_mysql.py`, `openfeature.py`, `hipaa.py` (every
data-bearing test patches `HIPAAService`), `websocket_results.py` — **24 of the 45
`endpoints/*.py` modules**, plus `api/v1/sample_size_calculator.py`. Partial: `results.py` sub-routes `/daily`, `/sample-size`,
`/sequential`, `/cuped`, `/invalidate-cache`; `post_stratification.py` (compute patched);
`llm_proxy.py`.

Services with no DB-backed test: `compliance_report_service`, `hipaa_service`,
`llm_proxy_service`, `llm_analytics_service`, `post_stratification_service`,
`fdr_correction_service`, `results_streaming_service`, `websocket_manager`,
`dynamodb_counter_service`, `clickhouse/databricks/mysql_connector`, `warehouse_service`,
`bayesian_service`, `cuped_service`, `sequential_testing_service`,
`dimensional_analysis_service`, `cache`, `ai_design_service`, `ai_experiment_planner_service`,
`experiment_template_service`, `experiment_wizard_service`, `export_service`, `etl_service`,
`interaction_detection_service`, `notification_service`, `scheduler_health_service`,
`power_calculator_service`, `email_notifier`, `slack_notifier`, `audit_signing_service`,
`auth_service`, `user_service` (no test at all), `mutual_exclusion_service` (indirect only).

"Integration" files that are mock-only or hybrid (evidence: `db_session` refs vs `patch(`):
`api/test_clickhouse_api.py` (0/22), `api/test_databricks_api.py` (0/18),
`api/test_mysql_api.py` (0/22), `api/test_openfeature_api.py` (`get_db → MagicMock()`),
`test_results_integration.py` (docstring: "No real PostgreSQL connection is required"),
`api/test_websocket_results.py` (0/27), `api/test_realtime_counters_api.py` (service mocked),
`api/test_hipaa_api.py` (0/38), `test_rules_engine_integration.py` (pure in-memory).
Hybrid: `test_bayesian_results_api.py` (10 patches on `AnalysisService.get_experiment_results`),
`test_post_strat_api.py`, `test_safety_api.py` (rollback class real, settings/check patched),
`test_compliance_api.py`, `test_sso_api.py`, `test_llm_experiments_api.py`.

The one DB-backed test that asserts numeric results from seeded events is
`integration/services/test_conversion_event_matching.py::TestResultsEngineCountsSdkEvents::test_results_endpoint_reports_the_same_rates`.
It is excluded from the required gate (no `requires_db` marker).

### 3.3 End-to-end

- **API-level journeys** (`backend/tests/e2e`, 20 tests): A/B lifecycle and flag rollout
  through the API. Run in the required gate. No journey covers SDK → tracking → results, MAB,
  CUPED/sequential/Bayesian, rollout schedule progression, safety rollback, workspaces, or SSO.
- **Browser journeys** (`frontend/tests/e2e`): auth (6), experiment lifecycle (6),
  feature flag (6), rbac (6), admin panel (6). Nightly only; no seeded data; page objects use
  zero `data-testid` selectors although the app has 292; `auth.fixture.ts` logs in via
  `/login`, which has no page (`frontend/src/pages/` has no `login.tsx`; `AuthContext` reads
  `admin_user` from localStorage), so auth specs pass vacuously.
- **What the demo walkthrough covered that the suite does not** (from `demo/DEMO_GUIDE.md` and
  commit `9c76da5`): React SDK assign → hero CTA conversion → bandit-sorted PLP → multivariate
  buy button → cart → CUPED checkout → purchase value → gradual-rollout search flag → live
  results with real p-values, bandit convergence, 25 API calls / 0 console errors. None of
  this is a repeatable spec anywhere.
- **Dashboard flows never exercised by any test:** `experiments/new` wizard (4 Step components
  untested), `results/[id]` and `results/index`, `feature-flags/new`, `power-calculator`,
  `workspaces/**` (6 pages), `admin/{api-keys,audit,roles,scheduler,users}`, `docs/**`.

### 3.4 Regression tests for this week's fixes

| Bug fixed (commit) | Regression test | Layer | In a required gate? | Would catch a re-break? |
|---|---|---|---|---|
| Tracking API dead (`c161a53`) | `integration/api/test_tracking_api.py` (Track/Batch/EventsByIds/Assign classes, real DB, 0 patches) | integration | **No** (no `requires_db` marker) | Yes, if it ran |
| Results ignored SDK conversions (`9c76da5`) | `integration/services/test_conversion_event_matching.py` (4) | integration | **No** | Yes |
| `GET /experiments/{id}/results` 500 (`053112b`) | `integration/api/test_experiments_lifecycle_api.py::TestGetExperimentResults` (empty data), `test_results_endpoint_reports_the_same_rates` (`/results/{id}` only) | integration | **No** | Partly — experiments-router path is asserted only with no events |
| Safety service dead / rollback pct (`053112b`) | `integration/services/test_safety_service_coverage.py` (81), `integration/api/test_safety_api.py::TestSafetyRollback` (6, asserts 75→0 and custom pct) | integration | Yes (`requires_db`) | Yes |
| Bandits never learned (`9c76da5`) | `integration/services/test_bandit_scheduler_db.py` (3), `test_tracking_api.py::TestBanditAssignment` (5) | integration | **No** | Yes |
| `BanditSchedulerRunner` not started | `unit/services/test_bandit_scheduler.py::TestBanditSchedulerRunner` | unit (mocked) | Yes | Only that the class starts; nothing asserts `main.py` lifespan wires it |
| Rate limit on SDK paths | `unit/middleware/test_rate_limiter.py::test_tracking_endpoints_have_higher_limits`, `::test_sdk_limit_is_configurable` | unit | Yes | Config-level only; no test sends >300 req/min through the real middleware |
| `CORS_ORIGINS` parsing/not applied | `unit/core/test_config_cors.py` (5 committed + 1 uncommitted); `smoke/test_wiring.py::TestCORSWiring` | unit + smoke | Yes | Yes |
| Rollout scheduler naive datetimes / next-stage start_date | `unit/core/test_rollout_scheduler_tz.py` (6) | unit (mocked session) | Yes | Yes for `_as_utc`; the tick itself is never run against Postgres |
| Experiment keys unset by seed | none — `test_tracking_api.py` reads `.key` from fixtures; `seed_demo_data.py` has no test | — | — | No |
| `backend.app.models` missing imports | `smoke/test_wiring.py::TestModelImports` | smoke | Yes | Partly (checks specific models) |
| React SDK non-existent endpoints (`9c76da5`) | `sdk/react/src/__tests__/*` (218, fetch mocked) | SDK unit | **No** (never run in CI); react not in live MANIFEST | Only if executed; mocked fetch cannot detect a wrong path |
| 11 SDKs non-existent routes (`c6e9a00`) | `tests/sdk-contract/live/` (10 SDKs) | live contract | Yes | Yes for those 10; ios/elixir/flutter/android/react-native/react uncovered |
| Dashboard targeting rules never evaluated | `integration/services/test_feature_flag_targeting_rules.py::TestDashboardRules` (14); `test_tracking_api.py::TestAssignEligibility::test_dashboard_shaped_targeting_rules_gate_new_users` (uncommitted) | integration | flag path yes; experiment path **no** | Yes |
| MEG/holdout/targeting ignored on assign (uncommitted) | `test_tracking_api.py::TestAssignEligibility` (8) | integration | **No** | Yes, if it ran; `/mutual-exclusion-groups` and `/holdout` CRUD have no DB test |

Net: 7 of the 15 bug classes have their regression test outside every required check.

### 3.5 Contract

- **SDK live contract:** 13 SDKs in `MANIFEST`, 10 run in `pr-qa-gate` (`--strict`).
  Not covered: `react` (no MANIFEST entry, no hash test, no live run — the SDK that caused
  this week's rewrite), `react-native`, `android` (no entry), `ios`, `elixir`, `flutter`
  (entries exist, never run in CI — no macOS runner, no BEAM/Dart setup).
- **OpenAPI drift:** no snapshot of `openapi.json` is committed or diffed anywhere. The only
  checks are `test_wiring.py` assertions that four route groups appear. Frontend types
  (`frontend/src/types/*.ts`) are hand-written; no generated client.
- **Schemathesis:** `backend/tests/realistic/test_api_fuzzing.py` (7 tests) is skipped unless
  `RUN_FUZZING=1`, and would still skip because schemathesis is not in any requirements file.
  It has never run in CI.
- `backend/tests/contract` (14 tests) validates three hand-written JSON schemas for
  experiment/flag/assignment responses only.

### 3.6 Background jobs / schedulers

`main.py` lifespan starts five schedulers (experiment, rollout, metrics, safety, bandit).
DB-backed tick tests: **bandit only** (`test_bandit_scheduler_db.py::test_run_once_picks_up_active_mab_experiment`).
Experiment scheduler: `unit/services/test_experiment_scheduler.py` patches `SessionLocal`.
Rollout: `unit/core/test_rollout_scheduler.py` (56 Mocks). Safety:
`unit/schedulers/test_safety_scheduler_rollback.py` (mocked). Metrics:
`unit/core/test_metrics_scheduler.py` has one test skipped as "flaky". No test starts the app
lifespan under `run_in_tests` and observes a scheduled state transition. `scheduler_health`
endpoints have no DB test.

### 3.7 Data / migrations

21 migration files, single head `d4e5f6a7b8c9`. The chain cannot replay from empty
(`bootstrap.py` docstring), so tests use `create_all`. Consequences: (a) a model change
without a migration passes every test; (b) a migration that diverges from the model passes
every test; (c) `alembic downgrade` has never been exercised. `test_alembic_migration.py`
(5 tests) and the `test_core_data_models.py` placeholders are all skipped/`pass`.
`check_and_fix_db.py` (root, 351 lines, hard-coded DSN) introspects `information_schema` and
issues DDL with no test. `bootstrap.py` runs in two CI jobs but has no test of its own two
branches (fresh vs existing DB).

### 3.8 Performance

`specs/performance_targets.py` defines p95/p99/min-RPS per endpoint;
`run_load_tests.py` exits 1 on SLA violation. Weekly `performance-tests.yml` runs one
locustfile (default `baseline`) and uploads CSVs; no trend comparison, no alerting, no PR
budget. The 71 pytest specs (`test_specs.py`, `test_validators.py`, `test_load_profiles.py`)
run nowhere. `unit/core/test_performance_benchmarks.py` is skipped on CI ("timing-sensitive").

### 3.9 Security

Gating on PRs: bandit `-ll` (twice — release-gate and security-scan), semgrep `--error`
(p/python, p/security-audit, p/secrets, p/owasp-top-ten), gitleaks, trivy fs HIGH/CRITICAL
on `backend/`. Not gating: pip-audit and `npm audit` (`continue-on-error: true`),
`frontend-security` result never read by the summary, no scan of `sdk/`, `infrastructure/`,
`demo/` or Lambda dependencies, no container image scan (trivy runs on the filesystem, not
the built image). Security summary treats `cancelled` as pass.

### 3.10 Frontend

552 Jest tests; last coverage report (`frontend/coverage/`, dated 2026-05-02) shows 87.6%
lines / 77.1% branches over `components|services|hooks|contexts` only — `src/pages` is
excluded from `collectCoverageFrom`, and there is no `coverageThreshold`. Pages with zero
tests (18/26): `admin/{api-keys,audit,roles,scheduler,users}`, `docs/*`, `experiments/new`,
`feature-flags/new`, `power-calculator`, `results/{[id],index}`, `workspaces/*` (6). Wizard
step components `StepTargeting/StepDefineHypothesis/StepReview/StepSampleSize` untested.
Visual: 8 tests, 0 baselines, so the first nightly run silently writes baselines. A11y: 9
tests, job cannot fail.

### 3.11 Test hygiene

- **Three pytest configs.** Root `pytest.ini` (cov addopts, `log_cli=True`), `backend/pytest.ini`
  (`asyncio_mode=auto`, markers incl. `requires_db`), `pyproject.toml` (`--cov=app`, wrong
  package). Which one applies depends on the path argument; `-o addopts=""` and `-p no:cov`
  are sprinkled across workflows to work around it.
- **Isolation.** `db_session` never truncates (docstring: TRUNCATE deadlocked against
  overlapping async fixtures); root `client` get-or-creates a single `test@example.com` admin;
  `integration/conftest.py` fixtures use UUID suffixes but pagination/list tests still see
  leaked rows — the documented order-dependent failures. 486 direct
  `app.dependency_overrides[...]` writes and 132 `.clear()` calls; `client` teardown clears
  overrides installed by other fixtures (`mock_auth`, `mock_api_key`).
- **Skips.** 77 skip sites, 0 `xfail`. Buckets: 15 `test_production.py` (env), 19 realistic
  (env), 11 `unit/api/test_deps.py` ("Cognito authentication not properly mocked"), 5 Alembic,
  1 "flaky" (`test_metrics_scheduler.py:56`), 1 "Works fine in its ./models/ directory".
- **Duplication.** `DictLikeCacheControl` in `e2e/conftest.py` and `contract/conftest.py`
  (working around a real bug: `create_feature_flag` calls `cache_control.get()`);
  `make_client_for_user` in `integration/conftest.py` and `test_llm_experiments_api.py`;
  the bcrypt literal in 18 files; three `TestClient` factories with different engines.
- **Session mixing.** Collecting `performance/` with DB layers in one session hung with 4s
  CPU (locust's gevent/ssl monkey-patch at import); each layer passes alone.
- **Stale plan.** `docs/testing/integration-testing-plan.md` cites `sdk-integration-tests.yml`,
  `compliance-tests.yml`, `integrations-tests.yml`, `split-url-tests.yml` — none exist.

### 3.12 Observability of tests

Coverage is produced only by `backend-tests.yml` (`--cov=backend.app`, Codecov upload without
token, `fail_ci_if_error: false`), a non-required, path-filtered job; no `codecov.yml`, no
`--cov-fail-under`, no badge source, README's "82%" is static text. Root `pytest.ini` addopts
reference `.coveragerc` but produce no report when invoked via `backend/tests/...` because
`backend/pytest.ini` wins rootdir discovery. JUnit XML artifacts exist for four jobs but no
test-history/flake dashboard. Frontend coverage is never uploaded.

---

## 4. Recommendations

### P0 — make the tests that exist actually gate (≤ 1 week)

| # | Add | Where | Effort | Would have caught |
|---|---|---|---|---|
| P0-1 | Remove `-m "integration and requires_db"`; run the whole `backend/tests/integration/` (or auto-mark via `pytest_collection_modifyitems` in `integration/conftest.py`). Merge `backend-tests.yml`'s full run into the required check and delete the topic workflows (`advanced-toggle`, `etl`, `realtime-counters`, `scheduler`, `segments`, `sdk-contract-tests`, `frontend-tests`). | `.github/workflows/integration-tests.yml`, `backend/tests/integration/conftest.py` | 0.5 d | tracking API, results 500, bandit learning, MEG/holdout on assign — the tests exist and are deselected |
| P0-2 | SDK unit matrix job (`sdk-unit-tests`): node (js, react, react-native, edge, openfeature), python (python, openfeature-python), go, java (maven), dotnet, ruby, php, elixir (`erlef/setup-beam`), flutter (`subosito/flutter-action`), android (gradle, `android-actions/setup-android`), ios on `macos-latest`. Make it required. | new `.github/workflows/sdk-unit-tests.yml` | 1–2 d | Android/Flutter/Elixir SDKs "never executed anywhere" |
| P0-3 | Add `react`, `react-native`, `android` to `tests/sdk-contract/live/MANIFEST` (a `contract_smoke` example each, react via `ServerClient` under node; RN via jest-node build; android via JVM unit variant) and run ios/elixir/flutter live on their runners. | `tests/sdk-contract/live/`, `sdk/react/examples/`, `pr-qa-gate.yml` | 1 d | React SDK calling non-existent endpoints |
| P0-4 | Run `pytest backend/lambda` in the unit job (add `backend/lambda` to `testpaths` or a second invocation). | `pr-qa-gate.yml` unit-tests | 0.5 d | Lambda assignment/flag evaluation regressions (currently invisible) |
| P0-5 | **Feature-path convention** (enforce via a new `.github/pull_request_template.md` — none exists today — and the `reviewer` agent): every user-facing feature ships with (a) one DB-backed test under `backend/tests/integration/api/` that drives the **public/SDK path** (`/tracking/*`, `/feature-flags/evaluate/*`, `/results/*`) with real rows and asserts numbers, and (b) one Playwright spec under `frontend/tests/e2e/` against a seeded backend for any dashboard surface. Name them `test_<feature>_path.py` / `<feature>.journey.spec.ts` so a grep can audit coverage. | `docs/testing/`, `.github/pull_request_template.md`, `.claude/agents/reviewer.md` | 0.5 d | every "found only by building a demo" bug |
| P0-6 | Regression-test checklist for PRs (see below) and a `regression/` marker so `pytest -m regression` lists them. | `.github/pull_request_template.md`, `backend/pytest.ini` | 0.25 d | re-breaks of this week's fixes |

### P1 — close the structural holes (2–4 weeks)

| # | Add | Where | Effort | Would have caught |
|---|---|---|---|---|
| P1-1 | **Browser E2E on PRs.** Job: pg15 + redis7 → `python -m backend.app.db.bootstrap` → `python backend/scripts/seed_demo_data.py` (+ `seed_shoplab.py --no-history`) → uvicorn :8000 with `APP_ENV=development` → `next build && next start -p 3100` → `npx playwright test --project=chromium tests/e2e/*.journey.spec.ts`. Fix `auth.fixture.ts` to the real auth mechanism (localStorage `admin_user` / demo-login) and switch page objects to `data-testid`. Commit visual baselines; make a11y fail on serious/critical. | new `browser-e2e` job in `pr-qa-gate.yml`; `frontend/tests/e2e/fixtures/auth.fixture.ts`, `pages/*.page.ts` | 3–4 d | dashboard targeting rules that nothing evaluated; results page 500 |
| P1-2 | **Test isolation.** Replace `db_session` with a transactional fixture: `connection = engine.connect(); trans = connection.begin(); session = Session(bind=connection, join_transaction_mode="create_savepoint")`; hand the same `connection` to `override_get_db` so endpoint commits become savepoints; `trans.rollback()` in teardown. Where a test needs cross-connection visibility (websocket, scheduler threads) mark it `@pytest.mark.commits` and give it `TRUNCATE ... RESTART IDENTITY CASCADE` in a dedicated fixture run serially. Add an autouse fixture that snapshots and restores `app.dependency_overrides` and delete the 132 `.clear()` calls. | `backend/tests/conftest.py`, `integration/conftest.py`, `e2e/conftest.py`, `contract/conftest.py` | 2–3 d | order-dependent pagination failures; fixture leakage |
| P1-3 | **Scheduler tick tests.** For each of experiment/rollout/metrics/safety: seed rows, bind the scheduler's `SessionLocal` to the test engine, call `process_*()` once, assert transitions (DRAFT→ACTIVE at `start_date`, stage 1→2 at `start_date`, rollback record written). One lifespan test with `run_in_tests=True` asserting all five runners start and stop. | `backend/tests/integration/schedulers/` | 2 d | rollout scheduler raising on every active schedule; bandit runner never started |
| P1-4 | **Migration checks.** (a) `alembic check` (autogenerate diff must be empty) against a bootstrapped DB in the integration job; (b) for every new migration since the stamped head: `upgrade head` then `downgrade -1` then `upgrade head` on a bootstrapped DB; (c) unit tests for `bootstrap.py` both branches and for `check_and_fix_db.py` (move it to `backend/scripts/`). | `backend/tests/integration/database/test_migrations.py`, `integration-tests.yml` | 1–2 d | model/migration drift; `Experiment.key` missing in seeded DBs |
| P1-5 | **OpenAPI snapshot + fuzz.** Commit `docs/api/openapi.json`; test that `app.openapi()` equals it (update via `make openapi`); add `schemathesis` to `backend/requirements.txt`; nightly job runs `RUN_FUZZING=1` against uvicorn + seeded DB. | `backend/tests/contract/test_openapi_snapshot.py`, `nightly-qa.yml` | 1 d | SDKs calling routes that do not exist; response-shape 500s |
| P1-6 | **Coverage as a gate.** One `pytest.ini` (delete `backend/pytest.ini` and the `[tool.pytest]` block, keep markers + `asyncio_mode=auto` in root); `--cov-fail-under=80` on the merged backend job; `coverageThreshold` (lines 85) in `frontend/jest.config.js`; Codecov token + `codecov.yml` with patch target; upload frontend lcov. | `pytest.ini`, `pyproject.toml`, `frontend/jest.config.js`, workflows | 0.5 d | silent coverage regressions |
| P1-7 | **Nightly "one session" job**: `pytest backend/tests/unit backend/tests/integration backend/tests/smoke backend/tests/contract backend/tests/e2e -p randomly` (add `pytest-randomly`) with `--reruns 0`; failures open an issue via `actions/github-script`. Keep `performance/` in its own invocation. | `nightly-qa.yml` | 0.5 d | order dependence |
| P1-8 | DB-backed API tests for the 25 endpoint modules in §3.2, starting with the ones on the public path: `bandit.py`, `mutual_exclusion_groups.py`, `global_holdout.py`, `results.py` sub-routes, `users.py`, `admin.py`, `export.py`, `metrics.py`, `scheduler_health.py`, `notifications.py`. | `backend/tests/integration/api/` | 4–5 d | bandit stats fallback; MEG/holdout CRUD regressions |
| P1-9 | Security summary: include `frontend-security`, treat `!= success` as failure, scan `sdk/`, `infrastructure/`, `backend/lambda/` with pip-audit/npm audit non-optional for HIGH+. | `security-scan.yml` | 0.5 d | — |

### P2 — depth and drift (backlog)

- Realistic scenarios (`RUN_REALISTIC=1`) and ShopLab simulator (`traffic.py --duration 60`)
  in nightly against the seeded stack; assert results converge (validator agent logic as code).
- Snapshot tests for the remaining 13 CDK stacks (`Template.from_stack(...).to_json()` diffed).
- Performance: run the 71 pytest specs in the unit job; store weekly Locust CSVs and fail on
  >20% p95 regression vs the previous run.
- `demo/shoplab` Jest + simulator pytest in the SDK matrix (they are the only consumer tests
  of the React SDK).
- Frontend page tests for the 18 untested pages; wizard step tests.
- Retire `docs/testing/integration-testing-plan.md` workflow names; point it at this document.
- Unify CI service versions (pg15-alpine, redis7-alpine) and `POSTGRES_SERVER`/`POSTGRES_SCHEMA`
  values via a reusable `workflow_call` that starts services and runs `bootstrap.py`.

### Regression-test checklist for PRs (for the new `.github/pull_request_template.md`)

- [ ] Bug reproduced by a failing test **before** the fix; test named `test_regression_<issue>_<summary>` and marked `@pytest.mark.regression`.
- [ ] Test sits at the layer where the bug was observed: API bug → DB-backed test in `backend/tests/integration/api/` through the public route; SDK bug → live contract entry or SDK unit test **that runs in CI**; dashboard bug → Playwright journey; scheduler bug → tick test.
- [ ] Test runs in a required check (`pytest --collect-only` with the exact CI arguments lists it).
- [ ] If the fix changed a response shape, `docs/api/openapi.json` is updated and the snapshot test passes.
- [ ] If the fix touched a model, a migration exists and `alembic check` is clean.
- [ ] Seed scripts (`seed_demo_data.py`, `seed_shoplab.py`) still produce the data the test needs (run `demo/setup-local.sh` or the seeded browser job).
