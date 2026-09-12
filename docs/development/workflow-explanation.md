# CI workflows

What runs on a pull request, what is required to merge, and what runs on a schedule.
All workflows live in `.github/workflows/`. Required checks are enforced by branch
protection on `main`; a pull request cannot be merged while any of them is red.

## Required checks on every pull request

| Check (status name) | Workflow | What it runs |
|---------------------|----------|--------------|
| Unit Tests | `pr-qa-gate.yml` | `backend/tests/unit` (+ Lambda tests) against a Postgres service |
| Smoke Tests | `pr-qa-gate.yml` | `backend/tests/smoke`: app import, route wiring, auth wiring |
| Frontend Tests | `pr-qa-gate.yml` | `npm test`, `tsc --noEmit`, `next build` |
| SDK Contract Tests | `pr-qa-gate.yml` | cross-SDK golden vectors (`tests/sdk-contract`) |
| SDK Live Contract | `pr-qa-gate.yml` | boots the API with `seed_sdk_contract`, drives every SDK through assign / evaluate / track |
| integration-tests | `integration-tests.yml` | `backend/tests/integration` with Postgres and Redis services |
| Security Scan Summary | `security-scan.yml` | Bandit, npm audit, Semgrep (`p/python`, `p/security-audit`, `p/secrets`, `p/owasp-top-ten`), Gitleaks, Trivy on the built image |
| Release Gate Summary | `release-gate.yml` | backend gate (unit + smoke), frontend gate (test + build), security gate (Bandit + Gitleaks) |

`Docker Smoke` (`pr-qa-gate.yml`) also runs on every pull request: it builds
`experimently-api:ce` and `experimently-web:ce`, starts `docker-compose.yml`, checks
`/health/ready`, that `/api/v1/experiments` is a 401 without credentials, logs in as the
seeded admin, mints an API key, assigns a user to `sdk_contract_ab` and verifies nginx
routing for a dynamic dashboard route. It becomes a required check in phase P1 of the
launch plan.

## Other pull-request and push workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `cognito-integration-tests.yml` | changes under `backend/app/**` or `backend/tests/integration/auth/**` | `backend/tests/integration/auth` with moto's Cognito mock; no database, so DB-backed auth tests live in `backend/tests/integration/api` instead |
| `infrastructure-tests.yml` | changes under `infrastructure/` | CDK stack unit tests |
| `security-scan.yml` | push, pull request, weekly | as above |

## Scheduled workflows

| Workflow | Schedule | Purpose |
|----------|----------|---------|
| `nightly-qa.yml` | nightly | unit, integration, smoke, SDK contract, frontend and accessibility suites in one run |
| `performance-tests.yml` | weekly and on demand | Locust load test against a freshly started API; SLA thresholds in `backend/tests/performance` |
| `security-scan.yml` | weekly | full scan including the container image |

## AWS deployment workflows

`deploy-dev.yml`, `deploy-prod.yml`, `db-migrate.yml` and `rollback.yml` deploy the CDK
stacks to AWS. They run only when the repository variable `AWS_ACCOUNT_ID` is set on the
upstream repository, so forks and the Community Edition never attempt a deploy. See
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
