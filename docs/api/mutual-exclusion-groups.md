# Mutual Exclusion Groups & Global Holdout

Mutual exclusion groups prevent users from being enrolled in multiple conflicting experiments simultaneously. A global holdout reserves a clean control group that is excluded from all experiments, enabling long-term measurement of cumulative experiment impact.

---

## Mutual Exclusion Groups

### When to Use

Use mutual exclusion groups when:
- Two or more experiments modify the same UI surface (e.g. both change the checkout page)
- Experiments are known to interact statistically (see [Interaction Detection](./interaction-detection.md))
- You need clean causal estimates and cannot tolerate cross-experiment contamination

### How It Works

Traffic is partitioned using consistent hashing on user ID. Each group has a `traffic_allocation` (0.0–1.0) that defines the fraction of users eligible for experiments within the group. Users are assigned to at most one experiment within the group.

---

## Mutual Exclusion Group API

### GET /api/v1/mutual-exclusion-groups

List all mutual exclusion groups.

**Query Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `status` | string | Filter by status: `active`, `archived` |
| `skip` | int | Pagination offset (default: 0) |
| `limit` | int | Page size (default: 100, max: 1000) |

```bash
curl -X GET "http://localhost:8000/api/v1/mutual-exclusion-groups" \
  -H "Authorization: Bearer $TOKEN"
```

---

### POST /api/v1/mutual-exclusion-groups

Create a new mutual exclusion group. Requires DEVELOPER or ADMIN role.

```bash
curl -X POST "http://localhost:8000/api/v1/mutual-exclusion-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Checkout Page Experiments",
    "description": "All experiments that modify the checkout flow",
    "traffic_allocation": 0.5
  }'
```

**Response**

```json
{
  "id": "group-uuid",
  "name": "Checkout Page Experiments",
  "description": "All experiments that modify the checkout flow",
  "traffic_allocation": 0.5,
  "status": "active",
  "experiments": [],
  "created_at": "2026-03-02T10:00:00Z"
}
```

---

### GET /api/v1/mutual-exclusion-groups/{group_id}

Retrieve a specific group including its member experiments.

---

### PUT /api/v1/mutual-exclusion-groups/{group_id}

Update group name, description, or traffic allocation. Requires DEVELOPER or ADMIN role.

---

### DELETE /api/v1/mutual-exclusion-groups/{group_id}

Archive a group (soft delete). Requires ADMIN role. Member experiments are not affected.

---

### POST /api/v1/mutual-exclusion-groups/{group_id}/experiments

Add an experiment to a mutual exclusion group.

```bash
curl -X POST "http://localhost:8000/api/v1/mutual-exclusion-groups/group-uuid/experiments" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"experiment_id": "exp-uuid"}'
```

---

### DELETE /api/v1/mutual-exclusion-groups/{group_id}/experiments/{experiment_id}

Remove an experiment from the group.

---

## Global Holdout

A global holdout reserves a percentage of users from **all** experiments platform-wide. Users in the holdout group see no experiments — they experience the baseline product. This lets you measure the cumulative effect of all experiments running on the platform.

Only one holdout can be active at a time.

### GET /api/v1/holdout

Returns the currently active global holdout, or `null` if none is active.

```bash
curl -X GET "http://localhost:8000/api/v1/holdout" \
  -H "Authorization: Bearer $TOKEN"
```

**Response**

```json
{
  "id": "holdout-uuid",
  "name": "Q1 2026 Holdout",
  "holdout_percentage": 5.0,
  "is_active": true,
  "created_at": "2026-01-01T00:00:00Z"
}
```

### GET /api/v1/holdout/all

List all holdout configurations (active and historical). Requires ADMIN role.

### POST /api/v1/holdout

Create a global holdout. Requires ADMIN role. Creating a new active holdout automatically deactivates the existing one.

```bash
curl -X POST "http://localhost:8000/api/v1/holdout" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Q1 2026 Holdout",
    "holdout_percentage": 5.0,
    "is_active": true
  }'
```

### PUT /api/v1/holdout/{holdout_id}

Update holdout configuration. Requires ADMIN role.

### GET /api/v1/holdout/check/{user_id}

Check whether a specific user is in the active global holdout.

```bash
curl -X GET "http://localhost:8000/api/v1/holdout/check/user-123" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{"user_id": "user-123", "in_holdout": false}
```

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
