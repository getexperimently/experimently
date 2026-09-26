# SSO Guide

!!! info "Part of the `sso` module"
    SSO / SAML / OIDC is one of the optional modules -- present in the **full profile**, absent from the core one. A core deployment does not serve these routes. See [Modules and profiles](../getting-started/modules.md) for what each profile includes and how to run the full one.

The `sso` module adds Single Sign-On (SSO) through OpenID Connect (OIDC) and OAuth 2 providers, and through SAML 2.0; it is part of the full profile and, like every module, Apache-2.0. An administrator creates one **SSO configuration** per email domain; users of that domain then sign in through the identity provider (IdP) instead of with a password.

---

## Supported Providers

A configuration's `provider_type` is one of `saml`, `google`, `github`, `okta`, `microsoft`, `azure_ad` and `onelogin`.

| `provider_type` | Protocol | Signs in from | Groups for `role_mapping` |
|---|---|---|---|
| `okta` | OpenID Connect | the dashboard's **Sign in with SSO** | the `groups` claim of Okta's user info |
| `google` | OpenID Connect | the dashboard's **Sign in with SSO** | none |
| `github` | OAuth 2 | the dashboard's **Sign in with SSO** | none |
| `saml` | SAML 2.0 | the identity provider (IdP-initiated) | the `groups` attribute of the assertion |
| `microsoft`, `azure_ad`, `onelogin` | -- | **not supported yet** | -- |

The providers `microsoft`, `azure_ad` and `onelogin` are **not supported yet**: signing in through a configuration of one of those types is refused. A SAML configuration (`provider_type: "saml"`) for the same identity provider is not affected -- Okta, Microsoft Entra ID (Azure AD) and OneLogin can all be used through SAML.

