import { useState, useEffect } from 'react';
import { useExperimentationContext } from '../context/ExperimentationProvider';
import { ExperimentAssignment } from '../client/types';

export function useExperiment(experimentKey: string): ExperimentAssignment {
  const { client, user } = useExperimentationContext();
  const [state, setState] = useState<ExperimentAssignment>({
    experimentKey,
    variantKey: 'control',
    variantName: 'Control',
    loading: true,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;

    // Use feature flag evaluation as a proxy for experiment assignment.
    // Full experiment assignment API will be added in Batch 2.
    client
      .evaluateFeatureFlag(user, experimentKey)
      .then(variant => {
        if (!cancelled) {
          const variantKey = variant ?? 'control';
          setState({
            experimentKey,
            variantKey,
            variantName: variantKey.charAt(0).toUpperCase() + variantKey.slice(1),
            loading: false,
            error: null,
          });
        }
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setState(prev => ({ ...prev, variantKey: 'control', loading: false, error }));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [client, user.userId, experimentKey]);

  return state;
}
