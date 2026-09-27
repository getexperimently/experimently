# Authentication

The platform uses two authentication methods, depending on who is calling:

| Method | Used For |
|--------|---------|
| **API Key** (`X-API-Key` header) | SDK clients, server-to-server calls, event tracking |
| **Bearer token** (`Authorization: Bearer` header) | People: the dashboard, and direct API calls made as a user |

The commands on this page run as written against the stack from the
[Quick Start](../getting-started/quick-start.md), in one terminal, top to bottom. Each one uses
the shell variables set by the ones before it.

---

## Bearer Token Authentication

A bearer token is issued when a user logs in, and authenticates later requests as that user.

Where the login is checked depends on `AUTH_PROVIDER`:

- **`local`** (the default, and what the Quick Start runs): the platform checks the email
  address and password against its own users. Its tokens last 12 hours
  (`LOCAL_AUTH_TOKEN_TTL_MINUTES`, default `720`). After 10 failed attempts within 15
  minutes, the address answers `423` until the 15 minutes are up.
- **`cognito`**: the credentials are passed to an AWS Cognito user pool, which issues an
  access token and a refresh token.

### Obtaining a Token

Log in with the account's email address and password. This saves the token in `$TOKEN`
and prints what else the response says:

```{.bash exec}
LOGIN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"admin@demo.com","password":"Demo1234!"}')
TOKEN=$(jq -r .access_token <<<"$LOGIN")

jq '{token_type, expires_in}' <<<"$LOGIN"
```
<!-- expect: "token_type": "bearer" -->
<!-- expect: "expires_in": 43200 -->

It prints `"token_type": "bearer"` and `"expires_in": 43200`, the token's lifetime in
seconds (12 hours). The response also carries the user's profile as `user`.

A wrong email address or password answers `401` with `{"detail":"Invalid email or password"}`.
`POST /api/v1/auth/login` takes JSON with `email` and `password`.
`POST /api/v1/auth/token` takes the same two as a form, with the email address in the
`username` field. That's the OAuth2 form the API's interactive documentation at
`localhost:8000/docs` uses for its **Authorize** button.

### Check Who You Are Logged In As

```{.bash exec}
curl -s localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer $TOKEN" | jq '{email, role}'
```
<!-- expect: "email": "admin@demo.com" -->
<!-- expect: "role": "ADMIN" -->

```json
{
  "email": "admin@demo.com",
  "role": "ADMIN"
}
```

The profile also carries `id`, `username`, `full_name`, `is_superuser`, `is_active` and
`auth_provider`.

### Using a Bearer Token

Pass the token in the `Authorization` header. This lists the experiments; the demo data
has three:

```{.bash exec}
curl -s localhost:8000/api/v1/experiments/ \
  -H "Authorization: Bearer $TOKEN" | jq -r '.items[].key'
```
<!-- expect: checkout_button_color -->

It prints each experiment's key, including `checkout_button_color`.

The collection URL ends with a slash, `/api/v1/experiments/`. Without the slash the API
answers `307 Temporary Redirect`, which `curl` doesn't follow, so nothing is printed.

### Token Expiry, Refresh and Logout

With the `local` provider there is no refresh token: when a token expires, requests answer
`401` and the user logs in again. `POST /api/v1/auth/logout` answers `204` so a client can
discard its token. The token itself stays valid until it expires, because nothing is
revoked on the server.

**Needs an identity provider.** With `AUTH_PROVIDER=cognito`, the login also returns a
refresh token, and this exchanges it for a new access token. `$REFRESH_TOKEN` is the
`refresh_token` from the Cognito login's response:

```{.bash skip reason="idp: needs a Cognito user pool and a refresh token it issued"}
curl -s -X POST localhost:8000/api/v1/auth/refresh \
  -H 'content-type: application/json' \
  -d "{\"refresh_token\": \"$REFRESH_TOKEN\"}"
```

If the refresh token has expired too, the user logs in again.

---

## API Key Authentication

API keys are long-lived credentials for programs. Use them when:

- integrating an SDK into your application;
- making server-to-server API calls from a backend service;
- tracking events from a client application.

### Creating an API Key

Creating a key takes a bearer token. This saves the new key in `$KEY`:

```{.bash exec}
KEY=$(curl -s -X POST localhost:8000/api/v1/api-keys \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"name": "Production App Key", "description": "Used by the checkout service"}' \
  | jq -r .key)

echo "${KEY:0:5}"
```
<!-- expect: eptk_ -->

It prints `eptk_`, the start of every key. The key is shown only in this response, so store
it securely. If you lose it, create a new key and delete the old one. See
[API Key Management](../security/api-keys.md) for listing, deleting and rotating keys.

### Using an API Key

