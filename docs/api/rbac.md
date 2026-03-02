# RBAC Post-MVP API Reference (P2-A)

## Overview

The RBAC (Role-Based Access Control) system in the experimentation platform combines three layers to determine what a user can do:

1. **Base Role** — One of four built-in system roles assigned to every user (`admin`, `developer`, `analyst`, `viewer`). Defined as the static `ROLE_PERMISSIONS` dict in `backend/app/core/permissions.py`.
2. **Custom Roles** — DB-backed roles with configurable per-resource/action permission sets. An admin can create any number of custom roles and assign them to users.
3. **Direct Permission Grants** — Per-user, per-resource grants that bypass role membership. Supports optional expiry timestamps for temporary grants.

### Effective Permissions Resolution

When checking if a user has a given permission, the system merges all three layers in order:

```
effective_permissions(user) =
    ROLE_PERMISSIONS[user.base_role]
    ∪ union(custom_role.permissions for each custom_role assigned to user)
    ∪ union(grant.permissions for each valid direct grant for user)
```

Superusers (`is_superuser=True`) bypass all checks and have full access to every resource and action.

### Permission Resolution Precedence

- Permissions are **additive** — a permission granted by any layer is granted overall.
- There is no deny mechanism; a higher layer cannot revoke a permission given by a lower layer.
- Expired or deactivated direct grants are excluded from the union.

---

## Authentication

All RBAC endpoints require a valid bearer token in the `Authorization` header:

```
Authorization: Bearer <token>
```

---

## Endpoints

### List Custom Roles

```
GET /api/v1/rbac/roles
```

Returns all custom roles. Any authenticated user can call this.

**Query Parameters**

| Parameter       | Type    | Default | Description                                          |
|-----------------|---------|---------|------------------------------------------------------|
| `include_system`| boolean | `true`  | When `false`, excludes the 4 built-in system roles. |

**Response 200**

```json
[
  {
    "id": "a1b2c3d4-...",
    "name": "data-scientist",
    "description": "Read access to experiments plus export",
    "is_system_role": false,
    "permissions": [
      {"resource": "experiment", "actions": ["read", "list"]},
      {"resource": "export", "actions": ["read"]}
    ],
    "created_at": "2026-03-01T10:00:00Z",
    "user_count": 5
  }
]
```

**Example**

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/rbac/roles?include_system=false"
```

---

### Create Custom Role

```
POST /api/v1/rbac/roles
```

Creates a new custom role. **ADMIN only.**

**Request Body**

```json
{
  "name": "read-only-experiments",
  "description": "Can view experiments and results but not create or modify",
  "permissions": [
    {"resource": "experiment", "actions": ["read", "list"]},
    {"resource": "report", "actions": ["read", "list"]}
  ]
}
```

**Name validation rules:**
- Minimum 2 characters, maximum 64 characters
- Must start with a lowercase letter (`a-z`)
- Only lowercase letters, digits, hyphens (`-`), and underscores (`_`) are allowed
- Examples of valid names: `data-scientist`, `read_only_experiments`, `analyst2`

**Available resources:** `experiment`, `feature_flag`, `user`, `role`, `permission`, `report`, `audit_log`, `export`

**Available actions:** `create`, `read`, `update`, `delete`, `list`

**Response 201**

```json
{
  "id": "a1b2c3d4-...",
  "name": "read-only-experiments",
  "description": "Can view experiments and results but not create or modify",
  "is_system_role": false,
  "permissions": [
    {"resource": "experiment", "actions": ["read", "list"]},
    {"resource": "report", "actions": ["read", "list"]}
  ],
  "created_at": "2026-03-01T10:00:00Z",
  "user_count": 0
}
```

**Error responses:**
- `409 Conflict` — A role with this name already exists
- `403 Forbidden` — Caller is not an admin
- `422 Unprocessable Entity` — Invalid name format or empty actions list

**Example**

```bash
curl -X POST http://localhost:8000/api/v1/rbac/roles \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "read-only-experiments",
    "permissions": [
      {"resource": "experiment", "actions": ["read", "list"]}
    ]
  }'
