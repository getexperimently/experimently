import { ApiError } from '@/services/api';

/**
 * What a failed create shows, in either view of `/experiments/new`.
 *
 * Mapped by HTTP status only. The API answers a taken key with 409 and a
 * plain message (#395), so nothing here reads the words of an error to decide
 * what it is, and the 409's own text is never shown: the page says it in its
 * own words, with the key it sent.
 */
export interface CreateError {
  message: string;
  /** The problem is the key: offer "Edit details", which goes to the key field. */
  editDetails?: boolean;
}

export const ROLE_CANNOT_CREATE =
  'Your role can view experiments but not create them. Ask an admin to create it or to change your role.';

export const SESSION_EXPIRED_CREATE =
  'Your session has expired. Sign in again in another tab, then press Create Experiment again. Your answers are still here.';

export type CreateView = 'guided' | 'advanced';

/** The duplicate-key copy. `key` is the key the page sent. */
export function duplicateKeyMessage(key: string | undefined, view: CreateView): string {
  const head = key
    ? `An experiment with the key “${key}” already exists.`
    : 'An experiment with this key already exists.';
  return view === 'guided'
    ? `${head} Choose a different key on the Details step.`
    : `${head} Choose a different key.`;
}

function sentence(text: string): string {
  const t = text.trim();
  return /[.!?]$/.test(t) ? t : `${t}.`;
}

/**
 * The error a view shows for a create that failed with `err`.
 *
 * - 401: the session copy. The create is sent with `redirectOn401: false`, so
 *   the page stays and the answers with it.
 * - 403: the API's reason, then what the role means and who can help.
 * - 409: the key is taken; the page's own sentence and "Edit details".
 * - anything else: the message the API client built (for a server error it
 *   carries the request ID once).
 */
export function describeCreateError(err: unknown, sentKey: string | undefined, view: CreateView): CreateError {
  if (err instanceof ApiError) {
    if (err.status === 401) return { message: SESSION_EXPIRED_CREATE };
    if (err.status === 403) return { message: `${sentence(err.message)} ${ROLE_CANNOT_CREATE}` };
    if (err.status === 409) return { message: duplicateKeyMessage(sentKey, view), editDetails: true };
  }
  return { message: err instanceof Error ? err.message : 'Failed to create experiment' };
}
