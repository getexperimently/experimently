# Integration Testing Plan — Full Platform

Covers all features through EP-036. Read alongside `docs/development/testing-guide.md`
for environment setup, fixtures, and common patterns.

---

## Quick Reference

| Feature | Issue | New Integration Tests | CI Workflow | External Mocks |
|---------|-------|-----------------------|-------------|----------------|
| Core A/B + Feature Flags | EP-001–020 | ~100 (existing) | `integration-tests.yml` | None |
| Cognito Auth | P1-A | 91 (existing) | `cognito-integration-tests.yml` | moto |
| RBAC | P2-A | 58 (existing) | `integration-tests.yml` | None |
| DynamoDB Counters | P2-B | 77 (existing) | `realtime-counters-tests.yml` | moto |
| Sequential Testing | EP-021 | 30 (existing) | `integration-tests.yml` | None |
| Mutual Exclusion | EP-022 | 40 (existing) | `integration-tests.yml` | None |
| **Java/JVM SDK** | **EP-031** | **~70 new** | `sdk-integration-tests.yml` | WireMock |
| **React SDK** | **EP-032** | **~50 new** | `sdk-integration-tests.yml` | MSW |
| **SOC 2 / ISO 27001** | **EP-033** | **~120 new** | `compliance-tests.yml` | None |
| **Salesforce/Jira/GitHub** | **EP-034** | **~90 new** | `integrations-tests.yml` | respx/WireMock |
| **Full Bayesian** | **EP-035** | **~45 new** | `integration-tests.yml` | None |
| **Split URL Testing** | **EP-036** | **~55 new** | `split-url-tests.yml` | LocalStack |

**Total new integration tests: ~430**

---

## Test Layer Philosophy

```
          Slowest / Most Realistic
          ┌──────────────────────────┐
          │     E2E / Workflow       │  Full stack, committed data
          ├──────────────────────────┤
          │    Integration (API)     │  Real DB, mocked auth + external APIs
          ├──────────────────────────┤
          │   Integration (Service)  │  Real DB, mocked HTTP
          ├──────────────────────────┤
          │    Contract              │  API shape validation (JSON Schema)
          ├──────────────────────────┤
          │    Unit                  │  All mocked
          └──────────────────────────┘
          Fastest / Most Isolated
```

Integration tests sit in the middle: they use a **real PostgreSQL database** and the
**real FastAPI app** via `TestClient`, but mock authentication (via `dependency_overrides`)
and all external HTTP APIs (Salesforce, Jira, GitHub, Slack, etc.).

---

## EP-031: Java/JVM SDK Integration Tests

### What Needs Integration Testing

The JVM SDK is a separate client artifact. Integration tests verify that:
1. The **platform API** produces responses the SDK can consume (contract layer)
2. The **assignment consistency** between the SDK's local evaluator and the Lambda assignment service
3. The **event ingestion pipeline** accepts batched events from the SDK

### Test Files

```
backend/tests/integration/sdk/
├── __init__.py
├── conftest.py                          # SDK-specific fixtures
├── test_sdk_ruleset_endpoint.py         # GET /api/v1/sdk/ruleset shape + content
├── test_sdk_assignment_consistency.py   # SDK hash == Lambda hash for same inputs
├── test_sdk_event_ingestion.py          # POST /api/v1/events accepts SDK batch format
└── test_sdk_api_key_auth.py             # SDK API key authentication flows

backend/tests/contract/schemas/
├── sdk_ruleset_schema.json              # JSON Schema for ruleset response
├── sdk_assignment_schema.json           # JSON Schema for assignment response
└── sdk_event_batch_schema.json          # JSON Schema for event batch request
```

### Key Test Scenarios

```python
# test_sdk_ruleset_endpoint.py
@pytest.mark.integration
class TestSDKRulesetEndpoint:

    def test_ruleset_includes_active_flags(self, admin_client, make_feature_flag):
        """Active flags appear in ruleset; archived flags do not."""
        active = make_feature_flag(status=FeatureFlagStatus.ACTIVE, rollout_percentage=50)
        archived = make_feature_flag(status=FeatureFlagStatus.ARCHIVED)

        response = admin_client.get("/api/v1/sdk/ruleset",
                                    headers={"X-API-Key": "test-sdk-key"})
        assert response.status_code == 200

        keys = [f["key"] for f in response.json()["feature_flags"]]
        assert active.key in keys
        assert archived.key not in keys

    def test_ruleset_includes_split_url_experiments(self, admin_client, make_experiment):
        """Split URL experiments included in ruleset for Lambda@Edge."""
        exp = make_experiment(experiment_type="split_url",
                              split_url_config={"control_url": "/pricing",
                                                "variants": [{"key": "v2", "url": "/pricing-v2",
                                                              "weight": 0.5}]})
        response = admin_client.get("/api/v1/sdk/ruleset",
                                    headers={"X-API-Key": "test-sdk-key"})
        assert "split_url_experiments" in response.json()

    def test_ruleset_respects_etag_caching(self, admin_client):
        """304 Not Modified returned when ruleset unchanged (ETag)."""
        r1 = admin_client.get("/api/v1/sdk/ruleset", headers={"X-API-Key": "test-key"})
        etag = r1.headers["ETag"]
        r2 = admin_client.get("/api/v1/sdk/ruleset",
                               headers={"X-API-Key": "test-key", "If-None-Match": etag})
        assert r2.status_code == 304


# test_sdk_assignment_consistency.py
@pytest.mark.integration
class TestSDKAssignmentConsistency:

    def test_sdk_hash_matches_lambda_hash(self, make_experiment, make_variant):
        """
        Consistent hashing must produce identical results in:
        - Python Lambda assignment service
        - JVM SDK (verified via contract test with known input/output pairs)
        """
        from backend.lambda.shared.consistent_hash import ConsistentHasher
        hasher = ConsistentHasher()

        # Known test vectors — must match JVM SDK output
        test_vectors = [
            ("user-001", "exp-abc", "control"),
            ("user-002", "exp-abc", "treatment"),
            ("user-abc-123", "exp-xyz", "control"),
        ]
        for user_id, exp_key, expected_variant in test_vectors:
            result = hasher.get_variant(user_id, exp_key, variants=["control", "treatment"],
                                        weights=[0.5, 0.5])
            assert result == expected_variant, (
                f"Hash mismatch for ({user_id}, {exp_key}): "
                f"got {result}, expected {expected_variant}"
            )
```