Google and GitHub send no groups, so a `role_mapping` has no effect on their sign-ins: see [Group-to-Role Mapping](#group-to-role-mapping).

---

## Overview

1. A user signs in: from the dashboard for an OIDC or OAuth 2 provider, or from the identity provider's own portal for SAML.
2. The platform checks what comes back: that an OIDC sign-in was started in this browser and its ID token, or a SAML assertion's signature.
3. It takes an email address the provider vouches for, and accepts it only in the configuration's own domain.
4. It finds the account with that email address, or creates one (JIT provisioning), and applies `role_mapping`.

---

## What to Register with the Identity Provider

`PUBLIC_BASE_URL` is the origin users reach the service at, for example `https://app.example.com`. The URLs below are built from it, and an IdP compares them exactly, so set it before registering them.

| Provider | Register | Value |
|---|---|---|
| `okta`, `google`, `github` | the redirect URI (Okta: *Sign-in redirect URI*; Google: *Authorized redirect URI*; GitHub: *Authorization callback URL*) | `{PUBLIC_BASE_URL}/api/v1/auth/sso/oidc/{provider_type}/callback`, e.g. `https://app.example.com/api/v1/auth/sso/oidc/google/callback` |
| `saml` | the ACS URL (Assertion Consumer Service; *Single sign-on URL* in Okta, *Reply URL* in Azure) | `{PUBLIC_BASE_URL}/api/v1/auth/sso/saml/{config_id}/acs`, where `config_id` is the `id` the configuration was created with |
| `saml` | the SP entity ID (*Audience URI* in Okta, *Identifier* in Azure) | the value of `SAML_SP_ENTITY_ID` |

When `PUBLIC_BASE_URL` is not set, the OIDC redirect URI is built from the request's own scheme and `Host` instead, which behind a proxy is usually not the URL the IdP has registered.

The SP metadata document, `GET /api/v1/auth/sso/saml/{config_id}/metadata`, advertises `SAML_SP_ENTITY_ID` and `SAML_SP_ACS_URL`. `SAML_SP_ACS_URL` is one value for the whole deployment, not one per configuration, and incoming assertions are checked against it: set it to the ACS URL above.

---

## Signing In from the Dashboard

When the API lists the `sso` module (`GET /api/v1/modules`), the dashboard's sign-in page shows **Sign in with SSO**. The user enters a work email; the dashboard sends only its domain.

1. The dashboard makes a random 32-byte secret, keeps it in the tab's `sessionStorage`, and navigates to `GET /api/v1/auth/sso/login?domain=<domain>&return_to=<dashboard origin>&handoff=<base64url SHA-256 of the secret>`.
2. The API finds the active OIDC configuration for the domain and redirects to its provider. The provider returns to the same callback it always has, `{PUBLIC_BASE_URL}/api/v1/auth/sso/oidc/{provider}/callback`: nothing changes in the identity provider's registration.
3. The callback redirects to `<dashboard>/sso/complete#code=<hand-off code>`. The code is valid for 60 seconds and is bound to the tab's secret. The access token itself never appears in a URL.
4. `/sso/complete` sends the code and the secret to `POST /api/v1/auth/sso/exchange` and receives the same session a password sign-in returns.

A browser's history keeps `/sso/complete#code=...`. That code expires after 60 seconds, and without the secret held by the tab that started the sign-in it cannot be exchanged.

A domain whose only active configuration is SAML cannot start here: the dashboard says to start from the identity provider's portal (`sso_saml_only`). A domain with more than one active OIDC configuration cannot sign in until an administrator removes the extra ones; the API logs a warning naming them, and the user sees `sso_not_configured`.

### What the user sees when a sign-in fails

The browser returns to `<dashboard>/login?sso_error=<code>` and the sign-in page explains what happened. The identity provider's own error text is never shown, only its OAuth error code (for example `access_denied`).

| `sso_error` | When |
|---|---|
| `sso_expired` | the sign-in took more than 10 minutes |
| `sso_state` | the callback did not carry the cookie of a sign-in this browser started, or its `state` did not match; also a hand-off code that was refused |
| `sso_idp_error` | the provider returned an OAuth `error` (the page shows the code, e.g. `access_denied`) |
| `sso_email` | the provider sent no usable email address |
| `sso_unverified` | the provider has not verified the email address (see [Accounts and email addresses](#jit-user-provisioning)) |
| `sso_domain` | the email address is not in the configuration's domain |
| `sso_account` | the account needs an administrator: more than one account has the email, or the identity is already linked to another account |
| `sso_inactive` | the account is deactivated |
| `sso_not_configured` | no active OIDC configuration for the domain, or more than one; or the configuration was deactivated or deleted during the sign-in |
| `sso_saml_only` | the domain's only active configuration is SAML |
| `sso_failed` | anything else, including a provider that is not supported yet |
| `sso_rate_limited` | the dashboard's own code: the exchange was rate-limited |
| `sso_unreachable` | the dashboard's own code: the API could not be reached |

For `sso_failed` and `sso_account` the page shows a Request ID when the API sent one; search the API log for it. A refusal in the callback is logged at WARNING with its `sso_error`, status, detail and request ID, and an unexpected error at ERROR with its traceback.

### Where the dashboard is: `DASHBOARD_ORIGINS`

`return_to` must be one of the dashboard origins the API accepts. These are:

- `DASHBOARD_ORIGINS`: optional, comma-separated or a JSON array, for example `https://app.example.com`. The first entry is the primary one.
- `PUBLIC_BASE_URL`'s origin.
- In `ENVIRONMENT=development` only: `http://localhost:3000` (`npm run dev`) and `http://localhost:3100` (the static export).

The CORS list is not used here, because it also names the demo apps and any site running an SDK.

**Set `DASHBOARD_ORIGINS` when the dashboard is not served from `PUBLIC_BASE_URL`**, for example when `PUBLIC_BASE_URL` is `https://api.example.com` and the dashboard is `https://app.example.com`. Otherwise every dashboard sign-in is refused with 400. In staging and production, the API logs a warning at startup when `DASHBOARD_ORIGINS` is empty and `PUBLIC_BASE_URL`'s host starts with `api.`.

A callback that arrives without the sign-in's cookie, or with a cookie the API did not issue, cannot say which dashboard it came from. It is sent to the primary dashboard origin (the first `DASHBOARD_ORIGINS` entry, otherwise `PUBLIC_BASE_URL`'s origin) at `/login?sso_error=sso_state`. **Development only:** when neither `DASHBOARD_ORIGINS` nor `PUBLIC_BASE_URL` is set, there is no primary origin, and such a callback is answered with a JSON 400 instead of a redirect.

### Signing in without the dashboard

The older `GET /api/v1/auth/sso/oidc/{provider}/login` still works without `return_to`, for API and CLI callers. Its optional `org_domain` parameter is compared with the stored `org_domain` exactly, so pass it lower-case; without it, the first active configuration of that provider is used. Its callback answers JSON: `access_token`, `token_type`, `user_id`, `email`, `role` and `provider`.

A SAML sign-in starts at the identity provider, which POSTs the assertion to the ACS. The ACS answers that POST with JSON (`access_token`, `token_type`, `user_id`, `email`, `role`); it does not redirect to the dashboard.

---

## API Endpoints

All paths are under `/api/v1`. The configuration endpoints need a signed-in user whose role is `admin`, or a superuser; any other signed-in user gets 403.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/auth/sso/saml/{config_id}/metadata` | SP metadata XML to give to the IdP |
| `POST` | `/api/v1/auth/sso/saml/{config_id}/acs` | ACS: the IdP POSTs the SAML response here (HTTP-POST binding, form field `SAMLResponse`) |
| `GET` | `/api/v1/auth/sso/login` | Starts a dashboard sign-in: `domain`, `return_to` and `handoff` are all required, and a missing or malformed one is a 400. Rate-limited to 30 a minute |
| `POST` | `/api/v1/auth/sso/exchange` | Exchanges a dashboard sign-in's hand-off code and secret for a session (`{access_token, token_type, user}`); rate-limited like the password login, 10 a minute |
| `GET` | `/api/v1/auth/sso/oidc/{provider}/login` | Starts an OIDC sign-in for API and CLI callers (the callback answers JSON) |
| `GET` | `/api/v1/auth/sso/oidc/{provider}/callback` | The OIDC redirect URI registered with the provider |
| `POST` | `/api/v1/auth/sso/configs` | Create an SSO configuration (admin only) |
| `GET` | `/api/v1/auth/sso/configs` | List SSO configurations (admin only) |
| `GET` | `/api/v1/auth/sso/configs/{config_id}` | Retrieve an SSO configuration (admin only) |
| `PUT` | `/api/v1/auth/sso/configs/{config_id}` | Update an SSO configuration; only the fields sent are changed (admin only) |
| `DELETE` | `/api/v1/auth/sso/configs/{config_id}` | Delete an SSO configuration (admin only) |

A configuration is returned without its `client_secret`.

---

## Creating an SSO Configuration

The examples use `https://app.example.com` for `PUBLIC_BASE_URL` and an administrator's access token in `$ADMIN_TOKEN`.

### Configuration Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `org_name` | `string` | Yes | Human-readable organization name |
| `org_domain` | `string` | Yes | The email domain this configuration signs in, e.g. `acme.com`. See below |
| `provider_type` | `string` | Yes | `saml`, `google`, `github` or `okta` (`microsoft`, `azure_ad` and `onelogin` are accepted but not supported yet) |
| `entity_id` | `string` | Yes | SAML: the IdP's entity ID, which must equal the `Issuer` of its assertions. OIDC and OAuth 2: the **client ID** |
| `sso_url` | `string` | SAML, Okta | SAML: the IdP's single sign-on URL. Okta: the authorization server, e.g. `https://acme.okta.com/oauth2/default`. Not used by `google` and `github`. Must be `https` |
| `x509_certificate` | `string` | SAML | The IdP's signing certificate, base64, with or without the `BEGIN`/`END CERTIFICATE` lines |
| `client_secret` | `string` | OIDC, OAuth 2 | The client secret. Never returned by the API |
| `role_mapping` | `object` | No | IdP group name to platform role; default `{}`. See [Group-to-Role Mapping](#group-to-role-mapping) |
| `is_active` | `boolean` | No | Default `true`. `false` stops every sign-in through this configuration |
| `is_enforced` | `boolean` | No | Default `false`. Stored and returned, but it has no effect: password sign-in is not blocked |

`org_domain` is stored normalised: surrounding spaces and a leading `@` removed, lower-cased, so `" @Acme.COM"` is stored as `acme.com`. There is one configuration per domain: creating a second configuration for a domain, or changing a configuration's `org_domain` to another configuration's, is refused with 409 `An SSO configuration already exists for this domain`, whatever the case or spacing of either. An `org_domain` that is empty once normalised is refused with 400 `org_domain is required`.

A configuration written by an earlier release keeps its `org_domain` as it was typed until an update sets `org_domain`; sign-in already compares it normalised.

### SAML Configuration

```{.bash skip reason="needs a full-profile deployment, an administrator's token and a real identity provider"}
curl -X POST https://app.example.com/api/v1/auth/sso/configs \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "org_name": "Acme Corp",
    "org_domain": "acme.com",
    "provider_type": "saml",
    "entity_id": "http://www.okta.com/exk1234567890",
    "sso_url": "https://acme.okta.com/app/acme_experimently/exk1234567890/sso/saml",
    "x509_certificate": "MIIC...",
    "role_mapping": {
      "experimently-admins": "admin",
      "developers": "developer",
      "analysts": "analyst"
    }
  }'
```

The response carries the configuration's `id`: the ACS URL to register is `https://app.example.com/api/v1/auth/sso/saml/<id>/acs`.

### OIDC Configuration

```{.bash skip reason="needs a full-profile deployment, an administrator's token and a real identity provider"}
curl -X POST https://app.example.com/api/v1/auth/sso/configs \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "org_name": "Acme Corp",
    "org_domain": "acme.com",
    "provider_type": "google",
    "entity_id": "123456789-abc.apps.googleusercontent.com",
    "client_secret": "GOCSPX-..."
  }'
```

---

## Provider-Specific Setup

### Okta SAML 2.0

1. In Okta, go to **Applications → Create App Integration → SAML 2.0**.
2. Create the configuration first (with a placeholder certificate if you do not have Okta's yet), to learn its `id`.
3. In Okta, set:
   - **Single sign-on URL**: `{PUBLIC_BASE_URL}/api/v1/auth/sso/saml/{config_id}/acs`
   - **Audience URI (SP Entity ID)**: the value of `SAML_SP_ENTITY_ID`
   - **Name ID format**: `EmailAddress`, **Application username**: `Email`
4. Under **Attribute Statements**, add `firstName` → `user.firstName` and `lastName` → `user.lastName` (the names are optional).
5. Under **Group Attribute Statements**, add a statement named `groups` with the filter that selects the groups you map.
6. From Okta's metadata, update the configuration: `entity_id` is the IdP's entity ID (the `Issuer`), `sso_url` its sign-on URL, `x509_certificate` its signing certificate.
7. Users sign in from their Okta dashboard.

### Okta (OIDC)

1. In Okta, create an **OIDC - OpenID Connect** app integration of type **Web Application**, with the **Authorization Code** grant.
2. Set the **Sign-in redirect URI** to `{PUBLIC_BASE_URL}/api/v1/auth/sso/oidc/okta/callback`.
3. Create the configuration with `provider_type: "okta"`, the **Client ID** as `entity_id`, the **Client secret** as `client_secret`, and the authorization server's URL as `sso_url`: `https://acme.okta.com/oauth2/default` for the default custom authorization server, or `https://acme.okta.com/oauth2` for the org authorization server. The ID token's `iss` must be that URL (the org URL, `https://acme.okta.com`, for the org authorization server).
4. For `role_mapping`, configure the authorization server to put a `groups` claim in the user info; the sign-in asks for the `groups` scope.

### Azure Active Directory (SAML)

Microsoft Entra ID (Azure AD) is used through SAML; its OIDC provider types are not supported yet.

1. In Azure, go to **Enterprise Applications → New Application → Create your own application → Integrate any other application you don't find in the gallery**.
2. Under **Single sign-on → SAML**, set:
   - **Identifier (Entity ID)**: the value of `SAML_SP_ENTITY_ID`
   - **Reply URL (Assertion Consumer Service URL)**: `{PUBLIC_BASE_URL}/api/v1/auth/sso/saml/{config_id}/acs`
3. The email is taken from the Name ID when it contains an `@`, otherwise from the `emailaddress` claim.
4. For `role_mapping`, add a group claim. The groups are read from the `groups` attribute or from `http://schemas.microsoft.com/ws/2008/06/identity/claims/groups`, and the keys of `role_mapping` must be what Azure sends (by default, group object IDs).
5. Download the **Certificate (Base64)**, and update the configuration: `entity_id` is the **Microsoft Entra Identifier**, `sso_url` the **Login URL**, `x509_certificate` the certificate.

### Google Workspace (OIDC)

1. In Google Cloud Console, go to **APIs & Services → Credentials → Create OAuth client ID**, of type **Web application**.
2. Add the authorized redirect URI `{PUBLIC_BASE_URL}/api/v1/auth/sso/oidc/google/callback`.
3. Create the configuration with `provider_type: "google"`, the **Client ID** as `entity_id` and the **Client secret** as `client_secret` (see [OIDC Configuration](#oidc-configuration)).

Only accounts of the Google Workspace domain that equals `org_domain` can sign in: a personal Google account is refused. Google sends no groups, so every new account is a `viewer`.

### GitHub (OIDC)

GitHub is OAuth 2, not OpenID Connect; it has no ID token.

1. In GitHub, go to **Settings → Developer settings → OAuth Apps → New OAuth App** (or the same under an organization's settings).
2. Set the **Authorization callback URL** to `{PUBLIC_BASE_URL}/api/v1/auth/sso/oidc/github/callback`.
3. Create the configuration with `provider_type: "github"`, the **Client ID** as `entity_id` and a client secret as `client_secret`.

The email address is taken from GitHub's list of the user's verified addresses (see below), not from the public profile. GitHub sends no groups or teams, so every new account is a `viewer`.

---

## JIT User Provisioning

Users who authenticate via SSO for the first time are provisioned with a platform account automatically. There is no setting to turn this off; to stop sign-ins through a configuration, set its `is_active` to `false`.

A sign-in is accepted only for an email address in the configuration's `org_domain`, exactly: `bob@acme.com` for `acme.com`, but not `bob@eu.acme.com` or `bob@acme.io`. Use one configuration per domain. The comparison ignores case and surrounding spaces. An existing account is matched by email address, ignoring case; if more than one account matches, the sign-in is refused.

The email address must be one the identity provider has verified:

| Provider | Where the email comes from | Required |
|---|---|---|
| Okta | the ID token's `email` | `email_verified` is `true` (the JSON boolean, or the string `"true"`) |
| Google | the ID token's `email` | `email_verified` is `true` (the JSON boolean, or the string `"true"`), and `hd` (the Google Workspace domain) equals the email's domain. A personal Google account has no `hd`, so it cannot sign in. |
| GitHub | `GET /user/emails` | a verified address in `org_domain`: the primary one if it is in the domain, otherwise the only one in the domain. The public profile email is not used. |
| SAML | the Name ID if it contains `@`, otherwise the `email` attribute, otherwise the `emailaddress` claim | the assertion's signature (see [SAML Assertion Validation](#saml-assertion-validation)) |

For Okta and Google, the user info's `sub` must also equal the ID token's.

An account already linked to the same identity under a different email address is not reused: that sign-in is refused, and an administrator resolves it.

A new account is created with no password and these fields; an existing account's name is not changed by a sign-in:

| Platform Field | SAML Source | OIDC / OAuth 2 Source |
|----------------|-------------|-------------|
| `email` | as above, lower-cased | as above, lower-cased |
| `first_name` | the `firstName` attribute | the user info's `given_name`, else the first word of `name` |
| `last_name` | the `lastName` attribute | the user info's `family_name`, else the rest of `name` |
| `role` | from the `groups` attribute via `role_mapping`, else `viewer` | from the user info's `groups` via `role_mapping`, else `viewer` |

### Upgrading

After upgrading from an earlier release, review the accounts created by SSO sign-in (accounts with no password set) and their roles, and remove any you do not recognise.

---

## Group-to-Role Mapping

The `role_mapping` field maps the group names the IdP sends to platform roles.

```json
{
  "role_mapping": {
    "experimently-admins": "admin",
    "developers":          "developer",
    "data-analysts":       "analyst",
    "contractors":         "viewer"
  }
}
```

Rules:

- The values are `admin`, `developer`, `analyst` and `viewer`, in any case.
- Keys are matched exactly, including case, against the group names the IdP sends.
- The user's groups are read in the order the IdP sends them, and the **first** one that has a mapping decides the role. It is not the highest-privilege one, and the order of `role_mapping` does not matter.
- A new user in no mapped group receives the `viewer` role.
- An existing user's role changes only when one of their groups is in the mapping. A sign-in with no mapped group leaves the role as it is, so removing someone from every mapped group does not demote them: to demote someone through SSO, map one of their groups to `viewer`. Superuser status is never changed by a sign-in.
- Groups come from SAML assertions and from Okta. Google and GitHub send none, so for them the mapping never applies: new users are `viewer`, and existing users keep their role.

---

## Security

### State Tokens and CSRF Protection

Starting an OIDC sign-in sets a signed, `HttpOnly`, `SameSite=Lax` cookie, `__Host-experimently_oidc`, in the browser that started it, and sends the provider a random `state` and a PKCE S256 challenge. The callback is accepted only with that cookie and the `state` inside it, so a callback link made in another browser -- an attacker's own login -- is refused before its code is exchanged. The cookie also carries the PKCE verifier, so an intercepted code cannot be redeemed without it. The sign-in expires after 10 minutes. The cookie is kept 5 minutes longer, so a callback that arrives late still carries it and is reported as expired (`sso_expired`) rather than as a sign-in from another browser. Every callback expires the cookie, and the provider refuses a second use of a code. The API keeps no sign-in state of its own, so any API task can finish a sign-in another one started.

The login also sends a `nonce`, and the ID token in the token endpoint's response must carry it, together with this client in `aud`, the provider's own `iss`, and an `exp` that has not passed. The ID token's signature is not checked. It comes straight from the token endpoint over TLS, which OpenID Connect Core §3.1.3.7 allows in place of a signature check. For the same reason, every provider endpoint must use `https`: an SSO configuration whose `sso_url` is `http://` is refused, in every environment except `test`. GitHub is OAuth 2, not OpenID Connect, and has no ID token.

Because the cookie is `Secure`, serve the API over HTTPS. Browsers that treat `http://localhost` as a secure context (Chrome and Firefox do) also accept it there, for development.

The cookie and the dashboard's hand-off code are signed with keys derived from `SECRET_KEY`.

### SAML Assertion Validation

SAML needs the `python3-saml` library, which the full profile's image installs from `modules/requirements.lock`. It checks, before an assertion is accepted:

- a signature on the response or on the assertion, made with the configured `x509_certificate`;
- the `Issuer` equals the configuration's `entity_id`;
- the `Audience`, when present, includes `SAML_SP_ENTITY_ID`;
- the `Destination` and the `Recipient`, when present, match `SAML_SP_ACS_URL`;
- `NotBefore` and `NotOnOrAfter`, with 5 minutes of clock skew allowed.

Only the HTTP-POST binding is accepted. Sign-in is IdP-initiated: the platform sends no authentication request, so there is none for a response to answer.

Without `python3-saml`, every SAML route answers 501, except in `ENVIRONMENT=development` and `test`, where a stand-in reads the Name ID and **validates nothing**. Never expose a development or test deployment's ACS to anyone.

### Certificate Rotation

The configuration holds one certificate. When the IdP switches to a new signing certificate, update `x509_certificate` with `PUT /api/v1/auth/sso/configs/{config_id}` at the same time; assertions signed with the other certificate are refused until the two agree.

---

## Environment Variables

| Variable | What it does |
|---|---|
| `PUBLIC_BASE_URL` | The origin users reach the service at, e.g. `https://app.example.com`. The OIDC redirect URI is built from it; see [What to Register](#what-to-register-with-the-identity-provider). Staging and production refuse to start without it or `ALLOWED_HOSTS` |
| `DASHBOARD_ORIGINS` | Where a dashboard sign-in may return to, when that is not `PUBLIC_BASE_URL`; see [`DASHBOARD_ORIGINS`](#where-the-dashboard-is-dashboard_origins) |
| `SAML_SP_ENTITY_ID` | This service's SAML entity ID, which the IdP puts in the `Audience`. Default `https://experimently.example.com` |
| `SAML_SP_ACS_URL` | The ACS URL the metadata advertises and assertions are checked against. Default `https://experimently.example.com/auth/sso/saml/acs`, which is not a route of this API: set it |
| `SECRET_KEY` | Signs the sign-in cookie and the hand-off code (through derived keys), and sessions |
| `ENVIRONMENT` | `development` adds the `localhost` dashboard origins and allows the SAML stand-in; `test` also allows the stand-in and `http` provider endpoints |

There are no environment variables for a provider's client ID or secret: they are fields of the configuration. The `OIDC_GOOGLE_*`, `OIDC_GITHUB_*` and `OIDC_MICROSOFT_*` settings exist but nothing reads them.

```{.bash skip reason="deployment settings; the values are examples"}
PUBLIC_BASE_URL=https://app.example.com
SAML_SP_ENTITY_ID=https://app.example.com
SAML_SP_ACS_URL=https://app.example.com/api/v1/auth/sso/saml/3f1c2b9e-0000-4000-8000-000000000000/acs
```

---

## Troubleshooting

### The identity provider refuses the redirect URI (`redirect_uri_mismatch`)

- The redirect URI registered with the provider must be exactly `{PUBLIC_BASE_URL}/api/v1/auth/sso/oidc/{provider_type}/callback`. Check `PUBLIC_BASE_URL`: no path and no trailing slash.

### Every dashboard sign-in answers 400 "return_to is not a dashboard origin this API accepts"

- The dashboard's origin is neither `PUBLIC_BASE_URL`'s origin nor listed in `DASHBOARD_ORIGINS`. Set `DASHBOARD_ORIGINS` to the origin shown in the browser's address bar, with no path and no trailing slash, for example `https://app.example.com`.

### "OIDC sign-in was not started in this browser, or its cookie was not sent" (`sso_state`)

- The callback arrived at a different host from the one the sign-in started on. The cookie belongs to one host: the login and the callback must both be on `PUBLIC_BASE_URL`'s host.
- The browser blocked the cookie, or the API is served over plain `http` from a host other than `localhost`: the cookie is `Secure`.
- The same message, or "OIDC state does not match this browser's sign-in", when the callback link was opened in another browser, or opened twice.

### "OIDC sign-in expired; start it again" (`sso_expired`)

- More than 10 minutes passed between starting the sign-in and returning from the provider.

### "OIDC provider endpoints must use https; check this SSO configuration's sso_url"

- An Okta configuration's `sso_url` is `http://`. Use the `https` URL of the authorization server.

### "OIDC ID token was not accepted (iss)"

- Okta: `sso_url` is not the authorization server that issued the token. For the default custom server it is `https://acme.okta.com/oauth2/default`; for the org server, `https://acme.okta.com/oauth2`. The other reasons in brackets are `missing`, `malformed`, `aud`, `azp`, `exp` and `nonce`; for `aud`, check that `entity_id` is the client ID.

### "This single sign-on provider is not supported yet"

- The configuration's `provider_type` is `microsoft`, `azure_ad` or `onelogin`. Use SAML for that identity provider.

### "The identity provider has not verified this account's email address" (`sso_unverified`)

- Okta or Google sent `email_verified` other than `true`, or GitHub has no verified address in `org_domain` (or more than one, none of them primary).

### "This account's email is not in the domain this single sign-on is configured for" (`sso_domain`)

- The email's domain is not exactly `org_domain` (a subdomain is a different domain), or a Google account's Workspace domain (`hd`) is not the email's domain.

### "An SSO configuration already exists for this domain"

- Another configuration has the same `org_domain`, ignoring case, surrounding spaces and a leading `@`. List the configurations and update or delete that one.

### "SAML validation failed: invalid_response"

The library refused the assertion. Check, in this order:

- `x509_certificate` is the IdP's current signing certificate, and the IdP signs the response or the assertion.
- `entity_id` is exactly the `Issuer` the IdP sends.
- `SAML_SP_ACS_URL` is the ACS URL the IdP posts to, and `SAML_SP_ENTITY_ID` the audience it sends.
- The API's clock is right: more than 5 minutes of skew fails.

### "SAML single sign-on is not available in this deployment: …"

- `python3-saml` is not installed, or cannot be imported. The full profile's image installs it; a hand-built environment needs it from `modules/requirements.txt`, and it needs the `xmlsec1` and `libxml2` libraries.

### "SSO config '…' is not active"

- The SAML configuration's `is_active` is `false`; its ACS and metadata answer 404.

### A user has the wrong role

- Check that the `role_mapping` keys exactly match the group names the IdP sends, including case. Use a SAML tracer browser extension to see a SAML assertion's `groups`.
- The first of the user's groups that has a mapping decides, in the order the IdP sends them.
- An existing user whose groups match nothing keeps their role.
- Google and GitHub send no groups.

### A domain's users are not offered SSO

- `org_domain` must be exactly the domain part of their email address; there are no wildcards.
- The configuration must be active (`is_active: true`): `GET /api/v1/auth/sso/configs/{config_id}`.
- A SAML-only domain signs in from the IdP's portal, not from the dashboard.
