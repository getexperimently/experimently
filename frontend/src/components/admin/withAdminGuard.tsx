import React from 'react';
import { UserRole } from '@/types/admin';
import { RequireAuth } from '@/components/RequireAuth';

export interface AdminGuardOptions {
  /**
   * Minimum role required (hierarchical: ADMIN > DEVELOPER > ANALYST > VIEWER).
   * `requiredRole: 'DEVELOPER'` admits DEVELOPER and ADMIN.
   */
  requiredRole?: UserRole;
  /** Explicit allow-list; takes precedence over `requiredRole`. */
  roles?: UserRole[];
  /**
   * Require a superuser account. Defaults to **true** for the admin area,
   * because every endpoint under /api/v1/admin is
   * `Depends(deps.get_current_superuser)`. Set false only for a page that
   * genuinely does not call one.
   */
  superuser?: boolean;
  /** Where the 403 view links back to. Default `/experiments`. */
  fallbackPath?: string;
}

const ROLE_ORDER: UserRole[] = ['VIEWER', 'ANALYST', 'DEVELOPER', 'ADMIN'];

/** Roles at or above `minimum` in the hierarchy. */
export function rolesAtLeast(minimum: UserRole): UserRole[] {
  const index = ROLE_ORDER.indexOf(minimum);
  return ROLE_ORDER.slice(index < 0 ? 0 : index);
}

/**
 * The admin area's audience is superusers, not a role.
 *
 * There used to be an `ADMIN_AREA_ROLES = ['ADMIN', 'DEVELOPER']` here,
 * matching the nav item, and neither matched the API: all six endpoints under
 * /api/v1/admin require `deps.get_current_superuser`. A DEVELOPER saw the
 * item, this guard admitted them, the page rendered, and
 * `GET /api/v1/admin/stats` returned 403 (#84).
 *
 * Restricting it to ADMIN would not have been enough either: `role` and
 * `is_superuser` are independent columns and `PUT /admin/users/{id}` sets
 * either without the other, so an ADMIN-without-superuser reaches the same
 * dead end. The guard asks the question the API asks, and the constant is
 * gone rather than left behind stating a rule nothing applies.
 */

/**
 * Page-level guard for the admin area, implemented on top of `RequireAuth`
 * and the `AuthContext` (no localStorage user object).
 */
export function withAdminGuard<P extends object>(
  Component: React.ComponentType<P>,
  options: AdminGuardOptions = {}
): React.FC<P> {
  const { requiredRole, roles, superuser = true, fallbackPath = '/experiments' } = options;
  // With `superuser` on (the default) the role list adds nothing for the admin
  // area -- every superuser passes it -- so it is only applied when a caller
  // asked for a specific role.
  const allowed = roles ?? (requiredRole ? rolesAtLeast(requiredRole) : undefined);

  const GuardedComponent: React.FC<P> = (props) => (
    <RequireAuth roles={allowed} superuser={superuser} fallbackPath={fallbackPath}>
      <Component {...props} />
    </RequireAuth>
  );

  GuardedComponent.displayName = `withAdminGuard(${Component.displayName ?? Component.name ?? 'Component'})`;

  return GuardedComponent;
}
