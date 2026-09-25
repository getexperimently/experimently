# Creating Feature Flags

This guide creates a flag, adds targeting rules, turns it on for 10% of users and
evaluates it: first in the dashboard, then with the REST API. The API commands run as
written against the stack from the [Quick Start](../getting-started/quick-start.md).

---

## Prerequisites

- **A running stack.** [Quick Start](../getting-started/quick-start.md) Step 1 starts one
  on `localhost`. On your own deployment, use its URL wherever this page says
  `localhost:8000` or `localhost:3000`.
- **A user account with the ADMIN or DEVELOPER role.** Creating, changing and turning a
  flag on all take a user login. An API key can't do them (the API answers `401`). An
  administrator creates accounts under **Admin → Users**. The examples below use the demo
  administrator, `admin@demo.com`.
- **An API key**, to evaluate the flag the way your application will. The API section
  creates one; in the dashboard, it's **Admin → API Keys**.

---

## Creating a Flag in the Dashboard

### Step 1: Open the form

Open the dashboard at `http://localhost:3000`, click **Feature Flags** in the top
navigation, then click **+ New Flag**.

### Step 2: Name the flag

| Field | Description | Example |
|-------|-------------|---------|
| **Name** (required) | The label shown in the dashboard. | `New Checkout Flow` |
| **Key** (required) | The identifier your code passes to the SDK. It's filled in from the name (`new_checkout_flow`), and you can edit it. Use lowercase letters, digits, `-` and `_`. The dashboard can't change it after the flag is created. | `new-checkout-flow` |
| **Description** | What the flag controls, and when it should be removed. | `Redesigned single-page checkout experience` |

### Step 3: Add targeting rules (optional)

Targeting rules turn the flag on for specific users, whatever the rollout percentage
is. Under **Targeting Rules**, click **+ Add Group**, then add one **+ Add Condition**
for each condition. A condition has three parts:
- an attribute: pick a suggestion such as `user.country`, or type any attribute your
  application sends;
- an operator;
- a value.

| Attribute | Operator | Value |
|-----------|----------|-------|
| `user.country` | `in` | `US, CA` |
| `user.plan` | `equals` | `enterprise` |

Each group's **AND**/**OR** decides how its conditions combine, and the **AND**/**OR**
above the groups decides how the groups combine.

If a user matches a rule, the flag is on for them. If they match no rule, the rollout
percentage in Step 4 decides. With no groups, the builder reads *No targeting rules —
all users will match*, and the rollout percentage decides for everyone.

### Step 4: Set the rollout percentage

The **Rollout percentage** slider sets the share of users who get the flag when they
match no targeting rule:

| Percentage | Effect |
|------------|--------|
| `0%` | Only users who match a targeting rule get the flag |
| `5%` | Matching users, plus 5% of everyone else |
| `100%` | Everyone |

Each user always lands on the same side of the percentage. Raising it adds users, and
takes none away.

### Step 5: Create the flag, then turn it on

Click **Create Feature Flag**. The flag starts **off** (its page reads *Not serving*), so
creating it never exposes anyone. When you're ready, turn it on with the switch beside
*Not serving*, and the page then reads *Serving*. The same switch turns it off again.

The dashboard's **On**/**Off** is the API's `status` of `"active"`/`"inactive"`, and you
set it with `is_active`.

---

## Creating a Flag with the API

Run these in one terminal, in order. Each step uses the shell variables set by the ones
before it (`$TOKEN`, `$FLAG_ID`, `$KEY`).

**URLs.** The collection URL ends with a slash (`/api/v1/feature-flags/`), and a single
flag's URL doesn't (`/api/v1/feature-flags/$FLAG_ID`). The other form answers
`307 Temporary Redirect`. `curl` doesn't follow the redirect, so nothing happens and
nothing is printed.

### Log in

```{.bash exec}
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"admin@demo.com","password":"Demo1234!"}' | jq -r .access_token)

curl -s localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN" | jq .role
```
<!-- expect: "ADMIN" -->

