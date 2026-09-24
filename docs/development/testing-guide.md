# Testing Guide

Comprehensive guide for writing and running tests in Experimently.

## Overview

The platform uses a multi-layer testing strategy:

| Layer | Location | Purpose | Speed |
|-------|----------|---------|-------|
| Unit | `backend/tests/unit/` | Test isolated functions | Fast |
| Integration | `backend/tests/integration/` | Test components with real DB | Medium |
| E2E | `backend/tests/e2e/` | Test full user workflows | Slow |
| Contract | `backend/tests/contract/` | Validate API response shapes | Fast |
| Frontend | `frontend/src/tests/` | Test React components | Fast |

> **New features (EP-031–036):** the cross-SDK contract suite lives in
> `tests/sdk-contract/`; run it with the SDK Contract Tests job.
> for the full integration testing plan covering Java/JVM SDK, React SDK, SOC 2 / ISO 27001
> audit logging, Salesforce/Jira/GitHub integrations, Full Bayesian, and Split URL Testing.
> That document includes test file layouts, key scenarios, fixture definitions, and CI workflow additions.

---

## Environment Setup

### Prerequisites

- Python 3.11+, virtualenv
- PostgreSQL (via Docker)
- Node.js 18+ (for frontend tests)

### Backend Setup

```bash
# 1. Activate virtualenv (ALWAYS do this first)
source venv/bin/activate

# 2. Start PostgreSQL
docker ps | grep postgres
# If not running:
docker-compose up -d db

# 3. Set test environment variables
export APP_ENV=test
export TESTING=true
export POSTGRES_DB=experimentation
export POSTGRES_SCHEMA=experimentation
```

### Frontend Setup

```bash
cd frontend
npm install
```

---

## Running Tests

### All Backend Tests

```bash
source venv/bin/activate
export APP_ENV=test TESTING=true
python -m pytest backend/tests/ -v
```

### By Layer

```bash
# Unit tests only (fast, no DB required)
python -m pytest backend/tests/unit/ -v

# Integration tests (requires PostgreSQL)
python -m pytest backend/tests/integration/ -v

# E2E tests (requires full stack)
python -m pytest backend/tests/e2e/ -v

# Contract tests
python -m pytest backend/tests/contract/ -v
```

### IMPORTANT: Run Suites Separately

Due to transaction isolation, run DB-heavy and API test suites in separate invocations:

```bash
# ✅ CORRECT — separate invocations
python -m pytest backend/tests/integration/database/ -v
python -m pytest backend/tests/integration/api/test_experiments_api.py -v

# ❌ WRONG — can corrupt connection pool
python -m pytest backend/tests/integration/ -v  # may cause SA warnings
```

### Specific Tests

```bash
# Single file
python -m pytest backend/tests/unit/services/test_experiment_service.py -v

# Specific test function
python -m pytest backend/tests/unit/core/test_rules_engine.py::test_evaluate_equals -xvs

# By marker
python -m pytest -m "unit" -v
python -m pytest -m "integration" -v
python -m pytest -m "requires_db" -v

# Skip slow tests
python -m pytest -m "not slow" -v

# Keyword match
python -m pytest -k "experiment" -v
```

### Frontend Tests

```bash
cd frontend
npm test                    # Run all tests
npm test -- --watchAll=false  # Single run (CI mode)
npm test -- --coverage      # With coverage report
```

---

## Test Markers

Declared in `[tool.pytest.ini_options] markers` in **`pyproject.toml`**.
There is no `pytest.ini`; the configuration was consolidated into
`pyproject.toml`. Declaring a marker there is what stops pytest warning about
it — `--strict-markers` is **not** enabled (`addopts = ""`), so an undeclared
marker warns rather than fails.

