import React from 'react';
import { render, screen } from '@testing-library/react';
import { SegmentComparisonTable } from '@/components/results/Breakdowns/SegmentComparisonTable';
import { DimensionalBreakdownResponse } from '@/types/results';

const makeBreakdown = (
  overrides: Partial<DimensionalBreakdownResponse> = {}
): DimensionalBreakdownResponse => ({
  dimension: 'platform',
  is_exploratory: true,
  adjusted_alpha: 0.0167,
  has_heterogeneous_effects: false,
  hte_warning: null,
  segments: [
    {
      segment_value: 'ios',
      sample_size: 500,
      variants: [
        {
          variant_id: 'ctrl',
          variant_name: 'Control',
          is_control: true,
          sample_size: 250,
          conversions: 25,
          mean: 0.1,
          confidence_interval: [0.065, 0.135],
          p_value: null,
          is_significant: false,
        },
        {
          variant_id: 'var1',
          variant_name: 'Variant B',
          is_control: false,
          sample_size: 250,
          conversions: 35,
          mean: 0.14,
          confidence_interval: [0.098, 0.182],
          p_value: 0.0412,
          is_significant: true,
        },
      ],
    },
    {
      segment_value: 'android',
      sample_size: 400,
      variants: [
        {
          variant_id: 'ctrl',
          variant_name: 'Control',
          is_control: true,
          sample_size: 200,
          conversions: 20,
          mean: 0.1,
          confidence_interval: [0.062, 0.138],
          p_value: null,
          is_significant: false,
        },
        {
          variant_id: 'var1',
          variant_name: 'Variant B',
          is_control: false,
          sample_size: 200,
          conversions: 22,
          mean: 0.11,
          confidence_interval: [0.07, 0.15],
          p_value: 0.72,
          is_significant: false,
        },
      ],
    },
  ],
  ...overrides,
});

describe('SegmentComparisonTable', () => {
  it('renders the table container with testid', () => {
    render(<SegmentComparisonTable breakdown={makeBreakdown()} />);
    expect(screen.getByTestId('segment-comparison-table')).toBeInTheDocument();
  });

  it('displays the exploratory warning when is_exploratory is true', () => {
    render(<SegmentComparisonTable breakdown={makeBreakdown({ is_exploratory: true })} />);
    expect(screen.getByRole('note', { name: /exploratory analysis warning/i })).toBeInTheDocument();
    expect(screen.getByText(/exploratory only/i)).toBeInTheDocument();
    // Should show the adjusted alpha
    expect(screen.getByText(/0\.0167/)).toBeInTheDocument();
  });

  it('does not show the exploratory warning when is_exploratory is false', () => {
    render(<SegmentComparisonTable breakdown={makeBreakdown({ is_exploratory: false })} />);
    expect(screen.queryByRole('note', { name: /exploratory analysis warning/i })).not.toBeInTheDocument();
  });

  it('shows HTE warning when has_heterogeneous_effects is true', () => {
    const breakdown = makeBreakdown({
      has_heterogeneous_effects: true,
      hte_warning: 'Significant variation detected across segments.',
    });
    render(<SegmentComparisonTable breakdown={breakdown} />);
    const hteWarning = screen.getByTestId('hte-warning');
    expect(hteWarning).toBeInTheDocument();
    expect(hteWarning).toHaveAttribute('role', 'alert');
    expect(screen.getByText('Significant variation detected across segments.')).toBeInTheDocument();
  });

  it('does not show HTE warning when has_heterogeneous_effects is false', () => {
    render(
      <SegmentComparisonTable
        breakdown={makeBreakdown({ has_heterogeneous_effects: false, hte_warning: null })}
      />
    );
    expect(screen.queryByTestId('hte-warning')).not.toBeInTheDocument();
  });

  it('renders a row for each variant in each segment', () => {
    render(<SegmentComparisonTable breakdown={makeBreakdown()} />);
    // 2 segments × 2 variants = 4 data rows + 1 header row = 5 rows total
    const rows = screen.getAllByRole('row');
    expect(rows).toHaveLength(5);
  });

  it('renders segment values as row headers', () => {
    render(<SegmentComparisonTable breakdown={makeBreakdown()} />);
    expect(screen.getByText('ios')).toBeInTheDocument();
    expect(screen.getByText('android')).toBeInTheDocument();
  });

  it('renders variant means as percentages', () => {
    render(<SegmentComparisonTable breakdown={makeBreakdown()} />);
    // Control mean 0.1 → 10.00%
    const tenPct = screen.getAllByText('10.00%');
    expect(tenPct.length).toBeGreaterThan(0);
    // Variant B ios mean 0.14 → 14.00%
    expect(screen.getByText('14.00%')).toBeInTheDocument();
  });

  it('shows Significant badge for significant non-control variants', () => {
    render(<SegmentComparisonTable breakdown={makeBreakdown()} />);
    expect(screen.getByText('Significant')).toBeInTheDocument();
  });

  it('shows Not significant badge for non-significant non-control variants', () => {
    render(<SegmentComparisonTable breakdown={makeBreakdown()} />);
    expect(screen.getByText('Not significant')).toBeInTheDocument();
  });

  it('does not show a significance badge for control variants', () => {
    // Control rows should have no badge in the significance column
    render(<SegmentComparisonTable breakdown={makeBreakdown()} />);
    // There are 2 control rows (one per segment); neither should have a badge.
    // The badge count should equal the number of non-control, non-null variant rows.
    const significantBadges = screen.getAllByText(/^(Significant|Not significant)$/);
    // 2 segments × 1 non-control variant = 2 badges
    expect(significantBadges).toHaveLength(2);
  });

  it('shows empty message when segments array is empty', () => {
    render(<SegmentComparisonTable breakdown={makeBreakdown({ segments: [] })} />);
    expect(
      screen.getByText(/no segment data available/i)
    ).toBeInTheDocument();
  });
});
