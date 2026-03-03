import React from 'react';
import { useFeatureFlag } from '../hooks/useFeatureFlag';
import { FeatureFlagEvaluation } from '../client/types';

/**
 * Higher-order component that injects feature flag evaluation as a prop.
 *
 * Wraps WrappedComponent and evaluates the given flagKey, passing the result
 * as the `flagEvaluation` prop. All original props are forwarded unchanged.
 * The `flagEvaluation` prop is stripped from the outward-facing component type —
 * callers do not need to provide it.
 *
 * @example
 * interface MyProps {
 *   flagEvaluation: FeatureFlagEvaluation | null;
 *   title: string;
 * }
 *
 * function MyComponent({ flagEvaluation, title }: MyProps) {
 *   return <div>{flagEvaluation?.isEnabled ? 'New UI' : 'Old UI'} — {title}</div>;
 * }
 *
 * const MyComponentWithFlag = withExperimentation(MyComponent, 'new-ui-flag');
 * // Usage: <MyComponentWithFlag title="hello" />  (no flagEvaluation needed)
 */
export function withExperimentation<P extends { flagEvaluation: FeatureFlagEvaluation | null }>(
  WrappedComponent: React.ComponentType<P>,
  flagKey: string
): React.FC<Omit<P, 'flagEvaluation'>> {
  function WithExperimentationComponent(props: Omit<P, 'flagEvaluation'>) {
    const evaluation = useFeatureFlag(flagKey);
    return <WrappedComponent {...(props as unknown as P)} flagEvaluation={evaluation} />;
  }

  const displayName = WrappedComponent.displayName ?? WrappedComponent.name ?? 'Component';
  WithExperimentationComponent.displayName = `withExperimentation(${displayName})`;

  return WithExperimentationComponent;
}