### CI Workflow Additions

The SDK integration tests require a **WireMock server** (for testing SDK → platform HTTP)
and are best run as a separate job in `sdk-integration-tests.yml`:

```yaml
# .github/workflows/sdk-integration-tests.yml
name: SDK Integration Tests
on:
  push:
    paths:
      - 'sdk/**'
      - 'backend/app/api/v1/endpoints/sdk*'
      - 'backend/tests/integration/sdk/**'
      - 'backend/tests/contract/**'

jobs:
  sdk-contract-tests:
    runs-on: ubuntu-latest
    services:
      postgres: { ... }
    steps:
      - name: Run SDK contract tests
        run: |
          python -m pytest backend/tests/contract/ -v \
            -m "contract" --junit-xml=test-results/contract.xml

      - name: Run SDK integration tests
        run: |
          python -m pytest backend/tests/integration/sdk/ -v \
            --junit-xml=test-results/sdk-integration.xml

      - name: Run JVM SDK tests (Java)
        working-directory: sdk/java
        run: mvn test -Dtest="*IntegrationTest" -pl experimentation-client
```

### Expected Test Count: ~70 tests
- Ruleset endpoint shape + content: 15
- Assignment consistency (hash vectors): 20
- Event ingestion + batching: 15
- API key auth: 10
- Contract (JSON Schema): 10

---

## EP-032: React SDK Integration Tests

### What Needs Integration Testing

The React SDK wraps the JS SDK with React primitives. Integration tests verify:
1. Provider correctly fetches flags from the platform
2. Hooks return correct values and re-render on changes
3. SSR bootstrap prevents re-fetch when data is fresh
4. Assignment impression events are sent

### Tooling

- **MSW (Mock Service Worker)** — intercepts `fetch` in Jest/JSDOM, mocks platform API
- **React Testing Library** — renders hooks and components in a real React tree
- **Playwright** — E2E SSR/hydration tests for Next.js integration

### Test Files

```
frontend/src/tests/sdk/
├── setup/msw-handlers.ts                # MSW request handlers (mock platform API)
├── integration/
│   ├── ExperimentationProvider.test.tsx # Provider init, loading, error states
│   ├── useFeatureFlag.test.tsx          # Hook return values + re-render on change
│   ├── useExperiment.test.tsx           # Assignment stability + impression tracking
│   ├── useVariantValue.test.tsx         # Variant payload extraction
│   ├── Experiment.component.test.tsx    # Declarative component rendering
│   └── ssr-bootstrap.test.tsx           # Bootstrap flags, no re-fetch if fresh
└── e2e/
    ├── nextjs-ssr-hydration.spec.ts     # Playwright: no flicker on initial load
    └── flag-live-update.spec.ts         # Playwright: component re-renders on flag change
```

### Key Test Scenarios

```typescript
// useFeatureFlag.test.tsx
import { renderHook, act } from '@testing-library/react';
import { server } from '../setup/msw-server';
import { http, HttpResponse } from 'msw';

describe('useFeatureFlag integration', () => {
  it('returns false while loading, then true when flag is enabled', async () => {
    server.use(
      http.get('/api/v1/sdk/ruleset', () =>
        HttpResponse.json({
          feature_flags: [{ key: 'dark-mode', enabled: true, rollout_percentage: 100 }]
        })
      )
    );

    const { result } = renderHook(() => useFeatureFlag('dark-mode', false), {
      wrapper: ({ children }) => (
        <ExperimentationProvider apiKey="test-key" userId="user-1">
          {children}
        </ExperimentationProvider>
      ),
    });

    expect(result.current).toBe(false);  // loading state = default
    await waitFor(() => expect(result.current).toBe(true));
  });

  it('returns stable assignment across re-renders', async () => {
    const { result, rerender } = renderHook(() => useExperiment('checkout-flow'), {
      wrapper: ProviderWrapper,
    });

    await waitForAssignment();
    const firstVariant = result.current.variant.key;

    rerender();  // force re-render
    expect(result.current.variant.key).toBe(firstVariant);  // must be stable
  });

  it('tracks impression event on first render only', async () => {
    const trackSpy = jest.fn();
    server.use(
      http.post('/api/v1/events', async ({ request }) => {
        trackSpy(await request.json());
        return HttpResponse.json({ ok: true });
      })
    );

    const { rerender } = render(<Experiment name="hero-test">...</Experiment>);
    rerender(<Experiment name="hero-test">...</Experiment>);

    await waitFor(() => expect(trackSpy).toHaveBeenCalledTimes(1));  // exactly once
  });
});
```

