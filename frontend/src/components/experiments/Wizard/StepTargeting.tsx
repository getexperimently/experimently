import React from 'react';
import { TargetingRuleBuilder } from '@/components/targeting/TargetingRuleBuilder';
import { TargetingRules } from '@/types/targeting';

interface StepTargetingProps {
  value: TargetingRules | null;
  onChange: (rules: TargetingRules) => void;
}

/**
 * Wizard step 3 — configure targeting rules.
 * Wraps the existing TargetingRuleBuilder component.
 * Empty rules mean the experiment targets all users.
 */
export function StepTargeting({ value, onChange }: StepTargetingProps) {
  return (
    <div data-testid="step-targeting" className="space-y-4">
      <div className="mb-6">
        <h2 className="text-xl font-semibold text-slate-800">
          Who should see this experiment?
        </h2>
        <p className="text-sm text-slate-500 mt-1">
          Add targeting rules to restrict the experiment audience. Leave empty to target all users.
        </p>
      </div>

      <TargetingRuleBuilder value={value} onChange={onChange} />
    </div>
  );
}
