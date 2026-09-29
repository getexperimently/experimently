# Team Workspaces — Overview

!!! info "Part of the `workspaces` module"
    Team workspaces is one of the optional modules -- present in the **full profile**, absent from the core one. A core deployment does not serve these routes. See [Modules and profiles](../getting-started/modules.md) for what each profile includes and how to run the full one.

## What Are Workspaces?

A **workspace** groups platform users into a team, with a workspace role for
each member. It represents a team, project, or product area — for example:

- `acme-mobile` for the mobile engineering team
- `acme-web` for the web product team
- `acme-growth` for the growth squad

A workspace holds its members, their workspace roles, its pending invitations
and its workspace API keys. The workspace routes (`/api/v1/workspaces/...`)
check membership and workspace role: only a member can read a workspace or its
member list, and only an ADMIN or OWNER of that workspace can change its
settings, members, invites or keys (any member can leave).

### What workspaces do not do

Workspaces do **not** decide which experiments, feature flags or API keys a
user can see or change. Experiments and feature flags are not created inside a
workspace, and workspace membership plays no part when they are listed, read
or changed. That is decided by the user's **platform role** (ADMIN, DEVELOPER,
ANALYST or VIEWER) across the whole installation — see [Role-based access
control](../rbac/README.md). Joining or leaving a workspace does not change
which experiments and flags a user can see or change.

If you need teams to be unable to see each other's experiments and flags, run a
separate installation for each team.

---

## Role Hierarchy

Every workspace member has exactly one workspace role. The roles form a
hierarchy, and a workspace role applies only to the workspace routes:

| Role          | On the workspace routes |
|---------------|-------------------------|
| **OWNER**     | Everything an ADMIN can do, and delete the workspace |
| **ADMIN**     | Update workspace settings, add and remove members, change member roles, send invites, create, list, rotate and revoke workspace API keys |
| **DEVELOPER** | Read the workspace and its member list; leave the workspace |
| **ANALYST**   | Read the workspace and its member list; leave the workspace |
| **VIEWER**    | Read the workspace and its member list; leave the workspace |

DEVELOPER, ANALYST and VIEWER are recorded for each member but currently grant
the same thing on the workspace routes. None of the five changes what the member
can do with experiments, feature flags or platform API keys; the platform role
does that.

### Changing Roles

- An ADMIN or OWNER can change a member's role among VIEWER, ANALYST,
  DEVELOPER and ADMIN. The last remaining OWNER cannot be demoted or removed.
- A member can remove themselves; an OWNER can do so only while there is at
  least one other OWNER.

---

## Plan Limits

Each workspace records resource limits determined by its plan:

| Resource          | Free  | Pro     | Enterprise |
|-------------------|-------|---------|------------|
| Max Experiments   | 10    | 1,000   | Unlimited  |
| Max Feature Flags | 50    | 5,000   | Unlimited  |
| Max Members       | 5     | 50      | Unlimited  |
| Max API Keys      | 3     | 20      | Unlimited  |

The member and API-key limits are enforced by the workspace routes: adding a
member, accepting an invite or creating a key past the limit returns HTTP
`422 Unprocessable Entity` with a descriptive error. The experiment and feature
flag limits are stored and returned, but not enforced, because experiments and
flags are not created inside a workspace.

---

## Workspace API Keys

!!! warning "Not yet accepted by the SDK or tracking endpoints"
    Workspace API keys are not yet accepted by the SDK, tracking or flag
    evaluation endpoints: a request that sends one in `X-API-Key` is answered
    `401 Invalid API Key`. To connect an SDK or send events, use a **platform
    API key** — see [API Key Management](../security/api-keys.md).

Workspace API keys are separate from platform API keys. They belong to a
workspace, and each carries a list of named scopes, recorded with the key:

| Scope               | Intended meaning |
|---------------------|------------------|
| `flags:read`        | Evaluate feature flags for end users |
| `experiments:read`  | Read experiment assignments and configuration |
| `track:write`       | Record analytics events |

Because no endpoint accepts a workspace key yet, these scopes are not applied
to any request.

### How they are stored and managed

- The plaintext key is shown **exactly once**, in the response that creates or
  rotates it. Later responses show only the key prefix (e.g. `ep_live_`).
- Keys are stored as SHA-256 hashes; the plaintext is not persisted.
- **Rotating** a key marks the old key inactive and returns a new one with the
  same name, scopes and expiry.
- **Revoking** a key marks it inactive without affecting the workspace's other
  keys.

---

## Invitations

Workspace members can be added in two ways:

1. **Direct add** (ADMIN+): Look up an existing platform user by their UUID and
   add them immediately with the desired role.
2. **Email invite** (ADMIN+): Create an invite for an email address. No email
   is sent. The dashboard shows the invitation link after you create it, with
   a **Copy link** button; the API response contains the token (the link is
   `/workspaces/invites/<token>` on the dashboard's address). Send the link to
   the recipient. The token is valid for 7 days. When the recipient accepts the
   invite (while authenticated), they are added as a member with the invited
   role.
   Anyone with the link can look the invitation up through the API, but only
   the invited account sees the address in full; everyone else sees it
   masked, for example `a•••@example.com`.

Only a user signed in with the invited address (compared without regard to
case) can accept it. Anyone else gets `403` with code `invite_email_mismatch`.
The address must be ASCII, and an alias is a different address:
`alice+work@example.com` does not accept an invite sent to `alice@example.com`.

> An invitation cannot grant the `OWNER` role.
