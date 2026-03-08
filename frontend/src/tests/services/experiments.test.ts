import { ExperimentsService } from '@/services/experiments';

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

describe('ExperimentsService.list', () => {
  it('calls the correct URL', async () => {
    mockOk({ items: [], total: 0, page: 1, limit: 20 });
    await ExperimentsService.list();
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain('/api/v1/experiments');
  });

  it('appends status filter param', async () => {
    mockOk({ items: [] });
    await ExperimentsService.list({ status: 'active' });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain('status=active');
  });

  it('appends page and limit params', async () => {
    mockOk({ items: [] });
    await ExperimentsService.list({ page: 2, limit: 10 });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain('page=2');
    expect(url).toContain('limit=10');
  });

  it('returns parsed JSON on success', async () => {
    const payload = { items: [{ id: '1' }], total: 1 };
    mockOk(payload);
    const result = await ExperimentsService.list();
    expect(result).toEqual(payload);
  });

  it('throws on non-ok response', async () => {
    mockError(500, 'Internal Server Error');
    await expect(ExperimentsService.list()).rejects.toThrow(
      'Failed to fetch experiments: Internal Server Error',
    );
  });
});

describe('ExperimentsService.get', () => {
  it('calls the correct URL', async () => {
    mockOk({ id: 'abc' });
    await ExperimentsService.get('abc');
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/experiments/abc`);
  });

  it('throws on error', async () => {
    mockError(404, 'Not Found');
    await expect(ExperimentsService.get('abc')).rejects.toThrow(
      'Failed to fetch experiment: Not Found',
    );
  });
});

describe('ExperimentsService.create', () => {
  it('sends POST with JSON body', async () => {
    const data = { name: 'Test', type: 'a_b', traffic_allocation: 100, variants: [] };
    mockOk({ id: '1', ...data });
    await ExperimentsService.create(data as never);
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/experiments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  });

  it('throws on error', async () => {
    mockError(400, 'Bad Request');
    await expect(ExperimentsService.create({} as never)).rejects.toThrow(
      'Failed to create experiment: Bad Request',
    );
  });
});

describe('ExperimentsService.update', () => {
  it('sends PUT with JSON body', async () => {
    const data = { name: 'Updated' };
    mockOk({ id: 'abc', ...data });
    await ExperimentsService.update('abc', data);
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/experiments/abc`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  });

  it('throws on error', async () => {
    mockError(403, 'Forbidden');
    await expect(ExperimentsService.update('abc', {})).rejects.toThrow(
      'Failed to update experiment: Forbidden',
    );
  });
});

describe('ExperimentsService.delete', () => {
  it('sends DELETE request', async () => {
    mockOk(undefined);
    await ExperimentsService.delete('abc');
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/experiments/abc`, {
      method: 'DELETE',
    });
  });

  it('throws on error', async () => {
    mockError(404, 'Not Found');
    await expect(ExperimentsService.delete('abc')).rejects.toThrow(
      'Failed to delete experiment: Not Found',
    );
  });
});
