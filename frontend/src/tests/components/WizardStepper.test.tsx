import React from 'react';
import { render, screen } from '@testing-library/react';
import { WizardStepper } from '@/components/experiments/Wizard/WizardStepper';

const STEPS = ['Choose Type', 'Hypothesis', 'Targeting', 'Sample Size', 'Review'];

describe('WizardStepper', () => {
  it('renders all steps', () => {
    render(<WizardStepper steps={STEPS} currentStep={0} />);
    STEPS.forEach((step) => {
      expect(screen.getByText(step)).toBeInTheDocument();
    });
  });

  it('renders the correct number of step indicators', () => {
    render(<WizardStepper steps={STEPS} currentStep={0} />);
    STEPS.forEach((_, index) => {
      expect(screen.getByTestId(`step-${index}`)).toBeInTheDocument();
    });
  });

  it('marks the current step as active', () => {
    render(<WizardStepper steps={STEPS} currentStep={2} />);
    const activeStep = screen.getByTestId('step-2');
    expect(activeStep).toHaveAttribute('data-active', 'true');
  });

  it('marks steps before current as completed', () => {
    render(<WizardStepper steps={STEPS} currentStep={3} />);
    // Steps 0, 1, 2 should be completed
    expect(screen.getByTestId('step-0')).toHaveAttribute('data-completed', 'true');
    expect(screen.getByTestId('step-1')).toHaveAttribute('data-completed', 'true');
    expect(screen.getByTestId('step-2')).toHaveAttribute('data-completed', 'true');
  });

  it('marks steps after current as pending', () => {
    render(<WizardStepper steps={STEPS} currentStep={1} />);
    // Steps 2, 3, 4 should be pending
    expect(screen.getByTestId('step-2')).toHaveAttribute('data-pending', 'true');
    expect(screen.getByTestId('step-3')).toHaveAttribute('data-pending', 'true');
    expect(screen.getByTestId('step-4')).toHaveAttribute('data-pending', 'true');
  });

  it('renders the wizard-stepper container', () => {
    render(<WizardStepper steps={STEPS} currentStep={0} />);
    expect(screen.getByTestId('wizard-stepper')).toBeInTheDocument();
  });

  it('shows step 0 as active and the rest as pending when on first step', () => {
    render(<WizardStepper steps={STEPS} currentStep={0} />);
    expect(screen.getByTestId('step-0')).toHaveAttribute('data-active', 'true');
    expect(screen.getByTestId('step-1')).toHaveAttribute('data-pending', 'true');
    expect(screen.getByTestId('step-4')).toHaveAttribute('data-pending', 'true');
  });

  it('shows all steps completed except last when on last step', () => {
    render(<WizardStepper steps={STEPS} currentStep={4} />);
    expect(screen.getByTestId('step-0')).toHaveAttribute('data-completed', 'true');
    expect(screen.getByTestId('step-4')).toHaveAttribute('data-active', 'true');
  });
});
