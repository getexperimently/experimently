# SSO Guide

!!! info "Part of the `sso` module"
    SSO / SAML / OIDC is one of the optional modules -- present in the **full profile**, absent from the core one. A core deployment does not serve these routes. See [Modules and profiles](../getting-started/modules.md) for what each profile includes and how to run the full one.

The `sso` module adds Single Sign-On (SSO) via SAML 2.0 and OpenID Connect (OIDC); it is part of the full profile and, like every module, Apache-2.0. SSO allows your organization to authenticate users through an existing Identity Provider (IdP) instead of platform-managed passwords.

---

## Supported Providers

| Provider | Protocol | JIT Provisioning | Group Mapping |
|----------|----------|-----------------|---------------|
| Okta | SAML 2.0 | Yes | Yes |
| Azure Active Directory | SAML 2.0 + OIDC | Yes | Yes |
| Google Workspace | OIDC | Yes | Yes |
| GitHub | OIDC | Yes | Yes |
| OneLogin | SAML 2.0 | Yes | Yes |
| Auth0 | SAML 2.0 + OIDC | Yes | Yes |

The OIDC providers `microsoft`, `azure_ad` and `onelogin` are **not supported yet**: signing in through a configuration of one of those types is refused. A SAML configuration (`provider_type: "saml"`) for the same identity provider is not affected.

---

## Overview

SSO operates alongside the existing AWS Cognito authentication. When SSO is configured for an organization domain:

1. Users whose email matches the organization's domain are redirected to the IdP for authentication.
2. The IdP authenticates the user and sends a signed assertion or token to the platform.
3. The platform validates the assertion, maps IdP groups to platform roles, and issues a session JWT.
4. If the user does not yet have a platform account, one is created automatically (JIT provisioning).

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/auth/sso/saml/{config_id}/metadata` | Returns SP metadata XML to give to the IdP |
| `POST` | `/auth/sso/saml/{config_id}/acs` | ACS (Assertion Consumer Service) endpoint — IdP posts SAML assertions here |
| `GET` | `/auth/sso/oidc/{provider}/login` | Initiates the OIDC authorization code flow |
| `GET` | `/auth/sso/oidc/{provider}/callback` | OIDC callback endpoint that exchanges the code for tokens |
| `POST` | `/auth/sso/configs` | Create a new SSO configuration (admin only) |
| `GET` | `/auth/sso/configs` | List all SSO configurations (admin only) |
| `GET` | `/auth/sso/configs/{config_id}` | Retrieve a specific SSO configuration (admin only) |
| `PUT` | `/auth/sso/configs/{config_id}` | Update an SSO configuration (admin only) |
| `DELETE` | `/auth/sso/configs/{config_id}` | Delete an SSO configuration (admin only) |

---

## Creating an SSO Configuration

### SAML Configuration

```bash
curl -X POST https://api.example.com/auth/sso/configs \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "org_name": "Acme Corp",
    "org_domain": "acme.com",
    "provider_type": "saml",
    "entity_id": "https://acme.okta.com",
    "sso_url": "https://acme.okta.com/app/sso/saml",
    "x509_certificate": "MIIC...",
    "role_mapping": {
      "admin-group": "ADMIN",
      "developers": "DEVELOPER",
      "analysts": "ANALYST",
      "viewers": "VIEWER"
    },
    "is_enforced": false
  }'
```

### OIDC Configuration

```bash
curl -X POST https://api.example.com/auth/sso/configs \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "org_name": "Acme Corp",
    "org_domain": "acme.com",
    "provider_type": "oidc",
    "oidc_provider": "google",
    "client_id": "123456789-abc.apps.googleusercontent.com",
    "client_secret": "GOCSPX-...",
    "role_mapping": {
      "admin-team": "ADMIN",
      "engineering": "DEVELOPER"
    },
    "is_enforced": false
  }'