| Marker | Usage |
|--------|-------|
| `@pytest.mark.unit` | Fast, no external dependencies |
| `@pytest.mark.integration` | Requires the database |
| `@pytest.mark.e2e` | Requires the full stack |
| `@pytest.mark.regression` | **Guards a specific past bug** — see below |
| `@pytest.mark.modules` | Needs the modules package; skipped in a core build |
| `@pytest.mark.smoke` | Wiring checks that must hold for any build of this tree |
| `@pytest.mark.slow` | Slow running |
| `@pytest.mark.api` | API tests |
| `@pytest.mark.contract` | API contract tests |
| `@pytest.mark.cors` | CORS tests |
| `@pytest.mark.security` | Security header tests |
| `@pytest.mark.dependency` | Dependency-injection tests |
| `@pytest.mark.validation` | Validation tests |
| `@pytest.mark.realistic` | Realistic scenarios (require a running platform) |
| `@pytest.mark.requires_db` | Explicit database requirement |
| `@pytest.mark.requires_aws` | Needs LocalStack or AWS |
| `@pytest.mark.cognito_integration` | Cognito tests (require moto) |

`regression` is not optional bookkeeping. Every bug fix carries a
`@pytest.mark.regression` test that fails on the old code, and the
`regression-guard` CI job fails a pull request labelled `bug` that changes no
test file. Run them with `pytest -m regression`.

Note the PR gates run by **directory** (`unit`, `integration`, `smoke`,
`contract`, `e2e`), not by marker — so an unmarked test still runs.

---

## Writing Backend Tests

### Unit Test Pattern

```python
# backend/tests/unit/services/test_my_service.py
import pytest
from unittest.mock import MagicMock, patch
from backend.app.services.my_service import MyService


def test_my_service_returns_correct_value():
    """Unit tests: mock all dependencies, test logic only."""
    db = MagicMock()
    service = MyService(db)

    result = service.compute(42)

    assert result == 84
    db.query.assert_called_once()
```

### Integration Test Pattern

```python
# backend/tests/integration/api/test_my_api.py
import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
class TestMyEndpoint:
    def test_create_resource(self, admin_client: TestClient):
        """Integration tests: real DB, mocked auth."""
        response = admin_client.post("/api/v1/my-resource", json={
            "name": "Test Resource",
            "value": 42,
        })

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Resource"

    def test_unauthorized_returns_403(self, analyst_client: TestClient):
        response = analyst_client.post("/api/v1/my-resource", json={"name": "Test"})
        assert response.status_code == 403
```

### Async Test Pattern

```python
import pytest

# Feature flag and report deps are ASYNC — use asyncio marker
@pytest.mark.asyncio
async def test_feature_flag_permission(db_session, admin_user):
    from backend.app.api.deps import get_feature_flag_access
    result = await get_feature_flag_access(
        flag_id=some_flag.id,
        current_user=admin_user,
        db=db_session,
    )
    assert result is not None

# Experiment deps are SYNC — no asyncio needed
def test_experiment_permission(db_session, admin_user):
    from backend.app.api.deps import get_experiment_access
    result = get_experiment_access(
        experiment_id=some_exp.id,
        current_user=admin_user,
        db=db_session,
    )
    assert result is not None
```

---

## Available Fixtures

### From Root `conftest.py` (`backend/tests/conftest.py`)

| Fixture | Type | Description |
|---------|------|-------------|
| `db_session` | `Session` | DB session with automatic rollback after each test |
| `test_client` | `TestClient` | Unauthenticated test client |

### From Integration `conftest.py` (`backend/tests/integration/conftest.py`)

| Fixture | Type | Description |
|---------|------|-------------|
| `admin_user` | `User` | Admin user (is_superuser=True) |
| `developer_user` | `User` | Developer role user |
| `analyst_user` | `User` | Analyst role user (read-only) |
| `viewer_user` | `User` | Viewer role user |
| `admin_client` | `TestClient` | Client authenticated as admin |
| `developer_client` | `TestClient` | Client authenticated as developer |
| `analyst_client` | `TestClient` | Client authenticated as analyst |
| `make_experiment` | `Callable` | Factory to create Experiment objects |
| `make_variant` | `Callable` | Factory to create Variant objects |
| `make_metric` | `Callable` | Factory to create Metric objects |
| `make_feature_flag` | `Callable` | Factory to create FeatureFlag objects |
| `make_event` | `Callable` | Factory to create Event objects |
| `make_assignment` | `Callable` | Factory to create Assignment objects |

