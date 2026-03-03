import { useFeatureFlag } from './useFeatureFlag';

/**
 * Simplified hook that returns just the variant string (or null if disabled/loading).
 *
 * Use this when you only need to know which variant a user is in
 * and don't need loading/error state from useFeatureFlag.
 */
export function useVariant(flagKey: string): string | null {
  const { variant } = useFeatureFlag(flagKey);
  return variant;
}