Pass the key in the `X-API-Key` header on every request. This tracks a purchase in the demo
data's `checkout_button_color` experiment:

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/tracking/track \
  -H "X-API-Key: $KEY" \
  -H 'content-type: application/json' \
  -d '{
    "user_id": "user-123",
    "experiment_key": "checkout_button_color",
    "event_type": "purchase_completed",
    "value": 49.99
  }' | jq .event_type
```
<!-- expect: "purchase_completed" -->

It prints `"purchase_completed"`, the stored event's type.

And this evaluates the demo data's `beta_features` flag for the same user:

```{.bash exec}
curl -s -G localhost:8000/api/v1/feature-flags/evaluate/beta_features \
  -H "X-API-Key: $KEY" \
  --data-urlencode "user_id=user-123" \
  --data-urlencode 'context={"plan":"pro"}' | jq .enabled
```
<!-- expect: true -->

It prints `true`.

An API key is accepted only by the endpoints an SDK calls: tracking, flag evaluation,
OpenFeature and edge bootstrap. Everything else takes a bearer token.

---

## Roles and Permissions

Every user has one of four built-in roles. The role decides which operations are available.

| Role | Description | Typical Users |
|------|-------------|---------------|
| **ADMIN** | Full access to all resources and administrative functions | Platform owners, engineering leads |
| **DEVELOPER** | Create and manage experiments and feature flags | Engineers, product developers |
| **ANALYST** | Read experiments, flags and results; create reports | Data analysts, product managers |
| **VIEWER** | Read-only access | Stakeholders, executives |

### What Each Role Can Do

| Action | VIEWER | ANALYST | DEVELOPER | ADMIN |
|--------|--------|---------|-----------|-------|
| View experiments, flags and results | Yes | Yes | Yes | Yes |
| Create and change experiments | — | — | Yes | Yes |
| Create and change feature flags | — | — | Yes | Yes |
| Create their own API keys | Yes | Yes | Yes | Yes |
| Manage users | — | — | — | Yes |

Access to a feature flag is by role, not by who created it: a DEVELOPER can change any flag,
and a VIEWER can change none, not even one they created.

To see a refusal, create a VIEWER account as the administrator:

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/users/ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"email": "viewer@example.com", "username": "viewer", "password": "Viewer1234!", "role": "VIEWER"}' \
  | jq '{email, role}'
```
<!-- expect: "role": "VIEWER" -->

It prints the new account's `email` and `"role": "VIEWER"`. A password needs at least eight
characters, with an upper-case letter, a lower-case letter and a digit.

Log in as the viewer, and try to create a flag:

```{.bash exec}
VIEWER_TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"viewer@example.com","password":"Viewer1234!"}' | jq -r .access_token)

curl -s -X POST localhost:8000/api/v1/feature-flags/ \
  -H "Authorization: Bearer $VIEWER_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"key": "viewer-flag", "name": "Viewer Flag"}'
```
<!-- expect: {"detail":"You don't have permission to create feature flags"} -->

The API answers `403 Forbidden` with `{"detail":"You don't have permission to create feature flags"}`.

With the modules installed, admins can also create custom roles with fine-grained
permissions, and grant temporary permissions to individual users. See the
[RBAC API Reference](rbac.md).

---

## Example Authenticated Requests

### Create an Experiment (DEVELOPER or ADMIN)

An experiment needs at least one variant and one metric:

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/experiments/ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
    "name": "Checkout Button Green",
    "hypothesis": "A green button increases checkout completion",
    "variants": [
      {"name": "Blue Button", "is_control": true, "traffic_allocation": 50},
      {"name": "Green Button", "traffic_allocation": 50}
    ],
    "metrics": [
      {"name": "Checkout completed", "event_name": "checkout_completed", "is_primary": true}
    ]
  }' | jq '{name, status}'
```
<!-- expect: "name": "Checkout Button Green" -->
<!-- expect: "status": "draft" -->

The experiment is created in `draft`, with a `key` made from its name, which SDKs use to
find it.

---

## Error Responses

### 401 Unauthorized

Returned when no credentials are sent, or they aren't valid:

```{.bash exec}
curl -s localhost:8000/api/v1/experiments/
```
<!-- expect: {"detail":"Not authenticated"} -->

It prints `{"detail":"Not authenticated"}`. An expired or malformed bearer token answers
`{"detail":"Could not validate credentials"}`, a missing API key `{"detail":"API key missing"}`
and an unknown or deleted one `{"detail":"Invalid API Key"}`.

### 403 Forbidden

Returned when the user is logged in but their role doesn't allow the operation, as in the
viewer's attempt above. The `detail` says what was refused.

---

## Security Notes

- Never commit API keys or access tokens to source control.
- Rotate API keys regularly: at least every 90 days for production keys.
- Use separate API keys for each service or environment.
- Access tokens expire; do not store them long-term.
- In production, send all API traffic over HTTPS.
