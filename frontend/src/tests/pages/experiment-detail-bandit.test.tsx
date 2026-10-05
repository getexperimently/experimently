/**
 * The bandit weights panel on the experiment page (#442 PR D): mounted for a
 * bandit, absent for a fixed split, the same read-only panel for all four
 * roles (reading it is allowed to every signed-in user), and a failure to
 * read the weights leaves the rest of the page intact.
 */
import React from 'react';
import { render, screen, within } from '@testing-library/react';
import ExperimentDetailPage from '@/pages/experiments/[id]';
import { BANDIT_ERROR } from '@/components/experiments/BanditWeightsSection';
import { apiFetch } from '@/services/api';
import { BanditStatus } from '@/types/bandit';
import { Experiment } from '@/types/experiments';
import { apiError, makeRouter, routedApi } from './helpers/apiMock';

jest.mock('@/services/api', () => ({
  ...jest.requireActual('@/services/api'),
  apiFetch: jest.fn(),
}));

const mockRouter = makeRouter({ pathname: '/experiments/[id]', query: { id: 'exp-1' } });
jest.mock('next/router', () => ({ useRouter: () => mockRouter }));

jest.mock('next/head', () => {
  const Head = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  Head.displayName = 'MockHead';
  return Head;
});

const mockUseAuth = jest.fn();
jest.mock('@/contexts/AuthContext', () => ({ useAuth: () => mockUseAuth() }));

const mockedApiFetch = apiFetch as jest.MockedFunction<typeof apiFetch>;

const BANDIT: Experiment = {
  id: 'exp-1',
  name: 'Recommendation algorithm',
  key: 'recommendation-algorithm',
  description: null,
  hypothesis: null,
  experiment_type: 'bandit',
  optimization_type: 'thompson_sampling',
  status: 'active',
  targeting_rules: null,
  tags: null,
  owner_id: 'someone-else',
  start_date: '2026-09-01T10:00:00Z',
  end_date: null,
  created_at: '2026-09-01T10:00:00Z',
  updated_at: '2026-09-01T10:00:00Z',
  variants: [
    { id: 'v-1', name: 'algo_v1', is_control: true, traffic_allocation: 50 },
    { id: 'v-2', name: 'algo_v2', is_control: false, traffic_allocation: 50 },
  ],
  metrics: [],
};

const STATUS: BanditStatus = {
  experiment_id: 'exp-1',
  algorithm: 'thompson_sampling',
  current_weights: [
    { variant_id: 'v-1', variant_name: 'algo_v1', current_weight: 0.2, successes: 10, pulls: 200, conversion_rate: 0.05 },
    { variant_id: 'v-2', variant_name: 'algo_v2', current_weight: 0.8, successes: 72, pulls: 800, conversion_rate: 0.09 },
  ],
  total_pulls: 1000,
  recommendation: 'DEPLOYING_algo_v2',
  last_updated: '2026-10-04T09:30:00+00:00',
};

function install(experiment: Experiment, bandit: () => unknown = () => STATUS) {
  mockedApiFetch.mockImplementation(
    routedApi([
      { path: '/api/v1/experiments/exp-1', handler: () => experiment },
      { path: '/api/v1/bandit/exp-1', handler: bandit },
    ]) as unknown as typeof apiFetch,
  );
}

/** A resolved, non-superuser user: never `null`, which would read as "may change". */
function signIn(role: string) {
  mockUseAuth.mockReturnValue({
    user: { id: 'user-1', email: `${role.toLowerCase()}@demo.com`, username: role.toLowerCase(), role, is_superuser: false },
    status: 'authenticated',
  });
}

const banditCalls = () =>
  mockedApiFetch.mock.calls.filter(([path]) => String(path).startsWith('/api/v1/bandit/'));

beforeEach(() => {
  mockedApiFetch.mockReset();
  signIn('ADMIN');
});

describe('mounting', () => {
  it('a bandit experiment shows the panel below the page', async () => {
    install(BANDIT);
    render(<ExperimentDetailPage />);
    const panel = await screen.findByTestId('bandit-weights');
    await within(panel).findByTestId('bandit-weights-table');
    expect(within(panel).getByRole('heading', { name: 'Current traffic weights' })).toBeInTheDocument();
  });

  it('a fixed-allocation experiment has no panel and never asks for weights', async () => {
    install({ ...BANDIT, experiment_type: 'a_b', optimization_type: 'fixed' });
    render(<ExperimentDetailPage />);
    await screen.findByTestId('experiment-detail');
    expect(screen.queryByTestId('bandit-weights')).toBeNull();
    expect(banditCalls()).toEqual([]);
  });

  it('a failure to read the weights leaves the rest of the page in place', async () => {
    install(BANDIT, () => {
      throw apiError(500, 'PLANTED-7f3 server text');
    });
    render(<ExperimentDetailPage />);
    expect(await screen.findByTestId('bandit-weights-error')).toHaveTextContent(BANDIT_ERROR);
    expect(screen.getByTestId('experiment-name')).toHaveTextContent('Recommendation algorithm');
    expect(screen.getByTestId('variants-table')).toBeInTheDocument();
    expect(screen.getByTestId('targeting-section')).toBeInTheDocument();
    expect(screen.queryByTestId('experiment-error')).toBeNull();
    expect(document.body.textContent).not.toContain('PLANTED');
  });
});

describe('every role reads the same panel, and none is offered a change', () => {
  const roles = ['ADMIN', 'DEVELOPER', 'ANALYST', 'VIEWER'] as const;

  async function panelFor(role: string) {
    signIn(role);
    install(BANDIT);
    const view = render(<ExperimentDetailPage />);
    const panel = await screen.findByTestId('bandit-weights');
    await within(panel).findByTestId('bandit-weights-table');
    const snapshot = {
      text: panel.textContent,
      buttons: within(panel).getAllByRole('button').map((b) => b.textContent),
    };
    view.unmount();
    return snapshot;
  }

  it.each(roles)('%s sees the weights with Refresh as the only control', async (role) => {
    const { buttons, text } = await panelFor(role);
    expect(buttons).toEqual(['Refresh']);
    expect(text).toContain('80.0%');
    // Only reads: no update or override request is ever sent.
    expect(banditCalls().every(([, options]) => (options?.method ?? 'GET').toUpperCase() === 'GET')).toBe(true);
  });

  it('the four roles see identical panels', async () => {
    const seen = [];
    for (const role of roles) seen.push(await panelFor(role));
    expect(seen.map((s) => s.text)).toEqual(Array(roles.length).fill(seen[0].text));
  });
});
