/**
 * Segment rules on the Segments pages (#440).
 *
 * The server checks a segment's rules when they are saved
 * (`validate_segment_rules`). Rows saved before that check may hold any JSON,
 * and such a segment is never evaluated: flags that use it answer `reason:
 * error` and experiments enrol no new users. `segmentRulesAreValid` mirrors
 * the server's shape checks so the list and the segment's page can say so
 * before anyone asks; the server stays the authority (`/evaluate` answers
 * 409 for these rows, and the page shows the same text).
 */
import { OperatorType, isSegmentOperator } from '@/types/targeting';

const TOP_KEYS = new Set(['logical_operator', 'groups']);
const LOGICAL_OPERATORS = new Set(['AND', 'OR', 'NOT']);

/** Every operator a segment's rules may use: the dashboard operators, without the two segment ones. */
const SEGMENT_RULE_OPERATORS = new Set<OperatorType>([
  'equals', 'not_equals', 'contains', 'not_contains', 'starts_with', 'ends_with',
  'greater_than', 'less_than', 'greater_than_or_equal', 'less_than_or_equal',
  'in', 'not_in', 'regex', 'is_null', 'is_not_null',
  'semver_eq', 'semver_gt', 'semver_lt', 'semver_gte', 'semver_lte',
  'geo_within_radius', 'time_window', 'array_contains', 'array_intersects',
]);

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function logicalOk(value: unknown): boolean {
  return value === undefined || (typeof value === 'string' && LOGICAL_OPERATORS.has(value.toUpperCase()));
}

/**
 * Whether stored rules have the shape the server accepts for a segment:
 * top-level keys within `logical_operator` and `groups`, a non-empty `groups`
 * list, every group a non-empty `conditions` list, every condition an
 * attribute and a dashboard operator that is not a segment operator.
 */
export function segmentRulesAreValid(rules: unknown): boolean {
  if (!isObject(rules)) return false;
  if (!Object.keys(rules).every((key) => TOP_KEYS.has(key))) return false;
  if (!logicalOk(rules.logical_operator)) return false;
  const groups = rules.groups;
  if (!Array.isArray(groups) || groups.length === 0) return false;
  return groups.every((group) => {
    if (!isObject(group) || !logicalOk(group.logical_operator)) return false;
    const conditions = group.conditions;
    if (!Array.isArray(conditions) || conditions.length === 0) return false;
    return conditions.every((condition) => {
      if (!isObject(condition)) return false;
      const { attribute, operator } = condition;
      if (typeof attribute !== 'string' || attribute.trim() === '') return false;
      if (typeof operator !== 'string' || isSegmentOperator(operator)) return false;
      return SEGMENT_RULE_OPERATORS.has(operator as OperatorType);
    });
  });
}