### Expected Test Count: ~50 tests
- Provider (init, loading, error, reconnect): 10
- `useFeatureFlag` hook: 10
- `useExperiment` hook: 10
- Declarative `<Experiment>` component: 8
- SSR bootstrap + Next.js hydration: 8
- Impression tracking: 4

---

## EP-033: SOC 2 / ISO 27001 Compliance Audit Logging

### What Needs Integration Testing

This is the **most critical feature for integration testing** because the contract is:
"every write to a sensitive resource must emit a correctly-formed audit event."

Verification requires real database writes (not mocks), so this is inherently an
integration testing problem.

### Test Files

```
backend/tests/integration/compliance/
├── __init__.py
├── conftest.py                              # audit_capture fixture, hmac_verifier
├── test_audit_crud_coverage.py              # Every audited endpoint emits audit event
├── test_audit_auth_events.py                # Login, logout, MFA, role grant events
├── test_audit_data_access.py                # Read events on PII-adjacent resources
├── test_audit_hmac_integrity.py             # HMAC signing + verification
├── test_audit_redaction.py                  # Sensitive fields redacted in stored JSON
├── test_audit_retention_policy.py           # Retention TTL set correctly per framework
└── test_compliance_report_generation.py     # Report generator produces correct output

backend/tests/integration/compliance/helpers.py
```

### Critical Fixture: `audit_capture`

```python
# conftest.py
@pytest.fixture
def audit_capture(db_session):
    """
    Context manager that captures AuditEvent records created during a test block.

    Usage:
        with audit_capture as events:
            admin_client.post("/api/v1/experiments", json={...})
        assert len(events) == 1
        assert events[0].action == "CREATE"
        assert events[0].resource_type == "experiment"
    """
    from backend.app.models.audit_log import AuditEvent

    class _Capture:
        def __init__(self):
            self.events = []

        def __enter__(self):
            self._before_count = db_session.query(AuditEvent).count()
            return self

        def __exit__(self, *args):
            self.events = (
                db_session.query(AuditEvent)
                .order_by(AuditEvent.timestamp.desc())
                .offset(self._before_count)
                .all()
            )

    return _Capture()
```

### Key Test Scenarios

```python
# test_audit_crud_coverage.py

# ── Parameterised coverage test — every audited endpoint ──────────────────────
AUDITED_ENDPOINTS = [
    ("POST",   "/api/v1/experiments",           "experiment",    "CREATE"),
    ("PUT",    "/api/v1/experiments/{id}",       "experiment",    "UPDATE"),
    ("DELETE", "/api/v1/experiments/{id}",       "experiment",    "DELETE"),
    ("POST",   "/api/v1/feature-flags",          "feature_flag",  "CREATE"),
    ("PUT",    "/api/v1/feature-flags/{id}",     "feature_flag",  "UPDATE"),
    ("POST",   "/api/v1/users",                  "user",          "CREATE"),
    ("POST",   "/api/v1/auth/roles/{id}/assign", "role",          "ROLE_GRANT"),
    ("POST",   "/api/v1/api-keys",               "api_key",       "KEY_CREATE"),
    ("DELETE", "/api/v1/api-keys/{id}",          "api_key",       "KEY_REVOKE"),
    # ... all audited endpoints
]

@pytest.mark.parametrize("method,path,resource_type,expected_action", AUDITED_ENDPOINTS)
@pytest.mark.integration
def test_endpoint_emits_audit_event(method, path, resource_type, expected_action,
                                    admin_client, audit_capture, make_fixtures):
    with audit_capture as cap:
        make_request(admin_client, method, path, make_fixtures)

    assert len(cap.events) >= 1, f"{method} {path} must emit at least one audit event"
    event = cap.events[0]
    assert event.resource_type == resource_type
    assert event.action == expected_action
    assert event.actor_id is not None
    assert event.timestamp is not None


# test_audit_hmac_integrity.py
@pytest.mark.integration
class TestAuditHMACIntegrity:

    def test_stored_events_have_valid_hmac(self, admin_client, db_session, make_experiment):
        """Every stored audit event can be verified with the current HMAC key."""
        from backend.app.services.audit_verifier import AuditVerifier
        from backend.app.models.audit_log import AuditEvent

        admin_client.post("/api/v1/experiments", json={...})

        events = db_session.query(AuditEvent).order_by(AuditEvent.timestamp.desc()).limit(5).all()
        verifier = AuditVerifier()

        for event in events:
            assert verifier.verify(event), f"HMAC verification failed for event {event.id}"

    def test_tampered_event_fails_verification(self, db_session, make_experiment):
        """Modifying any field invalidates the HMAC signature."""
        from backend.app.services.audit_verifier import AuditVerifier
        from backend.app.models.audit_log import AuditEvent

        event = db_session.query(AuditEvent).first()
        event.actor_ip = "999.999.999.999"  # tamper
        db_session.flush()

        assert not AuditVerifier().verify(event)


# test_audit_redaction.py
@pytest.mark.integration
class TestAuditRedaction:

    def test_password_not_stored_in_audit_log(self, admin_client, db_session):
        """hashed_password never appears in audit event new_value."""
        admin_client.post("/api/v1/users", json={
            "username": "newuser",
            "email": "new@example.com",
            "password": "S3cr3tP@ssword!",
        })

        from backend.app.models.audit_log import AuditEvent
        events = db_session.query(AuditEvent).filter_by(resource_type="user").all()
        for event in events:
            payload_str = str(event.new_value or "")
            assert "S3cr3tP@ssword!" not in payload_str
            assert "hashed_password" not in payload_str or "[REDACTED]" in payload_str

    def test_api_key_secret_redacted(self, admin_client, db_session):
        """API key secret value is redacted in audit log."""
        response = admin_client.post("/api/v1/api-keys", json={"name": "My Key"})
        secret = response.json()["secret"]

        from backend.app.models.audit_log import AuditEvent
        events = db_session.query(AuditEvent).filter_by(action="KEY_CREATE").all()
        for event in events:
            assert secret not in str(event.new_value or "")
```

