/**
 * useExperimentationClient — returns the raw ExperimentationClient and user
 * context from the enclosing ExperimentationProvider.
 *
 * Use this hook when you need direct access to the client (e.g. to call
 * `client.track()` imperatively or `client.clearCache()`).
 *
 * @example
 * ```tsx
 * function TrackButton() {
 *   const { client, userId } = useExperimentationClient();
 *   return (
 *     <Button onPress={() => client.track('cta_clicked', userId)} title="Click me" />
 *   );
 * }
 * ```
 */

import { useExperimentationContext } from '../context/ExperimentationContext';
import type { ExperimentationContextValue } from '../context/ExperimentationContext';

/**
 * Returns `{ client, userId, attributes }` from the enclosing
 * {@link ExperimentationProvider}.
 *
 * Throws if called outside of a provider.
 */
export function useExperimentationClient(): ExperimentationContextValue {
  return useExperimentationContext();
}
