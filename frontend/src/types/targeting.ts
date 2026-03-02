export type OperatorType =
  | 'equals' | 'not_equals' | 'contains' | 'not_contains'
  | 'starts_with' | 'ends_with' | 'greater_than' | 'less_than'
  | 'greater_than_or_equal' | 'less_than_or_equal'
  | 'in' | 'not_in' | 'regex' | 'is_null' | 'is_not_null'
  | 'semver_eq' | 'semver_gt' | 'semver_lt' | 'semver_gte' | 'semver_lte'
  | 'geo_within_radius' | 'time_window' | 'array_contains' | 'array_intersects';

export type LogicalOperator = 'AND' | 'OR';

export interface TargetingCondition {
  id: string;
  attribute: string;
  operator: OperatorType;
  value: string | number | boolean | string[] | null;
}

export interface TargetingRuleGroup {
  id: string;
  logical_operator: LogicalOperator;
  conditions: TargetingCondition[];
}

export interface TargetingRules {
  logical_operator: LogicalOperator;
  groups: TargetingRuleGroup[];
}

export interface AttributeSuggestion {
  value: string;
  label: string;
  type: 'string' | 'number' | 'boolean' | 'array' | 'semver';
  examples?: string[];
}

export const COMMON_ATTRIBUTES: AttributeSuggestion[] = [
  { value: 'user.country', label: 'User Country', type: 'string', examples: ['US', 'UK', 'DE'] },
  { value: 'user.plan', label: 'User Plan', type: 'string', examples: ['free', 'pro', 'enterprise'] },
  { value: 'user.age', label: 'User Age', type: 'number' },
  { value: 'user.email', label: 'User Email', type: 'string' },
  { value: 'device.type', label: 'Device Type', type: 'string', examples: ['mobile', 'desktop', 'tablet'] },
  { value: 'app.version', label: 'App Version', type: 'semver', examples: ['1.0.0', '2.3.1'] },
  { value: 'session.new_user', label: 'New User', type: 'boolean' },
  { value: 'user.tags', label: 'User Tags', type: 'array' },
];

export const OPERATORS_BY_TYPE: Record<string, OperatorType[]> = {
  string: ['equals', 'not_equals', 'contains', 'not_contains', 'starts_with', 'ends_with', 'regex', 'in', 'not_in', 'is_null', 'is_not_null'],
  number: ['equals', 'not_equals', 'greater_than', 'less_than', 'greater_than_or_equal', 'less_than_or_equal', 'in', 'not_in', 'is_null', 'is_not_null'],
  boolean: ['equals', 'not_equals', 'is_null', 'is_not_null'],
  array: ['array_contains', 'array_intersects', 'is_null', 'is_not_null'],
  semver: ['semver_eq', 'semver_gt', 'semver_lt', 'semver_gte', 'semver_lte'],
};

export const OPERATOR_LABELS: Record<OperatorType, string> = {
  equals: 'equals',
  not_equals: 'does not equal',
  contains: 'contains',
  not_contains: 'does not contain',
  starts_with: 'starts with',
  ends_with: 'ends with',
  greater_than: 'greater than',
  less_than: 'less than',
  greater_than_or_equal: 'greater than or equal to',
  less_than_or_equal: 'less than or equal to',
  in: 'is one of',
  not_in: 'is not one of',
  regex: 'matches regex',
  is_null: 'is empty',
  is_not_null: 'is not empty',
  semver_eq: 'version equals',
  semver_gt: 'version greater than',
  semver_lt: 'version less than',
  semver_gte: 'version >=',
  semver_lte: 'version <=',
  geo_within_radius: 'within radius of',
  time_window: 'within time window',
  array_contains: 'array contains',
  array_intersects: 'array intersects',
};