### CI Workflow: `compliance-tests.yml`

```yaml
name: Compliance & Audit Tests
on:
  push:
    paths:
      - 'backend/app/models/audit_log.py'
      - 'backend/app/services/audit*'
      - 'backend/app/api/v1/endpoints/**'   # any endpoint change requires audit re-check
      - 'backend/tests/integration/compliance/**'

jobs:
  compliance-tests:
    runs-on: ubuntu-latest
    services:
      postgres: { ... }
    steps:
      - name: Run audit CRUD coverage
        run: |
          python -m pytest backend/tests/integration/compliance/test_audit_crud_coverage.py \
            -v --tb=short -m "integration"

      - name: Run HMAC integrity tests
        run: |
          python -m pytest backend/tests/integration/compliance/test_audit_hmac_integrity.py \
            -v --tb=short

      - name: Run full compliance suite
        run: |
          python -m pytest backend/tests/integration/compliance/ \
            -v --tb=short --junit-xml=test-results/compliance.xml
```

### Expected Test Count: ~120 tests
- CRUD audit coverage (all endpoints, parameterised): 40
- Auth event logging: 15
- Data access (read) logging: 10
- HMAC signing + tamper detection: 15
- Field redaction: 15
- Retention policy: 10
- Report generation: 15

---

## EP-034: Third-Party Integrations (Salesforce, Jira, GitHub)

### What Needs Integration Testing

External API calls must be mocked using `respx` (for httpx-based calls) or `responses`
(for requests-based calls). Integration tests verify:
1. OAuth credential storage and retrieval (encrypted in DB)
2. Field sync jobs update `user_attributes` correctly
3. Jira ticket creation triggered by experiment status changes
4. GitHub webhook processing and PR annotation logic
5. Rate limit handling (429 responses from external APIs)

### Mocking Strategy

```python
# Use respx for httpx-based external calls
import respx
import httpx

@respx.mock
def test_salesforce_field_sync(respx_mock, admin_client, db_session):
    # Mock Salesforce SOQL query response
    respx_mock.get("https://mycompany.salesforce.com/services/data/v58.0/query").mock(
        return_value=httpx.Response(200, json={
            "records": [
                {"Id": "003xx000004TmiN", "Email__c": "alice@example.com",
                 "Plan__c": "enterprise", "Health_Score__c": 85}
            ]
        })
    )
    # Trigger sync
    response = admin_client.post("/api/v1/integrations/salesforce/sync")
    assert response.status_code == 200

    # Verify user_attributes updated in DB
    from backend.app.models.user import UserAttribute
    attr = db_session.query(UserAttribute).filter_by(key="plan",
                                                      value="enterprise").first()
    assert attr is not None
```

### Test Files

```
backend/tests/integration/integrations/
├── __init__.py
├── conftest.py                          # Mock OAuth tokens, integration config fixtures
├── test_salesforce_sync.py              # Field sync, write-back, rate limiting
├── test_salesforce_oauth.py             # OAuth flow, token storage, token refresh
├── test_jira_ticket_creation.py         # Ticket on experiment launch, results update
├── test_jira_webhook_inbound.py         # Jira → platform status sync
├── test_github_pr_annotation.py         # PR annotation on flag key detection
├── test_github_flag_cleanup.py          # Stale flag issue creation
├── test_github_webhook_security.py      # HMAC webhook signature verification
└── test_integration_credential_encryption.py  # KMS encryption/decryption
```

### Key Test Scenarios

