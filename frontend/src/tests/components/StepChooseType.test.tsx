import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { StepChooseType } from '@/components/experiments/Wizard/StepChooseType';

describe('StepChooseType', () => {
  it('renders three experiment type cards', () => {
    const onChange = jest.fn();
    render(<StepChooseType value={null} onChange={onChange} />);
    expect(screen.getByTestId('type-ab')).toBeInTheDocument();
    expect(screen.getByTestId('type-multivariate')).toBeInTheDocument();
    expect(screen.getByTestId('type-rollout')).toBeInTheDocument();
  });

  it('clicking the A/B card calls onChange with "ab"', () => {
    const onChange = jest.fn();
    render(<StepChooseType value={null} onChange={onChange} />);
    fireEvent.click(screen.getByTestId('type-ab'));
    expect(onChange).toHaveBeenCalledWith('ab');
  });

  it('clicking the multivariate card calls onChange with "multivariate"', () => {
    const onChange = jest.fn();
    render(<StepChooseType value={null} onChange={onChange} />);
    fireEvent.click(screen.getByTestId('type-multivariate'));
    expect(onChange).toHaveBeenCalledWith('multivariate');
  });

  it('clicking the rollout card calls onChange with "feature_flag_rollout"', () => {
    const onChange = jest.fn();
    render(<StepChooseType value={null} onChange={onChange} />);
    fireEvent.click(screen.getByTestId('type-rollout'));
    expect(onChange).toHaveBeenCalledWith('feature_flag_rollout');
  });

  it('selected card has different aria-pressed state', () => {
    render(<StepChooseType value="ab" onChange={jest.fn()} />);
    const abCard = screen.getByTestId('type-ab');
    expect(abCard).toHaveAttribute('aria-pressed', 'true');
  });

  it('non-selected cards have aria-pressed=false', () => {
    render(<StepChooseType value="ab" onChange={jest.fn()} />);
    expect(screen.getByTestId('type-multivariate')).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByTestId('type-rollout')).toHaveAttribute('aria-pressed', 'false');
  });

  it('renders the step-choose-type container', () => {
    render(<StepChooseType value={null} onChange={jest.fn()} />);
    expect(screen.getByTestId('step-choose-type')).toBeInTheDocument();
  });

  it('renders card labels', () => {
    render(<StepChooseType value={null} onChange={jest.fn()} />);
    expect(screen.getByText('A/B Test')).toBeInTheDocument();
    expect(screen.getByText('Multivariate')).toBeInTheDocument();
    expect(screen.getByText('Feature Flag Rollout')).toBeInTheDocument();
  });
});