The second command prints `"ADMIN"`. If it prints `null`, the login failed (it takes
the account's `email`, not a username) and `$TOKEN` holds no token.

### Create the flag

```{.bash exec}
FLAG=$(curl -s -X POST localhost:8000/api/v1/feature-flags/ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
    "key": "new-checkout-flow",
    "name": "New Checkout Flow",
    "description": "Redesigned single-page checkout experience",
    "rollout_percentage": 0,
    "is_active": false
  }')
FLAG_ID=$(jq -r .id <<<"$FLAG")

jq '{key, status, rollout_percentage}' <<<"$FLAG"
```
<!-- expect: "status": "inactive" -->
<!-- expect: "rollout_percentage": 0 -->

```json
{
  "key": "new-checkout-flow",
  "status": "inactive",
  "rollout_percentage": 0
}
```

`"is_active": false` creates the flag switched off. **Leave it out and the flag is created
on**, because `is_active` defaults to `true` in the API. (The dashboard always sends
`false`.) The response reports the state as `status`. It also carries the flag's
`id`, which this saves in `$FLAG_ID` for the next steps.

The request takes these fields:
- `key` and `name` (both required);
- `description`;
- `is_active`;
- `rollout_percentage` (0–100, default 0);
- `targeting_rules`;
- `tags`.

**The API ignores any other field without an error.** A `"status"` field, for example,
has no effect, so check the response. A key that already exists answers `409`, and a key
with capitals or spaces answers `422`.

### Add targeting rules

`targeting_rules` uses the same shape the dashboard rule builder writes: a top-level
`logical_operator` combining one or more groups, each group combining its conditions.
This example targets enterprise-plan users in the US, CA or GB, **or** any employee:

```{.bash exec}
curl -s -o /dev/null -w '%{http_code}\n' -X PUT localhost:8000/api/v1/feature-flags/$FLAG_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
    "targeting_rules": {
      "logical_operator": "OR",
      "groups": [
        {
          "logical_operator": "AND",
          "conditions": [
            {"attribute": "user.plan", "operator": "equals", "value": "enterprise"},
            {"attribute": "user.country", "operator": "in", "value": ["US", "CA", "GB"]}
          ]
        },
        {
          "logical_operator": "AND",
          "conditions": [
            {"attribute": "employee", "operator": "equals", "value": "true"}
          ]
        }
      ]
    }
  }'
```
<!-- expect: 200 -->

It prints `200`.

Operators: `equals`, `not_equals`, `contains`, `not_contains`, `starts_with`, `ends_with`,
`greater_than`, `less_than`, `greater_than_or_equal`, `less_than_or_equal`, `in`, `not_in`,
`regex`, `is_null`, `is_not_null`, `semver_eq`, `semver_gt`, `semver_lt`, `semver_gte`,
`semver_lte`, `geo_within_radius`, `time_window`, `array_contains`, `array_intersects`.
Values typed in the dashboard are strings; they are compared leniently against typed
context values (`"true"` matches `true`, `"17"` matches `17`, `"beta, internal"` is a list
for `in`/`not_in`, `"17.4"` is padded to `17.4.0` for `semver_*`).

Users who match a rule are bucketed with the rule's `rollout_percentage` (100 unless set on
the rules object); users who match no rule fall through to the flag's global
`rollout_percentage`. The native Enhanced Rules Engine shape (`{"rules": [...]}`) is accepted
as well.

#### Targeting context and attribute aliases

Rules are matched against the **context** the SDK sends with each evaluation (the user's
attributes: `context=<url-encoded JSON>` on `GET /feature-flags/evaluate/{key}`, or the
`context` object on the `POST` variant). Before matching, the context is expanded so that:

- every key is available as given (`{"country": "US"}` answers `country`);
- nested objects are flattened to dotted keys (`{"app": {"version": "3.2.1"}}` answers
  `app.version`);
- every top-level key also answers `user.<key>`, `device.<key>` and `app.<key>`
  (`{"country": "US"}` answers `user.country`; `{"os_version": "17.4.0"}` answers
  `device.os_version`), and `user.<key>` / `device.<key>` / `app.<key>` keys in the context
  answer the bare `<key>` too;
- explicit keys always win over aliases.

So a dashboard rule on `user.country` matches an SDK that sends `{"country": "US"}` without
any renaming on either side. A condition whose attribute is absent from the context does not
match (except `is_null`, which does).

### Turn the flag on at 10%

```{.bash exec}
echo '{"status": "inactive", "rollout_percentage": 10}' | jq '{status, rollout_percentage}'
```
<!-- expect: "status": "active" -->
<!-- expect: "rollout_percentage": 10 -->

```json
{
  "status": "active",
  "rollout_percentage": 10
}
```

`"is_active": false` turns it off again. `POST /api/v1/feature-flags/$FLAG_ID/activate`
and `.../deactivate` do the same without a body. A `"status"` field in the `PUT` is
ignored.

### Create an API key

Applications evaluate flags with an API key, not a user token. The key is shown only
once, and this saves it in `$KEY`:

```{.bash exec}
KEY=$(curl -s -X POST localhost:8000/api/v1/api-keys \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"name":"flag-guide"}' | jq -r .key)
```

---

## Flag Key Naming Conventions

A key is lowercase letters, digits, hyphens and underscores, starting with a letter or
digit. Anything else is refused with `422`. To keep your flag inventory readable:

- Pick hyphens or underscores and stick to one: `new-checkout-flow`, `dark_mode_v2`. The
  dashboard fills keys in with underscores.
- Name what the flag controls: `redesigned-header`, `ai-recommendations`.
- Add a version suffix if you expect more than one iteration: `checkout-flow-v2`.
- Don't put an environment name in the key. Each deployment has its own flags.
- Avoid generic names. `experiment-1` and `flag-test` are hard to interpret months later.

