/**
 * The results page shows one significance decision and no misleading units
 * (D36 results correctness, PR 0a; part of #439).
 *
 * Each block pins one thing the page used to get wrong:
 *  - the badge, the row colour and the recommendation decide significance
 *    from the same p-value, and the p column says whether it is adjusted
 *    (the dashboard requests no correction, so it reads "unadjusted");
 *  - the crown appears only on SHIP_VARIANT, and the reason is shown;
 *  - a non-finite or missing number reads "Not enough data to estimate";
 *  - a revenue/count/duration metric that the engine still analyses as a
 *    conversion (statistical_test_used = fisher_exact) is labelled as a share
 *    of users, never in currency or "per user";
 *  - the Live tab says which test it runs.
 */
import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import { MetricComparisonTable } from '@/components/results/MetricComparison/MetricComparisonTable';
import { ExperimentSummary } from '@/components/results/ResultsDashboard/ExperimentSummary';
import { ResultsDashboard } from '@/components/results/ResultsDashboard/ResultsDashboard';
import { LiveResultsPanel } from '@/components/experiments/LiveResultsPanel';
import { SegmentComparisonTable } from '@/components/results/Breakdowns/SegmentComparisonTable';
import { ResultsService } from '@/services/results';
import * as streamHook from '@/hooks/useExperimentStream';
import {
  DimensionalBreakdownResponse,
  ExperimentResultsResponse,
  MetricResult,
  VariantResult,
} from '@/types/results';

jest.mock('@/services/results');
jest.mock('@/hooks/useExperimentStream');

const mockUseExperimentStream = streamHook.useExperimentStream as jest.MockedFunction<
  typeof streamHook.useExperimentStream
>;

function variant(overrides: Partial<VariantResult>): VariantResult {
  return {
    variant_id: 'v',
    variant_name: 'V',
    is_control: false,
    sample_size: 1000,
    conversions: 100,
    mean: 0.1,
    std_dev: null,
    confidence_interval: [0.08, 0.12],
    p_value: null,
    adjusted_p_value: null,
    is_significant: false,
    effect_size: null,
    effect_size_label: null,
    relative_improvement_pct: null,
    power: null,
    ...overrides,
  };
}

const control = variant({
  variant_id: 'ctrl',
  variant_name: 'Control',
  is_control: true,
  mean: 0.1,
});

function conversionMetric(treatment: Partial<VariantResult>): MetricResult {
  return {
    metric_id: 'm-conv',
    metric_name: 'Signup',
    metric_type: 'conversion',
    is_primary: true,
    variants: [
      control,
      variant({
        variant_id: 'var-b',
        variant_name: 'Variant B',
        mean: 0.12,
        relative_improvement_pct: 20,
        statistical_test_used: 'fisher_exact',
        ...treatment,
      }),
    ],
  };
}

const revenueMetric: MetricResult = {
  metric_id: 'm-rev',
  metric_name: 'Revenue',
  metric_type: 'revenue',
  is_primary: true,
  variants: [
    variant({
      variant_id: 'ctrl',
      variant_name: 'Control',
      is_control: true,
      mean: 0.03,
      conversions: null,
    }),
    variant({
      variant_id: 'var-b',
      variant_name: 'Variant B',
      mean: 0.035,
      conversions: null,
      relative_improvement_pct: 16.7,
      p_value: 0.2,
      is_significant: false,
      statistical_test_used: 'fisher_exact',
    }),
  ],
};

