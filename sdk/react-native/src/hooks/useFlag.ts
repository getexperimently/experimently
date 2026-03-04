/**
 * useFlag — evaluates a feature flag for the current user.
 *
 * @example
 * ```tsx
 * function DarkModeButton() {
 *   const { value, loading, error } = useFlag('dark-mode');
 *   if (loading) return <ActivityIndicator />;
 *   return <Text>{value ? 'Dark mode ON' : 'Dark mode OFF'}</Text>;
 * }
 * ```
 */

import { useState, useEffect } from 'react';
import { useExperimentationContext } from '../context/ExperimentationContext';
import type { FlagState } from '../types';

/**
 * Evaluates feature flag `flagKey` for the `userId` supplied to the enclosing
 * {@link ExperimentationProvider}.
 *
 * @param flagKey  The feature flag key to evaluate.
 * @param attributes  Optional additional attributes for targeting.
 * @returns `{ value, loading, error }` — `value` is `true` when the flag is
 *   enabled for this user, `false` otherwise.
 */
export function useFlag(
  flagKey: string,
  attributes?: Record<string, unknown>
): FlagState {
  const { client, userId, attributes: ctxAttrs } = useExperimentationContext();
  const mergedAttrs = attributes ?? ctxAttrs;

  const [state, setState] = useState<FlagState>({
    value: false,
    loading: true,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;

    setState({ value: false, loading: true, error: null });

    client
      .evaluateFlag(flagKey, userId, mergedAttrs)
      .then((value) => {
        if (!cancelled) {
          setState({ value, loading: false, error: null });
        }
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setState({ value: false, loading: false, error });
        }
      });

    return () => {
      cancelled = true;
    };
    // Re-evaluate when client, userId, or flagKey changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, userId, flagKey]);

  return state;
}
