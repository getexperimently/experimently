import React, { createContext, useContext, useMemo, ReactNode } from 'react';
import { ExperimentationClient } from '../client/ExperimentationClient';
import { SdkConfig, UserContext } from '../client/types';

interface ExperimentationContextValue {
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
  // Stabilise the client — only recreate when apiKey or baseUrl changes
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const client = useMemo(
    () => new ExperimentationClient(config),
    // Intentionally omit full config object to avoid recreating on every render;
    // callers should memoize config or pass stable primitives.
    [config.apiKey, config.baseUrl]
  );

  const value = useMemo(() => ({ client, user }), [client, user.userId]);

  return (
    <ExperimentationContext.Provider value={value}>
      {children}
    </ExperimentationContext.Provider>
  );
}

export function useExperimentationContext(): ExperimentationContextValue {
  const ctx = useContext(ExperimentationContext);
  if (!ctx) {
    throw new Error('useExperimentationContext must be used within ExperimentationProvider');
  }
  return ctx;
}