function experiment(
  overrides: Partial<ExperimentResultsResponse> = {}
): ExperimentResultsResponse {
  return {
    experiment_id: 'exp-1',
    experiment_name: 'Checkout test',
    status: 'ACTIVE',
    start_date: '2026-09-01T00:00:00Z',
    end_date: null,
    confidence_level: 0.95,
    correction_method: 'none',
    sample_size_adequate: true,
    computed_at: '2026-09-15T00:00:00Z',
    summary: {
      total_users: 2000,
      total_events: 220,
      duration_days: 14,
      has_winner: false,
      winning_variant_id: null,
      recommendation: 'CONTINUE_TESTING',
      recommendation_reason: 'No statistically significant difference yet.',
    },
    metrics: [conversionMetric({})],
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  mockUseExperimentStream.mockReturnValue({
    snapshot: null,
    status: 'disconnected',
    error: null,
    connect: jest.fn(),
    disconnect: jest.fn(),
    refresh: jest.fn(),
    ping: jest.fn(),
  });
});

describe('one significance decision: a response with a correction uses the adjusted p', () => {
  // Raw p 0.01 would pass at alpha 0.05; Bonferroni-adjusted 0.08 does not.
  const metrics = [
    conversionMetric({
      p_value: 0.01,
      adjusted_p_value: 0.08,
      is_significant: false,
    }),
  ];

  it('shows the row as not significant and labels the adjusted value', () => {
    render(
      <MetricComparisonTable
        metrics={metrics}
        confidenceLevel={0.95}
        correctionMethod="bonferroni"
      />
    );
    const row = screen.getByRole('row', { name: /variant b/i });
    expect(within(row).getByText(/^not significant/i)).toBeInTheDocument();
    expect(within(row).queryByText(/^significant/i)).not.toBeInTheDocument();
    expect(within(row).getByText('0.0800')).toBeInTheDocument();
    expect(within(row).getByText(/adjusted \(Bonferroni\)/)).toBeInTheDocument();
    // The raw value stays available, named as raw.
    expect(within(row).getByText(/raw 0\.0100/)).toBeInTheDocument();
  });

  it('labels a Benjamini-Hochberg adjustment as BH', () => {
    render(
      <MetricComparisonTable
        metrics={metrics}
        confidenceLevel={0.95}
        correctionMethod="benjamini_hochberg"
      />
    );
    const row = screen.getByRole('row', { name: /variant b/i });
    expect(within(row).getByText(/adjusted \(BH\)/)).toBeInTheDocument();
  });
});