```python
# test_jira_ticket_creation.py
@pytest.mark.integration
class TestJiraTicketCreation:

    @respx.mock
    def test_jira_ticket_created_on_experiment_activation(
        self, respx_mock, admin_client, make_experiment, db_session
    ):
        """Activating an experiment creates a Jira issue."""
        respx_mock.post("https://mycompany.atlassian.net/rest/api/3/issue").mock(
            return_value=httpx.Response(201, json={"id": "10001", "key": "PROD-42"})
        )

        exp = make_experiment(status=ExperimentStatus.DRAFT)
        admin_client.put(f"/api/v1/experiments/{exp.id}/status",
                         json={"status": "active"})

        # Verify Jira key stored on experiment
        db_session.refresh(exp)
        assert exp.jira_issue_key == "PROD-42"

    @respx.mock
    def test_jira_not_called_when_integration_disabled(
        self, respx_mock, admin_client, make_experiment
    ):
        """No Jira call when integration is inactive."""
        jira_mock = respx_mock.post("https://mycompany.atlassian.net/rest/api/3/issue")
        exp = make_experiment(status=ExperimentStatus.DRAFT)
        admin_client.put(f"/api/v1/experiments/{exp.id}/status",
                         json={"status": "active"})
        assert not jira_mock.called


# test_github_webhook_security.py
@pytest.mark.integration
class TestGitHubWebhookSecurity:

    def test_valid_hmac_signature_accepted(self, test_client):
        """Webhook with correct HMAC-SHA256 signature is processed."""
        payload = json.dumps({"action": "opened", "pull_request": {...}}).encode()
        sig = "sha256=" + hmac.new(b"webhook-secret", payload, hashlib.sha256).hexdigest()

        response = test_client.post(
            "/api/v1/integrations/github/webhook",
            content=payload,
            headers={"X-Hub-Signature-256": sig, "X-GitHub-Event": "pull_request"},
        )
        assert response.status_code == 200

    def test_invalid_signature_rejected(self, test_client):
        """Webhook with wrong signature returns 401."""
        response = test_client.post(
            "/api/v1/integrations/github/webhook",
            json={"action": "opened"},
            headers={"X-Hub-Signature-256": "sha256=invalid", "X-GitHub-Event": "pull_request"},
        )
        assert response.status_code == 401
```

### CI Workflow: `integrations-tests.yml`

```yaml
name: Third-Party Integration Tests
on:
  push:
    paths:
      - 'backend/app/services/integrations/**'
      - 'backend/tests/integration/integrations/**'

jobs:
  integration-tests:
    runs-on: ubuntu-latest
    services:
      postgres: { ... }
    env:
      # Fake credentials — real calls mocked by respx
      SALESFORCE_INSTANCE_URL: "https://test.salesforce.com"
      JIRA_BASE_URL: "https://test.atlassian.net"
      GITHUB_APP_SECRET: "test-webhook-secret"
    steps:
      - name: Run third-party integration tests
        run: |
          python -m pytest backend/tests/integration/integrations/ \
            -v --tb=short --junit-xml=test-results/integrations.xml
```

### Expected Test Count: ~90 tests
- Salesforce (sync, write-back, OAuth, rate limit): 25
- Jira (ticket creation, results update, inbound webhook): 25
- GitHub (PR annotation, flag cleanup, webhook security): 25
- Credential encryption: 15

---

## EP-035: Full Bayesian Integration Tests

### What Needs Integration Testing

Bayesian computation requires a real database because:
1. Posterior parameters must be persisted and retrieved correctly
2. The stopping rule must integrate with the experiment scheduler
3. API responses must include Bayesian fields alongside frequentist results

### Test Files

```
backend/tests/integration/bayesian/
├── __init__.py
├── test_bayesian_results_api.py         # GET /results/{id} includes Bayesian fields
├── test_bayesian_posterior_storage.py   # Posterior params stored + retrieved from DB
├── test_bayesian_stopping_rule.py       # Scheduler honours expected_loss threshold
├── test_bayesian_config_validation.py   # Prior config validated on experiment create
└── test_bayesian_reference_values.py    # Accuracy tests against R/scipy reference
```

### Key Test Scenarios

