import { checkTargeting } from '@/components/experiments/new/formState';
import type { AudiencePreview, SegmentKind } from '@/services/segments';
import { formatCount } from '@/utils/segmentIds';
import type { TargetingRules } from '@/types/targeting';

/** What a segment's rule builder says with no groups. */
export const SEGMENT_RULES_EMPTY = 'No conditions yet. A segment needs at least one condition.';

/** Problems found before a segment is sent, in the order the form shows them. */
export function segmentFormProblems(name: string, kind: SegmentKind, rules: TargetingRules): string[] {
  const problems: string[] = [];
  const trimmed = name.trim();
  if (trimmed.length < 2 || trimmed.length > 128) problems.push('Name: 2 to 128 characters.');
  if (kind === 'rules') problems.push(...segmentRulesProblems(rules));
  return problems;
}

/** Problems with a segment's rules found before they are sent. */
export function segmentRulesProblems(rules: TargetingRules): string[] {
  if (rules.groups.length === 0) return [SEGMENT_RULES_EMPTY];
  return checkTargeting(rules);
}

/** The copy for a preview answer; `sample_size: 0` is honest, not a failure. */
export function previewText(preview: AudiencePreview): string {
  if (preview.sample_size === 0) {
    return (
      "No recent assignments carry user attributes, so the size can't be estimated yet. The segment still " +
      "works: it is evaluated against each request's attributes."
    );
  }
  const pct = Math.round(preview.estimated_percentage);
  return `About ${pct}% of ${formatCount(preview.sample_size)} recently assigned users match.`;
}

