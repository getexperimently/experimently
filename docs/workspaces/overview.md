# Multi-Tenant Team Workspaces — Overview

## What Are Workspaces?

Workspaces are the top-level isolation boundary in Experimently.
Each workspace has its own independent namespace for experiments, feature flags,
members, and API keys, making it safe for multiple teams to use the same platform
instance without interfering with each other.

A **workspace** represents a team, project, or product area — for example:
- `acme-mobile` for the mobile engineering team
- `acme-web` for the web product team
- `acme-growth` for the growth squad

All resources (experiments, feature flags, API keys) created inside a workspace
are invisible to users who are not workspace members.

---

## Role Hierarchy

Every workspace member has exactly one role. Roles form a strict hierarchy:

| Role        | Capabilities |
|-------------|-------------|
| **OWNER**   | Full control: update settings, delete workspace, manage all members and API keys |
| **ADMIN**   | Manage members, send invites, create and revoke API keys, update workspace settings |
| **DEVELOPER** | Create and manage experiments and feature flags within the workspace |
| **ANALYST** | View all experiments, feature flags, and analytics results; cannot create or modify resources |
| **VIEWER**  | Read-only access to approved workspace resources |

> Roles are **additive**: each role includes all permissions of the roles below it.

### Changing Roles

- An ADMIN (or OWNER) can change the role of any member, except the last remaining OWNER.
- An OWNER can voluntarily step down only if there is at least one other OWNER.

---

## Plan Limits

Each workspace has resource limits determined by its subscription plan:

| Resource          | Free  | Pro     | Enterprise |
|-------------------|-------|---------|------------|
| Max Experiments   | 10    | 1,000   | Unlimited  |
| Max Feature Flags | 50    | 5,000   | Unlimited  |
| Max Members       | 5     | 50      | Unlimited  |
| Max API Keys      | 3     | 20      | Unlimited  |

Plan limits are enforced at the API level — attempting to exceed a limit returns
an HTTP `422 Unprocessable Entity` with a descriptive error.

---

## Workspace-Scoped API Keys

Workspace API keys are separate from user-level API keys.  They are scoped to
a specific workspace and carry named **scopes** that restrict what operations the
key can perform.

### Standard Scopes

| Scope               | Description |
|---------------------|-------------|
| `flags:read`        | Evaluate feature flags for end users |
| `experiments:read`  | Read experiment assignments and configuration |
| `track:write`       | Record analytics events |

### Security Properties

- The plaintext key is shown **exactly once** at creation time.
  Subsequent API calls only return the key prefix (e.g. `ep_live_`) for identification.
- Keys are stored as SHA-256 hashes — the plaintext is never persisted.
- Keys can be **rotated** at any time; the old key is immediately invalidated.
- Keys can be **revoked** without affecting other keys in the workspace.

---

## Invitations

Workspace members can be added in two ways:

1. **Direct add** (ADMIN+): Look up an existing platform user by their UUID and
   add them immediately with the desired role.
2. **Email invite** (ADMIN+): Send an invite link to an email address. The invite
   token is valid for 7 days. When the recipient accepts the invite (while
   authenticated), they are added as a member with the invited role.

> The `OWNER` role cannot be granted via invitation.  It can only be assigned by
> an existing OWNER using the direct member-update endpoint.
