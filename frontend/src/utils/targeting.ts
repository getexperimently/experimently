import {
  TargetingCondition,
  TargetingRuleGroup,
  TargetingRules,
  OperatorType,
  COMMON_ATTRIBUTES,
  OPERATORS_BY_TYPE,
} from '@/types/targeting';

// Simple counter-based ID generator that works in both browser and Node test environments
let _idCounter = 0;
function generateId(): string {
  _idCounter += 1;
  const timestamp = Date.now();
  return `id-${timestamp}-${_idCounter}`;
}

export function createEmptyCondition(): TargetingCondition {
  return {
    id: generateId(),
    attribute: '',
    operator: 'equals',
    value: '',
  };
}

export function createEmptyGroup(): TargetingRuleGroup {
  return {
    id: generateId(),
    logical_operator: 'AND',
    conditions: [createEmptyCondition()],
  };
}

export function createEmptyRules(): TargetingRules {
  return {
    logical_operator: 'AND',
    groups: [],
  };
}

export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

export function validateRules(rules: TargetingRules): ValidationResult {
  const errors: string[] = [];

  for (let gi = 0; gi < rules.groups.length; gi++) {
    const group = rules.groups[gi];
    for (let ci = 0; ci < group.conditions.length; ci++) {
      const condition = group.conditions[ci];
      const condLabel = `Group ${gi + 1}, Condition ${ci + 1}`;

      if (!condition.attribute || condition.attribute.trim() === '') {
        errors.push(`${condLabel}: attribute is required`);
      }

      if (!condition.operator) {
        errors.push(`${condLabel}: operator is required`);
      }

      const validOperators: OperatorType[] = [
        'equals', 'not_equals', 'contains', 'not_contains',
        'starts_with', 'ends_with', 'greater_than', 'less_than',
        'greater_than_or_equal', 'less_than_or_equal',
        'in', 'not_in', 'regex', 'is_null', 'is_not_null',
        'semver_eq', 'semver_gt', 'semver_lt', 'semver_gte', 'semver_lte',
        'geo_within_radius', 'time_window', 'array_contains', 'array_intersects',
      ];

      if (condition.operator && !validOperators.includes(condition.operator)) {
        errors.push(`${condLabel}: invalid operator "${condition.operator}"`);
      }

      // Value is required unless operator is is_null or is_not_null
      const noValueOperators: OperatorType[] = ['is_null', 'is_not_null'];
      if (!noValueOperators.includes(condition.operator)) {
        if (condition.value === null || condition.value === undefined || condition.value === '') {
          errors.push(`${condLabel}: value is required for operator "${condition.operator}"`);
        }
      }
    }
  }

  return { valid: errors.length === 0, errors };
}

interface ConditionJson {
  attribute: string;
  operator: OperatorType;
  value: string | number | boolean | string[] | null;
}

interface GroupJson {
  logical_operator: string;
  conditions: ConditionJson[];
}

interface RulesJson {
  logical_operator: string;
  groups: GroupJson[];
}

export function rulesToJson(rules: TargetingRules): RulesJson {
  return {
    logical_operator: rules.logical_operator,
    groups: rules.groups.map((group) => ({
      logical_operator: group.logical_operator,
      conditions: group.conditions.map((condition) => ({
        attribute: condition.attribute,
        operator: condition.operator,
        value: condition.value,
      })),
    })),
  };
}

export function jsonToRules(json: object | null): TargetingRules {
  if (!json) {
    return createEmptyRules();
  }

  const raw = json as Partial<RulesJson>;

  return {
    logical_operator: (raw.logical_operator as 'AND' | 'OR') || 'AND',
    groups: (raw.groups || []).map((group) => ({
      id: generateId(),
      logical_operator: (group.logical_operator as 'AND' | 'OR') || 'AND',
      conditions: (group.conditions || []).map((condition) => ({
        id: generateId(),
        attribute: condition.attribute || '',
        operator: (condition.operator as OperatorType) || 'equals',
        value: condition.value ?? '',
      })),
    })),
  };
}

export function getAttributeType(attribute: string): string {
  const found = COMMON_ATTRIBUTES.find((a) => a.value === attribute);
  return found ? found.type : 'string';
}

export function getOperatorsForAttribute(attribute: string): OperatorType[] {
  const type = getAttributeType(attribute);
  return OPERATORS_BY_TYPE[type] || OPERATORS_BY_TYPE['string'];
}
