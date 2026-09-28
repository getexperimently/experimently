/**
 * /results/[id]: the Sequential tab shows the beta notice the API sends.
 *
 * The API is mocked at `apiFetch`, so the page, ResultsDashboard, the results
 * service and SequentialMonitor all run as they do in the browser. The
 * sequential fixture carries the notice text the backend's analysis-status
 * table produces (backend/app/core/analysis_status.py, "sequential").
 */
import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ResultDetailPage from '@/pages/results/[id]';
import { apiFetch } from '@/services/api';
import { makeRouter, routedApi } from './helpers/apiMock';

jest.mock('@/services/api', () => ({
  ...jest.requireActual('@/services/api'),
  apiFetch: jest.fn(),
}));

const mockRouter = makeRouter({ pathname: '/results/[id]', query: { id: 'exp-1' } });
jest.mock('next/router', () => ({ useRouter: () => mockRouter }));

jest.mock('next/head', () => {
  const Head = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  Head.displayName = 'MockHead';
  return Head;
});

jest.mock('recharts', () => {
  const OriginalModule = jest.requireActual('recharts');
  return {
    ...OriginalModule,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="responsive-container">{children}</div>
    ),
  };
});

const mockedApiFetch = apiFetch as jest.MockedFunction<typeof apiFetch>;

const SEQUENTIAL_NOTICE =
  'Beta: the stop/continue decision is mSPRT alone, at the significance ' +
  'level shown by the boundary (1/alpha). alpha_spending is always empty: ' +
  'the planned-looks (alpha-spending) table is not computed yet. The ' +
  'confidence sequence is being corrected. ' +
  'https://github.com/getexperimently/experimently/issues/231';

const RESULTS = {
  experiment_id: 'exp-1',
  experiment_name: 'Checkout button colour',
  status: 'ACTIVE',
  start_date: '2026-09-01T00:00:00Z',
  end_date: null,
  confidence_level: 0.95,
  correction_method: 'bonferroni',
  sample_size_adequate: false,
  computed_at: '2026-09-20T12:00:00Z',
  summary: {
    total_users: 2000,
    total_events: 240,
    duration_days: 21,
    has_winner: false,
    winning_variant_id: null,
    recommendation: 'CONTINUE_TESTING',
  },
  metrics: [],
};

const SEQUENTIAL = {
  method: 'msprt',
  msprt_result: {
    lambda_ratio: 2.1,
    always_valid_p_value: 0.48,
    can_stop: false,
    evidence_strength: 'inconclusive',
    boundary: 20.0,
  },
  confidence_sequence: null,
  evidence_trajectory: [],
  alpha_spending: [],
  long_running_risk: {
    is_at_risk: true,
    expected_duration_days: 14,
    actual_duration_days: 21,
    risk_ratio: 1.5,
    recommendation:
      'Experiment has exceeded 1.5x its expected duration. Running long is not ' +
      'evidence of no effect; consider increasing traffic allocation or revisiting ' +
      'the expected duration.',
  },
  recommended_action: 'continue',
  at_risk: true,
  analysis_status: 'beta',
  analysis_notice: SEQUENTIAL_NOTICE,
};

function install() {
  mockedApiFetch.mockImplementation(
    routedApi([
      { path: '/api/v1/results/exp-1', handler: () => RESULTS },
      {
        path: '/api/v1/results/exp-1/daily',
        handler: () => ({ experiment_id: 'exp-1', metric_id: null, series: [] }),
      },
      {
        path: '/api/v1/results/exp-1/sample-size',
        handler: () => ({
          required_sample_size_per_variant: 3000,
          current_sample_size_per_variant: 1000,
          is_adequate: false,
          achieved_power: 0.4,
          days_to_significance: null,
          projected_completion_date: null,
          baseline_rate: 0.12,
          mde: 0.02,
          confidence_level: 0.95,
          power_target: 0.8,
        }),
      },
      { path: '/api/v1/results/exp-1/sequential', handler: () => SEQUENTIAL },
    ]) as unknown as typeof apiFetch
  );
}

async function openSequentialTab() {
  render(<ResultDetailPage />);
  const tab = await screen.findByRole('tab', { name: /sequential/i });
  await userEvent.click(tab);
  await waitFor(() => expect(screen.getByTestId('sequential-monitor')).toBeInTheDocument());
}

describe('ResultDetailPage (/results/[id]) sequential tab', () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
    install();
  });

  it('shows the beta notice the API sends, with a Beta label and the issue link', async () => {
    await openSequentialTab();

    expect(
      screen.getByText(/the stop\/continue decision is mSPRT alone/i)
    ).toBeInTheDocument();
    const notice = screen.getByRole('region', { name: /beta/i });
    expect(within(notice).getByText('Beta')).toBeInTheDocument();
    expect(within(notice).getByRole('link', { name: /issue #231/i })).toHaveAttribute(
      'href',
      'https://github.com/getexperimently/experimently/issues/231'
    );
    expect(notice).not.toHaveAttribute('role', 'alert');
  });

  it('shows at_risk as an advisory note, not an alert or a stop recommendation', async () => {
    await openSequentialTab();

    const note = screen.getByTestId('long-running-risk');
    expect(note).toHaveAttribute('role', 'note');
    expect(note).toHaveTextContent(/not a reason to stop/i);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByTestId('action-label')).toHaveTextContent(/continue testing/i);
  });
});
