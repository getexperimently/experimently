import { useState, useEffect } from 'react';
import { useExperimentation } from '../context/ExperimentationProvider';
import { disabledEvaluation } from '../client/ExperimentationClient';
import { FeatureFlagEvaluation } from '../client/types';

/**
 * Evaluates a feature flag for the current user (server-side decision).
 *
 * Starts as `{ isEnabled: false, variant: null, config: null, loading: true }`,
 * re-evaluates when the flag key or user changes, and reports failures via
 * `error` while keeping the flag off.
 */
export function useFeatureFlag(flagKey: string): FeatureFlagEvaluation {
  const { client, user } = useExperimentation();
  const [state, setState] = useState<FeatureFlagEvaluation>(() =>
    disabledEvaluation(flagKey, { loading: true })
  );

  useEffect(() => {
    let cancelled = false;
    setState(disabledEvaluation(flagKey, { loading: true }));

    client
      .evaluateFeatureFlagDetailed(user, flagKey)
      .then(evaluation => {
        if (!cancelled) setState(evaluation);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const error = err instanceof Error ? err : new Error(String(err));
          setState(disabledEvaluation(flagKey, { error }));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [client, user, flagKey]);

  return state;
}
