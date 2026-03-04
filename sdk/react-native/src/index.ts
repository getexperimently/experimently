/**
 * @experimentation-platform/react-native-sdk
 *
 * React Native SDK for the Experimentation Platform.
 *
 * Key exports:
 *   - {@link ExperimentationClient} — core client for flag evaluation, assignments, and tracking.
 *   - {@link ExperimentationProvider} — React context provider.
 *   - {@link useFlag} — hook for feature flag evaluation.
 *   - {@link useExperiment} — hook for experiment assignment.
 *   - {@link useExperimentationClient} — hook for raw client access.
 *   - {@link hashUser} — the cross-SDK consistent hash function (exposed for testing).
 */

// Core client
export { ExperimentationClient } from './client';

// Evaluator (exposed for testing / custom integrations)
export { hashUser, evaluateLocally, assignVariant } from './evaluator';

// Cache & storage
export { EvaluationCache } from './cache';
export { OfflineStorage } from './storage';

// Context & provider
export { ExperimentationContext, useExperimentationContext } from './context/ExperimentationContext';
export { ExperimentationProvider } from './context/ExperimentationProvider';

// Hooks
export { useFlag } from './hooks/useFlag';
export { useExperiment } from './hooks/useExperiment';
export { useExperimentationClient } from './hooks/useExperimentationClient';

// Types
export type {
  SdkConfig,
  FeatureFlag,
  ExperimentAssignment,
  FlagState,
  ExperimentState,
  CacheEntry,
} from './types';
export type {
  ExperimentationContextValue,
} from './context/ExperimentationContext';
export type {
  ExperimentationProviderProps,
} from './context/ExperimentationProvider';
