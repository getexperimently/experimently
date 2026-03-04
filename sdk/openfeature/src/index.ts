/**
 * @experimentation-platform/openfeature-provider
 *
 * OpenFeature provider for the Experimentation Platform.
 *
 * @example
 * ```typescript
 * import OpenFeature from '@openfeature/server-sdk';
 * import { ExperimentationProvider } from '@experimentation-platform/openfeature-provider';
 *
 * await OpenFeature.setProviderAndWait(
 *   new ExperimentationProvider({ apiKey: 'my-api-key' })
 * );
 *
 * const client = OpenFeature.getClient();
 * const enabled = await client.getBooleanValue('my-feature', false, {
 *   targetingKey: 'user-123',
 * });
 * ```
 */

export { ExperimentationProvider } from './ExperimentationProvider';
export type { ExperimentationProviderOptions } from './ExperimentationProvider';
export type {
  FeatureFlagDefinition,
  FlagVariant,
  TargetingRule,
  FlagsResponse,
  EvaluateResponse,
  EvalReason,
} from './types';
