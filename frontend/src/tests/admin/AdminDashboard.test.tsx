import fs from 'fs';
import path from 'path';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { AdminDashboard } from '@/pages/admin/index';
import { AdminService } from '@/services/admin';
import { AdminStats } from '@/types/admin';

// Mock the AdminService
jest.mock('@/services/admin');

// Mock AdminLayout
jest.mock('@/components/admin/AdminLayout', () => ({
  AdminLayout: ({ children, title }: { children: React.ReactNode; title: string }) => (
    <div data-testid="admin-layout">
      <h1>{title}</h1>
      {children}
    </div>
  ),
}));

// Mock Next.js router
jest.mock('next/router', () => ({
  useRouter: () => ({
    pathname: '/admin',
    push: jest.fn(),
  }),
}));

// The shape `GET /api/v1/admin/stats` answers; the backend's
// `test_admin_stats_fixture.py` fails when the route's shape and this file part.
const mockStats: AdminStats = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', 'fixtures', 'admin-stats.json'), 'utf8'),
);

/** Each tile's label and the number under it, as the page shows them. */
function shownTiles(): Record<string, string> {
  return Object.fromEntries(
    screen.getAllByTestId('stat-tile').map((tile) => {
      const [label, value] = Array.from(tile.querySelectorAll('p')).map((p) => p.textContent ?? '');
      return [label, value];
    }),
  );
}

const mockGetStats = AdminService.getStats as jest.Mock;

beforeEach(() => {
  jest.clearAllMocks();
});

describe('AdminDashboard', () => {
  it('renders loading state initially', () => {
    mockGetStats.mockImplementation(() => new Promise(() => {}));
    render(<AdminDashboard />);
    expect(screen.getByTestId('loading-skeleton')).toBeInTheDocument();
  });

  it('renders stat tiles after data loads', async () => {
    mockGetStats.mockResolvedValue(mockStats);
    render(<AdminDashboard />);
    await waitFor(() => {
      expect(screen.getAllByTestId('stat-tile').length).toBeGreaterThan(0);
    });
  });

  it('renders 5 stat tiles', async () => {
    mockGetStats.mockResolvedValue(mockStats);
    render(<AdminDashboard />);
    await waitFor(() => {
      expect(screen.getAllByTestId('stat-tile')).toHaveLength(5);
    });
  });

  it('shows every number the stats route answers, under its label (#1007)', async () => {
    mockGetStats.mockResolvedValue(mockStats);
    render(<AdminDashboard />);
    await screen.findAllByTestId('stat-tile');
    expect(shownTiles()).toEqual({
      'Total Experiments': '25',
      'Active Experiments': '9',
      'Total Feature Flags': '52',
      'Active Feature Flags': '31',
      'Total Users': '41',
    });
  });

  it('shows error message on fetch failure', async () => {
    mockGetStats.mockRejectedValue(new Error('Network error'));
    render(<AdminDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('error-state')).toBeInTheDocument();
    });
  });

  it('uses AdminLayout', async () => {
    mockGetStats.mockResolvedValue(mockStats);
    render(<AdminDashboard />);
    expect(screen.getByTestId('admin-layout')).toBeInTheDocument();
    await screen.findAllByTestId('stat-tile');
  });

  it('renders with data-testid="admin-dashboard"', async () => {
    mockGetStats.mockResolvedValue(mockStats);
    render(<AdminDashboard />);
    expect(screen.getByTestId('admin-dashboard')).toBeInTheDocument();
    await screen.findAllByTestId('stat-tile');
  });

  it('handles zero values correctly', async () => {
    const zeroStats: AdminStats = {
      users: { total: 0, active: 0, superusers: 0 },
      experiments: { total: 0, active: 0 },
      events: { total: 0, daily_rate: 0 },
      feature_flags: { total: 0, active: 0 },
      timestamp: '2026-10-07T08:00:00.000000',
    };
    mockGetStats.mockResolvedValue(zeroStats);
    render(<AdminDashboard />);
    await screen.findAllByTestId('stat-tile');
    expect(Object.values(shownTiles())).toEqual(['0', '0', '0', '0', '0']);
  });
});
