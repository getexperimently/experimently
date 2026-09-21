# CI workflows

What runs on a pull request, what is required to merge, and what runs on a schedule.
All workflows live in `.github/workflows/`. Required checks are enforced by branch
protection on `main`; a pull request cannot be merged while any of them is red.

## Required checks on every pull request

The status name is what branch protection matches on — the job's `name:`, not its
id — so renaming a job silently drops its gate. Read the live list with:

```bash
gh api repos/<owner>/<repo>/branches/main/protection --jq '.required_status_checks.contexts'
```

| Check (status name) | Workflow | What it runs |
|---------------------|----------|--------------|
| Unit Tests | `pr-qa-gate.yml` | `backend/tests/unit` (+ Lambda tests) against a Postgres service |
| Module Tests | `pr-qa-gate.yml` | `modules/backend/tests` with both requirement sets installed |
| Smoke Tests | `pr-qa-gate.yml` | `backend/tests/smoke`: app import, route wiring, auth wiring |
| Base Requirements Only | `pr-qa-gate.yml` | the modules must register on `backend/requirements.txt` alone (`scripts/check_modules_register.py`), then the smoke suite |
| Frontend Tests | `pr-qa-gate.yml` | `npm test`, `tsc --noEmit`, `next build` |
| SDK Contract Tests | `pr-qa-gate.yml` | cross-SDK golden vectors (`tests/sdk-contract`) |
| SDK Live Contract / sdk-live-contract (core) | `pr-qa-gate.yml` | boots the API with `seed_sdk_contract`, drives every SDK through assign / evaluate / track |
| SDK Unit Tests | `sdk-unit-tests.yml` | aggregate of the per-SDK legs (each leg runs only when its SDK changed) |
| core-build | `pr-qa-gate.yml` | `scripts/core_build.sh`: copy the tree, delete `modules/`, rebuild and run the suites |
| full-build | `pr-qa-gate.yml` | the same sequence on the full tree |
| Browser E2E | `pr-qa-gate.yml` | Playwright specs against a booted stack |
| Docker Smoke | `pr-qa-gate.yml` | builds `experimently-api:core` and `experimently-web:core`, starts `docker-compose.yml`, checks `/health/ready`, that `/api/v1/experiments` is a 401 without credentials, logs in as the seeded admin, mints an API key, assigns a user to `sdk_contract_ab` and verifies nginx routing for a dynamic dashboard route |
| integration-tests | `integration-tests.yml` | `backend/tests/integration` with Postgres and Redis services |
| lint | `lint.yml` | ruff, import-linter, REUSE, lock check, eslint, tsc, hadolint, actionlint |
| regression-guard | `regression-guard.yml` | a pull request labelled `bug` must change a test file |
| Security Scan Summary | `security-scan.yml` | Bandit, npm audit, Semgrep (`p/python`, `p/security-audit`, `p/secrets`, `p/owasp-top-ten`), Gitleaks, Trivy on the built image |
| Release Gate Summary | `release-gate.yml` | backend gate (unit + smoke), frontend gate (test + build), security gate (Bandit + Gitleaks) |
| CDK Stack Tests (Python) | `infrastructure-tests.yml` | `infrastructure/tests`, including a real `cdk synth` of both profiles (`TestTheAppActuallySynthesises`) |

Deliberately **not** required, because it is path-filtered and a required check
that never reports leaves a pull request permanently pending: `cognito-integration`
(`cognito-integration-tests.yml`). `CDK Stack Tests (Python)` used to be in this
list for the same reason; its path filter was removed when it grew a real
`cdk synth` (see below), so it can now be required. The per-job checks behind an aggregate
(`Backend Gate`, `Frontend Gate`, `Security Gate`; `Python Security Scan`,
`Semgrep SAST`, …; `Select SDKs` and the per-SDK legs) are not listed either —
their summary job is.

## Other pull-request and push workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `cognito-integration-tests.yml` | changes under `backend/app/**` or `backend/tests/integration/auth/**` | `backend/tests/integration/auth` with moto's Cognito mock; no database, so DB-backed auth tests live in `backend/tests/integration/api` instead |
| `security-scan.yml` | push, pull request, weekly | as above |

## Scheduled workflows

| Workflow | Schedule | Purpose |
|----------|----------|---------|
| `nightly-qa.yml` | nightly | unit, integration, smoke, SDK contract, frontend and accessibility suites in one run |
| `performance-tests.yml` | weekly and on demand | Locust load test against a freshly started API; SLA thresholds in `backend/tests/performance` |
| `security-scan.yml` | weekly | full scan including the container image |
| `dependabot-lock.yml` | weekdays 09:00 UTC, and on demand | regenerates `runtime.lock` / `modules.lock` on Dependabot branches and pushes the result. Dependabot updates `runtime.txt` but cannot produce `uv pip compile --generate-hashes` output, so without this every runtime-dependency bump fails `lint` and `Unit Tests` (#185) |

## AWS deployment workflows

`deploy-dev.yml`, `deploy-prod.yml`, `db-migrate.yml` and `rollback.yml` deploy the CDK
stacks to AWS. They run only when the repository variable `AWS_ACCOUNT_ID` is set on the
upstream repository, so forks and self-hosted checkouts never attempt a deploy. See
[docs/deployment](../deployment/README.md).

## Running the same checks locally

```bash
source venv/bin/activate && export APP_ENV=test TESTING=true
python -m pytest backend/tests/unit backend/tests/smoke -q -p no:cov     # Unit + Smoke
python -m pytest backend/tests/integration -q -p no:cov                   # integration-tests
cd frontend && npm test && npx tsc --noEmit && npm run build              # Frontend Tests
python -m pytest tests/sdk-contract/test_python_sdk.py -o addopts="" && node tests/sdk-contract/test_js_sdk.js   # SDK Contract Tests
docker compose up -d --wait && curl -sf localhost:8000/health/ready       # Docker Smoke, first half
```

Postgres must be reachable on `localhost:5432` for the backend suites (`docker compose up -d postgres`).

## Conventions

- Backend tests are organised by directory (`unit`, `integration`, `smoke`, `contract`, `e2e`);
  the PR gates run by directory, not by marker, so an unmarked test still runs. Markers are
  declared in `pytest.ini`.
- Every bug fix ships with a regression test in the suite that would have caught it.
- A new workflow must either be added to the required-checks list in branch protection
  or documented here as advisory.