```python
# test_bayesian_reference_values.py
@pytest.mark.integration
class TestBayesianAccuracy:
    """
    Validate posterior computation against known analytical solutions.
    These are the single source of truth for correctness — if these fail,
    the Bayesian feature is broken regardless of other tests passing.
    """

    def test_beta_binomial_conjugate_update(self, db_session, make_experiment):
        """
        Prior: Beta(1, 1) (uniform)
        Observations: 30 conversions out of 1000 (3% rate)
        Expected posterior: Beta(31, 971)
        Expected mean: 31/1002 = 0.03094 (within 0.1% of true rate)
        """
        from backend.app.services.bayesian_service import BayesianService

        service = BayesianService()
        posterior = service.compute_posterior(
            prior={"family": "beta", "alpha": 1, "beta": 1},
            observations={"conversions": 30, "total": 1000}
        )

        assert abs(posterior.alpha - 31) < 0.01
        assert abs(posterior.beta - 971) < 0.01
        assert abs(posterior.mean - (31 / 1002)) < 0.001

    def test_probability_to_be_best_known_case(self):
        """
        If variant A has Beta(200, 800) and variant B has Beta(150, 850),
        P(A is best) should be > 95% (A clearly better at 20% vs 15%).
        """
        from backend.app.services.bayesian_service import BayesianService

        service = BayesianService()
        ptbb = service.compute_probability_to_be_best([
            {"alpha": 200, "beta": 800},  # 20% conversion
            {"alpha": 150, "beta": 850},  # 15% conversion
        ], n_samples=500_000)

        assert ptbb[0] > 0.95, f"P(A best) should be > 95%, got {ptbb[0]:.3f}"
        assert abs(ptbb[0] + ptbb[1] - 1.0) < 0.001  # must sum to 1


# test_bayesian_stopping_rule.py
@pytest.mark.integration
class TestBayesianStoppingRule:

    def test_experiment_stops_when_expected_loss_below_threshold(
        self, admin_client, make_experiment, db_session
    ):
        """
        When expected loss drops below the configured threshold,
        the scheduler marks the experiment COMPLETED with bayesian_decision=STOP_WINNER.
        """
        exp = make_experiment(
            bayesian_enabled=True,
            bayesian_config={"loss_threshold": 0.001},
            status=ExperimentStatus.ACTIVE,
        )

        # Inject posterior that clearly favours treatment
        from backend.app.models.experiment import ExperimentResult
        db_session.add(ExperimentResult(
            experiment_id=exp.id,
            bayesian_posterior={"control": {"alpha": 100, "beta": 900},
                                "treatment": {"alpha": 300, "beta": 700}},
            expected_loss=0.0005,  # below threshold
        ))
        db_session.commit()

        # Run scheduler
        from backend.app.core.scheduler import ExperimentScheduler
        import asyncio
        asyncio.run(ExperimentScheduler().process_bayesian_stopping())

        db_session.refresh(exp)
        assert exp.status == ExperimentStatus.COMPLETED
        assert exp.bayesian_decision == "STOP_WINNER"
```

### CI Additions

Add Bayesian tests to the existing `integration-tests.yml` as a new step:

```yaml
- name: Run Bayesian integration tests
  run: |
    python -m pytest backend/tests/integration/bayesian/ \
      -v --tb=short --junit-xml=test-results/bayesian.xml
```

### Expected Test Count: ~45 tests
- Results API (Bayesian fields present): 12
- Posterior storage + retrieval: 8
- Stopping rule (scheduler integration): 10
- Config validation on create: 5
- Reference value accuracy: 10

---

## EP-036: Split URL Testing Integration Tests

### What Needs Integration Testing

Split URL Testing has two distinct layers that need integration tests:
1. **Platform API** — creating/managing split URL experiments, URL validation
2. **Lambda@Edge** — routing logic, cookie handling, canonical injection

Lambda@Edge tests use LocalStack to simulate CloudFront + Lambda behaviour.

### Test Files

```
backend/tests/integration/split_url/
├── __init__.py
├── conftest.py                           # LocalStack fixtures, CloudFront mock event builder
├── test_split_url_experiment_api.py      # Create, activate, pause, stop via API
├── test_split_url_url_validation.py      # Invalid URLs rejected before activation
├── test_split_url_lambda_routing.py      # Lambda@Edge routes correct variant
├── test_split_url_cookie_persistence.py  # Same user → same variant across requests
├── test_split_url_canonical_injection.py # canonical + noindex tags injected
└── test_split_url_results_tracking.py    # Impressions counted per variant in DB
```

### Key Test Scenarios

```python
# test_split_url_lambda_routing.py
@pytest.mark.integration
@pytest.mark.requires_aws
class TestSplitURLLambdaRouting:
    """Tests the Lambda@Edge handler with simulated CloudFront viewer-request events."""

    def _make_cf_event(self, uri: str, cookie: str = "") -> dict:
        """Build a minimal CloudFront viewer-request event."""
        return {
            "Records": [{
                "cf": {
                    "request": {
                        "uri": uri,
                        "headers": {
                            "cookie": [{"value": cookie}] if cookie else [],
                            "host": [{"value": "www.example.com"}],
                        },
                        "clientIp": "1.2.3.4",
                    }
                }
            }]
        }

    def test_routes_to_variant_url(self, active_split_url_experiment):
        """Lambda@Edge rewrites URI to variant URL for treatment group."""
        from backend.lambda.split_url_router.handler import handler

        user_id = "user-treatment-001"  # known to hash to treatment
        event = self._make_cf_event("/pricing",
                                     cookie=f"exp_user_id={user_id}")
        result = handler(event, {})

        # URI rewritten to treatment URL
        assert result["uri"] in ["/pricing", "/pricing-v2"]  # deterministic by hash

    def test_non_experiment_url_passes_through(self):
        """URIs not covered by any active experiment pass through unchanged."""
        from backend.lambda.split_url_router.handler import handler

        event = self._make_cf_event("/about-us")
        result = handler(event, {})
        assert result["uri"] == "/about-us"

    def test_same_user_always_gets_same_variant(self, active_split_url_experiment):
        """Assignment is deterministic — 100 requests, same cookie, same URI."""
        from backend.lambda.split_url_router.handler import handler

        event = self._make_cf_event("/pricing", cookie="exp_user_id=user-stable-123")
        variants_seen = {handler(event, {})["uri"] for _ in range(100)}
        assert len(variants_seen) == 1, "User should always get the same variant"


# test_split_url_canonical_injection.py
@pytest.mark.integration
class TestCanonicalInjection:

    def test_treatment_response_has_canonical_to_control(self, active_split_url_experiment):
        """Treatment variant has <link rel="canonical"> pointing to control URL."""
        from backend.lambda.split_url_router.handler import inject_canonical

        html = "<html><head><title>Pricing V2</title></head><body></body></html>"
        result = inject_canonical(html, control_url="/pricing")

        assert '<link rel="canonical" href="/pricing">' in result

    def test_canonical_not_injected_for_non_html(self, active_split_url_experiment):
        """Canonical injection skipped for JSON/CSS responses."""
        from backend.lambda.split_url_router.handler import inject_canonical

        json_body = '{"price": 99}'
        result = inject_canonical(json_body, control_url="/pricing",
                                   content_type="application/json")
        assert result == json_body  # unchanged


# test_split_url_url_validation.py
@pytest.mark.integration
class TestSplitURLValidation:

    @respx.mock
    def test_experiment_rejected_if_variant_url_returns_404(self, respx_mock, admin_client):
        """Cannot activate a split URL experiment if variant URL is unreachable."""
        respx_mock.get("https://www.example.com/pricing-v2").mock(
            return_value=httpx.Response(404)
        )

        response = admin_client.post("/api/v1/experiments", json={
            "name": "Pricing Page Test",
            "experiment_type": "split_url",
            "split_url_config": {
                "control_url": "/pricing",
                "variants": [{"key": "v2", "url": "/pricing-v2", "weight": 0.5}],
            }
        })
        # Should fail validation
        assert response.status_code == 422
        assert "pricing-v2" in response.json()["detail"]
```

