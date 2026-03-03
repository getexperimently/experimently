import { useState, useEffect } from 'react';
import { useExperimentationContext } from '../context/ExperimentationProvider';
import { FeatureFlagEvaluation } from '../client/types';

export function useFeatureFlag(flagKey: string): FeatureFlagEvaluation {
  const { client, user } = useExperimentationContext();
  const [state, setState] = useState<FeatureFlagEvaluation>({
    flagKey,
    variant: null,
    isEnabled: false,
    loading: true,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;
    setState(prev => ({ ...prev, loading: true, error: null }));

    client
      .evaluateFeatureFlag(user, flagKey)
      .then(variant => {
        if (!cancelled) {
          setState({
            flagKey,
            variant,
            isEnabled: variant !== null,
            loading: false,
            error: null,
          });
        }
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setState({
            flagKey,
            variant: null,
            isEnabled: false,
            loading: false,
            error,
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [client, user.userId, flagKey]);

  return state;
}
