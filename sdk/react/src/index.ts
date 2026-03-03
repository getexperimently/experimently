export { ExperimentationProvider } from './context/ExperimentationProvider';
export { useFeatureFlag } from './hooks/useFeatureFlag';
export { useExperiment } from './hooks/useExperiment';
export { useTrackEvent } from './hooks/useTrackEvent';
export { useVariant } from './hooks/useVariant';
export { useMultipleFlags } from './hooks/useMultipleFlags';
export { ExperimentationClient } from './client/ExperimentationClient';
export { ServerClient } from './client/ServerClient';
export { withExperimentation } from './hoc/withExperimentation';
export type {
  SdkConfig,
  UserContext,
  FeatureFlag,
  FeatureFlagEvaluation,
  ExperimentAssignment,
} from './client/types';
