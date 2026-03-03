import { useState, useEffect } from 'react';
import { useExperimentationContext } from '../context/ExperimentationProvider';
import { FeatureFlagEvaluation } from '../client/types';

/**
 * Evaluates multiple feature flags in parallel.
 *
 * Returns a map of flagKey -> FeatureFlagEvaluation (or null during initial load).
 * All flags start as null and are populated once evaluation completes.
 * Re-evaluates when the flagKeys array changes (by JSON comparison).
 */
export function useMultipleFlags(
  flagKeys: string[]
): Record<string, FeatureFlagEvaluation | null> {
  const { client, user } = useExperimentationContext();

  const [state, setState] = useState<Record<string, FeatureFlagEvaluation | null>>(
    () => Object.fromEntries(flagKeys.map(k => [k, null]))
  );

  // Serialise keys to a stable string so useEffect detects changes correctly
  const keysJson = JSON.stringify(flagKeys);

  useEffect(() => {
    // Parse back from JSON so we have the current keys inside the effect
    const keys: string[] = JSON.parse(keysJson);

    if (keys.length === 0) {
      setState({});
      return;
    }

    // Reset to null for all keys while loading
    setState(Object.fromEntries(keys.map(k => [k, null])));

    let cancelled = false;

    Promise.all(
      keys.map(async (flagKey): Promise<[string, FeatureFlagEvaluation]> => {
        try {
          const variant = await client.evaluateFeatureFlag(user, flagKey);
          const evaluation: FeatureFlagEvaluation = {
            flagKey,
            variant,
            isEnabled: variant !== null,
            loading: false,
            error: null,
          };
          return [flagKey, evaluation];
        } catch (err) {
          const error = err instanceof Error ? err : new Error(String(err));
          return [
            flagKey,
            {
              flagKey,
              variant: null,
              isEnabled: false,
              loading: false,
              error,
            },
          ];
        }
      })
    ).then(entries => {
      if (!cancelled) {
        setState(Object.fromEntries(entries));
      }
    });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, user.userId, keysJson]);

  return state;
}
