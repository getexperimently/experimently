import React from 'react';
import { render, screen } from '@testing-library/react';
import { ConfidenceInterval } from '@/components/results/shared/ConfidenceInterval';

describe('ConfidenceInterval', () => {
  it('renders the formatted value', () => {
    render(<ConfidenceInterval value={0.125} bounds={null} />);
    expect(screen.getByTestId('ci-value')).toHaveTextContent('12.5%');
  });

  it('renders bounds when provided', () => {
    render(<ConfidenceInterval value={0.125} bounds={[0.102, 0.148]} />);
    expect(screen.getByTestId('ci-bounds')).toHaveTextContent('[10.2% – 14.8%]');
  });

  it('does not render bounds when null', () => {
    render(<ConfidenceInterval value={0.125} bounds={null} />);
    expect(screen.queryByTestId('ci-bounds')).not.toBeInTheDocument();
  });

  it('accepts a custom format function', () => {
    render(
      <ConfidenceInterval
        value={0.5}
        bounds={[0.4, 0.6]}
        format={(v) => v.toFixed(2)}
      />
    );
    expect(screen.getByTestId('ci-value')).toHaveTextContent('0.50');
    expect(screen.getByTestId('ci-bounds')).toHaveTextContent('[0.40 – 0.60]');
  });
});
