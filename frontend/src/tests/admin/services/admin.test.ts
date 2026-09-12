import { AdminService } from '@/services/admin';
import { ApiError, TOKEN_STORAGE_KEY } from '@/services/api';
import { SafetySettings } from '@/types/admin';

const mockFetch = jest.fn();
global.fetch = mockFetch;

const BASE = 'http://localhost:8000';

beforeEach(() => {
  mockFetch.mockReset();
  localStorage.clear();
  process.env.NEXT_PUBLIC_API_URL = BASE;
});

afterAll(() => {
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
        expect.stringContaining(`${BASE}/api/v1/admin/users`),
        expect.any(Object),
      );
    });

    it('passes page/limit params', async () => {
      mockOk({ items: [], total: 0, page: 2, limit: 10 });
      await AdminService.listUsers({ page: 2, limit: 10 });
      const url = mockFetch.mock.calls[0][0] as string;
      expect(url).toContain('page=2');
      expect(url).toContain('limit=10');
    });

    it('omits an empty search param', async () => {
      mockOk({ items: [] });
      await AdminService.listUsers({ search: '' });
      const url = mockFetch.mock.calls[0][0] as string;
      expect(url).not.toContain('search=');
    });

    it('sends the bearer token when one is stored', async () => {
      localStorage.setItem(TOKEN_STORAGE_KEY, 'tok');
      mockOk({ items: [] });
      await AdminService.listUsers();
      const init = mockFetch.mock.calls[0][1] as RequestInit;
      expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok');
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
      expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/admin/stats`, expect.any(Object));
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

  // `/api/v1/rbac/*` moved to the Enterprise tree; covered by src/ee/rbac.test.ts.

  describe('safety', () => {
    const settings: SafetySettings = {
      id: 'settings-1',
      enable_automatic_rollbacks: true,
      default_metrics: {
        error_rate: { warning_threshold: 0.02, critical_threshold: 0.05, comparison_type: 'greater_than' },
      },
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    };

    it('getSafetySettings calls GET /safety/settings', async () => {
      mockOk(settings);
      const result = await AdminService.getSafetySettings();
      expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/safety/settings`, expect.any(Object));
      expect(result.enable_automatic_rollbacks).toBe(true);
    });

    it('updateSafetySettings POSTs SafetySettingsUpdate to /safety/settings', async () => {
      mockOk(settings);
      await AdminService.updateSafetySettings({
        enable_automatic_rollbacks: true,
        default_metrics: settings.default_metrics,
      });
      const [url, init] = mockFetch.mock.calls[0];
      expect(url).toBe(`${BASE}/api/v1/safety/settings`);
      expect(init.method).toBe('POST');
      expect(JSON.parse(init.body)).toEqual({
        enable_automatic_rollbacks: true,
        default_metrics: settings.default_metrics,
      });
    });

    it('does not duplicate the per-flag safety check (FeatureFlagsService.safetyCheck owns it)', () => {
      expect(AdminService).not.toHaveProperty('getFlagSafetyStatus');
    });

    it('rollbackFlag POSTs /safety/feature-flags/{id}/rollback with query params', async () => {
      mockOk({ success: true, feature_flag_id: 'flag-1', message: 'ok', timestamp: 'now' });
      await AdminService.rollbackFlag('flag-1', 'error spike');
      const [url, init] = mockFetch.mock.calls[0];
      expect(url).toBe(
        `${BASE}/api/v1/safety/feature-flags/flag-1/rollback?percentage=0&reason=error+spike`,
      );
      expect(init.method).toBe('POST');
      expect(init.body).toBeUndefined();
    });

    it('rollbackFlag omits an empty reason and honours a custom percentage', async () => {
      mockOk({ success: true, feature_flag_id: 'flag-1', message: 'ok', timestamp: 'now' });
      await AdminService.rollbackFlag('flag-1', '   ', 10);
      const [url] = mockFetch.mock.calls[0];
      expect(url).toBe(`${BASE}/api/v1/safety/feature-flags/flag-1/rollback?percentage=10`);
    });
  });

  describe('getSchedulerHealth', () => {
    it('calls /scheduler/health endpoint', async () => {
      mockOk([]);
      await AdminService.getSchedulerHealth();
      expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/scheduler/health`, expect.any(Object));
    });
  });

  describe('sendTestNotification', () => {
    it('posts channel, message and recipient', async () => {
      mockOk({ success: true, channel: 'slack', message: 'sent' });
      await AdminService.sendTestNotification('slack', 'hello', '#ops');
      const [url, init] = mockFetch.mock.calls[0];
      expect(url).toBe(`${BASE}/api/v1/notifications/test`);
      expect(init.method).toBe('POST');
      expect(JSON.parse(init.body)).toEqual({ channel: 'slack', message: 'hello', recipient: '#ops' });
    });
  });

  describe('error handling', () => {
    it('throws ApiError on non-ok response', async () => {
      mockError(404, 'Not Found');
      const err = await AdminService.getStats().catch((e) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err.status).toBe(404);
    });
  });
});