```

### Configuration Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `org_name` | `string` | Yes | Human-readable organization name |
| `org_domain` | `string` | Yes | Email domain that triggers this SSO config (e.g., `acme.com`) |
| `provider_type` | `string` | Yes | `"saml"` or `"oidc"` |
| `entity_id` | `string` | SAML | IdP entity ID / issuer from the IdP metadata |
| `sso_url` | `string` | SAML | IdP SSO redirect URL |
| `x509_certificate` | `string` | SAML | PEM-encoded X.509 signing certificate from the IdP (without headers) |
| `oidc_provider` | `string` | OIDC | `"google"`, `"github"`, `"microsoft"`, or `"auth0"` |
| `client_id` | `string` | OIDC | OAuth2 client ID from the IdP |
| `client_secret` | `string` | OIDC | OAuth2 client secret from the IdP |
| `role_mapping` | `object` | No | Maps IdP group names to platform roles |
| `is_enforced` | `boolean` | No | Block password login for this org's domain (default: `false`) |

---

## Provider-Specific Setup

### Okta SAML 2.0

1. In Okta, go to **Applications → Create App Integration → SAML 2.0**.
2. Retrieve the SP metadata XML from:
   ```
   GET /auth/sso/saml/{config_id}/metadata
   ```
3. In Okta, set the following:
   - **Single sign-on URL (ACS URL)**: `https://your-platform.com/api/v1/auth/sso/saml/{config_id}/acs`
   - **Audience URI (SP Entity ID)**: The `SAML_SP_ENTITY_ID` environment variable value
   - **Name ID format**: `EmailAddress`
   - **Application username**: `Email`
4. Under **Attribute Statements**, add:
   - `email` → `user.email`
   - `first_name` → `user.firstName`
   - `last_name` → `user.lastName`
5. Under **Group Attribute Statements**, add:
   - Name: `groups`, Filter: `Matches regex .*`
6. Download the IdP metadata XML or copy the certificate and SSO URL.
7. Create the SSO config via the API with `entity_id`, `sso_url`, and `x509_certificate` from the Okta metadata.

### Azure Active Directory (SAML)

1. In Azure, go to **Enterprise Applications → New Application → Create your own application → Integrate with Azure AD (non-gallery)**.
2. Under **Single sign-on → SAML**, configure:
   - **Identifier (Entity ID)**: value of `SAML_SP_ENTITY_ID`
   - **Reply URL (ACS URL)**: `https://your-platform.com/api/v1/auth/sso/saml/{config_id}/acs`
3. Under **Attributes & Claims**, ensure the `emailaddress` claim maps to `user.mail`.
4. Add a group claim: **Groups assigned to the application**.
5. Download the **Certificate (Base64)** and copy the **Login URL** and **Azure AD Identifier**.
6. Create the SSO config using the downloaded certificate and the Login URL as `sso_url`.

### Azure Active Directory (OIDC)

1. In Azure, go to **App Registrations → New Registration**.
2. Set the redirect URI to: `https://your-platform.com/api/v1/auth/sso/oidc/microsoft/callback`.
3. Under **Certificates & Secrets**, create a new client secret.
4. Under **API Permissions**, add `openid`, `profile`, `email`, and `GroupMember.Read.All`.
5. Create the SSO config:

```bash
curl -X POST https://api.example.com/auth/sso/configs \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "org_domain": "acme.com",
    "provider_type": "oidc",
    "oidc_provider": "microsoft",
    "client_id": "<Application (client) ID>",
    "client_secret": "<client secret value>",
    "role_mapping": { "ExperimentationAdmins": "ADMIN" }
  }'
```

### Google Workspace (OIDC)

1. In Google Cloud Console, go to **APIs & Services → Credentials → Create OAuth 2.0 Client ID**.
2. Set the application type to **Web application**.
3. Add the authorized redirect URI: `https://your-platform.com/api/v1/auth/sso/oidc/google/callback`.
4. Copy the **Client ID** and **Client Secret**.
5. Create the SSO config:

```bash
curl -X POST https://api.example.com/auth/sso/configs \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "org_domain": "acme.com",
    "provider_type": "oidc",
    "oidc_provider": "google",
    "client_id": "123456789-abc.apps.googleusercontent.com",
    "client_secret": "GOCSPX-...",
    "role_mapping": {}
  }'
```

Google OIDC does not natively provide group membership. If role mapping by group is required, use Google Workspace Directory API and configure `role_mapping` with Google Group email addresses (e.g., `"admins@acme.com": "ADMIN"`).

### GitHub (OIDC)

1. In GitHub, go to **Settings → Developer Settings → OAuth Apps → New OAuth App** (for a personal app) or **Organization Settings → OAuth Apps** (for an org app).
2. Set the **Authorization callback URL** to: `https://your-platform.com/api/v1/auth/sso/oidc/github/callback`.
3. Create the SSO config:

```bash
curl -X POST https://api.example.com/auth/sso/configs \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "org_domain": "acme.com",
    "provider_type": "oidc",
    "oidc_provider": "github",
    "client_id": "Ov23li...",
    "client_secret": "abc123...",
    "role_mapping": {
      "acme-org/admin-team": "ADMIN",
      "acme-org/engineers": "DEVELOPER"
    }
  }'
```

GitHub team slugs in `role_mapping` should be in the format `{org-name}/{team-slug}`.

---

## JIT User Provisioning

Users who authenticate via SSO for the first time are provisioned with a platform account automatically. There is no setting to turn this off; to stop sign-ins through a configuration, set its `is_active` to `false`.

A sign-in is accepted only for an email address in the configuration's `org_domain`, exactly: `bob@acme.com` for `acme.com`, but not `bob@eu.acme.com` or `bob@acme.io`. Use one configuration per domain. The comparison ignores case and surrounding spaces. An existing account is matched by email address, ignoring case; if more than one account matches, the sign-in is refused.

The email address must be one the identity provider has verified:

| Provider | Where the email comes from | Required |
|---|---|---|
| Okta | the ID token's `email` | `email_verified` is `true` |
| Google | the ID token's `email` | `email_verified` is `true`, and `hd` (the Google Workspace domain) equals the email's domain. A personal Google account has no `hd`, so it cannot sign in. |
| GitHub | `GET /user/emails` | a verified address in `org_domain`: the primary one if it is in the domain, otherwise the only one in the domain. The public profile email is not used. |

An account already linked to the same identity under a different email address is not reused: that sign-in is refused, and an administrator resolves it.

The following attributes are populated from the IdP assertion or token:

| Platform Field | SAML Source | OIDC Source |
|----------------|-------------|-------------|
| `email` | `NameID` or `email` attribute | `email` claim |
| `first_name` | `first_name` attribute | `given_name` claim |
| `last_name` | `last_name` attribute | `family_name` claim |
| `role` | Derived from `groups` via `role_mapping` | Derived from groups via `role_mapping` |

If no role mapping matches, a new user is provisioned with the `VIEWER` role.

### Upgrading

After upgrading from an earlier release, review the accounts created by SSO sign-in (accounts with no password set) and their roles, and remove any you do not recognise.

---

## Group-to-Role Mapping

The `role_mapping` field maps IdP group names or email addresses to platform roles.

```json
{
  "role_mapping": {
    "admin-group":        "ADMIN",
    "developers":         "DEVELOPER",
    "data-analysts":      "ANALYST",
    "product-managers":   "VIEWER"
  }
}
```

Rules:
- Matching is case-sensitive.
- A user's role is determined by the first matching group in the mapping. Order groups from highest to lowest privilege.
- A new user in no mapped group receives the `VIEWER` role.
- An existing user's role changes only when one of their groups is in the mapping. A sign-in with no mapped group leaves the role as it is, so removing someone from every mapped group does not demote them: to demote someone through SSO, map one of their groups to `VIEWER`. Superuser status is never changed by a sign-in.
- If a user is in multiple mapped groups, the highest-privilege role wins (ADMIN > DEVELOPER > ANALYST > VIEWER).

---

## Enforced SSO

When `is_enforced: true`, all users whose email matches `org_domain` must authenticate via SSO. Password-based login is blocked for those accounts.

```bash
curl -X PUT https://api.example.com/auth/sso/configs/{config_id} \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"is_enforced": true}'
```

Before enforcing SSO:
1. Verify that all users in the organization can successfully complete the SSO flow.
2. Ensure at least one ADMIN user is accessible through the IdP.
3. Test the enforcement with a non-admin account before applying it to the entire organization.

Enforced SSO does not affect platform super-admin accounts, which can always log in with credentials as a break-glass mechanism.

---

## Security

### State Tokens and CSRF Protection

Starting an OIDC sign-in sets a signed, `HttpOnly`, `SameSite=Lax` cookie, `__Host-experimently_oidc`, in the browser that started it, and sends the provider a random `state` and a PKCE S256 challenge. The callback is accepted only with that cookie and the `state` inside it, so a callback link made in another browser -- an attacker's own login -- is refused before its code is exchanged. The cookie also carries the PKCE verifier, so an intercepted code cannot be redeemed without it. It expires after 10 minutes, and every callback expires it; the provider refuses a second use of a code. The API keeps no sign-in state of its own, so any API task can finish a sign-in another one started.

