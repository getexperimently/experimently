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
  /** Where the 403 view links back to. Default `/experiments`. */
  fallbackPath?: string;
}

const ROLE_ORDER: UserRole[] = ['VIEWER', 'ANALYST', 'DEVELOPER', 'ADMIN'];

/** Roles at or above `minimum` in the hierarchy. */
export function rolesAtLeast(minimum: UserRole): UserRole[] {
  const index = ROLE_ORDER.indexOf(minimum);
  return ROLE_ORDER.slice(index < 0 ? 0 : index);
}

/** Default admin-area audience: matches the "Admin" nav item in the AppShell. */
export const ADMIN_AREA_ROLES: UserRole[] = ['ADMIN', 'DEVELOPER'];

/**
 * Page-level guard for the admin area, implemented on top of `RequireAuth`
 * and the `AuthContext` (no localStorage user object).
 */
export function withAdminGuard<P extends object>(
  Component: React.ComponentType<P>,
  options: AdminGuardOptions = {}
): React.FC<P> {
  const { requiredRole, roles, fallbackPath = '/experiments' } = options;
  const allowed = roles ?? (requiredRole ? rolesAtLeast(requiredRole) : ADMIN_AREA_ROLES);

  const GuardedComponent: React.FC<P> = (props) => (
    <RequireAuth roles={allowed} fallbackPath={fallbackPath}>
      <Component {...props} />
    </RequireAuth>
  );

  GuardedComponent.displayName = `withAdminGuard(${Component.displayName ?? Component.name ?? 'Component'})`;

  return GuardedComponent;
}