describe('the dashboard request carries no correction: the p is labelled unadjusted', () => {
  // ResultsService.getResults sends no correction_method, so /results answers
  // with correction_method "none" and adjusted_p_value null.
  it('labels the p-value "unadjusted" and decides from it', () => {
    render(
      <MetricComparisonTable
        metrics={[conversionMetric({ p_value: 0.01, is_significant: true })]}
        confidenceLevel={0.95}
        correctionMethod="none"
      />
    );
    const row = screen.getByRole('row', { name: /variant b/i });
    expect(within(row).getByText('0.0100')).toBeInTheDocument();
    expect(within(row).getByText('unadjusted')).toBeInTheDocument();
    expect(within(row).queryByText(/adjusted \(/)).not.toBeInTheDocument();
    expect(within(row).getByText(/^significant \(p=0\.010\)/i)).toBeInTheDocument();
  });
});

describe('a Bonferroni breakdown names its correction', () => {
  const breakdown: DimensionalBreakdownResponse = {
    dimension: 'platform',
    is_exploratory: true,
    adjusted_alpha: 0.05 / 3,
    has_heterogeneous_effects: false,
    hte_warning: null,
    segments: [
      {
        segment_value: 'ios',
        sample_size: 2000,
        variants: [
          {
            variant_id: 'ctrl',
            variant_name: 'Control',
            is_control: true,
            sample_size: 1000,
            conversions: 100,
            mean: 0.1,
            confidence_interval: [0.08, 0.12],
            p_value: null,
            is_significant: false,
          },
          {
            // Raw p 0.03 is below 0.05 but not below the adjusted 0.0167.
            variant_id: 'var-b',
            variant_name: 'Variant B',
            is_control: false,
            sample_size: 1000,
            conversions: 128,
            mean: 0.128,
            confidence_interval: [0.11, 0.15],
            p_value: 0.03,
            is_significant: false,
          },
        ],
      },
    ],
  };

  it('labels the threshold "adjusted (Bonferroni)" and the p as unadjusted', () => {
    render(<SegmentComparisonTable breakdown={breakdown} />);
    expect(
      screen.getByRole('columnheader', { name: /significance at adjusted \(Bonferroni\) α/i })
    ).toBeInTheDocument();
    expect(screen.getByText(/α =\s*0\.0167/)).toBeInTheDocument();
    expect(
      screen.getByRole('columnheader', { name: /p-value \(unadjusted\)/i })
    ).toBeInTheDocument();
    const row = screen.getByRole('row', { name: /variant b/i });
    expect(within(row).getByText('0.0300')).toBeInTheDocument();
    expect(within(row).getByText('Not significant')).toBeInTheDocument();
  });
});

describe('the crown only on SHIP_VARIANT', () => {
  const leading = experiment({
    sample_size_adequate: false,
    summary: {
      total_users: 2000,
      total_events: 220,
      duration_days: 3,
      has_winner: true,
      winning_variant_id: 'var-b',
      recommendation: 'CONTINUE_TESTING',
      recommendation_reason:
        'Variant B shows 20.0% improvement on Signup (p=0.0100). Not every variant has reached the minimum sample size yet, so keep the experiment running before shipping.',
    },
    metrics: [conversionMetric({ p_value: 0.01, is_significant: true })],
  });

  it('shows no winner under CONTINUE_TESTING, and shows the reason', () => {
    render(<ExperimentSummary experiment={leading} />);
    expect(screen.queryByTestId('winner-indicator')).not.toBeInTheDocument();
    expect(screen.queryByText(/^winner$/i)).not.toBeInTheDocument();
    expect(
      screen.getByText(/Leading: Variant B \(not yet adequate sample\)/)
    ).toBeInTheDocument();
    expect(screen.getByTestId('recommendation-reason')).toHaveTextContent(
      /keep the experiment running before shipping/
    );
  });

  it('shows the crown on SHIP_VARIANT', () => {
    render(
      <ExperimentSummary
        experiment={{
          ...leading,
          sample_size_adequate: true,
          summary: { ...leading.summary, recommendation: 'SHIP_VARIANT' },
        }}
      />
    );
    expect(screen.getByTestId('winner-indicator')).toHaveTextContent('Variant B');
  });
});

describe('non-finite numbers', () => {
  it('renders "Not enough data to estimate", never NaN, Infinity or 0.00%', () => {
    const metrics: MetricResult[] = [
      {
        metric_id: 'm-nan',
        metric_name: 'Signup',
        metric_type: 'conversion',
        is_primary: true,
        variants: [
          variant({
            variant_id: 'ctrl',
            variant_name: 'Control',
            is_control: true,
            sample_size: 0,
            conversions: 0,
            mean: 0,
          }),
          variant({
            variant_id: 'var-b',
            variant_name: 'Variant B',
            mean: NaN,
            relative_improvement_pct: Infinity,
            p_value: NaN,
          }),
        ],
      },
    ];
    const { container } = render(
      <MetricComparisonTable metrics={metrics} confidenceLevel={0.95} />
    );
    const text = container.textContent ?? '';
    expect(text).not.toMatch(/NaN|Infinity|∞|0\.00%/);
    expect(
      screen.getAllByText(/Not enough data to estimate/).length
    ).toBeGreaterThanOrEqual(3);
  });
});

describe('revenue analysed as a conversion is not shown in units', () => {
  it('labels the row as a share of users, with no "$" and no "per user"', () => {
    const { container } = render(
      <MetricComparisonTable metrics={[revenueMetric]} confidenceLevel={0.95} />
    );
    const text = container.textContent ?? '';
    expect(text).not.toContain('$');
    expect(text).not.toMatch(/per user/i);
    expect(screen.getAllByText(/share of users with at least one event/i).length).toBe(2);
  });

  it('does not head a revenue metric "Conversion Rates"', async () => {
    (ResultsService.getResults as jest.Mock).mockResolvedValue(
      experiment({ metrics: [revenueMetric] })
    );
    (ResultsService.getDailyResults as jest.Mock).mockResolvedValue({
      experiment_id: 'exp-1',
      metric_id: null,
      series: [],
    });
    (ResultsService.getSampleSize as jest.Mock).mockResolvedValue(null);
    (ResultsService.getSequentialResults as jest.Mock).mockRejectedValue(new Error('none'));

    const { container } = render(<ResultsDashboard experimentId="exp-1" />);
    await waitFor(() => screen.getByRole('tablist'));
    expect(screen.queryByText(/Conversion Rates — Revenue/)).not.toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: /Revenue — share of users with at least one event/i })
    ).toBeInTheDocument();
    const text = container.textContent ?? '';
    expect(text).not.toContain('$');
    expect(text).not.toMatch(/per user/i);
  });
});

