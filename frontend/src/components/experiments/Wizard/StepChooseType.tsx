import React from 'react';

interface StepChooseTypeProps {
  value: string | null;
  onChange: (type: string) => void;
}

interface ExperimentTypeCard {
  id: string;
  label: string;
  description: string;
  testId: string;
}

const EXPERIMENT_TYPES: ExperimentTypeCard[] = [
  {
    id: 'ab',
    label: 'A/B Test',
    description:
      'Compare two variants — a control and a single treatment — to measure the impact of one change.',
    testId: 'type-ab',
  },
  {
    id: 'multivariate',
    label: 'Multivariate',
    description:
      'Test multiple variants simultaneously to understand how different combinations of changes perform.',
    testId: 'type-multivariate',
  },
  {
    id: 'feature_flag_rollout',
    label: 'Feature Flag Rollout',
    description:
      'Gradually roll out a feature to a percentage of users and measure its effect before full launch.',
    testId: 'type-rollout',
  },
];

/**
 * Wizard step 1 — choose the experiment type.
 * Renders three selectable cards: A/B Test, Multivariate, Feature Flag Rollout.
 */
export function StepChooseType({ value, onChange }: StepChooseTypeProps) {
  return (
    <div data-testid="step-choose-type" className="space-y-4">
      <div className="mb-6">
        <h2 className="text-xl font-semibold text-slate-800">
          What kind of experiment do you want to run?
        </h2>
        <p className="text-sm text-slate-500 mt-1">
          Choose the experiment type that best fits your goal.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {EXPERIMENT_TYPES.map((type) => {
          const isSelected = value === type.id;
          return (
            <button
              key={type.id}
              type="button"
              data-testid={type.testId}
              onClick={() => onChange(type.id)}
              className={`text-left p-5 rounded-lg border-2 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-400 ${
                isSelected
                  ? 'border-blue-600 bg-blue-50'
                  : 'border-slate-200 bg-white hover:border-slate-400 hover:bg-slate-50'
              }`}
              aria-pressed={isSelected}
            >
              <div
                className={`text-base font-semibold mb-2 ${
                  isSelected ? 'text-blue-700' : 'text-slate-800'
                }`}
              >
                {type.label}
              </div>
              <div className="text-sm text-slate-500">{type.description}</div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