---

## When a Flag Evaluates to Off

A flag is on or off for each user, and there's no separate default value. Evaluation
returns `enabled: false` when:

- the flag is off (`reason: "inactive"`);
- the user matches no targeting rule and falls outside the rollout percentage
  (`reason: "rollout"`);
- the user matches a rule but falls outside that rule's own rollout percentage
  (`reason: "targeting_rule"`);
- evaluation fails on the server (`reason: "error"`).

When the call itself fails (a network error or a wrong API key), the SDKs'
`isFeatureEnabled` and `is_feature_enabled` return `false`. So a flag your code can't
reach behaves as off.

---

## Evaluating the Flag from Your Application

### JavaScript SDK

```javascript
import { ExperimentationClient } from '@getexperimently/js-sdk';

const client = new ExperimentationClient({
  apiUrl: 'http://localhost:8000',   // your API origin; the SDK appends /api/v1/...
  apiKey: process.env.EXPERIMENTLY_API_KEY,
});

const isEnabled = await client.isFeatureEnabled('new-checkout-flow', {
  userId: 'user-123',
  attributes: { plan: 'enterprise', country: 'US' },
});

if (isEnabled) {
  showNewCheckoutFlow();
} else {
  showCurrentCheckoutFlow();
}
```

### Python SDK

```python
import os

from experimentation import ExperimentationClient

client = ExperimentationClient(
    api_url="http://localhost:8000",   # your API origin
    api_key=os.environ["EXPERIMENTLY_API_KEY"],
)

is_enabled = client.is_feature_enabled(
    flag_key="new-checkout-flow",
    user_id="user-123",
    user_attributes={"plan": "enterprise", "country": "US"},
)
```

### REST API (Direct)

Send the targeting context as a URL-encoded JSON object on the `GET` endpoint (this is
what the SDKs do):

```{.bash exec}
curl -s -G localhost:8000/api/v1/feature-flags/evaluate/new-checkout-flow \
  -H "X-API-Key: $KEY" \
  --data-urlencode "user_id=user-123" \
  --data-urlencode 'context={"plan":"enterprise","country":"US"}' | jq
```
<!-- expect: "enabled": true -->
<!-- expect: "reason": "targeting_rule" -->

```json
{
  "key": "new-checkout-flow",
  "enabled": true,
  "config": null,
  "reason": "targeting_rule"
}
```

Or send it as the `context` object in the body of the `POST` variant:

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/feature-flags/evaluate/new-checkout-flow \
  -H "X-API-Key: $KEY" \
  -H 'content-type: application/json' \
  -d '{"user_id": "user-123", "context": {"plan": "enterprise", "country": "US"}}' | jq .reason
```
<!-- expect: "targeting_rule" -->

It prints `"targeting_rule"`.

The same user on a free plan in Germany matches no rule. The 10% rollout then decides,
and `user-123` falls outside it:

```{.bash exec}
curl -s -G localhost:8000/api/v1/feature-flags/evaluate/new-checkout-flow \
  -H "X-API-Key: $KEY" \
  --data-urlencode "user_id=user-123" \
  --data-urlencode 'context={"plan":"free","country":"DE"}' | jq '{enabled, reason}'
```
<!-- expect: "enabled": false -->
<!-- expect: "reason": "rollout" -->

`reason` explains the outcome: `targeting_rule` (a rule matched and its rollout percentage
decided), `rollout` (no rule matched; the global rollout percentage decided), `inactive` or
`error`. A `context` that is not a JSON object returns `422`.
`GET /api/v1/feature-flags/user/{user_id}?context=...` evaluates every active flag the same way
and returns `{"flag-key": true|false, ...}`.

### Reporting client-side errors

Safety monitoring computes a flag's error rate from `error_logs` rows divided by its
evaluations. Clients can report the errors they see behind a flag (crashes, failed
requests) with the API key:

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/tracking/errors \
  -H "X-API-Key: $KEY" \
  -H 'content-type: application/json' \
  -d '{
    "feature_flag_key": "new-checkout-flow",
    "user_id": "user-123",
    "error_type": "crash",
    "message": "NullPointerException in CheckoutV2",
    "metadata": {"os": "Android", "os_version": "12.0.0"}
  }' | jq .error_type
```
<!-- expect: "crash" -->

It prints `"crash"`, the stored row's `error_type`.

`POST /api/v1/tracking/errors/batch` accepts `{"errors": [...]}` (up to 100) and returns
`{"success_count", "failure_count", "errors"}`. At least one of `feature_flag_key` /
`experiment_key` is required; unknown keys return `404` (single) or are listed per item
(batch).

---

## Next Steps

- [Gradual Rollouts](rollouts.md) — set up a staged rollout schedule with automatic progression
- [Safety Monitoring](safety.md) — configure automatic rollback if error rates spike
- [SDK Documentation](../sdk/javascript.md) — full SDK integration guide
