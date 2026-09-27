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
    "description": "Used by the checkout microservice to evaluate feature flags"
  }'
```

**Response: 201 Created**

```json
{
  "id": "key-uuid-here",
  "name": "Production Checkout Service",
  "key": "eptk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "prefix": "eptk_xxxx",
  "created_at": "2026-03-02T10:00:00Z",
  "expires_at": null
}
```

**The `key` value is shown only once.** Store it immediately in a secure location (a secrets manager, not a code repository). If you lose it, you must create a new key.

---

## Scopes

A key can carry a list of scope names (`"scopes"` in the create request). **Scopes do not limit
what a key can do today.** Any active key authenticates every API-key route (flag evaluation,
tracking, error reporting and the other `X-API-Key` routes) as the user who created it, whatever
its scopes say. Names such as `read`, `write` or `admin` on existing keys are labels only; nothing
checks them.

One scope is intended to be enforced: **`sdk:ruleset`**. The server-side local-evaluation ruleset
endpoint, once it ships, is intended to refuse any key that does not carry it. A key with
`sdk:ruleset` will be able to download every feature flag's targeting rules, including the values
in them, so keep such a key on a server and never ship it to a browser or a mobile app.

- In the dashboard (**Admin → API Keys → Create API Key**), tick **Server-side local evaluation
  (sdk:ruleset)**. Leave it unticked for any other key; the key is then created with no scopes.
- Through the API, send `"scopes": ["sdk:ruleset"]`.

Scope names are matched exactly and case-sensitively: the stored list is split on commas and each
entry is trimmed, so `"read, sdk:ruleset "` carries `sdk:ruleset`, while `SDK:RULESET`,
`xsdk:ruleset` and `sdk:ruleset-ro` do not.

---

## Using an API Key

Pass the API key in the `X-API-Key` header on every request:

```bash
# Evaluate a feature flag
curl -X POST http://localhost:8000/api/v1/feature-flags/evaluate/dark-mode \
  -H "X-API-Key: eptk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user-123", "context": {"plan": "pro"}}'

# Track a conversion event
curl -X POST http://localhost:8000/api/v1/tracking/track \
  -H "X-API-Key: eptk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
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
    "scopes": ["sdk:ruleset"],
    "created_at": "2026-03-02T10:00:00Z",
    "last_used_at": "2026-03-10T14:22:00Z",
    "is_active": true
  },
  {
    "id": "key-uuid-2",
    "name": "Old Staging Key",
    "scopes": [],
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
apiKey: "eptk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

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
checkout-service-prod    → eptk_aaaa…
recommendations-prod     → eptk_bbbb…
analytics-pipeline       → eptk_cccc…
```

### Audit key usage

The `last_used_at` field on each key tells you when it was last used. Revoke keys that have not been used for more than 30 days. This reduces your attack surface and keeps the key inventory clean.

### Grant `sdk:ruleset` only where it is needed

Give the `sdk:ruleset` scope only to a server that will evaluate flags locally. Every other key,
including any key used in a browser or a mobile app, should be created without it. Because scopes
do not otherwise limit a key, a separate key per service is what lets you revoke one integration
without touching the others.
