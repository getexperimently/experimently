# AWS Cognito Integration

This document explains how Experimently integrates with AWS Cognito for authentication and role-based access control.

## Overview

The platform uses AWS Cognito for user authentication and leverages Cognito groups to automatically assign user roles within the application. This integration provides the following features:

1. Users are automatically created in the system database upon first authentication via Cognito
2. User roles are automatically set based on Cognito group membership
3. Changes to Cognito groups are reflected in user roles on next login
4. Superusers (with full admin privileges) are automatically identified based on membership in designated admin groups

## User pool requirements

The user pool that `COGNITO_USER_POOL_ID` names must require an email address:

- make `email` a **required** standard attribute of the pool;
- if users sign in through a federated identity provider (SAML, OIDC, Google and so on), map
  the provider's email claim to the pool's `email` attribute.

The platform creates a user's account the first time they sign in, and takes the account's
email address from the pool's `email` attribute, so every identity that can sign in needs one.
Cognito does not let you change a pool's required attributes after the pool is created, so
set this when you create it. The reference pool in
`infrastructure/cdk/stacks/authentication_stack.py` already requires `email`.

## Configuration

The following settings in `backend/app/core/config.py` control the Cognito integration:

```python
# Cognito settings
COGNITO_GROUP_ROLE_MAPPING: Dict[str, str] = {
    "Admins": "admin",
    "Developers": "developer",
    "Analysts": "analyst",
    "Viewers": "viewer"
}
COGNITO_ADMIN_GROUPS: List[str] = ["Admins", "SuperUsers"]
SYNC_ROLES_ON_LOGIN: bool = True
```

- `COGNITO_GROUP_ROLE_MAPPING`: Maps Cognito group names to application roles
- `COGNITO_ADMIN_GROUPS`: Lists Cognito groups whose members are automatically given superuser status
- `SYNC_ROLES_ON_LOGIN`: When `True` (the default), every authenticated request -- not only
  sign-in -- sets the user's role and superuser status from their Cognito groups. A role
  changed in the dashboard would be overwritten on the user's next request, so
  `PATCH /api/v1/admin/users/{user_id}` refuses a role change with 409 while this is on;
  change the user's group in Cognito instead. Active status is not synced and can be
  changed there.

## User Roles

The application defines the following user roles, in order of decreasing privilege:

1. **ADMIN**: Full access to all features and data
2. **DEVELOPER**: Can create and manage experiments and feature flags
3. **ANALYST**: Can view all data but cannot create or modify experiments/flags
4. **VIEWER**: Read-only access to approved resources

## Role Assignment Logic

When a user authenticates via Cognito, the following logic determines their role:

1. The user's Cognito groups are retrieved via the Cognito API
2. If the user belongs to any group listed in `COGNITO_ADMIN_GROUPS`, they are:
   - Assigned superuser status (`is_superuser = True`)
   - Given the `ADMIN` role regardless of other group mappings
3. Otherwise, their role is determined by the highest-privilege role mapped from their Cognito groups
4. If the user doesn't belong to any mapped group, they default to the `VIEWER` role

## Role Precedence

If a user belongs to multiple Cognito groups that map to different roles, the highest-privilege role wins:

- `ADMIN` takes precedence over `DEVELOPER`
- `DEVELOPER` takes precedence over `ANALYST`
- `ANALYST` takes precedence over `VIEWER`

## Example

A user who belongs to both the "Developers" and "Analysts" Cognito groups will be assigned the `DEVELOPER` role in the application.

A user who belongs to the "SuperUsers" group (which is in `COGNITO_ADMIN_GROUPS`) will automatically be assigned the `ADMIN` role and given superuser status, even if "SuperUsers" is mapped to a different role in `COGNITO_GROUP_ROLE_MAPPING`.

## Implementation Details

The Cognito integration is implemented in the following files:

- `backend/app/core/cognito.py`: Contains utility functions for mapping Cognito groups to roles
- `backend/app/api/deps.py`: Implements the `get_current_user` dependency which handles role assignment
- `backend/app/services/auth_service.py`: Provides the interface to Cognito API

## Testing

To test the Cognito integration:

1. Configure your AWS Cognito User Pool with the appropriate groups
2. Set the required environment variables for Cognito connection
3. Create users and assign them to different groups in Cognito
4. Verify that users receive the expected roles when they log in to the application
