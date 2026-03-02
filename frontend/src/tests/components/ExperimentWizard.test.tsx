import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { ExperimentWizard } from '@/components/experiments/Wizard/ExperimentWizard';

describe('ExperimentWizard', () => {
  it('renders the wizard container', () => {
    render(
      <ExperimentWizard onComplete={jest.fn()} onCancel={jest.fn()} />
    );
    expect(screen.getByTestId('experiment-wizard')).toBeInTheDocument();
  });

  it('shows the first step (choose type) initially', () => {
    render(
      <ExperimentWizard onComplete={jest.fn()} onCancel={jest.fn()} />
    );
    expect(screen.getByTestId('step-choose-type')).toBeInTheDocument();
  });

  it('shows the WizardStepper component', () => {
    render(
      <ExperimentWizard onComplete={jest.fn()} onCancel={jest.fn()} />
    );
    expect(screen.getByTestId('wizard-stepper')).toBeInTheDocument();
  });

  it('clicking Next advances to step 2 (define hypothesis)', () => {
    render(
      <ExperimentWizard onComplete={jest.fn()} onCancel={jest.fn()} />
    );
    fireEvent.click(screen.getByTestId('wizard-next'));
    expect(screen.getByTestId('step-define-hypothesis')).toBeInTheDocument();
  });

  it('clicking Back from step 2 returns to step 1', () => {
    render(
      <ExperimentWizard onComplete={jest.fn()} onCancel={jest.fn()} />
    );
    // Advance to step 2
    fireEvent.click(screen.getByTestId('wizard-next'));
    expect(screen.getByTestId('step-define-hypothesis')).toBeInTheDocument();

    // Go back
    fireEvent.click(screen.getByTestId('wizard-back'));
    expect(screen.getByTestId('step-choose-type')).toBeInTheDocument();
  });

  it('calls onCancel when the Cancel button is clicked', () => {
    const onCancel = jest.fn();
    render(
      <ExperimentWizard onComplete={jest.fn()} onCancel={onCancel} />
    );
    fireEvent.click(screen.getByTestId('wizard-cancel'));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('does not show Back button on the first step', () => {
    render(
      <ExperimentWizard onComplete={jest.fn()} onCancel={jest.fn()} />
    );
    expect(screen.queryByTestId('wizard-back')).not.toBeInTheDocument();
  });

  it('shows the Next button on the first step', () => {
    render(
      <ExperimentWizard onComplete={jest.fn()} onCancel={jest.fn()} />
    );
    expect(screen.getByTestId('wizard-next')).toBeInTheDocument();
  });

  it('advances through all steps sequentially', () => {
    render(
      <ExperimentWizard onComplete={jest.fn()} onCancel={jest.fn()} />
    );
    // Step 1 → 2
    fireEvent.click(screen.getByTestId('wizard-next'));
    expect(screen.getByTestId('step-define-hypothesis')).toBeInTheDocument();

    // Step 2 → 3
    fireEvent.click(screen.getByTestId('wizard-next'));
    expect(screen.getByTestId('step-targeting')).toBeInTheDocument();

    // Step 3 → 4
    fireEvent.click(screen.getByTestId('wizard-next'));
    expect(screen.getByTestId('step-sample-size')).toBeInTheDocument();

    // Step 4 → 5 (review)
    fireEvent.click(screen.getByTestId('wizard-next'));
    expect(screen.getByTestId('step-review')).toBeInTheDocument();
  });

  it('shows the launch button on the review step', () => {
    render(
      <ExperimentWizard onComplete={jest.fn()} onCancel={jest.fn()} />
    );
    // Navigate to review step (step 5 = index 4)
    for (let i = 0; i < 4; i++) {
      fireEvent.click(screen.getByTestId('wizard-next'));
    }
    expect(screen.getByTestId('launch-button')).toBeInTheDocument();
  });

  it('does not show Next button on the review (last) step', () => {
    render(
      <ExperimentWizard onComplete={jest.fn()} onCancel={jest.fn()} />
    );
    // Navigate to review step
    for (let i = 0; i < 4; i++) {
      fireEvent.click(screen.getByTestId('wizard-next'));
    }
    expect(screen.queryByTestId('wizard-next')).not.toBeInTheDocument();
  });
});
