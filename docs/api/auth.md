# Authentication

The platform uses two authentication methods depending on the use case:

| Method | Used For |
|--------|---------|
| **API Key** (`X-API-Key` header) | SDK clients, server-to-server calls, event tracking |
| **JWT Bearer Token** (`Authorization: Bearer` header) | User sessions (dashboard and direct API calls) |

---

## API Key Authentication

API keys are long-lived credentials intended for programmatic access. Use them when:

- Integrating an SDK into your application
- Making server-to-server API calls from a backend service
- Tracking events from a client application

### Using an API Key

Pass the key in the `X-API-Key` header on every request:

```bash
curl -X POST http://localhost:8000/api/v1/tracking/track \
  -H "X-API-Key: your-api-key-here" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user-123", "event_type": "purchase_completed", "value": 49.99}'
```

### Creating an API Key

You must be authenticated with a JWT token (DEVELOPER or ADMIN role) to create API keys.

```bash
curl -X POST http://localhost:8000/api/v1/api-keys \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Production App Key",
    "description": "Used by the checkout service",
    "scopes": ["read", "write"]
  }'
```

**Response: 201 Created**

```json
{
  "id": "key-uuid",
  "name": "Production App Key",
  "key": "sk-live-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "scopes": ["read", "write"],
  "created_at": "2026-03-02T10:00:00Z"
}
```

The `key` value is shown only once. Store it securely. If you lose it, you must create a new key and revoke the old one.

---

## JWT Bearer Token Authentication

JWT tokens are issued by AWS Cognito and are used for user-facing API calls. Each token is valid for 30 minutes. A refresh token is also issued and can be used to obtain a new access token without re-authentication.

### Login Flow

1. The user submits credentials via the dashboard login page or directly to the token endpoint.
2. The platform validates credentials against AWS Cognito.
3. Cognito issues a JWT access token and a refresh token.
4. The access token is included in subsequent API requests.

### Using a Bearer Token

```bash
curl -X GET http://localhost:8000/api/v1/experiments \
  -H "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
```

### Obtaining a Token

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "your-email@example.com", "password": "your-password"}' \
  | jq -r '.access_token')

echo "Token: $TOKEN"
```

### Token Expiry and Refresh

Access tokens expire after 30 minutes (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`). After expiry, use the refresh token to obtain a new access token:

```bash
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "your-refresh-token"}'
```

If the refresh token is also expired, the user must log in again.

---

## Roles and Permissions

Every user is assigned one of four built-in roles. The role determines which API endpoints and operations are available.

| Role | Description | Typical Users |
|------|-------------|---------------|
| **ADMIN** | Full access to all resources and administrative functions | Platform owners, engineering leads |
| **DEVELOPER** | Create and manage experiments, feature flags, and integrations | Engineers, product developers |
| **ANALYST** | Read-only access to all experiments, results, and reports | Data analysts, product managers |
| **VIEWER** | Read-only access to approved experiments | Stakeholders, executives |

### What Each Role Can Do

| Action | VIEWER | ANALYST | DEVELOPER | ADMIN |
|--------|--------|---------|-----------|-------|
| View experiments and results | Read-only | Read-only | Read-only | Full |
| Create/update experiments | — | — | Own | All |
| Create/update feature flags | — | — | Own | All |
| View audit logs | — | Yes | Yes | Yes |
| Export compliance reports | — | — | — | Yes |
| Manage users and roles | — | — | — | Yes |
| View RBAC permissions | Own | Own | Own | All |

Admins can also create custom roles with fine-grained permissions and grant temporary direct permissions to individual users. See [RBAC API Reference](rbac.md).

---

## Example Authenticated Requests

### Check Who You Are Logged In As

```bash
curl -X GET http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "id": "user-uuid",
  "username": "jane.smith",
  "email": "jane.smith@example.com",
  "role": "developer",
  "is_active": true
}
```

### Create an Experiment (DEVELOPER+)

```bash
curl -X POST http://localhost:8000/api/v1/experiments \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Checkout Button Color",
    "hypothesis": "A green button increases checkout completion",
    "variants": [
      {"key": "control", "name": "Blue Button", "weight": 0.5},
      {"key": "treatment", "name": "Green Button", "weight": 0.5}
    ]
  }'
```

### List All Experiments (ANALYST+)

```bash
curl -X GET http://localhost:8000/api/v1/experiments \
  -H "Authorization: Bearer $TOKEN"
```

### Evaluate a Feature Flag (API Key)

```bash
curl -X POST http://localhost:8000/api/v1/feature-flags/dark-mode/evaluate \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user-123", "attributes": {"plan": "pro"}}'
```

---

## Error Responses

### 401 Unauthorized

Returned when no credentials are provided or the credentials are invalid.

```json
{"detail": "Not authenticated"}
```

```json
{"detail": "Invalid API key"}
```

### 403 Forbidden

Returned when the authenticated user lacks the required role for the requested operation.

```json
{"detail": "Not enough permissions. Required role: ADMIN"}
```

---

## Security Notes

- Never commit API keys or access tokens to source control
- Rotate API keys regularly — at least every 90 days for production keys
- Use separate API keys for each service or environment
- JWT access tokens expire after 30 minutes; do not store them long-term
- In production, all API traffic must be over HTTPS
- API keys and token validation are logged in the audit trail for compliance purposes