### Factory Fixture Usage

```python
def test_experiment_with_variants(
    admin_client, make_experiment, make_variant, make_metric
):
    # Create test data using factories
    exp = make_experiment(name="My Test Exp", status=ExperimentStatus.DRAFT)
    control = make_variant(exp, name="Control", is_control=True, traffic_allocation=50.0)
    treatment = make_variant(exp, name="Treatment", is_control=False, traffic_allocation=50.0)
    metric = make_metric(exp, name="Conversion", event_name="purchase")

    # Override defaults
    exp2 = make_experiment(
        name="Custom Experiment",
        description="Custom description",
        status=ExperimentStatus.ACTIVE,
    )
```

---

## Mocking Authentication

### Using Pre-built Client Fixtures

```python
def test_admin_can_do_everything(admin_client):
    # admin_client is already authenticated as ADMIN
    response = admin_client.post("/api/v1/experiments", json={...})
    assert response.status_code == 201


def test_analyst_is_read_only(analyst_client):
    # analyst_client authenticated as ANALYST
    response = analyst_client.delete("/api/v1/experiments/some-id")
    assert response.status_code == 403
```

### Custom Auth Mock

```python
from backend.app.main import app
from backend.app.api import deps
from fastapi.testclient import TestClient


def test_custom_user_scenario(db_session, some_user):
    from backend.tests.integration.conftest import make_client_for_user
    client = make_client_for_user(db_session, some_user)

    response = client.get("/api/v1/experiments")
    assert response.status_code == 200
```

---

## Mocking Imports

### Mocking External Services

```python
from unittest.mock import patch, MagicMock


def test_cognito_auth_mocked():
    mock_user_data = {
        "username": "testuser",
        "attributes": {"email": "test@example.com"},
        "groups": ["admin-group"],
    }

    with patch(
        "backend.app.services.auth_service.CognitoAuthService.get_user_with_groups",
        return_value=mock_user_data,
    ):
        # Test code here
        pass
```

### Mocking DB for Unit Tests

```python
def test_service_handles_db_error():
    db = MagicMock()
    db.query.side_effect = Exception("Connection refused")

    service = ExperimentService(db)

    with pytest.raises(Exception, match="Connection refused"):
        service.get_experiment("some-id")
```

---

## Database Test Patterns

### Transaction Rollback (Default)

The root `db_session` fixture wraps each test in a transaction that is rolled back after the test. No data persists between tests. This is the standard for integration tests.

```python
def test_creates_then_reads(db_session, make_experiment):
    # Data created here is rolled back after test
    exp = make_experiment(name="Rollback Test")
    assert db_session.query(Experiment).filter_by(name="Rollback Test").first()
    # After test — row is gone
```

### E2E Tests (Committed Data)

E2E tests use a separate `e2e_db_session` that allows real commits:

```python
# In backend/tests/e2e/conftest.py
@pytest.fixture
def e2e_db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
```

---

## Contract Tests

Contract tests validate that API responses match their expected JSON Schema:

```python
# backend/tests/contract/test_api_contracts.py
import jsonschema
import json

def test_experiment_response_matches_schema(admin_client):
    response = admin_client.post("/api/v1/experiments", json={...})
    assert response.status_code == 201

    schema = json.load(open("backend/tests/contract/schemas/experiment_schema.json"))
    jsonschema.validate(response.json(), schema)  # Raises if invalid
```

Schema files are in `backend/tests/contract/schemas/`:
- `experiment_schema.json`
- `feature_flag_schema.json`
- `assignment_schema.json`

---

## Frontend Testing