describe('the Live tab says what it computes', () => {
  it('labels the estimate as a live, unadjusted, conversion-only z-test', () => {
    render(<LiveResultsPanel experimentId="exp-1" />);
    expect(
      screen.getByText('Live estimate: z-test, unadjusted, conversion only')
    ).toBeInTheDocument();
  });

  it('does not call a live row "Significant"', () => {
    mockUseExperimentStream.mockReturnValue({
      snapshot: {
        event: 'results_update',
        experimentId: 'exp-1',
        timestamp: '2026-09-15T00:00:00Z',
        status: 'active',
        variants: [
          {
            key: 'control',
            name: 'Control',
            participantCount: 1000,
            conversionCount: 100,
            conversionRate: 0.1,
            relativeLift: 0,
            pValue: null,
            isControl: true,
          },
          {
            key: 'b',
            name: 'Variant B',
            participantCount: 1000,
            conversionCount: 130,
            conversionRate: 0.13,
            relativeLift: 0.3,
            pValue: 0.03,
            isControl: false,
          },
        ],
        totalParticipants: 2000,
        daysRunning: 7,
        isSignificant: true,
      },
      status: 'connected',
      error: null,
      connect: jest.fn(),
      disconnect: jest.fn(),
      refresh: jest.fn(),
      ping: jest.fn(),
    });
    render(<LiveResultsPanel experimentId="exp-1" />);
    expect(screen.queryByText(/^significant$/i)).not.toBeInTheDocument();
    expect(within(screen.getByTestId('variant-row-b')).getByText(/p < 0\.05 \(unadjusted\)/)).toBeInTheDocument();
  });
});

describe('accessibility (axe-core in jsdom; colour contrast is not computable here)', () => {
  const axeOptions: axe.RunOptions = {
    rules: { 'color-contrast': { enabled: false } },
  };

  async function violations(node: Element) {
    const result = await axe.run(node, axeOptions);
    return result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(', ')}`);
  }

  it.each(['Overview', 'Live'])('the %s tab has no axe violations', async (tabName) => {
    (ResultsService.getResults as jest.Mock).mockResolvedValue(
      experiment({
        correction_method: 'bonferroni',
        metrics: [
          conversionMetric({ p_value: 0.01, adjusted_p_value: 0.08 }),
          { ...revenueMetric, is_primary: false },
        ],
      })
    );
    (ResultsService.getDailyResults as jest.Mock).mockResolvedValue({
      experiment_id: 'exp-1',
      metric_id: null,
      series: [],
    });
    (ResultsService.getSampleSize as jest.Mock).mockResolvedValue(null);
    (ResultsService.getSequentialResults as jest.Mock).mockRejectedValue(new Error('none'));

    const user = userEvent.setup();
    const { container } = render(<ResultsDashboard experimentId="exp-1" />);
    await waitFor(() => screen.getByRole('tablist'));
    await user.click(screen.getByRole('tab', { name: new RegExp(tabName, 'i') }));
    expect(await violations(container)).toEqual([]);
  });
});
