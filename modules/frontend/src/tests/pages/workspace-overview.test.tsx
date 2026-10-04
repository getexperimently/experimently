/**
 * The workspace list and overview pages after #263 and #264: no link to a
 * workspace API-keys page, no plan badge and no usage or limit meters.
 *
 * The mocked responses still carry the removed plan and limit fields (`plan`,
 * `max_*`), as a row written before the change or an older API would, so the
 * test proves the pages render nothing from them rather than relying on their
 * absence.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import { ModulesProvider } from '@/contexts/ModulesContext';
import WorkspaceOverviewPage from '@modules/pages/workspaces/[id]/index';
import WorkspacesPage from '@modules/pages/workspaces/index';
import { workspaceService } from '@modules/services/workspaces';

jest.mock('next/router', () => ({
  useRouter: () => ({
    pathname: '/workspaces/[id]',
    asPath: '/workspaces/ws-1',
    query: { id: 'ws-1' },
    isReady: true,
    push: jest.fn(),
    replace: jest.fn(),
  }),
}));

jest.mock('next/head', () => {
  const MockHead = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  MockHead.displayName = 'MockHead';
  return MockHead;
});

jest.mock('@modules/services/workspaces', () => ({
  workspaceService: {
    get: jest.fn(),
    list: jest.fn(),
    create: jest.fn(),
    update: jest.fn(),
  },
}));

const LEGACY_ROW = {
  id: 'ws-1',
  name: 'Growth',
  slug: 'growth',
  description: 'Growth squad',
  is_active: true,
  member_count: 3,
  created_at: '2026-10-01T00:00:00Z',
  // Removed fields, as an existing row or an older API would still send them.
  plan: 'enterprise',
  max_experiments: 10,
  max_feature_flags: 50,
  max_members: 5,
  max_api_keys: 3,
};

beforeEach(() => {
  jest.clearAllMocks();
  (workspaceService.get as jest.Mock).mockResolvedValue(LEGACY_ROW);
  (workspaceService.list as jest.Mock).mockResolvedValue([LEGACY_ROW]);
});

function inFullProfile(page: React.ReactElement) {
  return render(
    <ModulesProvider initial={{ profile: 'full', modules: ['workspaces'], version: 'test' }}>
      {page}
    </ModulesProvider>,
  );
}

function hrefs(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('a[href]')).map(
    (a) => a.getAttribute('href') ?? '',
  );
}

function assertNoPlanOrLimits() {
  for (const label of ['Free', 'Pro', 'Enterprise']) {
    expect(screen.queryByText(label)).not.toBeInTheDocument();
  }
  expect(screen.queryByText(/usage\s*&\s*limits/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/approaching limit/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/api keys/i)).not.toBeInTheDocument();
}

describe('workspace overview page', () => {
  it('links to no workspace API-keys page and shows no plan or limits', async () => {
    const { container } = inFullProfile(<WorkspaceOverviewPage />);
    expect(await screen.findByRole('heading', { name: 'Growth' })).toBeInTheDocument();

    const links = hrefs(container);
    expect(links).toContain('/workspaces/ws-1/members');
    expect(links.filter((h) => /\/api-keys\/?$/.test(h))).toEqual([]);
    assertNoPlanOrLimits();
    // Only the members count is shown; the always-zero experiment and flag
    // counts are gone.
    expect(screen.queryByText('Experiments')).not.toBeInTheDocument();
    expect(screen.queryByText('Feature Flags')).not.toBeInTheDocument();
    expect(screen.getByText('Members')).toBeInTheDocument();
  });
});

describe('workspace list page', () => {
  it('shows each workspace without a plan badge or an experiment count', async () => {
    const { container } = inFullProfile(<WorkspacesPage />);
    expect(await screen.findByText('Growth')).toBeInTheDocument();

    expect(hrefs(container)).toContain('/workspaces/ws-1');
    expect(hrefs(container).filter((h) => /\/api-keys\/?$/.test(h))).toEqual([]);
    assertNoPlanOrLimits();
    expect(screen.queryByText(/experiments$/)).not.toBeInTheDocument();
  });
});
