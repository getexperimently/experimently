# API Endpoints Documentation

This document provides detailed information about all available API endpoints in Experimently.

## Authentication and Authorization

### Overview
The API uses two types of authentication:
1. OAuth2 Bearer tokens for user authentication
2. API keys for client applications

### OAuth2 Authentication
1. **Obtain Access Token**:
   ```bash
   curl -X POST "http://localhost:8000/api/v1/auth/token" \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "username=user@example.com&password=your_password"
   ```

2. **Using the Access Token**:
   ```bash
   curl -X GET "http://localhost:8000/api/v1/users/me" \
     -H "Authorization: Bearer your_access_token"
   ```

### API Key Authentication
1. **Obtain API Key**:
   - Contact your administrator to get an API key
   - API keys are used for client applications to access tracking and feature flag endpoints

2. **Using the API Key**:
   ```bash
   curl -X GET "http://localhost:8000/api/v1/feature-flags/user/123" \
     -H "X-API-Key: your_api_key"
   ```

### Authorization Levels
1. **Regular Users**:
   - Can access their own data
   - Cannot access admin endpoints

   - Feature flags are by role, not ownership: ADMIN and DEVELOPER may read, create,
     change and delete any flag; ANALYST and VIEWER may read any flag and change none
   - Experiments: reading an experiment and its results under
     `/api/v1/experiments/{experiment_id}` needs the role's READ on experiments (all four
     roles hold it); who owns the experiment is not considered. ADMIN and DEVELOPER may create
     experiments, clone any experiment, and update, start, pause, complete, archive or
     annotate (`metadata`) any experiment, schedule any experiment, and delete any
     experiment in DRAFT. ANALYST and VIEWER change no experiment, including one they
     own

2. **Superusers**:
   - Can access all user data
   - Can manage all experiments
   - Can access admin endpoints
   - Can create other users

## Usage Examples

### 1. User Registration and Authentication

