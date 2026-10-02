/**
 * Every rule the flag pages' builder can produce, within a fixed grid (#535 V8).
 *
 * One group with one condition per row: each attribute the builder suggests
 * (`COMMON_ATTRIBUTES`) plus four typed by hand, each operator the flag
 * builder offers for it (`getOperatorsForAttribute(attribute,
 * FLAG_OPERATOR_OPTIONS)`), and each value from `BUILDER_VALUES` (the value
 * input is `<input type=text>`, so a value is always text; the no-value
 * operators store null). Two more rows cover the group shapes: a group whose
 * last condition was removed, and two groups joined with OR.
 *
 * `flag-builder-outputs.json` records, per row, what the flag page sends and
 * which of three things happens to it; `flag-builder-outputs.test.ts` and
 * `backend/tests/unit/core/test_flag_builder_outputs.py` check that record
 * from the two sides.
 */
import { COMMON_ATTRIBUTES, TargetingCondition, TargetingRules } from '@/types/targeting';
import { FLAG_OPERATOR_OPTIONS, getOperatorsForAttribute } from '@/utils/targeting';

/** Attributes typed by hand: a valid custom name, two the server's charset refuses, and none at all. */
export const TYPED_ATTRIBUTES = ['os_version', 'plan-tier', 'user country', ''];

/** Values a user types into the value input. */
export const BUILDER_VALUES = ['', ' ', 'US', 'US, CA', '18', 'abc', '1.2.3', 'true', '(['];

const NO_VALUE_OPERATORS = new Set(['is_null', 'is_not_null']);

export interface GridRow {
  name: string;
  rules: TargetingRules;
}

function condition(attribute: string, operator: string, value: TargetingCondition['value']): TargetingCondition {
  return { id: `c-${attribute}-${operator}`, attribute, operator: operator as TargetingCondition['operator'], value };
}

function oneCondition(c: TargetingCondition): TargetingRules {
  return { logical_operator: 'AND', groups: [{ id: 'g-1', logical_operator: 'AND', conditions: [c] }] };
}

export function flagBuilderGrid(): GridRow[] {
  const rows: GridRow[] = [];
  const attributes = [...COMMON_ATTRIBUTES.map((a) => a.value), ...TYPED_ATTRIBUTES];
  for (const attribute of attributes) {
    for (const operator of getOperatorsForAttribute(attribute, FLAG_OPERATOR_OPTIONS)) {
      const values = NO_VALUE_OPERATORS.has(operator) ? [null] : BUILDER_VALUES;
      for (const value of values) {
        rows.push({
          name: `${attribute || '(blank)'}|${operator}|${JSON.stringify(value)}`,
          rules: oneCondition(condition(attribute, operator, value)),
        });
      }
    }
  }
  rows.push({
    name: 'group with its last condition removed',
    rules: { logical_operator: 'AND', groups: [{ id: 'g-1', logical_operator: 'AND', conditions: [] }] },
  });
  rows.push({
    name: 'two groups joined with OR',
    rules: {
      logical_operator: 'OR',
      groups: [
        { id: 'g-1', logical_operator: 'AND', conditions: [condition('user.country', 'in', 'US, CA')] },
        { id: 'g-2', logical_operator: 'AND', conditions: [condition('os_version', 'semver_gte', '1.2.3')] },
      ],
    },
  });
  return rows;
}
