import { useCallback } from 'react';
import { useExperimentation } from '../context/ExperimentationProvider';
import { TrackEventOptions } from '../client/types';

export type TrackEventFn = (
  eventName: string,
  properties?: Record<string, unknown>,
  options?: TrackEventOptions
) => void;

/**
 * Returns a stable fire-and-forget `track(eventName, properties?, options?)`
 * bound to the current user.
 *
 * Without `options.experimentKey` / `options.featureFlagKey` the event is
 * fanned out to every experiment and flag the client has cached for the user.
 */
export function useTrackEvent(): TrackEventFn {
  const { client, user } = useExperimentation();

  return useCallback<TrackEventFn>(
    (eventName, properties, options) => {
      void client.trackEvent(user.userId, eventName, properties, options);
    },
    [client, user.userId]
  );
}
