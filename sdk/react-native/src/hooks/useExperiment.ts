/**
 * useExperiment — retrieves the experiment variant for the current user.
 *
 * @example
 * ```tsx
 * function CheckoutPage() {
 *   const { variant, loading } = useExperiment('checkout-experiment');
 *   if (loading) return <ActivityIndicator />;
 *   return variant === 'treatment' ? <NewCheckout /> : <OldCheckout />;
 * }
 * ```
 */

import { useState, useEffect } from 'react';
import { useExperimentationContext } from '../context/ExperimentationContext';
import type { ExperimentState } from '../types';

/**
 * Returns the variant key for the current user in experiment `experimentKey`.
 *
 * @param experimentKey  The experiment key to retrieve an assignment for.
 * @returns `{ variant, loading, error }` — `variant` is `null` when the user
 *   is not assigned or the call fails.
 */
export function useExperiment(experimentKey: string): ExperimentState {
  const { client, userId, attributes } = useExperimentationContext();

  const [state, setState] = useState<ExperimentState>({
    variant: null,
    loading: true,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;

    setState({ variant: null, loading: true, error: null });

    client
      .getAssignment(experimentKey, userId, attributes)
      .then((variant) => {
        if (!cancelled) {
          setState({ variant, loading: false, error: null });
        }
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setState({ variant: null, loading: false, error });
        }
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, userId, experimentKey]);

  return state;
}
