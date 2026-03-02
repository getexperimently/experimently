import React from 'react';

interface WizardStepperProps {
  steps: string[];
  currentStep: number;
}

/**
 * Step indicator for the experiment creation wizard.
 * Shows completed / active / pending state for each step.
 */
export function WizardStepper({ steps, currentStep }: WizardStepperProps) {
  return (
    <div data-testid="wizard-stepper" className="flex items-center justify-between w-full mb-8">
      {steps.map((step, index) => {
        const isCompleted = index < currentStep;
        const isActive = index === currentStep;
        const isPending = index > currentStep;

        let pillClass =
          'flex-1 flex flex-col items-center gap-1 relative';

        let circleClass =
          'w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold border-2 transition-colors ';

        if (isCompleted) {
          circleClass += 'bg-green-500 border-green-500 text-white';
        } else if (isActive) {
          circleClass += 'bg-blue-600 border-blue-600 text-white';
        } else {
          circleClass += 'bg-white border-slate-300 text-slate-400';
        }

        const labelClass = isActive
          ? 'text-xs font-semibold text-blue-600 text-center'
          : isCompleted
          ? 'text-xs font-medium text-green-600 text-center'
          : 'text-xs text-slate-400 text-center';

        return (
          <React.Fragment key={index}>
            <div
              data-testid={`step-${index}`}
              data-completed={isCompleted}
              data-active={isActive}
              data-pending={isPending}
              className={pillClass}
            >
              <div className={circleClass}>
                {isCompleted ? (
                  <svg
                    className="w-4 h-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={3}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                ) : (
                  <span>{index + 1}</span>
                )}
              </div>
              <span className={labelClass}>{step}</span>
            </div>
            {index < steps.length - 1 && (
              <div
                className={`h-0.5 flex-1 mx-1 mt-4 mb-auto transition-colors ${
                  index < currentStep ? 'bg-green-400' : 'bg-slate-200'
                }`}
              />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}
