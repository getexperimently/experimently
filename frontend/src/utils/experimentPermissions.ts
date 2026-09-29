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
