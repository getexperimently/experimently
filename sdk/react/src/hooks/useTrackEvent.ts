import { useCallback } from 'react';
import { useExperimentationContext } from '../context/ExperimentationProvider';

export function useTrackEvent(): (eventName: string, properties?: Record<string, unknown>) => void {
  const { client, user } = useExperimentationContext();

  return useCallback(
    (eventName: string, properties?: Record<string, unknown>) => {
      client.trackEvent(user.userId, eventName, properties);
    },
    [client, user.userId]
  );
}
