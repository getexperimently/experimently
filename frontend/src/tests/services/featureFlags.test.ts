import { FeatureFlagsService } from '@/services/featureFlags';

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

describe('FeatureFlagsService.list', () => {
  it('calls the correct URL', async () => {
    mockOk({ items: [], total: 0 });
    await FeatureFlagsService.list();
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain('/api/v1/feature-flags');
  });

  it('appends status param', async () => {
    mockOk({ items: [] });
    await FeatureFlagsService.list({ status: 'active' });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain('status=active');
  });

  it('appends page and limit params', async () => {
    mockOk({ items: [] });
    await FeatureFlagsService.list({ page: 3, limit: 5 });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain('page=3');
    expect(url).toContain('limit=5');
  });

  it('returns parsed JSON', async () => {
    const payload = { items: [{ id: 'f1' }], total: 1 };
    mockOk(payload);
    const result = await FeatureFlagsService.list();
    expect(result).toEqual(payload);
  });

  it('throws on error', async () => {
    mockError(500, 'Server Error');
    await expect(FeatureFlagsService.list()).rejects.toThrow(
      'Failed to fetch feature flags: Server Error',
    );
  });
});

describe('FeatureFlagsService.get', () => {
  it('calls the correct URL', async () => {
    mockOk({ id: 'f1' });
    await FeatureFlagsService.get('f1');
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/feature-flags/f1`);
  });

  it('throws on error', async () => {
    mockError(404, 'Not Found');
    await expect(FeatureFlagsService.get('f1')).rejects.toThrow(
      'Failed to fetch feature flag: Not Found',
    );
  });
});

describe('FeatureFlagsService.create', () => {
  it('sends POST with JSON body', async () => {
    const data = { name: 'New Flag' };
    mockOk({ id: 'f1', ...data });
    await FeatureFlagsService.create(data);
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/feature-flags`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  });

  it('throws on error', async () => {
    mockError(400, 'Bad Request');
    await expect(FeatureFlagsService.create({ name: '' })).rejects.toThrow(
      'Failed to create feature flag: Bad Request',
    );
  });
});

describe('FeatureFlagsService.update', () => {
  it('sends PUT with JSON body', async () => {
    const data = { name: 'Updated' };
    mockOk({ id: 'f1', ...data });
    await FeatureFlagsService.update('f1', data);
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/feature-flags/f1`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  });

  it('throws on error', async () => {
    mockError(403, 'Forbidden');
    await expect(FeatureFlagsService.update('f1', {})).rejects.toThrow(
      'Failed to update feature flag: Forbidden',
    );
  });
});

describe('FeatureFlagsService.delete', () => {
  it('sends DELETE request', async () => {
    mockOk(undefined);
    await FeatureFlagsService.delete('f1');
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/feature-flags/f1`, {
      method: 'DELETE',
    });
  });

  it('throws on error', async () => {
    mockError(404, 'Not Found');
    await expect(FeatureFlagsService.delete('f1')).rejects.toThrow(
      'Failed to delete feature flag: Not Found',
    );
  });
});
