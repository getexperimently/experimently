import React from 'react';
import {
  TargetingCondition,
  OperatorType,
  COMMON_ATTRIBUTES,
  OPERATOR_LABELS,
} from '@/types/targeting';
import { getOperatorsForAttribute } from '@/utils/targeting';

interface ConditionRowProps {
  condition: TargetingCondition;
  onChange: (updated: TargetingCondition) => void;
  onRemove: () => void;
  readOnly?: boolean;
}

const NO_VALUE_OPERATORS: OperatorType[] = ['is_null', 'is_not_null'];
const MULTI_VALUE_OPERATORS: OperatorType[] = ['in', 'not_in'];

export function ConditionRow({ condition, onChange, onRemove, readOnly = false }: ConditionRowProps) {
  const availableOperators = getOperatorsForAttribute(condition.attribute);
  const showValueInput = !NO_VALUE_OPERATORS.includes(condition.operator);
  const isMultiValue = MULTI_VALUE_OPERATORS.includes(condition.operator);

  const handleAttributeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newAttribute = e.target.value;
    const newOperators = getOperatorsForAttribute(newAttribute);
    // If current operator is not in new operator list, reset to first available
    const newOperator = newOperators.includes(condition.operator)
      ? condition.operator
      : newOperators[0];
    onChange({ ...condition, attribute: newAttribute, operator: newOperator });
  };

  const handleOperatorChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newOperator = e.target.value as OperatorType;
    const newValue = NO_VALUE_OPERATORS.includes(newOperator) ? null : condition.value;
    onChange({ ...condition, operator: newOperator, value: newValue });
  };

  const handleValueChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange({ ...condition, value: e.target.value });
  };

  const datalistId = `attr-suggestions-${condition.id}`;

  return (
    <div
      className="flex gap-2 items-center p-2 rounded border border-slate-200"
      data-testid="condition-row"
    >
      {/* Attribute input with datalist */}
      <input
        data-testid="condition-attribute"
        type="text"
        list={datalistId}
        value={condition.attribute}
        onChange={handleAttributeChange}
        disabled={readOnly}
        placeholder="attribute"
        className="flex-1 min-w-0 rounded border border-slate-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-400 disabled:bg-slate-100 disabled:text-slate-500"
      />
      <datalist id={datalistId}>
        {COMMON_ATTRIBUTES.map((attr) => (
          <option key={attr.value} value={attr.value}>
            {attr.label}
          </option>
        ))}
      </datalist>

      {/* Operator dropdown */}
      <select
        data-testid="condition-operator"
        value={condition.operator}
        onChange={handleOperatorChange}
        disabled={readOnly}
        className="rounded border border-slate-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-400 disabled:bg-slate-100 disabled:text-slate-500"
      >
        {availableOperators.map((op) => (
          <option key={op} value={op}>
            {OPERATOR_LABELS[op]}
          </option>
        ))}
      </select>

      {/* Value input (hidden for is_null / is_not_null) */}
      {showValueInput && (
        <input
          data-testid="condition-value"
          type="text"
          value={condition.value === null || condition.value === undefined ? '' : String(condition.value)}
          onChange={handleValueChange}
          disabled={readOnly}
          placeholder={isMultiValue ? 'value1, value2' : 'value'}
          className="flex-1 min-w-0 rounded border border-slate-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-400 disabled:bg-slate-100 disabled:text-slate-500"
        />
      )}

      {/* Remove button */}
      {!readOnly && (
        <button
          data-testid="condition-remove"
          type="button"
          onClick={onRemove}
          className="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded text-red-500 hover:bg-red-50 hover:text-red-700 transition-colors"
          aria-label="Remove condition"
        >
          &times;
        </button>
      )}
    </div>
  );
}
