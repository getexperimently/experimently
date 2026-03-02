import React from 'react';
import { render, screen } from '@testing-library/react';
import { EvidenceRatioChart } from '@/components/results/Sequential/EvidenceRatioChart';
import { EvidencePoint } from '@/types/sequential';

// Mock recharts to avoid canvas rendering issues in tests
jest.mock('recharts', () => {
  const OriginalModule = jest.requireActual('recharts');
  return {
    ...OriginalModule,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="responsive-container">{children}</div>
    ),
  };
});

const mockTrajectory: EvidencePoint[] = [
  { sample_size: 100, lambda_ratio: 1.2, always_valid_p_value: 0.83, can_stop: false },
  { sample_size: 200, lambda_ratio: 3.5, always_valid_p_value: 0.29, can_stop: false },
  { sample_size: 300, lambda_ratio: 8.1, always_valid_p_value: 0.12, can_stop: false },
  { sample_size: 400, lambda_ratio: 15.0, always_valid_p_value: 0.067, can_stop: false },
  { sample_size: 500, lambda_ratio: 22.5, always_valid_p_value: 0.044, can_stop: true },
];

describe('EvidenceRatioChart', () => {
  it('renders empty state when trajectory is empty', () => {
    render(<EvidenceRatioChart trajectory={[]} boundary={20} />);
    expect(screen.getByTestId('evidence-chart-empty')).toBeInTheDocument();
    expect(screen.getByText(/no evidence data available/i)).toBeInTheDocument();
  });

  it('renders chart when trajectory has data', () => {
    render(<EvidenceRatioChart trajectory={mockTrajectory} boundary={20} />);
    expect(screen.getByTestId('evidence-ratio-chart')).toBeInTheDocument();
    expect(screen.queryByTestId('evidence-chart-empty')).not.toBeInTheDocument();
  });

  it('renders inside a responsive container', () => {
    render(<EvidenceRatioChart trajectory={mockTrajectory} boundary={20} />);
    expect(screen.getByTestId('responsive-container')).toBeInTheDocument();
  });
});
