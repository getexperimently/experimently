import { ExperimentsService } from '@/services/experiments';
import { ApiError, TOKEN_STORAGE_KEY } from '@/services/api';

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

const jsonInit = (method: string, data: unknown) =>
  expect.objectContaining({
    method,
    headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(data),
  });

describe('ExperimentsService.list', () => {
  it('calls the correct URL', async () => {
    mockOk({ items: [], total: 0, page: 1, limit: 20 });
    await ExperimentsService.list();
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toBe(`${BASE}/api/v1/experiments`);
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

  it('sends the bearer token when one is stored', async () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'tok');
    mockOk({ items: [] });
    await ExperimentsService.list();
    const init = mockFetch.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok');
  });

  it('throws ApiError on non-ok response', async () => {
    mockError(500, 'Internal Server Error');
    const err = await ExperimentsService.list().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(500);
    expect(err.message).toBe('Internal Server Error');
  });
});

describe('ExperimentsService.get', () => {
  it('calls the correct URL', async () => {
    mockOk({ id: 'abc' });
    await ExperimentsService.get('abc');
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/experiments/abc`, expect.any(Object));
  });

  it('throws on error', async () => {
    mockError(404, 'Not Found');
    await expect(ExperimentsService.get('abc')).rejects.toThrow('Not Found');
  });
});

describe('ExperimentsService.create', () => {
  it('sends POST with JSON body', async () => {
    const data = { name: 'Test', type: 'a_b', traffic_allocation: 100, variants: [] };
    mockOk({ id: '1', ...data });
    await ExperimentsService.create(data as never);
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/experiments`, jsonInit('POST', data));
  });

  it('throws on error', async () => {
    mockError(400, 'Bad Request');
    await expect(ExperimentsService.create({} as never)).rejects.toThrow('Bad Request');
  });
});

describe('ExperimentsService.update', () => {
  it('sends PUT with JSON body', async () => {
    const data = { name: 'Updated' };
    mockOk({ id: 'abc', ...data });
    await ExperimentsService.update('abc', data);
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/experiments/abc`, jsonInit('PUT', data));
  });

  it('throws on error', async () => {
    mockError(403, 'Forbidden');
    await expect(ExperimentsService.update('abc', {})).rejects.toThrow('Forbidden');
  });
});

describe('ExperimentsService.delete', () => {
  it('sends DELETE request', async () => {
    mockOk(undefined);
    await ExperimentsService.delete('abc');
    expect(mockFetch).toHaveBeenCalledWith(
      `${BASE}/api/v1/experiments/abc`,
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('throws on error', async () => {
    mockError(404, 'Not Found');
    await expect(ExperimentsService.delete('abc')).rejects.toThrow('Not Found');
  });
});
