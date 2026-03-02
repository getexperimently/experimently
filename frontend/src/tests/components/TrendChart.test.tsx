import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TrendChart } from '@/components/results/Visualizations/TrendChart';
import { VariantTimeSeries } from '@/types/results';

const dailyPoint = (date: string, mean: number) => ({
  date,
  sample_size: 100,
  conversions: Math.round(mean * 100),
  mean,
});

const mockSeries: VariantTimeSeries[] = [
  {
    variant_id: 'ctrl',
    variant_name: 'Control',
    is_control: true,
    values: [dailyPoint('2024-01-01', 0.10), dailyPoint('2024-01-02', 0.11)],
    cumulative: [dailyPoint('2024-01-01', 0.10), dailyPoint('2024-01-02', 0.105)],
  },
  {
    variant_id: 'var1',
    variant_name: 'Variant B',
    is_control: false,
    values: [dailyPoint('2024-01-01', 0.13), dailyPoint('2024-01-02', 0.14)],
    cumulative: [dailyPoint('2024-01-01', 0.13), dailyPoint('2024-01-02', 0.135)],
  },
];

describe('TrendChart', () => {
  it('renders one line per variant', () => {
    render(<TrendChart series={mockSeries} />);
    expect(screen.getAllByTestId('trend-line')).toHaveLength(2);
  });

  it('shows variant names in trend lines', () => {
    render(<TrendChart series={mockSeries} />);
    expect(screen.getByText('Control')).toBeInTheDocument();
    expect(screen.getByText('Variant B')).toBeInTheDocument();
  });

  it('shows empty state when no series data', () => {
    render(<TrendChart series={[]} />);
    expect(screen.getByTestId('trend-empty')).toBeInTheDocument();
    expect(screen.getByText(/no trend data/i)).toBeInTheDocument();
  });

  it('renders cumulative view toggle button', () => {
    render(<TrendChart series={mockSeries} />);
    expect(screen.getByRole('button', { name: /cumulative/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /daily/i })).toBeInTheDocument();
  });

  it('switches to daily view when clicking Daily', async () => {
    render(<TrendChart series={mockSeries} />);
    const dailyButton = screen.getByRole('button', { name: /daily/i });
    await userEvent.click(dailyButton);
    expect(dailyButton).toHaveAttribute('aria-pressed', 'true');
  });

  it('defaults to cumulative view', () => {
    render(<TrendChart series={mockSeries} />);
    const cumulativeButton = screen.getByRole('button', { name: /cumulative/i });
    expect(cumulativeButton).toHaveAttribute('aria-pressed', 'true');
  });
});
