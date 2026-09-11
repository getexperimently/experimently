import React, { createContext, useContext, useMemo, ReactNode } from 'react';
import { ExperimentationClient } from '../client/ExperimentationClient';
import { SdkConfig, UserContext } from '../client/types';

export interface ExperimentationContextValue {
  client: ExperimentationClient;
  user: UserContext;
}

const ExperimentationContext = createContext<ExperimentationContextValue | null>(null);

interface ProviderProps {
  config: SdkConfig;
  user: UserContext;
  children: ReactNode;
}

export function ExperimentationProvider({ config, user, children }: ProviderProps) {
  // Stabilise the client — only recreate when a config primitive changes, so
  // callers may pass an inline config object without losing the cache.
  const client = useMemo(
    () => new ExperimentationClient(config),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [config.apiKey, config.baseUrl, config.timeoutMs, config.cacheTtlMs]
  );

  // Stabilise the user reference by content so hooks only re-run when the
  // identity or attributes actually change.
  const attributesKey = JSON.stringify(user.attributes ?? null);
  const value = useMemo(
    () => ({ client, user }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [client, user.userId, attributesKey]
  );

  return (
    <ExperimentationContext.Provider value={value}>
      {children}
    </ExperimentationContext.Provider>
  );
}

/** Access the SDK client and current user. Must be used inside ExperimentationProvider. */
export function useExperimentation(): ExperimentationContextValue {
  const ctx = useContext(ExperimentationContext);
  if (!ctx) {
    throw new Error('useExperimentation must be used within ExperimentationProvider');
  }
  return ctx;
}

/** Alias of {@link useExperimentation}, kept for backwards compatibility. */
export const useExperimentationContext = useExperimentation;
