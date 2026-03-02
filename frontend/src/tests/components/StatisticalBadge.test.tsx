import React from 'react';
import { render, screen } from '@testing-library/react';
import { StatisticalBadge } from '@/components/results/shared/StatisticalBadge';

describe('StatisticalBadge', () => {
  it('shows significant badge when p_value < alpha', () => {
    render(<StatisticalBadge pValue={0.03} confidenceLevel={0.95} />);
    expect(screen.getByText(/significant/i)).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveClass('bg-green-100');
  });

  it('includes the p-value in the label when significant', () => {
    render(<StatisticalBadge pValue={0.03} confidenceLevel={0.95} />);
    expect(screen.getByRole('status')).toHaveTextContent('p=0.030');
  });

  it('shows not significant when p_value >= alpha', () => {
    render(<StatisticalBadge pValue={0.12} confidenceLevel={0.95} />);
    expect(screen.getByText(/not significant/i)).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveClass('bg-gray-100');
  });

  it('shows not significant when p_value equals alpha exactly', () => {
    render(<StatisticalBadge pValue={0.05} confidenceLevel={0.95} />);
    expect(screen.getByText(/not significant/i)).toBeInTheDocument();
  });

  it('renders N/A when p_value is null', () => {
    render(<StatisticalBadge pValue={null} confidenceLevel={0.95} />);
    expect(screen.getByText('N/A')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveClass('bg-gray-100');
  });

  it('respects different confidence levels (99%)', () => {
    // alpha = 0.01, so p=0.02 is NOT significant at 99% confidence
    render(<StatisticalBadge pValue={0.02} confidenceLevel={0.99} />);
    expect(screen.getByText(/not significant/i)).toBeInTheDocument();
  });

  it('respects different confidence levels (90%)', () => {
    // alpha = 0.10, so p=0.08 IS significant at 90% confidence
    render(<StatisticalBadge pValue={0.08} confidenceLevel={0.90} />);
    expect(screen.getByText(/^significant/i)).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveClass('bg-green-100');
  });
});
