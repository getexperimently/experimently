import React from 'react';
import { TargetingRuleGroup, TargetingCondition, LogicalOperator } from '@/types/targeting';
import { createEmptyCondition } from '@/utils/targeting';
import { ConditionRow } from './ConditionRow';

interface RuleGroupCardProps {
  group: TargetingRuleGroup;
  groupIndex: number;
  isFirst: boolean;
  onChange: (updated: TargetingRuleGroup) => void;
  onRemove: () => void;
  readOnly?: boolean;
}

export function RuleGroupCard({
  group,
  groupIndex,
  isFirst,
  onChange,
  onRemove,
  readOnly = false,
}: RuleGroupCardProps) {
  const handleLogicalOperatorChange = (op: LogicalOperator) => {
    onChange({ ...group, logical_operator: op });
  };

  const handleAddCondition = () => {
    onChange({
      ...group,
      conditions: [...group.conditions, createEmptyCondition()],
    });
  };

  const handleConditionChange = (index: number, updated: TargetingCondition) => {
    const newConditions = group.conditions.map((c, i) => (i === index ? updated : c));
    onChange({ ...group, conditions: newConditions });
  };

  const handleRemoveCondition = (index: number) => {
    const newConditions = group.conditions.filter((_, i) => i !== index);
    onChange({ ...group, conditions: newConditions });
  };

  return (
    <div className="border border-blue-200 rounded-lg p-4 bg-blue-50">
      {/* Header row */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold text-blue-800">
          Group {groupIndex + 1}
        </span>
        <div className="flex items-center gap-2">
          {/* AND/OR toggle */}
          <div className="flex rounded overflow-hidden border border-blue-300">
            <button
              data-testid="group-logical-and"
              type="button"
              disabled={readOnly}
              onClick={() => handleLogicalOperatorChange('AND')}
              className={`px-2 py-0.5 text-xs font-medium transition-colors disabled:opacity-50 ${
                group.logical_operator === 'AND'
                  ? 'bg-blue-600 text-white'
                  : 'bg-white text-blue-600 hover:bg-blue-50'
              }`}
            >
              AND
            </button>
            <button
              data-testid="group-logical-or"
              type="button"
              disabled={readOnly}
              onClick={() => handleLogicalOperatorChange('OR')}
              className={`px-2 py-0.5 text-xs font-medium transition-colors disabled:opacity-50 ${
                group.logical_operator === 'OR'
                  ? 'bg-blue-600 text-white'
                  : 'bg-white text-blue-600 hover:bg-blue-50'
              }`}
            >
              OR
            </button>
          </div>

          {/* Remove group button */}
          {!readOnly && (
            <button
              data-testid="remove-group"
              type="button"
              onClick={onRemove}
              className="text-xs text-red-500 hover:text-red-700 px-2 py-0.5 rounded hover:bg-red-50 transition-colors border border-red-200"
              aria-label="Remove group"
            >
              Remove Group
            </button>
          )}
        </div>
      </div>

      {/* Conditions */}
      <div className="space-y-2">
        {group.conditions.map((condition, index) => (
          <div key={condition.id}>
            {/* Condition connector label */}
            {index > 0 && (
              <div className="text-xs text-blue-600 font-medium px-2 py-0.5 text-center">
                {group.logical_operator}
              </div>
            )}
            <ConditionRow
              condition={condition}
              onChange={(updated) => handleConditionChange(index, updated)}
              onRemove={() => handleRemoveCondition(index)}
              readOnly={readOnly}
            />
          </div>
        ))}
      </div>

      {/* Add Condition button */}
      {!readOnly && (
        <button
          data-testid="add-condition"
          type="button"
          onClick={handleAddCondition}
          className="mt-3 text-xs text-blue-600 hover:text-blue-800 px-3 py-1 rounded border border-blue-300 hover:bg-blue-100 transition-colors"
        >
          + Add Condition
        </button>
      )}
    </div>
  );
}
