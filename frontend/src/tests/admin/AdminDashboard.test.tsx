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

const mockStats: AdminStats = {
  total_experiments: 25,
  active_experiments: 10,
  total_feature_flags: 50,
  active_feature_flags: 30,
  total_users: 100,
};

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

  it('shows correct total_experiments value', async () => {
    mockGetStats.mockResolvedValue(mockStats);
    render(<AdminDashboard />);
    await waitFor(() => {
      expect(screen.getByText('25')).toBeInTheDocument();
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
  });

  it('renders with data-testid="admin-dashboard"', async () => {
    mockGetStats.mockResolvedValue(mockStats);
    render(<AdminDashboard />);
    expect(screen.getByTestId('admin-dashboard')).toBeInTheDocument();
  });

  it('handles zero values correctly', async () => {
    const zeroStats: AdminStats = {
      total_experiments: 0,
      active_experiments: 0,
      total_feature_flags: 0,
      active_feature_flags: 0,
      total_users: 0,
    };
    mockGetStats.mockResolvedValue(zeroStats);
    render(<AdminDashboard />);
    await waitFor(() => {
      const zeros = screen.getAllByText('0');
      expect(zeros.length).toBeGreaterThanOrEqual(5);
    });
  });
});
