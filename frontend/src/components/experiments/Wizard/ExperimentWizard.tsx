'use client';

import React, { useState } from 'react';
import { WizardStepper } from './WizardStepper';
import { StepChooseType } from './StepChooseType';
import { StepDefineHypothesis } from './StepDefineHypothesis';
import { StepTargeting } from './StepTargeting';
import { StepSampleSize } from './StepSampleSize';
import { StepReview } from './StepReview';
import { TargetingRules } from '@/types/targeting';

interface ExperimentWizardProps {
  onComplete: (experimentId: string) => void;
  onCancel: () => void;
}

interface WizardState {
  experimentType: string | null;
  hypothesis: string;
  primaryMetricId: string | null;
  targetingRules: TargetingRules | null;
  baselineRate: number;
  mde: number;
}

const WIZARD_STEP_LABELS = [
  'Choose Type',
  'Hypothesis',
  'Targeting',
  'Sample Size',
  'Review',
];

const INITIAL_STATE: WizardState = {
  experimentType: null,
  hypothesis: '',
  primaryMetricId: null,
  targetingRules: null,
  baselineRate: 0.1,
  mde: 0.05,
};

/** Simple two-proportion sample size calculation (80% power, 95% CI). */
function computeSampleSize(baselineRate: number, mde: number): number {
  const p1 = baselineRate;
  const p2 = baselineRate + mde;
  const z_alpha = 1.96; // 95% confidence (two-tailed)
  const z_beta = 0.8416; // 80% power
  const pooled = (p1 + p2) / 2;
  const numerator = Math.pow(z_alpha * Math.sqrt(2 * pooled * (1 - pooled)) + z_beta * Math.sqrt(p1 * (1 - p1) + p2 * (1 - p2)), 2);
  const denominator = Math.pow(p2 - p1, 2);
  return Math.ceil(numerator / denominator);
}

/**
 * ExperimentWizard — container orchestrating all wizard steps.
 * Manages step navigation and accumulated wizard state.
 */
export function ExperimentWizard({ onComplete, onCancel }: ExperimentWizardProps) {
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [wizardState, setWizardState] = useState<WizardState>(INITIAL_STATE);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const totalSteps = WIZARD_STEP_LABELS.length;
  const isFirstStep = currentStepIndex === 0;
  const isLastStep = currentStepIndex === totalSteps - 1;

  const goNext = () => {
    if (!isLastStep) {
      setCurrentStepIndex((prev) => prev + 1);
    }
  };

  const goBack = () => {
    if (!isFirstStep) {
      setCurrentStepIndex((prev) => prev - 1);
    }
  };

  const handleLaunch = async () => {
    setIsSubmitting(true);
    try {
      // In production: POST to /api/v1/wizard/drafts/{id}/submit
      // For now simulate with a placeholder experiment ID.
      const mockExperimentId = `exp-${Date.now()}`;
      onComplete(mockExperimentId);
    } finally {
      setIsSubmitting(false);
    }
  };

  const requiredSampleSize = computeSampleSize(wizardState.baselineRate, wizardState.mde);

  const renderStep = () => {
    switch (currentStepIndex) {
      case 0:
        return (
          <StepChooseType
            value={wizardState.experimentType}
            onChange={(type) =>
              setWizardState((prev) => ({ ...prev, experimentType: type }))
            }
          />
        );
      case 1:
        return (
          <StepDefineHypothesis
            hypothesis={wizardState.hypothesis}
            onHypothesisChange={(h) =>
              setWizardState((prev) => ({ ...prev, hypothesis: h }))
            }
            primaryMetricId={wizardState.primaryMetricId}
            onMetricChange={(id) =>
              setWizardState((prev) => ({ ...prev, primaryMetricId: id }))
            }
          />
        );
      case 2:
        return (
          <StepTargeting
            value={wizardState.targetingRules}
            onChange={(rules) =>
              setWizardState((prev) => ({ ...prev, targetingRules: rules }))
            }
          />
        );
      case 3:
        return (
          <StepSampleSize
            baselineRate={wizardState.baselineRate}
            mde={wizardState.mde}
            requiredSampleSize={requiredSampleSize}
            daysEstimate={null}
          />
        );
      case 4:
        return (
          <StepReview
            draft={{
              experimentType: wizardState.experimentType,
              hypothesis: wizardState.hypothesis || null,
              primaryMetricId: wizardState.primaryMetricId,
              baselineRate: wizardState.baselineRate,
              mde: wizardState.mde,
            }}
            onLaunch={handleLaunch}
            isSubmitting={isSubmitting}
          />
        );
      default:
        return null;
    }
  };

  return (
    <div
      data-testid="experiment-wizard"
      className="bg-white rounded-xl shadow-lg border border-slate-200 p-6 max-w-3xl mx-auto"
    >
      {/* Stepper */}
      <WizardStepper steps={WIZARD_STEP_LABELS} currentStep={currentStepIndex} />

      {/* Step content */}
      <div className="min-h-64">{renderStep()}</div>

      {/* Navigation buttons */}
      <div className="flex justify-between mt-8 pt-4 border-t border-slate-100">
        <div>
          {!isFirstStep && (
            <button
              type="button"
              data-testid="wizard-back"
              onClick={goBack}
              className="px-4 py-2 text-sm font-medium text-slate-600 border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors"
            >
              Back
            </button>
          )}
        </div>

        <div className="flex gap-3">
          <button
            type="button"
            data-testid="wizard-cancel"
            onClick={onCancel}
            className="px-4 py-2 text-sm font-medium text-slate-500 hover:text-slate-700 transition-colors"
          >
            Cancel
          </button>

          {!isLastStep && (
            <button
              type="button"
              data-testid="wizard-next"
              onClick={goNext}
              className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
            >
              Next
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
