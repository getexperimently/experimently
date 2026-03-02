import React from 'react';
import { TargetingRules, TargetingRuleGroup, LogicalOperator } from '@/types/targeting';
import { createEmptyGroup, createEmptyRules } from '@/utils/targeting';
import { RuleGroupCard } from './RuleGroupCard';

interface TargetingRuleBuilderProps {
  value: TargetingRules | null;
  onChange: (rules: TargetingRules) => void;
  readOnly?: boolean;
  className?: string;
}

export function TargetingRuleBuilder({
  value,
  onChange,
  readOnly = false,
  className = '',
}: TargetingRuleBuilderProps) {
  const rules = value ?? createEmptyRules();

  const totalConditions = rules.groups.reduce(
    (sum, group) => sum + group.conditions.length,
    0
  );

  const handleRootLogicalOperatorChange = (op: LogicalOperator) => {
    onChange({ ...rules, logical_operator: op });
  };

  const handleAddGroup = () => {
    onChange({ ...rules, groups: [...rules.groups, createEmptyGroup()] });
  };

  const handleGroupChange = (index: number, updated: TargetingRuleGroup) => {
    const newGroups = rules.groups.map((g, i) => (i === index ? updated : g));
    onChange({ ...rules, groups: newGroups });
  };

  const handleRemoveGroup = (index: number) => {
    const newGroups = rules.groups.filter((_, i) => i !== index);
    onChange({ ...rules, groups: newGroups });
  };

  return (
    <div className={`space-y-4 ${className}`}>
      {/* Header row */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-700">Targeting Rules</h3>

        {/* Top-level AND/OR toggle */}
        {rules.groups.length > 0 && (
          <div className="flex rounded overflow-hidden border border-slate-300">
            <button
              data-testid="root-logical-and"
              type="button"
              disabled={readOnly}
              onClick={() => handleRootLogicalOperatorChange('AND')}
              className={`px-3 py-1 text-xs font-medium transition-colors disabled:opacity-50 ${
                rules.logical_operator === 'AND'
                  ? 'bg-slate-700 text-white'
                  : 'bg-white text-slate-600 hover:bg-slate-50'
              }`}
            >
              AND
            </button>
            <button
              data-testid="root-logical-or"
              type="button"
              disabled={readOnly}
              onClick={() => handleRootLogicalOperatorChange('OR')}
              className={`px-3 py-1 text-xs font-medium transition-colors disabled:opacity-50 ${
                rules.logical_operator === 'OR'
                  ? 'bg-slate-700 text-white'
                  : 'bg-white text-slate-600 hover:bg-slate-50'
              }`}
            >
              OR
            </button>
          </div>
        )}
      </div>

      {/* Empty state */}
      {rules.groups.length === 0 && (
        <div className="rounded-lg border-2 border-dashed border-slate-200 p-6 text-center">
          <p className="text-sm text-slate-500 mb-3">
            No targeting rules — all users will match
          </p>
          {!readOnly && (
            <button
              data-testid="add-group"
              type="button"
              onClick={handleAddGroup}
              className="inline-flex items-center gap-1 px-4 py-2 rounded bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 transition-colors"
            >
              + Add Group
            </button>
          )}
        </div>
      )}

      {/* Groups */}
      {rules.groups.length > 0 && (
        <div className="space-y-2">
          {rules.groups.map((group, index) => (
            <div key={group.id}>
              {/* Connector between groups */}
              {index > 0 && (
                <div
                  data-testid="group-connector"
                  className="text-center py-1 text-xs font-bold text-slate-500 uppercase"
                >
                  {rules.logical_operator}
                </div>
              )}
              <RuleGroupCard
                group={group}
                groupIndex={index}
                isFirst={index === 0}
                onChange={(updated) => handleGroupChange(index, updated)}
                onRemove={() => handleRemoveGroup(index)}
                readOnly={readOnly}
              />
            </div>
          ))}
        </div>
      )}

      {/* Add Group button (shown at bottom when groups exist) */}
      {rules.groups.length > 0 && !readOnly && (
        <button
          data-testid="add-group"
          type="button"
          onClick={handleAddGroup}
          className="w-full py-2 rounded border-2 border-dashed border-slate-300 text-sm text-slate-500 hover:border-blue-400 hover:text-blue-600 transition-colors"
        >
          + Add Group
        </button>
      )}

      {/* Summary */}
      {rules.groups.length > 0 && (
        <div
          data-testid="rules-summary"
          className="text-xs text-slate-500"
        >
          {rules.groups.length} {rules.groups.length === 1 ? 'group' : 'groups'},{' '}
          {totalConditions} {totalConditions === 1 ? 'condition' : 'conditions'} total
        </div>
      )}
    </div>
  );
}
