# Mutual Exclusion Groups & Global Holdout

Mutual exclusion groups prevent users from being enrolled in multiple conflicting experiments simultaneously. A global holdout reserves a clean control group that is excluded from all experiments, enabling long-term measurement of cumulative experiment impact.

The commands on this page run as written against the stack from the
[Quick Start](../getting-started/quick-start.md), in one terminal, top to bottom. Each one uses
the shell variables set by the ones before it. Log in first:

```{.bash exec}
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"admin@demo.com","password":"Demo1234!"}' | jq -r .access_token)

curl -s localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN" | jq .role
```
<!-- expect: "ADMIN" -->

It prints `"ADMIN"`.

**URLs.** On this page the collection URLs have no trailing slash
(`/api/v1/mutual-exclusion-groups`, `/api/v1/holdout`). With one, the API answers
`307 Temporary Redirect`, which `curl` doesn't follow, so nothing is printed.

---

## Mutual Exclusion Groups

### When to Use

Use mutual exclusion groups when:
- Two or more experiments modify the same UI surface (e.g. both change the checkout page)
- Experiments are known to interact statistically (see [Interaction Detection](./interaction-detection.md))
- You need clean causal estimates and cannot tolerate cross-experiment contamination

### How It Works

Traffic is partitioned using consistent hashing on user ID. Each group has a `traffic_allocation` (0.0–1.0) that defines the fraction of users eligible for experiments within the group. Users are assigned to at most one experiment within the group.

A user who is not eligible is still answered by `POST /api/v1/tracking/assign`, with status
`200`, the control variant, `"assigned": false` and `"reason": "mutual_exclusion"`. Nothing
is recorded for them.

---

## Mutual Exclusion Group API

### POST /api/v1/mutual-exclusion-groups

Create a new mutual exclusion group. Requires DEVELOPER or ADMIN role. This saves the new
group's id in `$GROUP_ID`:

```{.bash exec}
GROUP=$(curl -s -X POST localhost:8000/api/v1/mutual-exclusion-groups \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
    "name": "Checkout Page Experiments",
    "description": "All experiments that modify the checkout flow",
    "traffic_allocation": 0.5
  }')
GROUP_ID=$(jq -r .id <<<"$GROUP")

jq '{name, traffic_allocation, status, experiments}' <<<"$GROUP"
```
<!-- expect: "name": "Checkout Page Experiments" -->
<!-- expect: "traffic_allocation": 0.5 -->
<!-- expect: "status": "active" -->

```json
{
  "name": "Checkout Page Experiments",
  "traffic_allocation": 0.5,
  "status": "active",
  "experiments": []
}
```

The response also carries the group's `id`, `description`, `owner_id`, `created_at` and
`updated_at`.

---

### GET /api/v1/mutual-exclusion-groups

List all mutual exclusion groups.

**Query Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `status` | string | Filter by status: `active`, `archived` |
| `skip` | int | Pagination offset (default: 0) |
| `limit` | int | Page size (default: 100, max: 1000) |

```{.bash exec}
curl -s localhost:8000/api/v1/mutual-exclusion-groups \
  -H "Authorization: Bearer $TOKEN" | jq -r '.total, .items[].name'
```
<!-- expect: 1 -->
<!-- expect: Checkout Page Experiments -->

The response is `{"items": [...], "total": N}`. This prints the total, `1`, and each group's
name: `Checkout Page Experiments`.

---

### POST /api/v1/mutual-exclusion-groups/{group_id}/experiments

Add an experiment to a mutual exclusion group. This adds the demo data's
`checkout_button_color` experiment, looking up its id by its key:

```{.bash exec}
EXP_ID=$(curl -s localhost:8000/api/v1/experiments/ \
  -H "Authorization: Bearer $TOKEN" \
  | jq -r '.items[] | select(.key == "checkout_button_color") | .id')

curl -s -X POST localhost:8000/api/v1/mutual-exclusion-groups/$GROUP_ID/experiments \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d "{\"experiment_id\": \"$EXP_ID\"}" | jq .status
```
<!-- expect: "ok" -->

