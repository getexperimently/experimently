/**
 * Whether the API would accept a change to a segment from this user (#440).
 *
 * Segments use the EXPERIMENT permissions (`segments.py`
 * `_require_permission`): create, update, archive and the member routes need
 * EXPERIMENT CREATE, UPDATE or DELETE, which ADMIN and DEVELOPER hold, and a
 * superuser is not limited by the table. ANALYST and VIEWER read only.
 *
 * Unlike `canChangeExperiment`, a user who is not resolved yet gets no write
 * control: the Segments pages render after the session resolves, and the UI
 * is never more permissive than the API.
 */
const ROLES_THAT_CAN_CHANGE = ['ADMIN', 'DEVELOPER'];

export function canChangeSegments(
  user: { role?: string | null; is_superuser?: boolean } | null | undefined,
): boolean {
  if (!user) return false;
  if (user.is_superuser) return true;
  return ROLES_THAT_CAN_CHANGE.indexOf(String(user.role)) !== -1;
}
