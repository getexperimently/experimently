# Experimently — common tasks.
#
#   make dev        start Postgres + Redis and run the API and dashboard locally
#   make demo       build the images and run the whole stack in Docker
#   make test       the checks a pull request must pass
#
# Everything runs from the repository root; the backend is imported as
# `backend.app.*`, so `uvicorn backend.app.main:app` is the entry point.

SHELL := /bin/bash
VENV := venv
PY := $(VENV)/bin/python
PYTEST := $(VENV)/bin/python -m pytest
COMPOSE := docker compose

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

.PHONY: venv
venv: ## Create the virtualenv and install backend dependencies
	python3.11 -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r backend/requirements.txt

.PHONY: install
install: venv ## Install backend and frontend dependencies
	cd frontend && npm ci

.PHONY: db
db: ## Start Postgres and Redis only
	$(COMPOSE) up -d --wait postgres redis

.PHONY: bootstrap
bootstrap: ## Create the schema and the first administrator (idempotent)
	$(PY) -m backend.app.db.bootstrap

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

.PHONY: dev
dev: db bootstrap ## Run the API (:8000) with reload; start the dashboard with `make web`
	AUTH_PROVIDER=local $(VENV)/bin/uvicorn backend.app.main:app --reload --port 8000

.PHONY: web
web: ## Run the dashboard dev server (:3000)
	cd frontend && npm run dev

.PHONY: demo
demo: ## Build the images and run the full stack, including the demo apps
	SEED=demo,shoplab,streampulse $(COMPOSE) --profile demo up -d --build --wait

.PHONY: up
up: ## Run the core stack in Docker (API, dashboard, Postgres, Redis)
	$(COMPOSE) up -d --build --wait

.PHONY: down
down: ## Stop the stack and drop its volumes
	$(COMPOSE) down -v --remove-orphans

.PHONY: logs
logs: ## Follow the API and dashboard logs
	$(COMPOSE) logs -f api frontend

# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

.PHONY: test
test: test-backend test-frontend ## Everything a pull request must pass

.PHONY: test-backend
test-backend: ## Backend unit, integration and smoke tests
	APP_ENV=test TESTING=true $(PYTEST) backend/tests/unit backend/tests/integration backend/tests/smoke -q

.PHONY: test-unit
test-unit: ## Backend unit tests
	APP_ENV=test TESTING=true $(PYTEST) backend/tests/unit -q

.PHONY: test-integration
test-integration: ## Backend integration tests (needs Postgres on localhost:5432)
	APP_ENV=test TESTING=true $(PYTEST) backend/tests/integration -q

.PHONY: test-frontend
test-frontend: ## Dashboard tests, type check and production build
	cd frontend && npm test && npx tsc --noEmit && npm run build

.PHONY: test-coverage
test-coverage: ## Backend tests with a coverage report
	APP_ENV=test TESTING=true $(PYTEST) backend/tests/unit backend/tests/integration \
		--cov=backend.app --cov-report=term-missing

.PHONY: test-sdk
test-sdk: ## Cross-SDK golden-vector contract tests
	$(PYTEST) tests/sdk-contract/test_python_sdk.py -q
	node tests/sdk-contract/test_js_sdk.js

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------

.PHONY: lint
lint: ## Format check, import order, type check and lint
	$(VENV)/bin/black --check backend/
	$(VENV)/bin/isort --check-only backend/
	$(VENV)/bin/flake8 backend/
	cd frontend && npm run lint

.PHONY: format
format: ## Format the backend in place
	$(VENV)/bin/black backend/
	$(VENV)/bin/isort backend/

.PHONY: openapi
openapi: ## Regenerate the OpenAPI fixture the URL guard checks against
	$(PY) -m backend.scripts.dump_openapi frontend/src/tests/fixtures/openapi.json
