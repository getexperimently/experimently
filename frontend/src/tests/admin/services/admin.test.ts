import { AdminService } from '@/services/admin';

const mockFetch = jest.fn();
global.fetch = mockFetch;

const BASE = 'http://localhost:8000';

beforeEach(() => {
  mockFetch.mockReset();
  delete process.env.NEXT_PUBLIC_API_URL;
});

function mockOk(data: unknown) {
  mockFetch.mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: () => Promise.resolve(data),
  } as Response);
}

function mockError(status = 500, statusText = 'Internal Server Error') {
  mockFetch.mockResolvedValueOnce({
    ok: false,
    status,
    statusText,
  } as Response);
}

describe('AdminService', () => {
  describe('listUsers', () => {
    it('calls correct endpoint', async () => {
      mockOk({ items: [], total: 0, page: 1, limit: 20 });
      await AdminService.listUsers();
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining(`${BASE}/api/v1/admin/users`)
      );
    });

    it('passes page/limit params', async () => {
      mockOk({ items: [], total: 0, page: 2, limit: 10 });
      await AdminService.listUsers({ page: 2, limit: 10 });
      const url = mockFetch.mock.calls[0][0] as string;
      expect(url).toContain('page=2');
      expect(url).toContain('limit=10');
    });
  });

  describe('getStats', () => {
    it('calls /admin/stats endpoint', async () => {
      mockOk({
        total_experiments: 10,
        active_experiments: 5,
        total_feature_flags: 20,
        active_feature_flags: 12,
        total_users: 50,
      });
      await AdminService.getStats();
      expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/admin/stats`);
    });
  });

  describe('updateUser', () => {
    it('calls PUT with correct data', async () => {
      mockOk({ id: '1', username: 'admin', email: 'admin@test.com', role: 'ADMIN', is_active: true, created_at: '' });
      await AdminService.updateUser('1', { is_active: false });
      expect(mockFetch).toHaveBeenCalledWith(
        `${BASE}/api/v1/admin/users/1`,
        expect.objectContaining({
          method: 'PUT',
          headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ is_active: false }),
        })
      );
    });
  });

  describe('deleteUser', () => {
    it('calls DELETE on correct endpoint', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, status: 204 } as Response);
      await AdminService.deleteUser('42');
      expect(mockFetch).toHaveBeenCalledWith(
        `${BASE}/api/v1/admin/users/42`,
        expect.objectContaining({ method: 'DELETE' })
      );
    });
  });

  describe('listAuditLogs', () => {
    it('passes filters as query params', async () => {
      mockOk({ items: [], total: 0, page: 1, limit: 20 });
      await AdminService.listAuditLogs({
        action_type: 'CREATE',
        entity_type: 'feature_flag',
        start_date: '2024-01-01',
      });
      const url = mockFetch.mock.calls[0][0] as string;
      expect(url).toContain('action_type=CREATE');
      expect(url).toContain('entity_type=feature_flag');
      expect(url).toContain('start_date=2024-01-01');
    });
  });

  describe('listRoles', () => {
    it('calls /rbac/roles endpoint', async () => {
      mockOk([]);
      await AdminService.listRoles();
      expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/rbac/roles`);
    });
  });

  describe('getSafetySettings', () => {
    it('calls /safety/settings endpoint', async () => {
      mockOk({
        error_rate_threshold: 0.05,
        latency_threshold_ms: 500,
        rollback_policy: 'auto',
        monitoring_window_minutes: 15,
      });
      await AdminService.getSafetySettings();
      expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/safety/settings`);
    });
  });

  describe('getSchedulerHealth', () => {
    it('calls /scheduler/health endpoint', async () => {
      mockOk([]);
      await AdminService.getSchedulerHealth();
      expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/scheduler/health`);
    });
  });

  describe('error handling', () => {
    it('throws error on non-ok response', async () => {
      mockError(404, 'Not Found');
      await expect(AdminService.getStats()).rejects.toThrow();
    });
  });
});