```

---

### Get Custom Role

```
GET /api/v1/rbac/roles/{role_name}
```

Get details of a specific role. Any authenticated user can call this.

**Path Parameters**

| Parameter   | Type   | Description       |
|-------------|--------|-------------------|
| `role_name` | string | The role's name.  |

**Response 200**

```json
{
  "id": "a1b2c3d4-...",
  "name": "data-scientist",
  "description": null,
  "is_system_role": false,
  "permissions": [...],
  "created_at": "2026-03-01T10:00:00Z",
  "user_count": 3
}
```

**Error responses:**
- `404 Not Found` — Role does not exist

---

### Update Custom Role

```
PUT /api/v1/rbac/roles/{role_name}
```

Update a custom role's description or permission set. **ADMIN only.** System roles cannot be modified.

**Request Body** (all fields optional)

```json
{
  "description": "Updated description",
  "permissions": [
    {"resource": "experiment", "actions": ["read", "list", "create"]}
  ]
}
```

**Response 200** — Updated role object (same shape as GET)

**Error responses:**
- `400 Bad Request` — Attempted to modify a system role
- `403 Forbidden` — Caller is not an admin
- `404 Not Found` — Role does not exist

---

### Delete Custom Role

```
DELETE /api/v1/rbac/roles/{role_name}
```

Delete a custom role. **ADMIN only.** System roles cannot be deleted.

**Response 204** — No content

**Error responses:**
- `400 Bad Request` — Attempted to delete a system role
- `403 Forbidden` — Caller is not an admin
- `404 Not Found` — Role does not exist

---

### Assign Role to User

```
POST /api/v1/rbac/roles/assign
```

Assign a custom role to a user. **ADMIN only.** This operation is idempotent — assigning a role to a user who already has it is a no-op.

**Request Body**

```json
{
  "user_id": "user-uuid",
  "role_name": "data-scientist",
  "reason": "Promoted to data science team"
}
```

**Response 200**

```json
{
  "status": "assigned",
  "user_id": "user-uuid",
  "role": "data-scientist"
}
```

**Error responses:**
- `403 Forbidden` — Caller is not an admin
- `404 Not Found` — Role does not exist

**Example**

```bash
curl -X POST http://localhost:8000/api/v1/rbac/roles/assign \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "abc123", "role_name": "data-scientist"}'
```

---

### Revoke Role from User

```
POST /api/v1/rbac/roles/revoke
```

Revoke a custom role from a user. **ADMIN only.**

**Request Body**

```json
{
  "user_id": "user-uuid",
  "role_name": "data-scientist",
  "reason": "Moved to different team"
}
```

**Response 200**

```json
{
  "status": "revoked",
  "user_id": "user-uuid",
  "role": "data-scientist"
}
```

---

### Get Effective Permissions

```
GET /api/v1/rbac/users/{user_id}/permissions
```

Returns the fully resolved permission set for a user, merging base role + custom roles + valid direct grants.

**Access control:** Users can view their own permissions. Admins can view any user's permissions.

**Response 200**

```json
{
  "user_id": "user-uuid",
  "username": "jane.doe",
  "base_role": "analyst",
  "custom_roles": ["data-scientist", "export-reader"],
  "permissions": {
    "experiment": ["list", "read"],
    "export": ["list", "read"],
    "feature_flag": ["list", "read"],
    "permission": ["read"],
    "report": ["create", "delete", "list", "read", "update"],
    "role": ["read"],
    "user": ["read"]
  },
  "is_superuser": false
}
```

Note: actions within each resource are returned sorted alphabetically.

**Error responses:**
- `403 Forbidden` — Non-admin user trying to view another user's permissions
- `404 Not Found` — User does not exist

**Example**

```bash
# View your own permissions
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/rbac/users/my-user-id/permissions"

# Admin viewing another user's permissions
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  "http://localhost:8000/api/v1/rbac/users/other-user-id/permissions"
```

---

### Grant Direct Permission

```
POST /api/v1/rbac/users/{user_id}/grant
```

Grant a specific resource permission directly to a user, bypassing role assignment. Supports optional expiry for temporary grants. **ADMIN only.**

**Request Body**

```json
{
  "user_id": "user-uuid",
  "resource": "report",
  "actions": ["create", "read"],
  "reason": "Temporary access for Q1 reporting",
  "expires_at": "2026-04-01T00:00:00Z"
}
```

`expires_at` is optional. If omitted, the grant never expires.

**Response 201**

```json
{
  "status": "granted",
  "user_id": "user-uuid",
  "resource": "report",
  "actions": ["create", "read"]
}
```

**Error responses:**
- `403 Forbidden` — Caller is not an admin

**Example — Temporary permission with expiry**

```bash
curl -X POST "http://localhost:8000/api/v1/rbac/users/abc123/grant" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "abc123",
    "resource": "export",
    "actions": ["read"],
    "reason": "One-week access for audit",
    "expires_at": "2026-03-08T00:00:00Z"
  }'