### Component Test Pattern

```typescript
// frontend/src/tests/components/MyComponent.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import MyComponent from '@/components/MyComponent';

describe('MyComponent', () => {
  it('renders correctly', () => {
    render(<MyComponent title="Hello" />);
    expect(screen.getByText('Hello')).toBeInTheDocument();
  });

  it('handles click events', () => {
    const onClick = jest.fn();
    render(<MyComponent onClick={onClick} />);
    fireEvent.click(screen.getByRole('button'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
```

### Mocking Recharts

```typescript
// frontend/src/tests/__mocks__/recharts.tsx
jest.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: any) => <div>{children}</div>,
  BarChart: ({ children }: any) => <div data-testid="bar-chart">{children}</div>,
  Bar: ({ name }: any) => <div data-testid="variant-bar">{name}</div>,
  LineChart: ({ children }: any) => <div data-testid="line-chart">{children}</div>,
  Line: ({ name }: any) => <div data-testid="trend-line">{name}</div>,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  Legend: () => null,
}));
```

### Mocking fetch

```typescript
const mockFetch = jest.fn();
global.fetch = mockFetch;

beforeEach(() => {
  mockFetch.mockResolvedValue({
    ok: true,
    json: () => Promise.resolve(mockData),
  });
});
```

---

## Debugging Tests

### Verbose Output

```bash
# Maximum verbosity with full traceback
python -m pytest backend/tests/unit/my_test.py -xvs

# Stop on first failure
python -m pytest backend/tests/ -x

# Show local variables on failure
python -m pytest backend/tests/ --tb=long -l
```

### Debugging DB State

```python
def test_debug_db_state(db_session, make_experiment):
    exp = make_experiment(name="Debug Test")
    db_session.flush()

    # Inspect directly
    from sqlalchemy import text
    result = db_session.execute(text("SELECT * FROM experimentation.experiments LIMIT 5"))
    print(result.fetchall())

    # Use breakpoint
    breakpoint()  # Drops into pdb
```

### Clearing Schema Cache

```python
# If tests fail with "Class is not mapped" errors:
from backend.app.core.database_config import clear_schema_cache
clear_schema_cache()
```

---

## CI/CD

The platform runs integration tests in GitHub Actions via `.github/workflows/integration-tests.yml`:

```yaml
services:
  postgres:
    image: postgres:14
    env:
      POSTGRES_DB: experimentation_test
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports: ["5432:5432"]
  redis:
    image: redis:7
    ports: ["6379:6379"]

steps:
  - name: Run integration tests
    run: |
      source venv/bin/activate
      export APP_ENV=test TESTING=true
      python -m pytest backend/tests/integration/database/ -v
      python -m pytest backend/tests/integration/api/ -v
      python -m pytest backend/tests/contract/ -v
```

---

## Coverage

```bash
# Generate coverage report
python -m pytest backend/tests/ --cov=backend/app --cov-report=html

# View in browser
open htmlcov/index.html

# Minimum threshold check
python -m pytest --cov=backend/app --cov-fail-under=80
```

Current coverage targets:
- Unit tests: >90%
- Integration tests: >70%
- Overall: >80%

---

## Common Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| `import errors` | Virtualenv not activated | `source venv/bin/activate` |
| `SAWarning: transaction already deassociated` | Mixed commit/rollback tests in same session | Run suites in separate pytest invocations |
| `invalid input value for enum` | Using string `"conversion"` instead of enum | Use `MetricType.CONVERSION` enum object |
| `Class is not mapped` | Inconsistent import paths | Use full qualified imports: `from backend.app.models...` |
| `connection refused` | PostgreSQL not running | `docker-compose up -d db` |
| `AttributeError: 'CacheControl' has no attribute 'get'` | Dict-style access on Pydantic model | Use `DictLikeCacheControl` shim in test fixtures |
| `hashed_password` integrity error | User created without password hash | Set `hashed_password="$2b$12$..."` in user fixture |