!!! note "Cognito only"
    The password-reset and token-refresh endpoints (`POST /api/v1/auth/forgot-password`,
    `/reset-password` and `/refresh`) are available only when `AUTH_PROVIDER=cognito`.
    The sign-up and confirmation endpoints (`POST /api/v1/auth/signup` and `/confirm`)
    also need `COGNITO_SELF_SIGNUP_ENABLED=true`; without it they answer 404 and an
    administrator creates users ([Adding a user](../cognito_integration.md#adding-a-user)).
    With any other provider, including the default `local`, all five answer 404. With
    `local`, sign in with `POST /api/v1/auth/login`; an administrator creates accounts
    and resets passwords.

    The dashboard does not yet sign in with Cognito. Sign in through the API with
    `POST /api/v1/auth/token`. SSO sign-in needs `AUTH_PROVIDER=local`.

Step 1: Register a new user:

Only with `COGNITO_SELF_SIGNUP_ENABLED=true` and a user pool that allows self sign-up; otherwise see [Adding a user](../cognito_integration.md#adding-a-user).

```bash
curl -X POST "http://localhost:8000/api/v1/auth/signup" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "john.doe",
    "email": "john@example.com",
    "password": "SecurePass123!",
    "given_name": "John",
    "family_name": "Doe"
  }'
```

Step 2: Confirm registration:

```bash
curl -X POST "http://localhost:8000/api/v1/auth/confirm" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "john.doe",
    "confirmation_code": "123456"
  }'
```

Step 3: Login to get access token:

```bash
curl -X POST "http://localhost:8000/api/v1/auth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=john.doe&password=SecurePass123!"
```

### 2. Managing Experiments

Step 1: List experiments:

```bash
curl -X GET "http://localhost:8000/api/v1/experiments/" \
  -H "Authorization: Bearer your_access_token" \
  -H "Content-Type: application/json"
```

Step 2: Create a new experiment:

```bash
curl -X POST "http://localhost:8000/api/v1/experiments/" \
  -H "Authorization: Bearer your_access_token" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Button Color Test",
    "description": "Testing different button colors",
    "hypothesis": "Red buttons will have higher click rates",
    "experiment_type": "AB_TEST",
    "start_date": "2024-04-01T00:00:00Z",
    "end_date": "2024-04-30T23:59:59Z",
    "targeting_rules": {
      "logical_operator": "AND",
      "groups": [
        {
          "logical_operator": "AND",
          "conditions": [
            {"attribute": "country", "operator": "in", "value": ["US", "CA"]},
            {"attribute": "browser", "operator": "in", "value": ["chrome", "firefox"]}
          ]
        }
      ]
    }
  }'
```

Step 3: Get experiment results:

```bash
curl -X GET "http://localhost:8000/api/v1/experiments/123/results" \
  -H "Authorization: Bearer your_access_token" \
  -H "Content-Type: application/json"
```

### 3. Feature Flag Management

Step 1: List feature flags:

```bash
curl -X GET "http://localhost:8000/api/v1/feature-flags/" \
  -H "Authorization: Bearer your_access_token" \
  -H "Content-Type: application/json"
```

Step 2: Create a feature flag:

```bash
curl -X POST "http://localhost:8000/api/v1/feature-flags/" \
  -H "Authorization: Bearer your_access_token" \
  -H "Content-Type: application/json" \
  -d '{
    "key": "new_checkout_flow",
    "name": "New Checkout Flow",
    "description": "Rolling out new checkout experience",
    "is_active": true,
    "rollout_percentage": 50,
    "targeting_rules": {
      "logical_operator": "AND",
      "groups": [
        {
          "logical_operator": "AND",
          "conditions": [
            {"attribute": "country", "operator": "in", "value": ["US"]},
            {"attribute": "plan", "operator": "equals", "value": "premium"}
          ]
        }
      ]
    }
  }'
```

Step 3: Get feature flags for a user (client-side):

```bash
curl -X GET "http://localhost:8000/api/v1/feature-flags/user/123" \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json"
```

### 4. Tracking Events

Step 1: Assign a user to an experiment (sticky; every call for an enrolled user records that the user saw the experiment):

```bash
curl -X POST "http://localhost:8000/api/v1/tracking/assign" \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{"experiment_key": "hero_banner", "user_id": "123", "context": {"device": "mobile"}}'
```

Step 2: Track a conversion for that experiment (variant is resolved from the assignment):

```bash
curl -X POST "http://localhost:8000/api/v1/tracking/track" \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "purchase",
    "user_id": "123",
    "experiment_key": "hero_banner",
    "value": 99.99,
    "metadata": {"product_id": "ABC123", "payment_method": "credit_card"}
  }'
```

Step 3: Get user assignments:

```bash
curl -X GET "http://localhost:8000/api/v1/tracking/assignments/123" \
  -H "X-API-Key: your_api_key"
```

### 5. Admin Operations

Step 1: List all users (superuser only):

```bash
curl -X GET "http://localhost:8000/api/v1/admin/users" \
  -H "Authorization: Bearer your_access_token" \
  -H "Content-Type: application/json"
```

Step 2: Create a new user (superuser only):

```bash
curl -X POST "http://localhost:8000/api/v1/users/" \
  -H "Authorization: Bearer your_access_token" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "jane.smith",
    "email": "jane@example.com",
    "password": "SecurePass123!",
    "full_name": "Jane Smith",
    "is_active": true,
    "is_superuser": false
  }'
```

## Rate Limiting and API Constraints

### Rate Limits
Limits are counted per client address. Most routes allow 300 requests a minute.
AI design (`POST /api/v1/ai/design`) allows 10 a minute, and AI results
interpretation (`POST /api/v1/ai/interpret/{experiment_id}`) 10 a minute for every
experiment id together. The [API Documentation Guide](api-docs-guide.md#rate-limiting)
lists every route with its own limit. Over a limit the API answers `429` with a
`Retry-After` header (see [Rate Limiting](#3-rate-limiting) below).

### Request Size Limits
- Maximum request body size: 1MB
- Maximum response size: 10MB

### Pagination
- Default page size: 100 items
- Maximum page size: 500 items
- All list endpoints support pagination using `skip` and `limit` parameters

### Caching
- Experiment data is cached for 1 hour when `CACHE_ENABLED` is on (it is off by default)
- Feature flags are not cached: the flag list and a flag's detail are read from the database on every request, whatever `CACHE_ENABLED` says
- Results data is cached for 5 minutes
- Cache-Control headers are included in responses

## Authentication Endpoints

!!! note "Cognito only"
    The password-reset and token-refresh endpoints (`POST /api/v1/auth/forgot-password`,
    `/reset-password` and `/refresh`) are available only when `AUTH_PROVIDER=cognito`.
    The sign-up and confirmation endpoints (`POST /api/v1/auth/signup` and `/confirm`)
    also need `COGNITO_SELF_SIGNUP_ENABLED=true`; without it they answer 404 and an
    administrator creates users ([Adding a user](../cognito_integration.md#adding-a-user)).
    With any other provider, including the default `local`, all five answer 404. With
    `local`, sign in with `POST /api/v1/auth/login`; an administrator creates accounts
    and resets passwords.

    The dashboard does not yet sign in with Cognito. Sign in through the API with
    `POST /api/v1/auth/token`. SSO sign-in needs `AUTH_PROVIDER=local`.

### Sign Up
- **Endpoint**: `POST /api/v1/auth/signup`
- **Description**: Register a new user
- **Request Body**:
  ```json
  {
    "username": "string",
    "password": "string",
    "email": "string",
    "given_name": "string",
    "family_name": "string"
  }
  ```
- **Response**: 201 Created
  ```json
  {
    "user_id": "string",
    "confirmed": false,
    "message": "string"
  }
  ```

### Confirm Sign Up
- **Endpoint**: `POST /api/v1/auth/confirm`
- **Description**: Confirm user registration with verification code
- **Request Body**:
  ```json
  {
    "username": "string",
    "confirmation_code": "string"
  }
  ```
- **Response**: 200 OK
  ```json
  {
    "message": "Account confirmed successfully. You can now sign in.",
    "confirmed": true
  }
  ```

### Login
- **Endpoint**: `POST /api/v1/auth/token`
- **Description**: OAuth2 compatible token login
- **Request Body**: Form data
  - username: string (with `AUTH_PROVIDER=local`, the user's email address)
  - password: string
- With `AUTH_PROVIDER=local`: The email address is matched whatever its letter case (A–Z), and every casing of it counts toward the same failed attempts.
- **Response**: 200 OK
  ```json
  {
    "access_token": "string",
    "token_type": "bearer",
    "expires_in": 3600
  }
  ```

### Get User Info
- **Endpoint**: `GET /api/v1/auth/me`
- **Description**: Get current user information
- **Headers**: Authorization: Bearer {token}
- **Response**: 200 OK
  ```json
  {
    "username": "string",
    "email": "string",
    "given_name": "string",
    "family_name": "string"
  }
  ```

## User Management Endpoints

### List Users
- **Endpoint**: `GET /api/v1/users/`
- **Description**: List users (all for superusers, self for regular users)
- **Headers**: Authorization: Bearer {token}
- **Query Parameters**:
  - skip: int (default: 0)
  - limit: int (default: 100, max: 100)
- **Response**: 200 OK
  ```json
  {
    "items": [
      {
        "id": "string",
        "username": "string",
        "email": "string",
        "full_name": "string",
        "is_active": true,
        "is_superuser": false,
        "role": "VIEWER",
        "created_at": "datetime",
        "updated_at": "datetime",
        "last_login": "datetime",
        "preferences": {}
      }
    ],
    "total": 100,
    "skip": 0,
    "limit": 100
  }
  ```
- **Fields**: `full_name` is the first and last name joined by a space (or
  whichever one is set), and `null` when neither is. `email`, `role`,
  `last_login` and `preferences` may be `null`.

### Create User
- **Endpoint**: `POST /api/v1/users/`
- **Description**: Create new user (superuser only)
- **Headers**: Authorization: Bearer {token}
- **Request Body**:
  ```json
  {
    "username": "string",
    "email": "string",
    "password": "string",
    "full_name": "string",
    "is_active": true,
    "is_superuser": false
  }
  ```
- **Password**: at least 8 characters and at most 72 bytes (UTF-8), with an
  upper-case letter, a lower-case letter and a digit. Anything else is a 422.
- **Response**: 201 Created
- **Errors**: 409 "Email already registered" when another account holds the
  email address in any letter case (`Pat.Lee@example.com` and
  `pat.lee@example.com` are the same address here). 409 "Username already
  registered" when another account has the username.

### Get User
- **Endpoint**: `GET /api/v1/users/{user_id}`
- **Description**: Get user by ID
- **Headers**: Authorization: Bearer {token}
- **Path Parameters**:
  - user_id: string (UUID)
- **Response**: 200 OK
  ```json
  {
    "id": "string",
    "username": "string",
    "email": "string",
    "full_name": "string",
    "is_active": true,
    "is_superuser": false,
    "created_at": "datetime",
    "updated_at": "datetime"
  }
  ```

### Update User
- **Endpoint**: `PUT /api/v1/users/{user_id}`
- **Description**: Update a user. A superuser may update any user and every
  field. Anyone else may update only their own account (another user's is a
  403), may not change its email address or username, and has `is_active`
  and `is_superuser` ignored.
- **Headers**: Authorization: Bearer {token}
- **Request Body**: `username` and `email` are required. A user who is not a
  superuser sends the account's current values; they are accepted only if the
  username is exactly the stored one and the email address is the stored one
  as `EmailStr` parses it (it lower-cases the domain, not the part before the
  `@`), and they are not written.
  ```json
  {
    "username": "string",
    "email": "user@example.com",
    "full_name": "string",
    "password": "string"
  }
  ```
- **Password**: `password` sets **another** account's password: a superuser's
  reset, which needs no old password. It follows the same rules as a new
  account's (see Create User); a weaker one, or `""`, is a 422. Leave it out,
  or send `null`, to keep the password as it is. Your own password is changed
  with `POST /api/v1/users/me/password` (below), which asks for the current
  one; sending your own `password` here is a 403 for every caller,
  superusers included. `PUT /api/v1/admin/users/{user_id}` treats `password`
  the same way.
- **Your own access**: a superuser cannot remove their own superuser access or
  deactivate their own account here; another superuser does it. The request is
  refused when it would change your own `is_superuser` or `is_active` from
  `true` to `false`, and nothing in it is written, other fields included.
  Resending the stored values (`true`) is accepted, so a client that reads the
  account and sends it back with an edit is not refused.
- **During a concurrent change**: a request that turns off another superuser's
  `is_superuser` or `is_active` first waits for any change in progress to an
  active superuser's account, then checks that you are still an active
  superuser. If another administrator has just deactivated or deleted your
  account, the answer is 400 "Inactive user"; if they have just removed your
  superuser access, 403 "Not enough permissions". Nothing is written either
  way. The wait is at most 5 seconds; a request that would wait longer answers
  500 and writes nothing.
- **Audit log**: a change to `is_superuser` is recorded as `role_assign`, with
  the role and superuser flag before and after, and a change to `is_active` as
  `user_deactivate` or `user_activate`, in the same transaction as the change.
  If the entry cannot be written, nothing is saved.
- **Response**: 200 OK, the user as in Get User
- **Errors**: 400 "You can't remove your own superuser access. Ask another
  administrator to do it." when a superuser's request would turn off their own
  `is_superuser`. 400 "You can't deactivate your own account." when it would
  turn off their own `is_active`; when both would change, the answer is the
  first. 403 "Only an administrator can change an account's email address
  or username." when a user who is not a superuser sends a different email
  address or username. Administrators change them with
  `PUT /api/v1/admin/users/{user_id}`. 403 "To change your own password, use
  POST /api/v1/users/me/password, which asks for your current password." when
  the request sets the caller's own password.
  409 "Email already registered" when a superuser sets an email address that
  another account holds in any letter case. Changing only the letter case of
  the account's own address is accepted, and resending the stored address
  unchanged is never refused. 409 "Username already registered" when a
  superuser sets a username another account has.

### Delete User
- **Endpoint**: `DELETE /api/v1/users/{user_id}`
- **Description**: A superuser deletes any account but their own. Anyone else
  deletes only their own account (another user's is a 403).
- **Headers**: Authorization: Bearer {token}
- **During a concurrent change**: deleting an account that is an active
  superuser first waits for any change in progress to an active superuser's
  account, then checks that you are still an active superuser. If another
  administrator has just deactivated or deleted your account, the answer is
  400 "Inactive user"; if they have just removed your superuser access, 403
  "Not enough permissions". Nothing is written either way. The wait is at most
  5 seconds; a request that would wait longer answers 500 and writes nothing.
- **Response**: 204 No Content
- **Errors**: 400 "Superusers cannot delete themselves" when a superuser
  deletes their own account. 403 "Not enough permissions" when anyone else
  deletes another account. 404 "User not found".

### Change Your Password
- **Endpoint**: `POST /api/v1/users/me/password`
- **Description**: Change your own password. Available when `AUTH_PROVIDER`
  is `local`; otherwise the route answers 404 before the body is validated
  against the schema. Changing the password does not end other sessions: a
  token issued before the change keeps working until it expires. To end them
  straight away, an administrator sets `is_active` to `false`.
- **Headers**: Authorization: Bearer {token}
- **Request Body**: `new_password` follows the same rules as a new account's.
  ```json
  {
    "current_password": "string",
    "new_password": "string"
  }
  ```
- **Response**: 204 No Content
- **Errors**: 403 when `current_password` is missing or incorrect ("The
  current password is incorrect."), or when the account has no password of
  its own; 422 when `new_password` breaks the rules; 423 with `Retry-After`
  after too many wrong current passwords (the same count as failed logins,
  10 within 15 minutes by default); 429 after 5 requests a minute from one
  address. A wrong current password is a 403, not a 401: the session is
  still signed in. The runnable example is in
  [Authentication](auth.md#change-your-own-password).

## Experiment Endpoints

### List Experiments
- **Endpoint**: `GET /api/v1/experiments/`
- **Description**: List experiments with filtering and pagination
- **Headers**: Authorization: Bearer {token}
- **Query Parameters**:
  - status_filter: string (optional)
  - skip: int (default: 0)
  - limit: int (default: 100, max: 500)
  - search: string (optional)
  - sort_by: string (default: "created_at")
  - sort_order: string (default: "desc")
- **Response**: 200 OK
  ```json
  {
    "items": [
      {
        "id": "string",
        "name": "string",
        "description": "string",
        "status": "string",
        "created_at": "datetime",
        "updated_at": "datetime"
      }
    ],
    "total": 100,
    "skip": 0,
    "limit": 100
  }
  ```

### Get Experiment
- **Endpoint**: `GET /api/v1/experiments/{experiment_id}`
- **Description**: Get experiment details
- **Headers**: Authorization: Bearer {token}
- **Path Parameters**:
  - experiment_id: string (UUID)
- **Response**: 200 OK
  ```json
  {
    "id": "string",
    "name": "string",
    "description": "string",
    "status": "string",
    "created_at": "datetime",
    "updated_at": "datetime"
  }
  ```

### Get Experiment Results
- **Endpoint**: `GET /api/v1/experiments/{experiment_id}/results`
- **Description**: Get experiment results and analysis. The same payload as
  `GET /api/v1/results/{experiment_id}` with no options: the experiment's
  stored `correction_method` and `confidence_level` (see
  [How results are judged](#how-results-are-judged)).
- **Headers**: Authorization: Bearer {token}
- **Path Parameters**:
  - experiment_id: string (UUID)
- **Response**: 200 OK
  ```json
  {
    "experiment_id": "string",
    "status": "string",
    "metrics": [
      {
        "name": "string",
        "control_value": 0.0,
        "treatment_value": 0.0,
        "difference": 0.0,
        "p_value": 0.0,
        "is_significant": true
      }
    ],
    "sample_size": {
      "control": 100,
      "treatment": 100
    }
  }
  ```

### How results are judged

Each experiment stores a `correction_method` (`none`, `bonferroni` or
`benjamini_hochberg`) and a `confidence_level` (0.80 to 0.99). A new
experiment gets `benjamini_hochberg` at `0.95` unless `POST
/api/v1/experiments/` names others; experiments created before these fields
existed were given the same defaults. Both are returned by every experiment
response.

- `GET /api/v1/results/{experiment_id}`, its alias
  `GET /api/v1/experiments/{experiment_id}/results`,
  `GET /api/v1/results/{experiment_id}/sample-size`, the data export and the
  experiment report use the stored values, and so does the interaction test
  of `GET /api/v1/interactions/{exp_a_id}/{exp_b_id}` (beta): the correction
  across one experiment's treatments, and the level for `is_significant`.
  `?correction_method=` and
  `?confidence_level=` on the first and third apply to that request only; the
  response's `correction_method` and `confidence_level` say what the numbers
  were computed under. `?correction_method=none` shows the uncorrected
  numbers.
- With one treatment the correction changes no decision: `adjusted_p_value`
  equals `p_value`, and `is_significant`, the winner and the summary are the
  same as with `none`. With two or more treatments it can: a treatment with
  `p_value` 0.035 has `adjusted_p_value` 0.071 under `benjamini_hochberg`
  when the other treatment's p-value is higher, and is not significant at
  0.95.
- Both fields can be changed with `PUT /api/v1/experiments/{experiment_id}`
  only while the experiment is a `draft`. After that nobody can change them,
  a superuser included, and re-sending the stored value is refused as well
  (`Cannot update correction_method for experiments in active status`). An
  experiment that was already running when these fields were added keeps
  `benjamini_hochberg` for good; `?correction_method=none` on its results
  shows the numbers it showed before. A clone is a draft and starts with its
  source's values.
- Not affected: the breakdown (`?breakdown=`) uses the stored confidence
  level only as its base alpha, with its own Bonferroni correction over
  segments; sequential testing (its own `alpha`) does not follow the stored
  level (CUPED does, and applies the stored correction); the Bayesian results,
  post-stratification, live results (a fixed, uncorrected 0.05), the AI
  interpretation, the power calculator (`GET
  /api/v1/experiments/analysis/sample-size`) and warehouse analysis runs are
  unchanged.

## Feature Flag Endpoints

### List Feature Flags
- **Endpoint**: `GET /api/v1/feature-flags/`
- **Description**: List feature flags with filtering and pagination
- **Headers**: Authorization: Bearer {token}
- **Query Parameters**:
  - status_filter: string (optional)
  - skip: int (default: 0)
  - limit: int (default: 100, max: 500)
  - search: string (optional)
- **Response**: 200 OK
  ```json
  [
    {
      "id": "string",
      "key": "string",
      "name": "string",
      "description": "string",
      "status": "string",
      "created_at": "datetime",
      "updated_at": "datetime"
    }
  ]
  ```

### Get User Feature Flags
- **Endpoint**: `GET /api/v1/feature-flags/user/{user_id}`
- **Description**: Get all feature flags evaluated for a user
- **Headers**: X-API-Key: {api_key}
- **Path Parameters**:
  - user_id: string
- **Query Parameters**:
  - context: object (optional)
- **Response**: 200 OK
  ```json
  {
    "feature_flag_key": true,
    "another_flag": false
  }
  ```

### Archived Flags
An archived flag stays archived until it is unarchived:

| Request | On an archived flag |
|---|---|
| `PUT /api/v1/feature-flags/{id}` with `"is_active": true` | 400, flag unchanged |
| `POST /api/v1/feature-flags/{id}/activate` | 400, flag unchanged |
| `POST /api/v1/feature-flags/{id}/enable` | 400, flag unchanged |
| `POST /api/v1/feature-flags/{id}/toggle` | 400, flag unchanged |
| `POST /api/v1/feature-flags/bulk-toggle`, `"action": "enable"` | 200; that flag's result has `"success": false` and the same sentence in `error`; the other flags are processed |
| `PUT` with `"is_active": false`, `/deactivate`, `/disable`, bulk `disable` | 200, still archived |
| `POST /api/v1/feature-flags/{id}/unarchive` | 200, now inactive |

Each 400 carries the detail `This flag is archived. Unarchive it before turning it on.`

### Unarchive Feature Flag (beta)
- **Endpoint**: `POST /api/v1/feature-flags/{flag_id}/unarchive`
- **Description**: Move an archived flag to inactive. It is not turned on; do that
  separately. A flag that is not archived is returned unchanged. Written to the audit
  log as `feature_flag_update` (`ARCHIVED` to `INACTIVE`).
- **Headers**: Authorization: Bearer {token}
- **Permissions**: ADMIN and DEVELOPER; ANALYST and VIEWER get 403
- **Response**: 200 OK, the flag (the same shape as `GET /api/v1/feature-flags/{flag_id}`)
- **Errors**: 403 without permission to change flags, 404 for an unknown flag

## Tracking Endpoints

All tracking endpoints use API-key authentication (`X-API-Key`) and address experiments and flags by their
public `key`. They share the per-IP `SDK_RATE_LIMIT_PER_MINUTE` ceiling (default 6000/min), except
`POST /api/v1/tracking/assign/batch`, which has its own limit of 60 requests a minute.

### Assign User to Experiment
- **Endpoint**: `POST /api/v1/tracking/assign`
- **Description**: Return the user's variant for an ACTIVE experiment. Sticky per user; bandit experiments
  route new users by the current `BanditState` weights. Every call for an enrolled user records a view
  event (the user saw the experiment): the first call and every later sticky call alike.
- **Eligibility**: a new user is first checked against the global holdout, the experiment's mutual
  exclusion group and its targeting rules (evaluated against `context`). An ineligible user still gets
  200 OK with the control variant, `assigned: false` and `reason` set to `holdout`, `mutual_exclusion` or
  `targeting`; nothing is recorded for them. A user who already has an assignment keeps it.
- **Headers**: X-API-Key: {api_key}
- **Body**: `{"experiment_key": string, "user_id": string, "context": object?}`
- **Response**: 200 OK
  ```json
  {
    "experiment_key": "string",
    "user_id": "string",
    "variant_id": "uuid",
    "variant_name": "string",
    "is_control": false,
    "configuration": {},
    "assigned": true,
    "reason": "assigned"
  }
  ```
  `assigned` is `false` when the user was not enrolled; `reason` is `assigned`, `holdout`,
  `mutual_exclusion` or `targeting`.
- **Errors**: 404 when no ACTIVE experiment has that key

### Assign a List of Users to an Experiment (beta)
- **Endpoint**: `POST /api/v1/tracking/assign/batch`
- **Description**: Assign up to 1,000 users to an ACTIVE experiment in one request. Each user gets
  what `POST /api/v1/tracking/assign` would give them, with the bandit weights read at the start of
  the request: the same eligibility checks for a new user (global holdout, mutual exclusion group,
  targeting rules against that user's `context`) and the same sticky answer for a user already
  assigned. Users are processed in the order sent, and each new assignment is saved on its own.
  Only assignments are recorded: the user's first `POST /api/v1/tracking/assign` (from an SDK, when
  they actually see the experiment) records the view. Assigned users count in the experiment's
  results from the moment they are assigned, and for a bandit experiment they count as pulls.
  See [Assign a customer list to an experiment](../guides/assign-customer-list.md).
- **Headers**: `X-API-Key: {api_key}`, a key with the `sdk:ruleset` scope whose owner is an ADMIN,
  a DEVELOPER or a superuser. That scope also lets the key download every feature flag's targeting
  rules (`GET /api/v1/sdk/ruleset`), so keep the key on a server; see
  [Scopes](../security/api-keys.md#scopes).
- **Body**: `{"experiment_key": string, "users": [{"user_id": string, "context": object?}]}`
  - `users`: 1 to 1,000 entries; each `user_id` 1 to 255 characters and different from every other
    in the request.
  - Unknown fields are refused, in the body and in each user.
- **Response**: 200 OK
  ```json
  {
    "experiment_key": "spring-email",
    "variants": {
      "7b0a1a2e-4c3d-4f5e-8a9b-0c1d2e3f4a5b": {"name": "control", "is_control": true, "configuration": {"subject": "Spring sale"}},
      "c41f9e10-2b7a-4d8e-9f01-3a5b6c7d8e9f": {"name": "urgent", "is_control": false, "configuration": {"subject": "48 hours left"}}
    },
    "assignments": [
      {"user_id": "cust-001", "variant_id": "c41f9e10-2b7a-4d8e-9f01-3a5b6c7d8e9f", "assigned": true, "reason": "assigned"},
      {"user_id": "cust-002", "variant_id": "7b0a1a2e-4c3d-4f5e-8a9b-0c1d2e3f4a5b", "assigned": false, "reason": "holdout"}
    ],
    "counts": {"assigned": 1, "holdout": 1, "mutual_exclusion": 0, "targeting": 0}
  }
  ```
  `assignments` is in request order, one entry per user. `assigned: false` means the user was not
  enrolled and nothing was recorded for them; `variant_id` is then the control, the experience to
  show them, and `reason` says why: `holdout` (the user is in the global holdout),
  `mutual_exclusion` (the user is enrolled in, or hashed to, another experiment of the same mutual
  exclusion group) or `targeting` (the user's `context` does not match the experiment's targeting
  rules). `counts` always has all four keys.
- **Errors**: see the table below. A 409 or a 500 may follow partial assignment: the users before the
  failure are assigned. Send the same request again; that is safe, because assignments are sticky.
  Any other 4xx assigns nobody.
- **Rate limit**: 60 requests a minute per client address, counted separately from the other
  tracking routes (60 × 1,000 = 60,000 users a minute). Over it the API answers 429 with
  `Retry-After: 60`; wait that long before sending again.

| Status | When | `detail` |
|---|---|---|
| 401 | no key | `API key missing` |
| 401 | an unknown, expired or revoked key | `Invalid API Key` |
| 403 | the key lacks the scope | `This API key does not have the 'sdk:ruleset' scope. Create a key with the 'sdk:ruleset' scope for server-side SDK use.` |
| 403 | the key's owner is no longer an active ADMIN, DEVELOPER or superuser | `This key's owner can no longer change feature flags or experiments, so the key is refused for server-side SDK use.` |
| 404 | no ACTIVE experiment has that key | `Active experiment with key 'spring-email' not found` |
| 409 | the experiment was paused, completed or deleted (or its variants changed) during the request | `The experiment changed during the request. Users earlier in the list may already be assigned; resending the same request is safe.` |
| 422 | `users` is empty | loc `["body","users"]`, msg `List should have at least 1 item after validation, not 0` |
| 422 | more than 1,000 users | loc `["body","users"]`, msg `at most 1,000 users per request; split the list` |
| 422 | a `user_id` appears twice | loc `["body","users",4,"user_id"]`, msg `duplicate user_id; each user may appear once per request (first seen at users[1])` |
| 422 | a `user_id` empty or over 255 characters, an unknown field, or text the database cannot store | pydantic's message at the field's loc |
| 429 | over 60 requests a minute | `Too Many Requests. Please slow down and retry after a moment.`, with `Retry-After` |
| 500 | anything else | `Could not assign the users to the experiment (request ID: <id>).` |

A 422 names positions and fields, never the ids that were sent.

### Track Event
- **Endpoint**: `POST /api/v1/tracking/track`
- **Description**: Record one event. `experiment_key` and `feature_flag_key` are both optional.
  An event with no key is stored as history and counts in no experiment's results; tag outcome
  events. A key that is given but not found answers 404.
  `event_type` is free text (SDKs send the event name); `event_name` defaults to `event_type`. Metrics count
  events by `event_name`: a metric with `event_name: "purchase"` counts every `purchase` event.
- **Headers**: X-API-Key: {api_key}
- **Body**: `{"event_type": string, "event_name": string?, "user_id": string, "experiment_key": string?, "feature_flag_key": string?, "value": number?, "metadata": object?, "timestamp": datetime?}`
- **Response**: 200 OK (the stored event); 404 a key that was given was not found; 422 invalid body

### Batch Track Events
- **Endpoint**: `POST /api/v1/tracking/batch`
- **Description**: Record up to 100 events (same shape as `/track`) in one request. An entry with no
  key is stored as history, not refused; an entry whose key is not found is reported in `errors`.
- **Response**: 200 OK `{"success_count": int, "failure_count": int, "errors": [...]|null}`; 413 above 100 events

### Track Event by Ids
- **Endpoint**: `POST /api/v1/tracking/events`
- **Description**: Same as `/track` but keyed by internal ids (`experiment_id`, `variant_id`, `feature_flag_id`);
  `event_name` is required. Used by server-side integrations and seeding tools.
- **Headers**: X-API-Key: {api_key}
- **Response**: 200 OK (the stored event); 404 an id names no stored row, and nothing is stored: the detail names
  each such field, for example `No experiment has that experiment_id.`; 422 invalid body, or an id that is not a UUID

### Get User Assignments
- **Endpoint**: `GET /api/v1/tracking/assignments/{user_id}`
- **Description**: Get user's experiment assignments
- **Headers**: X-API-Key: {api_key}
- **Path Parameters**:
  - user_id: string
- **Query Parameters**:
  - active_only: boolean (default: true)
- **Response**: 200 OK
  ```json
  [
    {
      "experiment_id": "string",
      "variant_id": "string",
      "assignment_date": "datetime"
    }
  ]
  ```

## Admin Endpoints

### List Users (Admin)
- **Endpoint**: `GET /api/v1/admin/users`
- **Description**: List all users, newest first (superuser only)
- **Headers**: Authorization: Bearer {token}
- **Query Parameters**:
  - skip: int (default: 0)
  - limit: int (default: 100, max: 100)
  - search: string (optional, at most 100 characters). Lists only the users
    whose username, email, first name or last name contains the term, ignoring
    letter case. The term is matched literally: `%`, `_` and `\` are ordinary
    characters, not wildcards. Leading and trailing spaces are ignored, and an
    empty or all-space term lists every user. `total` counts the matching
    users, so `skip`/`limit` page through the matches. A term matching nothing
    answers 200 with `"items": []` and `"total": 0`. Each column is matched
    on its own, so `Jane Smith` does not match a first name `Jane` and last
    name `Smith`; search for either part.
- **Errors**: 422 when `search` is longer than 100 characters or contains a
  NUL character.
- **Response**: 200 OK
  ```json
  {
    "items": [
      {
        "id": "string",
        "username": "string",
        "email": "string",
        "full_name": "string",
        "is_active": true,
        "is_superuser": false,
        "role": "VIEWER",
        "created_at": "datetime",
        "updated_at": "datetime",
        "last_login": "datetime",
        "preferences": {}
      }
    ],
    "total": 100,
    "skip": 0,
    "limit": 100
  }
  ```
- **Fields**: `full_name` is the first and last name joined by a space (or
  whichever one is set), and `null` when neither is. `email`, `role`,
  `last_login` and `preferences` may be `null`.

### Update User (Admin)
- **Endpoint**: `PUT /api/v1/admin/users/{user_id}`
- **Description**: Update any user, including `is_superuser` (superuser only)
- **Headers**: Authorization: Bearer {token}
- **Request Body**: as Update User; `password` is treated the same way
- **Your own access**: a superuser cannot remove their own superuser access or
  deactivate their own account here; another superuser does it. The request is
  refused when it would change your own `is_superuser` or `is_active` from
  `true` to `false`, and nothing in it is written, other fields included.
  Resending the stored values (`true`) is accepted, so a client that reads the
  account and sends it back with an edit is not refused.
- **During a concurrent change**: a request that turns off another superuser's
  `is_superuser` or `is_active` first waits for any change in progress to an
  active superuser's account, then checks that you are still an active
  superuser. If another administrator has just deactivated or deleted your
  account, the answer is 400 "Inactive user"; if they have just removed your
  superuser access, 403 "Not enough permissions". Nothing is written either
  way. The wait is at most 5 seconds; a request that would wait longer answers
  500 and writes nothing.
- **Audit log**: a change to `is_superuser` is recorded as `role_assign`, with
  the role and superuser flag before and after, and a change to `is_active` as
  `user_deactivate` or `user_activate`, in the same transaction as the change.
  If the entry cannot be written, nothing is saved.
- **Response**: 200 OK, the user
- **Errors**: 400 "You can't remove your own superuser access. Ask another
  administrator to do it." when the request would turn off your own
  `is_superuser`. 400 "You can't deactivate your own account." when it would
  turn off your own `is_active`; when both would change, the answer is the
  first. 404 "User not found". 409 "Email already registered" when the
  request sets an email address that another account holds in any letter
  case. Changing only the letter case of the account's own address is
  accepted, and resending the stored address unchanged is never refused.
  409 "Username already registered" when the request sets a username another
  account has.

### Change a User's Role or Active Status (Admin)
- **Endpoint**: `PATCH /api/v1/admin/users/{user_id}`
- **Stability**: beta (`x-stability: beta`); the shape may still change.
- **Description**: Change another account's role, its active status, or both
  (superuser only). This is what the dashboard's Edit user dialog calls.
- **Headers**: Authorization: Bearer {token}
- **Request Body**: only the keys to change, at least one of them:
  ```json
  {
    "role": "ANALYST",
    "is_active": false
  }
  ```
  - `role`: `ADMIN`, `DEVELOPER`, `ANALYST` or `VIEWER`, in any letter case.
  - `is_active`: `false` deactivates the account, `true` reactivates it.
  - `null` is refused, and so is any other key (`is_superuser`, `username`,
    `password`, ...): 422. Use `PUT` above for those.
- **Response**: 200 OK, the user. Sending the values the account already has
  changes nothing and still answers 200.
- **Deactivating a user**: they can no longer sign in, requests with a token
  they already hold are refused, and **the API keys they created stop
  working, including keys your applications use**. Check which keys a user
  created before deactivating them.
- **During a concurrent change**: deactivating an account that is a superuser
  first waits for any change in progress to an active superuser's account,
  then checks that you are still an active superuser. If another administrator
  has just deactivated or deleted your account, the answer is 400 "Inactive
  user"; if they have just removed your superuser access, 403 "Not enough
  permissions". Nothing is written either way. The wait is at most 5 seconds;
  a request that would wait longer answers 500 and writes nothing.
- **Errors**:
  - 400 "You can't change your own role. Ask another administrator to do it."
  - 400 "You can't deactivate your own account."
  - 400 "Inactive user" when your own account was deactivated or deleted
    while the request was in flight.
  - 403 "Not enough permissions" for an account that is not a superuser,
    whatever its role, including one whose superuser access was removed
    while the request was in flight.
  - 404 "User not found".
  - 409 "Roles on this deployment come from Cognito groups and are updated on
    every request. Change this user's group in Cognito instead." when
    `AUTH_PROVIDER=cognito` and `SYNC_ROLES_ON_LOGIN` is on (the default) and
    the request changes `role`. Changing `is_active` is still accepted there.
  - 422 for a body that is empty, has an unknown key, a `null`, or a role
    outside the four above.
- Every change is recorded in the audit log, in the same transaction as the
  change: a role change as `role_assign`, with the role and superuser flag
  before and after, and an active-status change as `user_deactivate` or
  `user_activate`. If the entry cannot be written, nothing is saved.

### Delete User (Admin)
- **Endpoint**: `DELETE /api/v1/admin/users/{user_id}`
- **Description**: Delete user (superuser only)
- **Headers**: Authorization: Bearer {token}
- **Path Parameters**:
  - user_id: string (UUID)
- **During a concurrent change**: deleting an account that is an active
  superuser first waits for any change in progress to an active superuser's
  account, then checks that you are still an active superuser. If another
  administrator has just deactivated or deleted your account, the answer is
  400 "Inactive user"; if they have just removed your superuser access, 403
  "Not enough permissions". Nothing is written either way. The wait is at most
  5 seconds; a request that would wait longer answers 500 and writes nothing.
- **Response**: 204 No Content
- **Errors**: 400 "Cannot delete your own user account" when the account is
  your own. 404 "User not found".

## Error Responses

All endpoints may return the following error responses:

### 400 Bad Request
```json
{
  "detail": "Error message"
}
```

### 401 Unauthorized
```json
{
  "detail": "Could not validate credentials"
}
```

### 403 Forbidden
```json
{
  "detail": "Not enough permissions"
}
```

### 404 Not Found
```json
{
  "detail": "Resource not found"
}
```

### 500 Internal Server Error

The SDK routes that store data answer a failure to store it with JSON: a fixed sentence
followed by the request ID, never the error itself.

```json
{
  "detail": "Could not store the event (request ID: 3f2c9a7e-5b1d-4c8e-9f0a-6d2b1e4c7a90)."
}
```

| Route | `detail` |
|---|---|
| `POST /api/v1/tracking/assign` | `Could not assign the user to the experiment (request ID: <id>).` |
| `POST /api/v1/tracking/assign/batch` | `Could not assign the users to the experiment (request ID: <id>).` |
| `POST /api/v1/tracking/track`, `POST /api/v1/tracking/events` | `Could not store the event (request ID: <id>).` |
| `POST /api/v1/tracking/errors` | `Could not store the error report (request ID: <id>).` |
| `POST /api/v1/tracking/errors/batch` (the whole batch) | `Could not store the error reports (request ID: <id>).` |

The ID is the response's `X-Request-ID`. When that value is not 1 to 128 characters of
`A-Z a-z 0-9 . _ : -`, it is left out and the sentence simply ends: `Could not store the event.`

The two batch routes answer 200 and list each item they could not store in `errors`. An item
refused for its own content (an unknown key, an invalid event) keeps the message saying why; an
item the server failed to store has `error` set to `Could not store this event (request ID: <id>).`
(`/tracking/batch`) or `Could not store this error report (request ID: <id>).`
(`/tracking/errors/batch`).

Any other unhandled error answers with a plain-text body, not JSON:

```text
Internal Server Error
```

It carries the usual CORS headers, so a dashboard on another origin can read it, and an
`X-Request-ID` header: search the API log for that id to find the traceback. The body never
includes the error's details.

## Error Handling Examples

### 1. Authentication Errors

Invalid credentials:

```bash
curl -X POST "http://localhost:8000/api/v1/auth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=wrong@example.com&password=wrong_password"
```

Response (401 Unauthorized):

```json
{
  "detail": "Incorrect username or password"
}
```

Expired token:

```bash
curl -X GET "http://localhost:8000/api/v1/users/me" \
  -H "Authorization: Bearer expired_token"
```

Response (401 Unauthorized):

```json
{
  "detail": "Token has expired"
}
```

### 2. Validation Errors

Invalid experiment creation:

```bash
curl -X POST "http://localhost:8000/api/v1/experiments/" \
  -H "Authorization: Bearer your_access_token" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "",
    "experiment_type": "INVALID_TYPE"
  }'
```

Both fields are invalid on purpose: `name` is empty and `experiment_type` is not a type.

Response (422 Unprocessable Entity):

```json
{
  "detail": [
    {
      "loc": ["body", "name"],
      "msg": "name cannot be empty",
      "type": "value_error"
    },
    {
      "loc": ["body", "experiment_type"],
      "msg": "invalid experiment type",
      "type": "value_error"
    }
  ]
}
```

### 3. Rate Limiting

Too many requests:

```bash
curl -X GET "http://localhost:8000/api/v1/experiments/" \
  -H "Authorization: Bearer your_access_token"
```

Response (429 Too Many Requests):

```json
{
  "detail": "Too Many Requests. Please slow down and retry after a moment."
}
```

## Targeting Rules and Experiment Types

### Targeting Rules

`targeting_rules` uses the shape the dashboard's rule builder writes: groups of
conditions, each condition an `attribute`, an `operator` and a `value`.

```json
{
  "logical_operator": "OR",
  "groups": [
    {
      "logical_operator": "AND",
      "conditions": [
        {"attribute": "country", "operator": "in", "value": ["US", "CA"]},
        {"attribute": "device_type", "operator": "equals", "value": "mobile"}
      ]
    },
    {
      "logical_operator": "AND",
      "conditions": [
        {"attribute": "plan", "operator": "in", "value": ["premium", "beta"]}
      ]
    }
  ]
}
```

- `logical_operator` is `AND`, `OR` or `NOT` (any case), at the top level and
  on each group. Left out, it is `AND`.
- The operators are `equals`, `not_equals`, `contains`, `not_contains`,
  `starts_with`, `ends_with`, `greater_than`, `less_than`,
  `greater_than_or_equal`, `less_than_or_equal`, `in`, `not_in`, `regex`,
  `is_null`, `is_not_null`, `semver_eq`, `semver_gt`, `semver_lt`,
  `semver_gte`, `semver_lte`, `geo_within_radius`, `time_window`,
  `array_contains`, `array_intersects`, `in_segment` and `not_in_segment`
  (below).
- An experiment's rules may carry a top-level `rollout_percentage`, a number
  from 0 to 100: that share of the users who match is admitted. Which users
  is decided by the rules' top-level `id` (text, at most 100 characters):
  two rules with the same `id` and percentage admit the same users.
- When rules with a `rollout_percentage` below 100 and no `id` are stored on
  an experiment that is started for the first time (from `draft`, by
  `POST /start` or by its scheduled `start_date`), the experiment's own id is
  stored as their `id`, so each experiment admits its own share of users.
  The same happens when such rules are saved on a `paused` experiment whose
  stored rules admitted everyone they matched. A `PUT` whose rules have no
  `id` keeps the stored one. An `id` you send is never replaced, and
  resuming a `paused` experiment changes nothing: an experiment started
  without an `id` before this behaviour existed keeps admitting the users it
  admitted then. Cloning an experiment drops an `id` equal to the source
  experiment's own id, so the clone is given its own when it first starts;
  any other `id` is copied.
- `null`, `{}` and `{"groups": []}` mean no targeting: every user is eligible.

**`in_segment`, `not_in_segment`.** `{"attribute": "segment", "operator": "in_segment", "value": "<segment id>"}`.
One segment per condition; to match any of several, put one condition per segment in an `OR`
group. A ruleset can use at most 10 different segments. A user is a member of an ID-list segment
when the user the flag or experiment is evaluated for (the request's `user_id`) is in its list,
and of a rules segment when the attributes sent with the request match its rules; in a segment's
rules, `user_id` is that same user, whatever the context says. Membership is decided by the
server from its own records: nothing in the context you send makes a user a member. A condition
on the attribute `segment` with any other operator, such as `equals`, compares the context value
as before. Saving rules that name a segment that is unknown, inactive or archived, or whose rules
are not valid, answers 422, and a segment condition in a native `default_rule` (returned without
its conditions being evaluated) is refused. When the server cannot decide a user's membership of
a segment the rules name (a flag unarchived after its segment was archived, a segment rule whose
pattern cannot be evaluated for this context), it does not guess: the flag answers
`enabled: false` with `reason: "error"` and the experiment does not enrol the user
(`reason: "targeting"`), whichever of the two operators the condition uses. Flags that use a
segment are always evaluated by the server, never by an SDK's local evaluation.
A segment condition requires nothing from the context. A user who lacks an attribute is not
refused outright: on experiments, as on flags, they fail only the conditions on that attribute
(`is_null` passes), so another `OR` branch can still enrol them, and they match a `NOT` group on
that attribute (a user with no `country` matches `NOT (country equals US)`, but not
`country not_equals US`). Users already assigned to an experiment keep their assignment.

See [Segments](../guides/segments.md#target-a-flag-or-an-experiment-at-a-segment).

`POST /api/v1/experiments/` and `PUT /api/v1/experiments/{experiment_id}` answer
422 for experiment rules that would not be applied as written: a list of rules, a flat object such as
`{"country": ["US"]}`, an unknown key, `groups` together with `rules`,
`logical_operator` without `groups`, a group with no conditions, an unknown
operator or logical operator, a value the operator cannot use, and a list
operator with more than 1,000 values. The message names the place, for example
`groups[0].conditions[1].operator: unknown operator`, and never repeats the
submitted value.

Cloning an experiment copies its stored rules as they are, without this check,
so an experiment created before the check keeps rules it would now refuse. The
one exception is a segment: a clone whose rules name a segment that is not
active, or whose rules are not valid, answers 409 and creates nothing.

`POST /api/v1/feature-flags/` and `PUT /api/v1/feature-flags/{flag_id}` answer
422 for flag rules on the same terms. A flag's rules are also refused for a
top-level `name`, and for native rules without `rules` (a `default_rule` on its
own, which the flag evaluator does not read). A problem with the rules as a
whole reads `targeting rules: <reason>`, for example `targeting rules: unknown
key`. A flag's stored rules are not re-checked and are evaluated as before, but
a `PUT` that sends back stored rules the API now refuses answers 422; leave
`targeting_rules` out of the request instead.
`python -m backend.scripts.check_targeting_rules` lists the flags whose stored
rules are refused. See
[Add targeting rules](../feature-flags/create.md#add-targeting-rules).

An experiment's targeting can be changed only while it is `draft` or `paused`,
whatever the caller's role, superusers included:

- `draft`: `targeting_rules` may be sent with any other field.
- `paused`: `targeting_rules` must be the only field in the request; together
  with anything else the request is refused with 400.
- `active`, `completed`, `archived`: any request that includes
  `targeting_rules` is refused with 400, even when the value equals the stored
  one. The detail names the state, for example `Targeting can be changed only
  while the experiment is draft or paused; it is active.` Pause the experiment,
  change the targeting, then start it again.

People already assigned keep their variant. The new rules decide for everyone
not yet in the experiment, including people turned away before the change,
once the experiment is started again.

### Updating an experiment

Every field of `PUT /api/v1/experiments/{experiment_id}` is optional: a field
left out keeps its value. `name`, `status`, `experiment_type`,
`sequential_testing_enabled`, `optimization_type`, `correction_method` and
`confidence_level` cannot be set to `null`;
such a request is refused with 422, nothing is changed, and the message names
the field, for example `name cannot be null`. `name` is at most 100
characters, as on create. Other fields, such as `description`, may still be
sent as `null`.

A refusal because of the experiment's state is a 400 whose detail names the
state; a 403 means the caller's role may not update experiments, and is
decided before the state is looked at. Outside `draft`, only a superuser may
change an experiment's other fields (`Cannot update experiments in active
status`), and `variants`, `metrics`, `start_date`, `end_date`,
`correction_method` and `confidence_level` cannot be changed by anyone
(`Cannot update variants for experiments in active status`).

`schedule` is not accepted by this endpoint. A request that contains it, with
any value including `null` or `{}`, is refused with 422, nothing is changed,
and the error is on `["body", "schedule"]` with the message `schedule is not
applied by this endpoint; use PUT /api/v1/experiments/{experiment_id}/schedule`.
Schedule an experiment with `PUT /api/v1/experiments/{experiment_id}/schedule`.

### An experiment's status

An experiment's status changes only through its lifecycle endpoints, whatever
the caller's role, superusers included:

- `POST /api/v1/experiments/{experiment_id}/start`: `draft` or `paused` to
  `active`. It checks for at least two variants, a control variant and at
  least one metric, and sets `start_date` to now when it has none. A draft
  started before its scheduled `start_date` starts now, and its `start_date`
  is set to now; a scheduled `end_date` is kept. An experiment with no
  `start_date` whose `end_date` has passed is refused with 400 and nothing is
  changed; set a later `end_date`, or clear it with `null`, through
  `PUT /api/v1/experiments/{experiment_id}/schedule` and start it again.
- `POST /api/v1/experiments/{experiment_id}/pause`: `active` to `paused`.
- `POST /api/v1/experiments/{experiment_id}/complete`: `active` or `paused` to
  `completed`, and sets `end_date` to now. An experiment that an earlier
  version started before its scheduled start can still have a `start_date`
  after now; complete sets it to one microsecond before the new `end_date`.
- `POST /api/v1/experiments/{experiment_id}/archive`: any status but
  `archived` to `archived`.

`PUT /api/v1/experiments/{experiment_id}` does not change it. A `status` equal
to the current one is accepted and changes nothing, so an experiment fetched
with `GET` can be sent back as it is. Any other value is refused with 422,
nothing is changed, and the error is on `["body", "status"]` with the message
`status changes through POST /api/v1/experiments/{id}/start, /pause, /complete
or /archive; it cannot be set by an update.`

`POST /api/v1/experiments/` always creates a `draft`. `status` may be left out
or sent as `"draft"`; any other value is refused with 422 and nothing is
created.

### Experiment Types

#### 1. A/B Testing
```json
{
  "experiment_type": "AB_TEST",
  "variants": [
    {
      "id": "control",
      "name": "Control",
      "weight": 0.5
    },
    {
      "id": "treatment",
      "name": "Treatment",
      "weight": 0.5
    }
  ]
}
```

#### 2. Multivariate Testing
```json
{
  "experiment_type": "MULTIVARIATE",
  "factors": [
    {
      "name": "button_color",
      "levels": ["red", "blue", "green"]
    },
    {
      "name": "button_size",
      "levels": ["small", "medium", "large"]
    }
  ],
  "design": "FULL_FACTORIAL"
}
```

#### 3. Feature Flag
```json
{
  "experiment_type": "FEATURE_FLAG",
  "default_value": false,
  "overrides": [
    {
      "user_id": "user1",
      "value": true
    },
    {
      "user_segment": "beta_users",
      "value": true
    }
  ]
}
```

## SDK Usage

### Python SDK

#### Installation

The `experimently` package is on PyPI (0.1.0, beta). The [Python SDK](../sdk/python.md#installation)
page also shows how to install it from this repository.

```bash
pip install experimently==0.1.0
```

#### Basic Usage
```python
from experimentation import ExperimentationClient

# Initialize client
client = ExperimentationClient(
    api_key="your_api_key",
    base_url="http://localhost:8000"
)

# Get feature flags for a user
flags = client.get_user_feature_flags(
    user_id="user123",
    context={
        "country": "US",
        "browser": "chrome"
    }
)

# Track an event
client.track_event(
    event_type="PURCHASE",
    user_id="user123",
    experiment_id="exp456",
    variant_id="var789",
    value=99.99,
    metadata={
        "product_id": "ABC123",
        "payment_method": "credit_card"
    }
)

# Get experiment assignments
assignments = client.get_user_assignments(
    user_id="user123",
    active_only=True
)
```

### JavaScript SDK

#### Installation

The `@getexperimently/js-sdk` package is on npm (0.1.0, beta). The
[JavaScript SDK](../sdk/javascript.md#installation) page also shows how to build and install it
from this repository.

```bash
npm install @getexperimently/js-sdk@0.1.0
```

#### Basic Usage
```javascript
import { ExperimentationClient } from '@getexperimently/js-sdk';

// Initialize client
const client = new ExperimentationClient({
  apiKey: 'your_api_key',
  baseUrl: 'http://localhost:8000'
});

// Get feature flags for a user
const flags = await client.getUserFeatureFlags('user123', {
  context: {
    country: 'US',
    browser: 'chrome'
  }
});

// Track an event
await client.trackEvent({
  eventType: 'PURCHASE',
  userId: 'user123',
  experimentId: 'exp456',
  variantId: 'var789',
  value: 99.99,
  metadata: {
    productId: 'ABC123',
    paymentMethod: 'credit_card'
  }
});

// Get experiment assignments
const assignments = await client.getUserAssignments('user123', {
  activeOnly: true
});
```

### SDK Features

#### 1. Automatic Caching
```python
# Python
client = ExperimentationClient(
    api_key="your_api_key",
    cache_ttl=3600  # Cache for 1 hour
)

# JavaScript
const client = new ExperimentationClient({
  apiKey: 'your_api_key',
  cacheTTL: 3600  // Cache for 1 hour
});
```

#### 2. Error Handling
```python
# Python
try:
    flags = client.get_user_feature_flags("user123")
except ExperimentationError as e:
    if e.code == "RATE_LIMIT":
        # Handle rate limiting
    elif e.code == "INVALID_API_KEY":
        # Handle invalid API key
```

```javascript
// JavaScript
try {
  const flags = await client.getUserFeatureFlags('user123');
} catch (error) {
  if (error.code === 'RATE_LIMIT') {
    // Handle rate limiting
  } else if (error.code === 'INVALID_API_KEY') {
    // Handle invalid API key
  }
}
```

#### 3. Batch Operations
```python
# Python
client.track_events([
    {
        "event_type": "PURCHASE",
        "user_id": "user1",
        "value": 99.99
    },
    {
        "event_type": "PURCHASE",
        "user_id": "user2",
        "value": 149.99
    }
])
```

```javascript
// JavaScript
await client.trackEvents([
  {
    eventType: 'PURCHASE',
    userId: 'user1',
    value: 99.99
  },
  {
    eventType: 'PURCHASE',
    userId: 'user2',
    value: 149.99
  }
]);
```

## Framework Integration Examples

### React Integration

#### 1. Using React Hook
```typescript
// hooks/useExperimentation.ts
import { useState, useEffect } from 'react';
import { ExperimentationClient } from '@getexperimently/js-sdk';

const client = new ExperimentationClient({
  apiKey: process.env.REACT_APP_API_KEY,
  baseUrl: process.env.REACT_APP_API_URL
});

export function useExperimentation(userId: string) {
  const [flags, setFlags] = useState<Record<string, boolean>>({});
  const [assignments, setAssignments] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    async function loadData() {
      try {
        const [flagsData, assignmentsData] = await Promise.all([
          client.getUserFeatureFlags(userId, {
            context: {
              browser: navigator.userAgent,
              screenSize: `${window.innerWidth}x${window.innerHeight}`
            }
          }),
          client.getUserAssignments(userId, { activeOnly: true })
        ]);
        setFlags(flagsData);
        setAssignments(assignmentsData);
      } catch (err) {
        setError(err as Error);
      } finally {
        setLoading(false);
      }
    }

    loadData();
  }, [userId]);

  return { flags, assignments, loading, error };
}

// Usage in component
function MyComponent({ userId }: { userId: string }) {
  const { flags, assignments, loading, error } = useExperimentation(userId);

  if (loading) return <div>Loading...</div>;
  if (error) return <div>Error: {error.message}</div>;

  return (
    <div>
      {flags.newFeature && <NewFeatureComponent />}
      {assignments.map(assignment => (
        <ExperimentVariant key={assignment.experiment_id} variant={assignment.variant_id}>
          {/* Variant content */}
        </ExperimentVariant>
      ))}
    </div>
  );
}
```

#### 2. Using Context Provider
```typescript
// contexts/ExperimentationContext.tsx
import React, { createContext, useContext, useEffect, useState } from 'react';
import { ExperimentationClient } from '@getexperimently/js-sdk';

interface ExperimentationContextType {
  flags: Record<string, boolean>;
  assignments: any[];
  trackEvent: (eventType: string, value?: number, metadata?: any) => Promise<void>;
}

const ExperimentationContext = createContext<ExperimentationContextType | null>(null);

export function ExperimentationProvider({
  children,
  userId,
  apiKey
}: {
  children: React.ReactNode;
  userId: string;
  apiKey: string;
}) {
  const client = new ExperimentationClient({ apiKey });
  const [flags, setFlags] = useState<Record<string, boolean>>({});
  const [assignments, setAssignments] = useState<any[]>([]);

  useEffect(() => {
    // Load initial data
    loadExperimentationData();
  }, [userId]);

  async function loadExperimentationData() {
    try {
      const [flagsData, assignmentsData] = await Promise.all([
        client.getUserFeatureFlags(userId),
        client.getUserAssignments(userId)
      ]);
      setFlags(flagsData);
      setAssignments(assignmentsData);
    } catch (error) {
      console.error('Failed to load experimentation data:', error);
    }
  }

  async function trackEvent(eventType: string, value?: number, metadata?: any) {
    try {
      await client.trackEvent({
        eventType,
        userId,
        value,
        metadata
      });
    } catch (error) {
      console.error('Failed to track event:', error);
    }
  }

  return (
    <ExperimentationContext.Provider value={{ flags, assignments, trackEvent }}>
      {children}
    </ExperimentationContext.Provider>
  );
}

export function useExperimentationContext() {
  const context = useContext(ExperimentationContext);
  if (!context) {
    throw new Error('useExperimentationContext must be used within ExperimentationProvider');
  }
  return context;
}

// Usage in app
function App() {
  return (
    <ExperimentationProvider userId="user123" apiKey="your_api_key">
      <MyApp />
    </ExperimentationProvider>
  );
}
```

### Node.js Integration

#### 1. Express.js Middleware
```typescript
// middleware/experimentation.ts
import { ExperimentationClient } from '@getexperimently/js-sdk';

const client = new ExperimentationClient({
  apiKey: process.env.API_KEY,
  baseUrl: process.env.API_URL
});

export function experimentationMiddleware() {
  return async (req: any, res: any, next: any) => {
    try {
      const userId = req.user?.id || req.headers['x-user-id'];
      if (!userId) {
        return next();
      }

      const [flags, assignments] = await Promise.all([
        client.getUserFeatureFlags(userId, {
          context: {
            ip: req.ip,
            userAgent: req.headers['user-agent']
          }
        }),
        client.getUserAssignments(userId)
      ]);

      // Attach to request object
      req.experimentation = {
        flags,
        assignments,
        trackEvent: async (eventType: string, value?: number, metadata?: any) => {
          await client.trackEvent({
            eventType,
            userId,
            value,
            metadata: {
              ...metadata,
              path: req.path,
              method: req.method
            }
          });
        }
      };

      next();
    } catch (error) {
      console.error('Experimentation middleware error:', error);
      next();
    }
  };
}

// Usage in Express app
import express from 'express';
import { experimentationMiddleware } from './middleware/experimentation';

const app = express();

app.use(experimentationMiddleware());

app.get('/api/products', async (req, res) => {
  const { flags, trackEvent } = req.experimentation;

  // Use feature flags
  if (flags.newPricingModel) {
    // New pricing logic
  }

  // Track events
  await trackEvent('VIEW_PRODUCTS', undefined, {
    category: 'electronics'
  });

  res.json({ /* products */ });
});
```

#### 2. NestJS Integration
```typescript
// experimentation.module.ts
import { Module } from '@nestjs/common';
import { ExperimentationService } from './experimentation.service';
import { ExperimentationController } from './experimentation.controller';

@Module({
  providers: [ExperimentationService],
  controllers: [ExperimentationController],
  exports: [ExperimentationService]
})
export class ExperimentationModule {}

// experimentation.service.ts
import { Injectable } from '@nestjs/common';
import { ExperimentationClient } from '@getexperimently/js-sdk';

@Injectable()
export class ExperimentationService {
  private client: ExperimentationClient;

  constructor() {
    this.client = new ExperimentationClient({
      apiKey: process.env.API_KEY,
      baseUrl: process.env.API_URL
    });
  }

  async getUserFlags(userId: string, context?: any) {
    return this.client.getUserFeatureFlags(userId, { context });
  }

  async getUserAssignments(userId: string) {
    return this.client.getUserAssignments(userId);
  }

  async trackEvent(eventType: string, userId: string, value?: number, metadata?: any) {
    return this.client.trackEvent({
      eventType,
      userId,
      value,
      metadata
    });
  }
}

// experimentation.controller.ts
import { Controller, Get, Post, Body, Param, UseGuards } from '@nestjs/common';
import { ExperimentationService } from './experimentation.service';
import { AuthGuard } from '@nestjs/passport';

@Controller('experimentation')
@UseGuards(AuthGuard('jwt'))
export class ExperimentationController {
  constructor(private experimentationService: ExperimentationService) {}

  @Get('flags/:userId')
  async getUserFlags(@Param('userId') userId: string) {
    return this.experimentationService.getUserFlags(userId);
  }

  @Post('events')
  async trackEvent(
    @Body() body: {
      eventType: string;
      userId: string;
      value?: number;
      metadata?: any;
    }
  ) {
    return this.experimentationService.trackEvent(
      body.eventType,
      body.userId,
      body.value,
      body.metadata
    );
  }
}
```

#### 3. Next.js API Routes
```typescript
// pages/api/experimentation/flags.ts
import { NextApiRequest, NextApiResponse } from 'next';
import { ExperimentationClient } from '@getexperimently/js-sdk';

const client = new ExperimentationClient({
  apiKey: process.env.API_KEY,
  baseUrl: process.env.API_URL
});

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== 'GET') {
    return res.status(405).json({ message: 'Method not allowed' });
  }

  try {
    const userId = req.query.userId as string;
    if (!userId) {
      return res.status(400).json({ message: 'userId is required' });
    }

    const flags = await client.getUserFeatureFlags(userId, {
      context: {
        userAgent: req.headers['user-agent'],
        ip: req.headers['x-forwarded-for'] || req.socket.remoteAddress
      }
    });

    res.status(200).json(flags);
  } catch (error) {
    console.error('Error fetching feature flags:', error);
    res.status(500).json({ message: 'Internal server error' });
  }
}

// pages/api/experimentation/events.ts
export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== 'POST') {
    return res.status(405).json({ message: 'Method not allowed' });
  }

  try {
    const { eventType, userId, value, metadata } = req.body;

    await client.trackEvent({
      eventType,
      userId,
      value,
      metadata: {
        ...metadata,
        path: req.headers.referer,
        userAgent: req.headers['user-agent']
      }
    });

    res.status(200).json({ message: 'Event tracked successfully' });
  } catch (error) {
    console.error('Error tracking event:', error);
    res.status(500).json({ message: 'Internal server error' });
  }
}
```

---

## Advanced Analytics Endpoints

### Sequential Testing

See [Sequential Testing Guide](sequential-testing.md) for full documentation.

```
GET /api/v1/results/{experiment_id}/sequential
```
Returns mSPRT analysis, always-valid confidence intervals, an early stopping recommendation and the advisory `at_risk` flag. `alpha_spending` is always empty: no planned-looks table is computed yet.

**Query params:** `alpha` (above 0 and at most 0.2; overrides the experiment's stored `sequential_testing_config.alpha`, default `0.05`)

`GET /api/v1/results/{experiment_id}` and `GET /api/v1/experiments/{experiment_id}/results` embed the same analysis, at the stored `alpha`, as `sequential_testing`: `null` when sequential testing is off or the analysis could not be computed, and cached with the results ([In the results response](sequential-testing.md#in-the-results-response)).

---

### Sample Size

See [Statistical Power Analysis](../statistics/power-analysis.md#during-the-experiment-the-sample-size-tab) for the method.

```text
GET /api/v1/results/{experiment_id}/sample-size
```
Returns the users each variant needs to detect a relative lift of `mde` over the baseline on the
primary metric (a two-sided two-proportion test), the smallest variant's users so far, the power
they give at that MDE, and every input used with where it came from. Nothing is saved.

**Query params** (all optional; send only what you want to change):

| Parameter | Default | Range |
|---|---|---|
| `baseline_conversion_rate` | the control variant's observed rate so far | above 0, below 1 |
| `mde` | `0.05` (relative: 12% → 12.6%) | above 0, below 1 |
| `confidence_level` | the experiment's stored `confidence_level` | 0.80 to 0.99 |
| `power_target` | `0.80` | 0.50 to 0.99 |
| `correction_method` | the experiment's stored `correction_method` | `none`, `bonferroni`, `benjamini_hochberg`; the last two plan each comparison at `alpha / (variants - 1)` |

**Response** (`SampleSizeResult`): `required_sample_size_per_variant`, `current_sample_size_per_variant`
(the smallest variant), `is_adequate`, `achieved_power`, `baseline_rate`, `baseline_source`
(`observed` or `request`), `baseline_users`, `mde`, `mde_absolute`, `confidence_level`, `alpha`
(per comparison), `comparisons`, `correction_method`, `power_target`, `metric_id`, `metric_name`,
`metric_type`, `analysed_as` (always `conversion` today), `guide_only_reasons` (why a fixed sample
size is only a guide here: `adaptive_allocation`, `unequal_allocation`, `sequential_testing`,
`bayesian`) and `unavailable_reason`. `days_to_significance` and `projected_completion_date` are always `null`.

With nothing to plan from, the answer is still **200**: `required_sample_size_per_variant`,
`achieved_power` and `baseline_rate` are `null`, and `unavailable_reason` is one of
`no_metric`, `no_control_data`, `no_control_conversions`, `rate_at_boundary` (every control user
converted), `effect_out_of_range` (the observed rate raised by `mde` reaches 100%) or
`effect_too_small` (the observed rate raised by `mde` changes too little for the size to be a
finite number). A `baseline_conversion_rate` that `mde` raises to 100% or more answers **422**,
and so does one that `mde` changes too little for the size to be a finite number; an unknown
experiment answers **404**.

---

### CUPED Variance Reduction

See [CUPED Guide](cuped.md) for full documentation.

```
GET /api/v1/results/{experiment_id}/cuped
```
Returns, for each conversion metric and each treatment, the effect against the control adjusted for each user's own events before assignment, with the variance reduction and the share of users with history. History counts only if the server received it before the user was assigned.

It takes no query parameters: the method comes from the experiment's `variance_reduction_config`, the interval from its stored `confidence_level` and `corrected_p_value` from its stored `correction_method`. A comparison that cannot be computed is listed with `unavailable_reason`.

---

### Dimensional Analysis / Segment Breakdown

See [Dimensional Analysis Guide](dimensional-analysis.md) for full documentation.

```
GET /api/v1/experiments/{experiment_id}/segmented-results/{segment_by}
```
Returns per-segment statistics with Bonferroni-corrected significance thresholds.

**Query params:** `dimension` (required), `metric_id`, `base_alpha` (default `0.05`)

---

### Multi-Armed Bandit

See [Multi-Armed Bandit Guide](multi-armed-bandit.md) for full documentation.

```
GET  /api/v1/bandit/{experiment_id}           — Current variant weights and stats
POST /api/v1/bandit/{experiment_id}/update    — Trigger weight recalculation (DEVELOPER+)
PUT  /api/v1/bandit/{experiment_id}/weights   — Override weights manually (ADMIN)
```

---

### Interaction Detection

See [Interaction Detection Guide](interaction-detection.md) for full documentation.

```
GET /api/v1/interactions/scan                  — Overlap of every pair of active experiments
GET /api/v1/interactions/{exp_a_id}/{exp_b_id} — Pairwise analysis (beta: overlap, and an interaction test on each primary metric)
```

Access: ANALYST, DEVELOPER or ADMIN (VIEWER returns 403).

---

## Platform Management Endpoints

### Mutual Exclusion Groups

See [Mutual Exclusion Groups Guide](mutual-exclusion-groups.md) for full documentation.

```
GET    /api/v1/mutual-exclusion-groups                              — List groups
POST   /api/v1/mutual-exclusion-groups                              — Create group (DEVELOPER+)
GET    /api/v1/mutual-exclusion-groups/{group_id}                   — Get group
PUT    /api/v1/mutual-exclusion-groups/{group_id}                   — Update group (DEVELOPER+)
DELETE /api/v1/mutual-exclusion-groups/{group_id}                   — Archive group (ADMIN)
POST   /api/v1/mutual-exclusion-groups/{group_id}/experiments       — Add experiment
DELETE /api/v1/mutual-exclusion-groups/{group_id}/experiments/{eid} — Remove experiment
```

---

### Global Holdout

See [Mutual Exclusion Groups Guide](mutual-exclusion-groups.md) for full documentation.

```
GET  /api/v1/holdout              — Get active holdout
GET  /api/v1/holdout/all          — List all holdouts (ADMIN)
POST /api/v1/holdout              — Create holdout (ADMIN)
PUT  /api/v1/holdout/{id}         — Update holdout (ADMIN)
GET  /api/v1/holdout/check/{uid}  — Check if user is in holdout
GET  /api/v1/holdout/{id}/results — Holdout vs everyone else for one metric (beta)
```

---

### Warehouse analysis (beta)

The full profile serves the warehouse analysis routes under
`/api/v1/warehouse/analysis`; every other path under `/api/v1/warehouse`
answers 404. Snowflake and BigQuery are available; Amazon Athena is not yet. See
[Warehouse analysis](warehouse-analytics.md).

---

### Experiment Wizard

See [Experiment Wizard Guide](../guides/experiment-wizard.md) for full documentation.

All six wizard operations are **deprecated**: the dashboard does not use them, and they
may be removed in a later release.

```
POST /api/v1/wizard/drafts              — Create draft (deprecated)
GET  /api/v1/wizard/drafts              — List my drafts (deprecated)
GET  /api/v1/wizard/drafts/{id}         — Get draft (deprecated)
PUT  /api/v1/wizard/drafts/{id}/step    — Update draft step (deprecated)
POST /api/v1/wizard/validate            — Validate step data (deprecated)
POST /api/v1/wizard/drafts/{id}/submit  — Submit → create experiment (deprecated)
```

---

### Rollout Schedules

```
POST   /api/v1/rollout-schedules                      — Create schedule
GET    /api/v1/rollout-schedules                      — List schedules
GET    /api/v1/rollout-schedules/{id}                 — Get schedule
PUT    /api/v1/rollout-schedules/{id}                 — Update schedule
DELETE /api/v1/rollout-schedules/{id}                 — Delete schedule
POST   /api/v1/rollout-schedules/{id}/activate        — Activate
POST   /api/v1/rollout-schedules/{id}/pause           — Pause
POST   /api/v1/rollout-schedules/{id}/cancel          — Cancel
POST   /api/v1/rollout-schedules/{id}/stages          — Add stage
PUT    /api/v1/rollout-schedules/stages/{stage_id}    — Update stage
DELETE /api/v1/rollout-schedules/stages/{stage_id}    — Delete stage
POST   /api/v1/rollout-schedules/stages/{stage_id}/advance — Manual advance
```

---

### Audit Logs & Bulk Toggle

See [Audit Logging Guide](audit-logging.md) for full documentation.

```
GET  /api/v1/audit-logs/                  — Query audit logs
GET  /api/v1/audit-logs/entity/{entity_type}/{entity_id}
                                          — Entries for one entity (ADMIN, ANALYST)
GET  /api/v1/audit-logs/user/{user_id}    — Entries for one actor
GET  /api/v1/audit-logs/stats             — Aggregate stats (ADMIN, ANALYST)
GET  /api/v1/audit-logs/stream            — SSE real-time stream
POST /api/v1/feature-flags/bulk-toggle    — Bulk enable/disable/archive (DEVELOPER+);
                                            enable refuses archived flags one by one
GET  /api/v1/feature-flags/{id}/history   — Flag change history
```

ADMIN and ANALYST read every audit entry; DEVELOPER and VIEWER read only their
own entries on the list, user, stream and history routes. See
[Permissions](audit-logging.md#permissions).

---

### Safety Monitoring

See [Safety Monitoring](../feature-flags/safety.md).

```
GET  /api/v1/safety/settings                              — Global settings (superuser)
POST /api/v1/safety/settings                              — Create/update global settings (superuser)
GET  /api/v1/safety/feature-flags/{flag_id}/config        — Per-flag safety config (defaults when none)
POST /api/v1/safety/feature-flags/{flag_id}/config        — Create/update per-flag config (rollback_percentage 0–100, else 422; 0 = off)
GET  /api/v1/safety/feature-flags/{flag_id}/check         — Run the safety check now
POST /api/v1/safety/feature-flags/{flag_id}/rollback      — Manual rollback (?percentage=0&reason=...; percentage 0–100, else 422; 0 = off for every user, schedule paused) (superuser)
```

---

### Audience Segments

```
POST   /api/v1/segments                  — Create segment (DEVELOPER+)
GET    /api/v1/segments                  — List segments (?status=active|inactive|archived)
GET    /api/v1/segments/{id}             — Get segment
PUT    /api/v1/segments/{id}             — Update segment (DEVELOPER+; 409: in use, below)
DELETE /api/v1/segments/{id}             — Archive segment: sets status archived (DEVELOPER+; 409: in use)
POST   /api/v1/segments/{id}/evaluate    — Is this user context a member? (409: stored rules not valid)
POST   /api/v1/segments/bulk-evaluate    — One user context against up to 50 segments
GET    /api/v1/segments/{id}/experiments — Experiments and flags whose rules mention the segment's id
POST   /api/v1/segments/{id}/preview     — Estimate the share of users the rules in the body match
POST   /api/v1/segments/{id}/members        — Add user IDs to an id_list segment (beta; DEVELOPER+)
POST   /api/v1/segments/{id}/members/remove — Remove user IDs from an id_list segment (beta; DEVELOPER+)
```

`{id}` is the segment's UUID; any other text answers 422.

A segment's `kind` is `rules` (the default: users whose attributes match its rules) or
`id_list` (users whose `user_id` is in its list; see
[below](#segments-made-from-a-list-of-user-ids-beta)). It is set on create and never
changed.

**Segment rules use the targeting rule format** that flag and experiment targeting use,
and are checked when saved:

```json
{"logical_operator": "AND",
 "groups": [{"logical_operator": "AND",
             "conditions": [{"attribute": "country", "operator": "equals", "value": "US"},
                            {"attribute": "plan", "operator": "in", "value": "pro, team"}]}]}
```

The operators are the flag operators listed under
[Add targeting rules](../feature-flags/create.md#add-targeting-rules) (`equals`, `in`,
`regex`, `semver_gte`, ...), except `in_segment` and `not_in_segment`: a segment cannot
refer to a segment. A segment needs at least one group, and every group at least
one condition. It holds at most 20 groups, 50 conditions, 10 `regex` conditions and 1,000
list values in total. `POST` and `PUT /api/v1/segments` answer 422 for anything else, with
`loc` `["body", "rules"]` and a fixed message naming the place and the reason, for example
`groups[0].conditions[0].operator: unknown operator` or `rules: unknown key`. The message
never repeats the submitted rules. Saved rules are returned exactly as sent.

A user is a member when the rules match the `user_context` sent to evaluate, evaluated as
a feature flag evaluates the same rules: `{"user": {"country": "US"}}` and
`{"user.country": "US"}` both answer a rule on `country`. `matched_rules` lists each
condition, in any group, that the context satisfies on its own, as
`"<attribute> <operator> <value>"`; it is empty when the user is not a member. A `regex`
condition that cannot be evaluated makes the user not a member.

`POST /api/v1/segments/{id}/preview` evaluates the rules in its body against the stored
contexts of up to `sample_size` assignments (10 to 10,000, default 1,000). Only assignments
that carry a context are counted, and `sample_size` in the answer is how many there were.
Assignment does not store a context today, so the answer is usually
`{"estimated_percentage": 0.0, "sample_size": 0, "matched": 0}`: there was nothing to
estimate from, which is not the same as 0%. The preview also refuses, before any query,
`regex` conditions times `sample_size` above 500 and conditions plus groups times
`sample_size` above 50,000, at `loc` `["query", "sample_size"]`.

**A segment in use cannot be archived or made inactive.** Flags and experiments target a
segment with `in_segment` / `not_in_segment` ([Targeting Rules](#targeting-rules)).
`DELETE /api/v1/segments/{id}`, and a `PUT` that sets `status` to `inactive` or `archived`,
answer 409 and change nothing while a flag that is not archived (a disabled one included), or
an experiment that is draft, active or paused, has a rule naming the segment:

```json
{"detail": {"code": "segment_in_use",
            "message": "This segment is used by 1 feature flag and 2 experiments. Remove it from their targeting rules first.",
            "feature_flags": [{"id": "...", "key": "checkout-v2", "name": "Checkout v2"}],
            "experiments": [{"id": "...", "key": "pricing-page", "name": "Pricing page", "status": "paused"}]}}
```

A stored row that mentions the segment's id but whose rules cannot be read is listed too.

#### Upgrading: segment rules

Releases before this check stored segment rules in a format of their own,
`{"operator": "and", "conditions": [{"attribute", "operator": "eq", "value"}]}`, which
nothing checked: a condition the engine did not understand was skipped, and a segment left
with no condition matched every user. That format is now refused when saved.

**Segments already stored are left as they are.** Their rules are kept and returned by
`GET` unchanged, but they are not evaluated: `POST /api/v1/segments/{id}/evaluate` answers
**409** with the detail `Segment rules not valid: ...`, and bulk-evaluate answers `false`
for that segment. The same holds for a stored segment with no groups, an empty group or an
unknown operator. A `PUT` that leaves `rules` out (to rename one, say) still succeeds.

To list them, run `python -m backend.scripts.check_targeting_rules` from the repository
root against the API's database settings. Beside its flag lines it prints one line per
segment that is not archived and whose rules are not valid,
`segment <id> <name> <place> rules not valid: <reason>`, writes nothing, and exits 0
(2 when it cannot read the database). Rewrite each listed segment's rules in the format
above with `PUT /api/v1/segments/{id}`.

No flag or experiment changes behaviour: no targeting rule can refer to a segment.

#### Segments made from a list of user IDs (beta)

Create the segment with `kind` `id_list` and no `rules`:

```json
{"name": "Enterprise pilot", "kind": "id_list"}
```

Sending `rules` with `id_list`, or leaving them out with `rules`, answers 422. The answer
carries `"kind": "id_list"` and `"rules": null`, and `GET /api/v1/segments/{id}` adds
`member_count`, how many IDs the list holds (it is `null` for a rules segment and in the
list route). A `PUT` that sends `kind`, or `rules` for an id list, answers 422; renaming one
works as for any segment.

Add and remove IDs with the member routes, which are beta (`x-stability: beta`):

```json
POST /api/v1/segments/{id}/members          {"add": ["user-123", "user-456"]}
→ 200 {"added": 2, "already_members": 0, "member_count": 2}

POST /api/v1/segments/{id}/members/remove   {"remove": ["user-123", "user-999"]}
→ 200 {"removed": 1, "not_members": 1, "member_count": 1}
```

- **Limits.** 1 to 10,000 IDs per request, each a string of 1 to 255 characters, matched
  exactly (not trimmed, not case-folded). A segment holds at most 1,000,000 IDs. Send a
  longer list in chunks of 10,000.
- **Sending the same IDs again is safe.** An ID already in the segment is counted in
  `already_members` and left alone; removing one that is not there is counted in
  `not_members`. An ID repeated within one request counts once, so `added +
  already_members` (or `removed + not_members`) is the number of distinct IDs sent.
- **Refusals.** 422 with `loc` `["body", "add"]` (or `"remove"`) and a fixed message that
  never repeats an ID: `add: at least 1 ID is required`, `add: at most 10,000 IDs per
  request`, `add[17]: an ID is 1 to 255 characters`. Any other field in the body answers
  422 (`{"ids": [...]}` is refused, not ignored). A request that would take the segment
  past 1,000,000 answers 422 `this segment would have 1,000,250 members; a segment holds at
  most 1,000,000` and adds nothing. A rules segment answers 409 `members can be added only
  to an id_list segment` (`removed only from` on remove), an archived one 409 `this
  segment is archived; its members cannot be changed`, an unknown one 404.
- **Who.** DEVELOPER and ADMIN; ANALYST and VIEWER get 403. Each change writes one
  `segment_update` audit entry with the counts, never the IDs.

`POST /api/v1/segments/{id}/evaluate` answers an id list on `user_context.user_id`: the user
is a member when it is a string in the list, and `matched_rules` is empty. A context with no
`user_id`, or a `user_id` that is not a string, is not a member. Bulk-evaluate answers the
same way. Preview takes rules, so it answers 422 for a body with none.

---

### Notifications & Alerting

See [Alerting Guide](alerting.md) for full documentation.

```
GET  /api/v1/notifications/preferences         — Get my preferences
PUT  /api/v1/notifications/preferences         — Update my preferences
GET  /api/v1/notifications/admin/preferences   — List all (ADMIN)
GET  /api/v1/notifications/delivery-log        — Delivery history (ADMIN)
POST /api/v1/notifications/test                — Send test notification (DEVELOPER+)
```

---

### AI Design & MCP

See [MCP Server Guide](../mcp-server.md) for full documentation.

```
POST /api/v1/ai/design                    — AI experiment design suggestion
POST /api/v1/ai/interpret/{experiment_id} — AI results interpretation
GET  /api/v1/ai/sample-size               — Sample size calculator
GET  /api/v1/ai/templates                 — List experiment templates
GET  /api/v1/ai/templates/{id}            — Get template
GET  /api/v1/mcp/manifest                 — MCP tool manifest (public)
```

---

### Scheduler Health

```
GET  /api/v1/scheduler/health           — Health summary for every scheduler
GET  /api/v1/scheduler/health/{name}    — Health of one scheduler
GET  /api/v1/scheduler/{name}/history   — Recent run history for one scheduler
POST /api/v1/scheduler/notify/test      — Send a test notification
```

---

### ETL / Glue Jobs

```
POST /api/v1/etl/jobs/run               — Trigger an ETL job run
GET  /api/v1/etl/jobs/{run_id}/status   — Status of one run
POST /api/v1/etl/crawler/run            — Trigger the Glue crawler
GET  /api/v1/etl/crawler/status         — Crawler status
POST /api/v1/etl/partitions/add         — Register a date's 24 hourly partitions
```

`POST /api/v1/etl/query` has been removed and answers 404.

These routes act only on the Glue names the deployment configured. Any other
name answers **404** with a fixed `detail`, and Glue is not called:

| Route | Parameter | Accepted value | Otherwise |
|---|---|---|---|
| `GET .../jobs/{run_id}/status` | `job_name` | `GLUE_ETL_JOB_NAME` or `GLUE_METRICS_JOB_NAME` | `"Unknown ETL job"` |
| `GET .../crawler/status`, `POST .../crawler/run` | `crawler_name` | `GLUE_CRAWLER_NAME`, the default when omitted | `"Unknown crawler"` |
| `POST .../partitions/add` | `database`, `table` | `GLUE_DATABASE` and `GLUE_EVENTS_TABLE` | `"Unknown Glue table"` |

`POST .../jobs/run` takes a `job_type`, not a name. A setting left empty
configures nothing, so with it empty its routes answer 404 for every name, as
does `jobs/run` for a job type whose job is unset. A run that Glue does not
have answers 404 `"Job run not found"`.

`POST .../partitions/add?database=...&table=...&date=YYYY-MM-DD` registers the
24 hourly partitions (`year`, `month`, `day`, `hour`) of that date under the
Glue table's own storage location, and answers **201** with the 24 partitions
only when Glue registered every one of them or already had it. Re-running a
date is safe: hours already registered are accepted. Otherwise:

| Status | `detail` | When |
|---|---|---|
| 404 | `"Unknown Glue table"` | `database` or `table` is not the configured pair. Glue is not called |
| 422 | `"date must be a calendar date in YYYY-MM-DD format"` | `date` is anything else, such as `2026-10`, `2026-1-01` or `2026-13-45`. Glue is not called |
| 404 | `"Glue table not found. Run the crawler first."` | the configured table is not in the Glue catalog yet |
| 500 | `"Could not read the Glue table (request ID: ...)."` | Glue refused to read the table, or the table has no storage location |
| 500 | `"Could not register the partitions (request ID: ...)."` | Glue refused to register at least one partition for a reason other than it already existing. Some hours may already be registered; fix the cause and re-run the date |

The cause of a 500 is in the server log under the request ID, not in the
response.

The API reaches Glue in the region named by `AWS_DEFAULT_REGION`, never
`AWS_REGION`. With it unset, the job, crawler and partitions routes answer
500. `GLUE_EVENTS_TABLE` must be the table the crawler creates. See
[AWS integration: Glue](../integrations/aws.md#glue-the-etl-routes).

---

### Real-time DynamoDB Counters

```
GET  /api/v1/counters/{experiment_id}              — Get experiment counters
POST /api/v1/counters/{experiment_id}/increment    — Increment counter
POST /api/v1/counters/{experiment_id}/reset        — Reset counters (ADMIN)
POST /api/v1/counters/bulk                         — Bulk counter update
```

Reset is `POST .../reset`, not `DELETE` — this page said `DELETE` for a route
that has never existed.

On the two routes that take `{experiment_id}`, the path is what is written:
the body's `experiment_id` must equal it, and a request where they disagree is
answered **400** rather than written somewhere else (#95).

`bulk` takes no `{experiment_id}` **by design**: each of its up-to-100
increments names its own experiment, so one call may span several and there is
no single experiment for the URL to name.

---

## Additional Endpoints

The following endpoints extend the core API. See the dedicated reference pages linked below for full request/response schemas, authentication requirements, and code examples.

---

### Compliance Audit Logging

See [Compliance API Reference](compliance.md) for full documentation.

ADMIN or ANALYST for the listing and the reports; ADMIN for the export.

```text
GET /api/v1/compliance/audit-events                — List audit events (paginated, filterable; every profile)
GET /api/v1/compliance/reports/soc2                — SOC 2 report, default period 365 days (compliance module)
GET /api/v1/compliance/reports/iso27001            — ISO 27001 report, default period 730 days (compliance module)
GET /api/v1/compliance/export                      — Download as JSON or CSV (ADMIN; compliance module)
```

**Query parameters for `audit-events`**: `page`, `limit`, `action`, `resource_type`, `actor_id`, `start_time`, `end_time`

**Query parameters for `export`**: `format` (`json`|`csv`), `start_time`, `end_time`

With the compliance module, each event is signed with HMAC-SHA256 and the signature is in its `hmac_signature` field; the report checks them. See [Compliance API Reference](compliance.md) for what is recorded.

---

### Third-Party Integrations

See [Integrations API Reference](integrations.md) for full documentation.

Read (the list and the get) needs the **ADMIN** or **DEVELOPER** role; create, update and delete need **ADMIN**. An ANALYST or a VIEWER is refused with `403` on every one of them. A configuration is addressed by its type (`jira`, `salesforce` or `github`), not by an id.

**Integration CRUD**:

```
POST   /api/v1/integrations                      — Create integration (ADMIN)
GET    /api/v1/integrations                      — List integrations (ADMIN or DEVELOPER)
GET    /api/v1/integrations/{integration_type}   — Get integration details (ADMIN or DEVELOPER)
PUT    /api/v1/integrations/{integration_type}   — Update integration config (ADMIN)
DELETE /api/v1/integrations/{integration_type}   — Delete integration (ADMIN)
```

**Webhook receivers**:

```
POST /api/v1/integrations/webhooks/jira        — Receive Jira issue events
POST /api/v1/integrations/webhooks/salesforce  — Receive Salesforce JSON (Flow/Apex callout)
POST /api/v1/integrations/webhooks/github      — Receive GitHub events (HMAC-SHA256 validated)
```

Supported `IntegrationType` values: `jira`, `salesforce`, `github` (lower case, in the body and in the path).

---

### Bayesian Experimentation

See [Bayesian API Reference](bayesian.md) for full documentation.

Bayesian analysis is enabled per experiment with two fields on the standard experiment
create/update request body. The experiment response carries both, plus `bayesian_decision`:

| Field | Type | Description |
|---|---|---|
| `bayesian_enabled` | `boolean` | Computes Bayesian results for this experiment. Turning it on without a config stores the defaults |
| `bayesian_config` | `object` | `prior_family`, `alpha`, `beta`, `loss_threshold`, `rope`, `credible_level`; see [the `bayesian_config` object](bayesian.md#turning-bayesian-analysis-on). An invalid value is refused with `422` |
| `bayesian_decision` | `string` | Response only: the latest recommendation, `CONTINUE`, `STOP_WINNER`, `STOP_EQUIVALENT` or `STOP_FUTILE`. Nothing stops the experiment on it |

When `bayesian_enabled` is `true`, `GET /api/v1/results/{experiment_id}` embeds a
`bayesian_results` block, and `GET /api/v1/results/{experiment_id}/bayesian` returns it on
its own: a posterior, credible interval, probability to be best and expected loss for each
variant, and the decision.

---

### Server-Side Split URL Testing

See [Split URL API Reference](split-url.md) for full documentation.

Split URL experiments use `experiment_type: SPLIT_URL` and require a `split_url_config` in the request body. Variant assignment and URL redirection are meant to happen in the split-URL module's Lambda@Edge router, on a CloudFront distribution. The CDK app creates no CloudFront distribution, so the router runs only if you add the module's construct to a stack yourself.

**Experiment management** uses the existing experiment CRUD endpoints with `experiment_type=SPLIT_URL`:

```
POST /api/v1/experiments/              — Create split URL experiment (set experiment_type=SPLIT_URL)
PUT  /api/v1/experiments/{id}          — Update split URL config
GET  /api/v1/experiments/{id}          — Returns split_url_config in response
```

**Split URL-specific endpoint**:

```
GET /api/v1/experiments/{experiment_id}/split-url/preview  — Preview variant assignment for a user (dev/QA)
```

Query parameters for preview: `user_id` (required), `attributes` (optional JSON object).

**`SplitUrlConfig` schema** (`split_url_config` field):

```json
{
  "variants": [
    { "url": "https://example.com/page-v1", "weight": 50 },
    { "url": "https://example.com/page-v2", "weight": 50 }
  ]
}
```

All weights must be integers (0-100) and must sum to exactly 100.

**Lambda@Edge behaviour**: On each request the edge function reads the cookie `exp_{experiment_key}`. If absent, it hashes `user_id` to assign a variant, then returns a `302 Found` redirect to the variant URL and sets a 1-year `Set-Cookie` header for persistence.

---

### Java SDK

The Java SDK and Spring Boot starter are distributed as Maven/Gradle artifacts. No new backend API endpoints are introduced; the SDK communicates with the existing experiment assignment and feature flag evaluation endpoints.

See [SDK Integration Guide](../sdk-guide.md#java-sdk) for installation, Spring Boot auto-configuration (`@EnableExperimentation`), and the Spring Boot properties reference (`experimentation.api-url`, `experimentation.api-key`, `experimentation.cache-ttl-seconds`, `experimentation.cache-max-size`).

---

### React SDK

The React SDK is distributed as an npm package (`@experimentation/react-sdk`). No new backend API endpoints are introduced; the SDK consumes the existing assignment and feature flag endpoints.

See [SDK Integration Guide](../sdk-guide.md#react-sdk) for `ExperimentationProvider` setup, all hooks (`useFeatureFlag`, `useExperiment`, `useTrackEvent`, `useVariant`, `useMultipleFlags`), the `withExperimentation` HOC, and SSR/Next.js `ServerClient` usage.
