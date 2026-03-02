import React from 'react';
import { render, screen } from '@testing-library/react';
import { StatTile } from '@/components/admin/StatTile';

describe('StatTile', () => {
  it('renders label and value', () => {
    render(<StatTile label="Total Users" value={42} />);
    expect(screen.getByText('Total Users')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
  });

  it('renders subtitle when provided', () => {
    render(<StatTile label="Total Users" value={42} subtitle="Last 30 days" />);
    expect(screen.getByText('Last 30 days')).toBeInTheDocument();
  });

  it('does not render subtitle when not provided', () => {
    render(<StatTile label="Total Users" value={42} />);
    // No subtitle element should be present
    expect(screen.queryByTestId('stat-tile-subtitle')).not.toBeInTheDocument();
  });

  it('applies correct color classes for blue', () => {
    render(<StatTile label="Test" value={0} color="blue" />);
    const tile = screen.getByTestId('stat-tile');
    expect(tile).toHaveClass('border-blue-200');
  });

  it('applies correct color classes for green', () => {
    render(<StatTile label="Test" value={0} color="green" />);
    const tile = screen.getByTestId('stat-tile');
    expect(tile).toHaveClass('border-green-200');
  });

  it('renders with data-testid', () => {
    render(<StatTile label="Test" value={99} />);
    expect(screen.getByTestId('stat-tile')).toBeInTheDocument();
  });
});
