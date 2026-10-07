/**
 * The Workspaces page shows each workspace's member count from the list
 * response (#1008). `GET /api/v1/workspaces/` used to answer no count, and the
 * page showed "0 members" for every workspace; the rows below have the shape
 * the list answers now (`WorkspaceWithStatsResponse`).
 */
import React from 'react';
import { render, screen, within } from '@testing-library/react';
import { ModulesProvider } from '@/contexts/ModulesContext';
import WorkspacesPage from '@modules/pages/workspaces/index';
import { workspaceService } from '@modules/services/workspaces';

jest.mock('next/router', () => ({
  useRouter: () => ({
    pathname: '/workspaces',
    asPath: '/workspaces',
    query: {},
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
  workspaceService: { list: jest.fn(), create: jest.fn() },
}));

function row(id: string, name: string, member_count?: number) {
  return {
    id,
    name,
    slug: name.toLowerCase(),
    description: null,
    is_active: true,
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    ...(member_count === undefined ? {} : { member_count }),
  };
}

function renderPage() {
  return render(
    <ModulesProvider initial={{ profile: 'full', modules: ['workspaces'], version: 'test' }}>
      <WorkspacesPage />
    </ModulesProvider>,
  );
}

async function card(name: string): Promise<HTMLElement> {
  const heading = await screen.findByRole('heading', { name });
  const link = heading.closest('a');
  if (!link) throw new Error(`no card for ${name}`);
  return link;
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe('workspace list member counts', () => {
  it("shows each workspace's own member count", async () => {
    (workspaceService.list as jest.Mock).mockResolvedValue([
      row('ws-1', 'Growth', 3),
      row('ws-2', 'Solo', 1),
    ]);
    renderPage();

    expect(within(await card('Growth')).getByText(/^3 members$/)).toBeInTheDocument();
    expect(within(await card('Solo')).getByText(/^1 member$/)).toBeInTheDocument();
  });

  it('shows no count, rather than 0, for a workspace the list gives none for', async () => {
    (workspaceService.list as jest.Mock).mockResolvedValue([row('ws-1', 'Growth')]);
    renderPage();

    const growth = await card('Growth');
    expect(within(growth).queryByTestId('workspace-member-count')).not.toBeInTheDocument();
    expect(within(growth).queryByText(/members?$/)).not.toBeInTheDocument();
  });
});
