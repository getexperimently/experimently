# API Key Management

API keys provide programmatic access to the platform for SDK clients, server-side applications, and automated scripts. Unlike JWT tokens (which are tied to a user session and expire after 30 minutes), API keys are long-lived credentials intended for service-to-service communication.

---

## What API Keys Are Used For

- **SDK integration**: The JavaScript, Python, Java, and React SDKs authenticate using an API key to evaluate feature flags and track events
- **Server-to-server calls**: Backend services that need to read experiment configurations or track conversions
- **Automated scripts**: CI/CD pipelines that need to read experiment status or create test feature flags
- **Event ingestion**: High-throughput tracking endpoints accept API keys to avoid JWT overhead

API keys are not intended for end-user authentication. User-facing applications should use JWT tokens obtained via the login flow.

---

## Creating an API Key

You must be authenticated with a DEVELOPER or ADMIN role JWT token to create API keys.

```bash
curl -X POST http://localhost:8000/api/v1/api-keys \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Production Checkout Service",
    "description": "Used by the checkout microservice to evaluate feature flags",
    "scopes": ["read", "write"]
  }'
```

**Response: 201 Created**

```json
{
  "id": "key-uuid-here",
  "name": "Production Checkout Service",
  "description": "Used by the checkout microservice to evaluate feature flags",
  "key": "sk-live-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "scopes": ["read", "write"],
  "created_at": "2026-03-02T10:00:00Z",
  "last_used_at": null,
  "is_active": true
}
```

**The `key` value is shown only once.** Store it immediately in a secure location (a secrets manager, not a code repository). If you lose it, you must create a new key.

---

## Available Scopes

| Scope | Permissions |
|-------|-------------|
| `read` | Read feature flags, experiments, results, and configurations |
| `write` | Track events, update rollout percentages, submit assignments |
| `admin` | Create/delete flags and experiments, manage users (use sparingly) |

Grant the minimum scopes required for the use case:

- SDK tracking only: `write`
- Read experiment results in a reporting script: `read`
- Automated flag management: `read` + `write`
- Full administrative automation: `read` + `write` + `admin`

---

## Using an API Key

Pass the API key in the `X-API-Key` header on every request:

```bash
# Evaluate a feature flag
curl -X POST http://localhost:8000/api/v1/feature-flags/dark-mode/evaluate \
  -H "X-API-Key: sk-live-xxxx" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user-123", "attributes": {"plan": "pro"}}'

# Track a conversion event
curl -X POST http://localhost:8000/api/v1/tracking/track \
  -H "X-API-Key: sk-live-xxxx" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user-123", "event_type": "purchase", "value": 49.99}'
```

In SDK initialization:

```javascript
// JavaScript
const client = new ExperimentationClient({
  apiUrl: 'https://your-platform.example.com',
  apiKey: process.env.EXPERIMENTATION_API_KEY,
});
```

```python
# Python
client = ExperimentationClient(
    api_url="https://your-platform.example.com",
    api_key=os.environ["EXPERIMENTATION_API_KEY"],
)
```

---

## Listing Keys

You can list all API keys (without exposing the secret values):

```bash
curl -X GET http://localhost:8000/api/v1/api-keys \
  -H "Authorization: Bearer $TOKEN"
```

```json
[
  {
    "id": "key-uuid-1",
    "name": "Production Checkout Service",
    "scopes": ["read", "write"],
    "created_at": "2026-03-02T10:00:00Z",
    "last_used_at": "2026-03-10T14:22:00Z",
    "is_active": true
  },
  {
    "id": "key-uuid-2",
    "name": "Old Staging Key",
    "scopes": ["read"],
    "created_at": "2026-01-15T09:00:00Z",
    "last_used_at": "2026-02-01T11:30:00Z",
    "is_active": false
  }
]
```

The `last_used_at` timestamp helps you identify keys that are no longer in use.

---

## Revoking a Key

Revoke a key immediately when it is no longer needed, or if you suspect it has been compromised:

```bash
curl -X DELETE http://localhost:8000/api/v1/api-keys/key-uuid-here \
  -H "Authorization: Bearer $TOKEN"
```

**Response: 204 No Content**

Revoked keys are permanently deactivated. Requests using a revoked key receive `401 Unauthorized`. If the revoked key is in active use by a service, that service will start failing immediately — revoke only after updating the service to use a new key.

---

## Key Rotation Best Practices

Rotate API keys on a regular schedule to limit the window of exposure if a key is compromised.

### Recommended Rotation Schedule

| Environment | Recommended Rotation |
|-------------|---------------------|
| Production | Every 90 days |
| Staging / Development | Every 180 days |
| CI/CD pipelines | On every major deployment |

### Zero-Downtime Rotation Procedure

1. Create a new API key with the same scopes as the old key
2. Update your service's secrets (Secrets Manager, environment variables, etc.) to the new key
3. Deploy or restart the service so it uses the new key
4. Verify the service is operating normally with the new key (check `last_used_at` on the new key)
5. Revoke the old key

This procedure ensures the service is never without a valid key during rotation.

---

## Security Best Practices

### Never commit keys to source control

API keys in source code can be inadvertently exposed in logs, error messages, or git history. Always load keys from environment variables or a secrets manager.

```bash
# Bad — hardcoded in code
apiKey: "sk-live-xxxxxxxx"

# Good — loaded from environment
apiKey: process.env.EXPERIMENTATION_API_KEY
```

### Use a secrets manager

Store production API keys in a dedicated secrets manager:

- **AWS Secrets Manager**: Integrates with ECS task definitions and Lambda environment variables
- **HashiCorp Vault**: For multi-cloud or on-premise setups
- **Kubernetes Secrets**: For Kubernetes-based deployments

### Separate keys per service

Use one API key per service or application. This limits the blast radius of a compromised key — you can revoke the specific service's key without affecting other services.

```
checkout-service-prod    → sk-live-aaaa
recommendations-prod     → sk-live-bbbb
analytics-pipeline       → sk-live-cccc
```

### Audit key usage

The `last_used_at` field on each key tells you when it was last used. Revoke keys that have not been used for more than 30 days. This reduces your attack surface and keeps the key inventory clean.

### Use minimum required scopes

Do not grant `admin` scope to a key that only needs to read experiments. Follow the principle of least privilege.