```

---

### Revoke Direct Permission

```
DELETE /api/v1/rbac/users/{user_id}/grant/{resource}
```

Revoke all direct permission grants for a user+resource combination. **ADMIN only.**

**Path Parameters**

| Parameter  | Type   | Description                |
|------------|--------|----------------------------|
| `user_id`  | UUID   | Target user's ID           |
| `resource` | string | Resource name (e.g. `export`) |

**Response 200**

```json
{
  "status": "revoked",
  "count": 1
}
```

`count` is the number of grant records deleted.

---

## How-To Examples

### Create a "Read-Only Experiments" Custom Role

This is the most common use case: a user who should be able to see experiments and results but never create or modify them.

```bash
# Step 1: Create the role
curl -X POST http://localhost:8000/api/v1/rbac/roles \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "read-only-experiments",
    "description": "View-only access to experiments and reports",
    "permissions": [
      {"resource": "experiment", "actions": ["read", "list"]},
      {"resource": "report", "actions": ["read", "list"]},
      {"resource": "feature_flag", "actions": ["read", "list"]}
    ]
  }'

# Step 2: Assign the role to a user
curl -X POST http://localhost:8000/api/v1/rbac/roles/assign \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "the-user-uuid",
    "role_name": "read-only-experiments",
    "reason": "Stakeholder who needs to monitor experiments"
  }'

# Step 3: Verify the user's effective permissions
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  "http://localhost:8000/api/v1/rbac/users/the-user-uuid/permissions"
```

### Grant a Temporary Export Permission

Allow a data analyst to export data for a week-long audit without permanently changing their role:

```bash
curl -X POST "http://localhost:8000/api/v1/rbac/users/analyst-uuid/grant" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "analyst-uuid",
    "resource": "export",
    "actions": ["read", "list"],
    "reason": "Q1 compliance audit access",
    "expires_at": "2026-03-08T23:59:59Z"
  }'
```

After `expires_at`, the direct grant is automatically excluded from the effective permissions calculation without requiring manual cleanup.

To revoke early:

```bash
curl -X DELETE \
  "http://localhost:8000/api/v1/rbac/users/analyst-uuid/grant/export" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### Check What a User Can Do

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  "http://localhost:8000/api/v1/rbac/users/some-user-uuid/permissions" | \
  python3 -m json.tool
```

---

## Service API (Internal)

The `RBACService` in `backend/app/services/rbac_service.py` can be used directly in other services:

```python
from backend.app.services.rbac_service import RBACService

# Check if user can perform an action (merges all layers)
can_do_it = RBACService.check_effective_permission(
    db, user, resource="experiment", action="create"
)

# Get the full resolved permission set
effective = RBACService.get_effective_permissions(db, user)
print(effective.permissions)  # {"experiment": ["create", "list", "read", ...], ...}
```

`check_effective_permission` is an additive alternative to `check_permission()` from `permissions.py`. It does NOT modify the existing static check — it checks custom roles and direct grants in addition to the base role.

---

## Data Models

### CustomRole

| Column          | Type       | Description                                      |
|-----------------|------------|--------------------------------------------------|
| `id`            | UUID       | Primary key                                      |
| `name`          | string(64) | Unique role name (lowercase, slugified)          |
| `description`   | text       | Optional human-readable description              |
| `is_system_role`| boolean    | `true` for built-in roles (protected from edits) |
| `permissions`   | JSONB      | List of `{resource, actions[]}` objects          |
| `created_by_id` | UUID FK    | User who created the role                        |
| `created_at`    | datetime   | Creation timestamp                               |
| `updated_at`    | datetime   | Last update timestamp                            |

### UserCustomRole

| Column           | Type     | Description                    |
|------------------|----------|--------------------------------|
| `id`             | UUID     | Primary key                    |
| `user_id`        | UUID FK  | Reference to user              |
| `role_id`        | UUID FK  | Reference to custom role       |
| `assigned_by_id` | UUID FK  | Admin who made the assignment  |
| `reason`         | text     | Optional audit reason          |
| `assigned_at`    | datetime | When the assignment was made   |

### DirectPermissionGrant

| Column          | Type     | Description                                   |
|-----------------|----------|-----------------------------------------------|
| `id`            | UUID     | Primary key                                   |
| `user_id`       | UUID FK  | Target user                                   |
| `resource`      | string   | Resource name (e.g. `export`)                 |
| `actions`       | JSONB    | List of action strings (e.g. `["read"]`)      |
| `granted_by_id` | UUID FK  | Admin who granted the permission              |
| `reason`        | text     | Optional audit reason                         |
| `expires_at`    | datetime | Optional expiry; `null` means never expires   |
| `is_active`     | boolean  | Can be deactivated without deleting           |