It prints `"ok"`. The response also names the `experiment_id` and `group_id`.

---

### GET /api/v1/mutual-exclusion-groups/{group_id}

Retrieve a specific group, including its member experiments:

```{.bash exec}
curl -s localhost:8000/api/v1/mutual-exclusion-groups/$GROUP_ID \
  -H "Authorization: Bearer $TOKEN" | jq -c '.experiments'
```
<!-- expect: "name":"Checkout Button Color" -->

It prints the member experiments' `id`, `name` and `status`:

```json
[{"id":"5673f9cd-8bbf-40c5-9bba-6613f87a78d4","name":"Checkout Button Color","status":"active"}]
```

---

### PUT /api/v1/mutual-exclusion-groups/{group_id}

Update group name, description, or traffic allocation. Requires DEVELOPER or ADMIN role.

---

### DELETE /api/v1/mutual-exclusion-groups/{group_id}

Archive a group (soft delete). Requires ADMIN role. Member experiments are not affected.

---

### DELETE /api/v1/mutual-exclusion-groups/{group_id}/experiments/{experiment_id}

Remove an experiment from the group.

---

## Global Holdout

A global holdout reserves a percentage of users from **all** experiments platform-wide. Users in the holdout group see no experiments — they experience the baseline product. This lets you measure the cumulative effect of all experiments running on the platform.

Only one holdout can be active at a time.

### GET /api/v1/holdout

Returns the currently active global holdout, or `null` if none is active:

```{.bash exec}
curl -s localhost:8000/api/v1/holdout \
  -H "Authorization: Bearer $TOKEN"
```
<!-- expect: null -->

It prints `null`: the demo data has no holdout.

### GET /api/v1/holdout/all

List all holdout configurations (active and historical). Requires ADMIN role.

### POST /api/v1/holdout

Create a global holdout. Requires ADMIN role. Creating a new active holdout automatically deactivates the existing one.

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/holdout \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
    "name": "Quarterly Holdout",
    "holdout_percentage": 5.0,
    "is_active": true
  }' | jq '{name, holdout_percentage, is_active}'
```
<!-- expect: "name": "Quarterly Holdout" -->
<!-- expect: "holdout_percentage": 5 -->
<!-- expect: "is_active": true -->

```json
{
  "name": "Quarterly Holdout",
  "holdout_percentage": 5,
  "is_active": true
}
```

The response also carries the holdout's `id`, `description`, `owner_id`, `created_at` and
`updated_at`.

### PUT /api/v1/holdout/{holdout_id}

Update holdout configuration. Requires ADMIN role.

### GET /api/v1/holdout/check/{user_id}

Check whether a specific user is in the active global holdout:

```{.bash exec}
curl -s localhost:8000/api/v1/holdout/check/user-123 \
  -H "Authorization: Bearer $TOKEN"
```
<!-- expect: "is_in_holdout":false -->
<!-- expect: "bucket":44 -->

```json
{"user_id":"user-123","is_in_holdout":false,"holdout_percentage":5,"bucket":44}
```

Each user has a fixed `bucket` from 0 to 99, a hash of their id. A user is in the holdout
when their bucket is below `holdout_percentage`: `user-123`'s bucket is 44, so a 5% holdout
leaves them out. A new user in the holdout is answered by `POST /api/v1/tracking/assign`
with the control variant, `"assigned": false` and `"reason": "holdout"`.

---

## Permissions

| Action | Minimum Role |
|--------|-------------|
| List groups / view holdout | DEVELOPER |
| Create / update groups | DEVELOPER |
| Add/remove experiments from groups | DEVELOPER |
| Archive groups / manage holdout | ADMIN |

---

## Recommended Setup

1. Create mutual exclusion groups for each major product surface (checkout, onboarding, pricing)
2. Add experiments to the appropriate group before activating them
3. Set a 5% global holdout at the start of each quarter for cumulative impact measurement
4. Review holdout vs. overall population metrics monthly