### CI Workflow: `split-url-tests.yml`

```yaml
name: Split URL Testing
on:
  push:
    paths:
      - 'backend/lambda/split_url_router/**'
      - 'backend/tests/integration/split_url/**'
      - 'infrastructure/split_url*'

jobs:
  split-url-tests:
    runs-on: ubuntu-latest
    services:
      postgres: { ... }
      localstack:
        image: localstack/localstack:latest
        env:
          SERVICES: "lambda,cloudfront"
        ports:
          - 4566:4566

    steps:
      - name: Run Split URL integration tests
        env:
          AWS_ENDPOINT_URL: "http://localhost:4566"
          AWS_DEFAULT_REGION: "us-east-1"
          AWS_ACCESS_KEY_ID: "test"
          AWS_SECRET_ACCESS_KEY: "test"
        run: |
          python -m pytest backend/tests/integration/split_url/ \
            -v --tb=short --junit-xml=test-results/split-url.xml
```

### Expected Test Count: ~55 tests
- Experiment API (create, validate, activate, pause): 15
- Lambda@Edge routing (variant assignment, passthrough): 15
- Cookie persistence (stability, TTL): 8
- Canonical + noindex injection: 8
- Results tracking (impression counts): 9

---

## Updated `integration-tests.yml` (Master Workflow)

The main workflow should orchestrate all new sub-workflows and run core tests:

```yaml
# .github/workflows/integration-tests.yml  (updated)
name: Integration Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  # ── Existing core tests ──────────────────────────────────────────────────
  core-integration:
    name: Core Integration Tests
    runs-on: ubuntu-latest
    services:
      postgres: { ... }
      redis: { ... }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.9' }
      - run: pip install -r backend/requirements.txt
      - name: Run migrations
        run: python -m alembic -c app/db/alembic.ini upgrade head
      - name: DB + API integration tests
        run: |
          python -m pytest backend/tests/integration/database/ -v --tb=short
          python -m pytest backend/tests/integration/api/ -v --tb=short
          python -m pytest backend/tests/integration/services/ -v --tb=short
          python -m pytest backend/tests/integration/workflows/ -v --tb=short
      - name: Contract tests
        run: python -m pytest backend/tests/contract/ -v --tb=short
      - name: Bayesian integration tests           # EP-035 new
        run: python -m pytest backend/tests/integration/bayesian/ -v --tb=short

  # ── New: Compliance tests ────────────────────────────────────────────────
  compliance:
    name: Compliance Audit Tests (EP-033)
    runs-on: ubuntu-latest
    services:
      postgres: { ... }
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r backend/requirements.txt
      - run: |
          python -m pytest backend/tests/integration/compliance/ \
            -v --tb=short --junit-xml=test-results/compliance.xml

  # ── New: Third-party integrations ────────────────────────────────────────
  third-party-integrations:
    name: Salesforce / Jira / GitHub Integration Tests (EP-034)
    runs-on: ubuntu-latest
    services:
      postgres: { ... }
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r backend/requirements.txt
      - run: |
          python -m pytest backend/tests/integration/integrations/ \
            -v --tb=short --junit-xml=test-results/integrations.xml

  # ── New: Split URL / Lambda@Edge ─────────────────────────────────────────
  split-url:
    name: Split URL Testing (EP-036)
    runs-on: ubuntu-latest
    services:
      postgres: { ... }
      localstack:
        image: localstack/localstack:latest
        env: { SERVICES: "lambda" }
        ports: ["4566:4566"]
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r backend/requirements.txt
      - run: |
          python -m pytest backend/tests/integration/split_url/ \
            -v --tb=short --junit-xml=test-results/split-url.xml

  # ── New: SDK contract tests ──────────────────────────────────────────────
  sdk-contracts:
    name: SDK Contract Tests (EP-031 / EP-032)
    runs-on: ubuntu-latest
    services:
      postgres: { ... }
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r backend/requirements.txt
      - run: |
          python -m pytest backend/tests/integration/sdk/ \
            backend/tests/contract/ \
            -v --tb=short --junit-xml=test-results/sdk-contracts.xml

  # ── Collect all results ──────────────────────────────────────────────────
  collect-results:
    name: Collect Test Results
    needs:
      - core-integration
      - compliance
      - third-party-integrations
      - split-url
      - sdk-contracts
    runs-on: ubuntu-latest
    if: always()
    steps:
      - uses: actions/upload-artifact@v4
        with:
          name: all-integration-test-results
          path: test-results/
          retention-days: 30
```