The login also sends a `nonce`, and the ID token in the token endpoint's response must carry it, together with this client in `aud`, the provider's own `iss`, and an `exp` that has not passed. The ID token's signature is not checked. It comes straight from the token endpoint over TLS, which OpenID Connect Core §3.1.3.7 allows in place of a signature check. For the same reason, every provider endpoint must use `https`: an SSO configuration whose `sso_url` is `http://` is refused, in every environment except `test`. GitHub is OAuth 2, not OpenID Connect, and has no ID token.

Because the cookie is `Secure`, serve the API over HTTPS. Browsers that treat `http://localhost` as a secure context (Chrome and Firefox do) also accept it there, for development.

### SAML Assertion Validation

The platform validates all of the following before accepting a SAML assertion:
- XML signature using the configured `x509_certificate`
- `NotBefore` and `NotOnOrAfter` time constraints (5-minute clock skew tolerance)
- `Audience` restriction matches the SP entity ID
- `InResponseTo` matches the pending authentication request ID (replay prevention)
- HTTP POST binding is required; HTTP Redirect binding is not accepted for assertions

### Certificate Rotation

To rotate the IdP signing certificate without downtime:
1. Add the new certificate as a second entry in a `x509_certificates` array (if your IdP supports multiple certificates simultaneously).
2. Update the SSO config with the new certificate once the IdP is rotated.
3. Remove the old certificate.

### OIDC Token Validation

OIDC ID tokens are validated using the IdP's JWKS endpoint (`/.well-known/openid-configuration`). The platform caches the public keys with automatic refresh on key rotation.

---

## Environment Variables

Configure the following in your deployment environment before enabling SSO:

```bash
# Feature flag

# SAML Service Provider settings
SAML_SP_ENTITY_ID=https://your-platform.com
SAML_SP_ACS_URL=https://your-platform.com/auth/sso/saml/acs
SAML_SP_PRIVATE_KEY=<base64-encoded PKCS8 private key>
SAML_SP_CERTIFICATE=<base64-encoded X.509 public certificate>

# OIDC provider credentials
OIDC_GOOGLE_CLIENT_ID=123456789-abc.apps.googleusercontent.com
OIDC_GOOGLE_CLIENT_SECRET=GOCSPX-...

OIDC_GITHUB_CLIENT_ID=Ov23li...
OIDC_GITHUB_CLIENT_SECRET=abc123...

OIDC_MICROSOFT_CLIENT_ID=<Azure Application (client) ID>
OIDC_MICROSOFT_CLIENT_SECRET=<Azure client secret>
OIDC_MICROSOFT_TENANT_ID=<Azure Directory (tenant) ID>

OIDC_AUTH0_CLIENT_ID=...
OIDC_AUTH0_CLIENT_SECRET=...
OIDC_AUTH0_DOMAIN=your-tenant.auth0.com

# State token security
# Generate with: openssl rand -hex 32

# JIT provisioning default role when no group mapping matches
SSO_DEFAULT_ROLE=VIEWER

# Session cookie settings
SSO_SESSION_COOKIE_SECURE=true
SSO_SESSION_COOKIE_SAMESITE=Lax
```

---

## Troubleshooting

### "SAML signature validation failed"

- Verify that `x509_certificate` in the SSO config matches the current signing certificate in the IdP.
- Ensure the certificate is PEM-encoded without the `-----BEGIN CERTIFICATE-----` / `-----END CERTIFICATE-----` headers.
- Check for trailing whitespace or newlines in the certificate string.

### "Invalid ACS URL"

- Confirm the ACS URL configured in the IdP matches exactly: `https://your-platform.com/api/v1/auth/sso/saml/{config_id}/acs`
- The `config_id` in the URL must match the UUID returned by `POST /auth/sso/configs`.

### "State token expired or invalid"

- The OIDC or SAML flow took longer than 10 minutes to complete.
- The user's browser blocked the state cookie (check `SameSite` and `Secure` settings).
- Multiple tabs initiated different auth flows simultaneously.

### "User provisioned but has wrong role"

- Check that the `role_mapping` keys exactly match the group names sent by the IdP.
- For SAML, inspect the raw assertion to confirm the `groups` attribute is being sent. Use a SAML tracer browser extension during testing.
- For GitHub OIDC, verify the team slug format is `{org-name}/{team-slug}`.

### "SSO not triggered for my email domain"

- Confirm `org_domain` in the SSO config exactly matches the domain portion of the user's email (case-insensitive comparison is applied, but no wildcard support).
- Verify the SSO config is active (`is_active: true`) by calling `GET /auth/sso/configs/{config_id}`.
