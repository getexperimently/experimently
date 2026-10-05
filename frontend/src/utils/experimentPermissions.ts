/**
 * Whether the API would accept a create from this user.
 *
 * Mirrors `check_permission(user, EXPERIMENT, CREATE)`: a superuser bypasses
 * the role table, otherwise ADMIN and DEVELOPER hold CREATE. A user with a
 * custom role or a direct grant (`GET /api/v1/rbac/users/{id}/permissions`)
 * is not covered here — they are offered creation only if their built-in role
 * allows it, so the UI is never more permissive than the API.
 *
 * Shared by the experiments list (the "+ New Experiment" button) and
 * `/experiments/new` (which shows a notice instead of the form), so the two
 * cannot disagree.
 */
const ROLES_THAT_CAN_CREATE = ['ADMIN', 'DEVELOPER'] as const;

export function canCreateExperiment(
  user: { role?: string; is_superuser?: boolean } | null | undefined,
): boolean {
  // No session yet (the page renders before the context resolves): offer
  // creation rather than flickering it in; the API still decides.
  if (!user) return true;
  if (user.is_superuser) return true;
  return ROLES_THAT_CAN_CREATE.includes(user.role as 'ADMIN' | 'DEVELOPER');
}

/**
 * Whether the API would accept a lifecycle change (start, pause, complete,
 * archive) from this user.
 *
 * Mirrors `deps.get_experiment_change_access`: a superuser is always
 * accepted; otherwise the role must hold EXPERIMENT UPDATE, which ADMIN and
 * DEVELOPER do. Who created the experiment is not part of the question, so an
 * ANALYST or VIEWER is refused on an experiment they own as well.
 *
 * Schedule uses the same check; the dashboard does not offer it. Delete checks
 * EXPERIMENT DELETE instead, which exactly the same roles hold, so the
 * page's "Edit details" and "Delete draft" both use this helper
 * (`backend/tests/unit/core/test_dashboard_experiment_roles.py` keeps the
 * role lists here equal to `permissions.py`).
 */
const ROLES_THAT_CAN_CHANGE = ['ADMIN', 'DEVELOPER'] as const;

export function canChangeExperiment(
  user: { role?: string | null; is_superuser?: boolean } | null | undefined,
): boolean {
  // No session yet: keep the buttons rather than flickering them in; the
  // API still decides.
  if (!user) return true;
  if (user.is_superuser) return true;
  return ROLES_THAT_CAN_CHANGE.includes(user.role as 'ADMIN' | 'DEVELOPER');
}
