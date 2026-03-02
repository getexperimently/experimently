import React from 'react';
import { render, screen } from '@testing-library/react';
import { WinnerIndicator } from '@/components/results/shared/WinnerIndicator';

describe('WinnerIndicator', () => {
  it('renders variant name when show is true', () => {
    render(<WinnerIndicator variantName="Variant B" show />);
    expect(screen.getByTestId('winner-indicator')).toBeInTheDocument();
    expect(screen.getByText('Variant B')).toBeInTheDocument();
  });

  it('renders the crown emoji', () => {
    render(<WinnerIndicator variantName="Variant B" show />);
    expect(screen.getByRole('img', { name: /winner/i })).toBeInTheDocument();
  });

  it('renders nothing when show is false', () => {
    render(<WinnerIndicator variantName="Variant B" show={false} />);
    expect(screen.queryByTestId('winner-indicator')).not.toBeInTheDocument();
    expect(screen.queryByText('Variant B')).not.toBeInTheDocument();
  });

  it('applies green background styling', () => {
    render(<WinnerIndicator variantName="Variant B" show />);
    expect(screen.getByTestId('winner-indicator')).toHaveClass('bg-green-100');
  });
});