---

## New Test Markers

Add to `backend/pytest.ini`:

```ini
[pytest]
markers =
    unit: Fast unit tests, no external deps
    integration: Requires database
    e2e: Requires full stack running
    slow: Tests taking >5 seconds
    requires_db: Explicit DB requirement
    requires_aws: Needs LocalStack or AWS
    contract: API contract validation
    compliance: SOC 2 / ISO 27001 audit tests     # NEW
    sdk: SDK-specific tests                        # NEW
    split_url: Split URL Lambda@Edge tests         # NEW
    third_party: External API integration tests    # NEW
    bayesian: Bayesian statistics tests            # NEW
```

---

## New Fixtures to Add to `integration/conftest.py`

```python
# Compliance
@pytest.fixture
def audit_capture(db_session):
    """Capture AuditEvent records created during a test block."""
    ...  # see EP-033 section above

# Integrations
@pytest.fixture
def mock_salesforce_oauth(respx_mock):
    """Pre-configured respx mock for Salesforce OAuth + SOQL."""
    ...

@pytest.fixture
def mock_jira_api(respx_mock):
    """Pre-configured respx mock for Jira REST API v3."""
    ...

@pytest.fixture
def mock_github_api(respx_mock):
    """Pre-configured respx mock for GitHub REST API v3."""
    ...

# Split URL
@pytest.fixture
def cloudfront_event_factory():
    """Factory for CloudFront viewer-request Lambda events."""
    def _factory(uri, cookie="", ip="1.2.3.4"):
        return {"Records": [{"cf": {"request": {
            "uri": uri,
            "headers": {"cookie": [{"value": cookie}]} if cookie else {},
            "clientIp": ip,
        }}}]}
    return _factory

@pytest.fixture
def active_split_url_experiment(db_session, make_experiment, make_variant):
    """Creates an active split URL experiment with /pricing variants."""
    exp = make_experiment(
        experiment_type="split_url",
        status=ExperimentStatus.ACTIVE,
        split_url_config={
            "control_url": "/pricing",
            "variants": [{"key": "v2", "url": "/pricing-v2", "weight": 0.5}],
            "inject_canonical": True,
            "noindex_variants": True,
        }
    )
    return exp

# Bayesian
@pytest.fixture
def bayesian_experiment(make_experiment):
    """Creates an active experiment with Bayesian enabled."""
    return make_experiment(
        bayesian_enabled=True,
        bayesian_config={"loss_threshold": 0.001, "rope": [-0.001, 0.001]},
        status=ExperimentStatus.ACTIVE,
    )
```

---

## Summary: New Test Files to Create

| Feature | New Test Files | Approx Tests |
|---------|---------------|-------------|
| EP-031 Java/JVM SDK | 4 backend + 3 contract schema files | ~70 |
| EP-032 React SDK | 6 frontend integration + 2 E2E | ~50 |
| EP-033 SOC 2 / ISO 27001 | 7 backend integration files | ~120 |
| EP-034 Salesforce/Jira/GitHub | 8 backend integration files | ~90 |
| EP-035 Full Bayesian | 5 backend integration files | ~45 |
| EP-036 Split URL Testing | 6 backend integration files | ~55 |
| **Total** | **38 new test files** | **~430 new integration tests** |

---

## Running New Integration Tests Locally

```bash
source venv/bin/activate
export APP_ENV=test TESTING=true

# Compliance / audit (EP-033)
python -m pytest backend/tests/integration/compliance/ -v

# Third-party integrations (EP-034) — no real API calls, all mocked with respx
python -m pytest backend/tests/integration/integrations/ -v

# Bayesian (EP-035)
python -m pytest backend/tests/integration/bayesian/ -v

# Split URL — requires LocalStack
docker-compose up -d localstack
python -m pytest backend/tests/integration/split_url/ -v -m "requires_aws"

# SDK contracts
python -m pytest backend/tests/integration/sdk/ backend/tests/contract/ -v

# All new integration tests at once (minus LocalStack tests)
python -m pytest backend/tests/integration/ \
  -m "not requires_aws" -v --tb=short -p no:cov
```
