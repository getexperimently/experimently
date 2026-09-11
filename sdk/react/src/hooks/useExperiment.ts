import { useState, useEffect } from 'react';
import { useExperimentation } from '../context/ExperimentationProvider';
import { defaultAssignment } from '../client/ExperimentationClient';
import { ExperimentAssignment } from '../client/types';

/**
 * Assigns the current user to an experiment via `POST /api/v1/tracking/assign`.
 *
 * While loading or on error the control defaults are returned
 * (`variantKey: 'control'`, `variantName: 'Control'`, `variantId: null`,
 * `isControl: true`, `configuration: null`). Re-assigns when the experiment
 * key or user changes (the server keeps assignments sticky).
 */
export function useExperiment(experimentKey: string): ExperimentAssignment {
  const { client, user } = useExperimentation();
  const [state, setState] = useState<ExperimentAssignment>(() =>
    defaultAssignment(experimentKey, { loading: true })
  );

  useEffect(() => {
    let cancelled = false;
    setState(defaultAssignment(experimentKey, { loading: true }));

    client
      .assignExperiment(user, experimentKey)
      .then(assignment => {
        if (!cancelled) setState(assignment);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const error = err instanceof Error ? err : new Error(String(err));
          setState(defaultAssignment(experimentKey, { error }));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [client, user, experimentKey]);

  return state;
}
