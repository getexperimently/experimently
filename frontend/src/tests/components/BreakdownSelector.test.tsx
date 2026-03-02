import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  BreakdownSelector,
  BREAKDOWN_OPTIONS,
} from '@/components/results/Breakdowns/BreakdownSelector';

describe('BreakdownSelector', () => {
  it('renders the select element with testid', () => {
    render(<BreakdownSelector value={null} onChange={jest.fn()} />);
    expect(screen.getByTestId('breakdown-selector')).toBeInTheDocument();
  });

  it('renders all breakdown options including the empty default', () => {
    render(<BreakdownSelector value={null} onChange={jest.fn()} />);
    const select = screen.getByTestId('breakdown-selector');
    // None option + all BREAKDOWN_OPTIONS
    const options = select.querySelectorAll('option');
    expect(options).toHaveLength(BREAKDOWN_OPTIONS.length + 1);
    expect(screen.getByRole('option', { name: '— None —' })).toBeInTheDocument();
  });

  it('reflects the current value as selected', () => {
    render(<BreakdownSelector value="country" onChange={jest.fn()} />);
    const select = screen.getByTestId('breakdown-selector') as HTMLSelectElement;
    expect(select.value).toBe('country');
  });

  it('calls onChange with null when "None" is selected', async () => {
    const onChange = jest.fn();
    render(<BreakdownSelector value="platform" onChange={onChange} />);
    await userEvent.selectOptions(
      screen.getByTestId('breakdown-selector'),
      ''
    );
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it('calls onChange with the dimension string when a dimension is selected', async () => {
    const onChange = jest.fn();
    render(<BreakdownSelector value={null} onChange={onChange} />);
    await userEvent.selectOptions(
      screen.getByTestId('breakdown-selector'),
      'user_tier'
    );
    expect(onChange).toHaveBeenCalledWith('user_tier');
  });
});
