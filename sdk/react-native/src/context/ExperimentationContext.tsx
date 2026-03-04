/**
 * React context for the ExperimentationClient.
 */

import React from 'react';
import type { ExperimentationClient } from '../client';

export interface ExperimentationContextValue {
  client: ExperimentationClient;
  userId: string;
  attributes?: Record<string, unknown>;
}

export const ExperimentationContext =
  React.createContext<ExperimentationContextValue | null>(null);

ExperimentationContext.displayName = 'ExperimentationContext';

/**
 * Retrieves the ExperimentationContext value.
 * Throws if called outside of an ExperimentationProvider.
 */
export function useExperimentationContext(): ExperimentationContextValue {
  const ctx = React.useContext(ExperimentationContext);
  if (!ctx) {
    throw new Error(
      'useExperimentationContext must be used inside an <ExperimentationProvider>.'
    );
  }
  return ctx;
}
