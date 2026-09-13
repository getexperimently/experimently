import {
  ApiError,
  TOKEN_STORAGE_KEY,
  apiBase,
  apiFetch,
  apiUrl,
  buildQuery,
  clearToken,
  getToken,
  isApiError,
  messageForDetail,
  navigation,
  redirectToLogin,
  safeNextPath,
  setToken,
  wsBase,
} from '@/services/api';

const mockFetch = jest.fn();
global.fetch = mockFetch;

/** Await a promise that is expected to reject and return the ApiError. */
async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (err) {
    return err as ApiError;
  }
  throw new Error('expected promise to reject');
}

let assignSpy: jest.SpyInstance;

beforeEach(() => {
  mockFetch.mockReset();
  localStorage.clear();
  delete process.env.NEXT_PUBLIC_API_URL;
  delete process.env.NEXT_PUBLIC_WS_URL;
  window.history.replaceState({}, '', '/experiments?page=2');
  assignSpy = jest.spyOn(navigation, 'assign').mockImplementation(() => {});
});

afterEach(() => {
  assignSpy.mockRestore();
});

function jsonResponse(status: number, body: unknown, extra: Partial<Response> = {}): Response {
  const text = body === undefined ? '' : JSON.stringify(body);
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'STATUS',
    headers: { get: (name: string) => (name.toLowerCase() === 'content-type' ? 'application/json' : null) },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(text),
    ...extra,
  } as unknown as Response;
}

describe('apiBase / apiUrl / buildQuery', () => {
  it('defaults to same-origin (empty string)', () => {
    expect(apiBase()).toBe('');
    expect(apiUrl('/api/v1/experiments')).toBe('/api/v1/experiments');
  });

  it('falls back to localhost:8000 only under next dev', () => {
    const original = process.env.NODE_ENV;
    try {
      (process.env as Record<string, string | undefined>).NODE_ENV = 'development';
      expect(apiBase()).toBe('http://localhost:8000');
      process.env.NEXT_PUBLIC_API_URL = '';
      expect(apiBase()).toBe('');
      delete process.env.NEXT_PUBLIC_API_URL;
      (process.env as Record<string, string | undefined>).NODE_ENV = 'production';
      expect(apiBase()).toBe('');
    } finally {
      (process.env as Record<string, string | undefined>).NODE_ENV = original;
    }
  });

  it('uses NEXT_PUBLIC_API_URL and strips trailing slashes', () => {
    process.env.NEXT_PUBLIC_API_URL = 'http://localhost:8000/';
    expect(apiBase()).toBe('http://localhost:8000');
    expect(apiUrl('api/v1/x')).toBe('http://localhost:8000/api/v1/x');
  });

  it('omits undefined and null query values', () => {
    expect(buildQuery({ a: 1, b: undefined, c: null, d: 'x', e: false })).toBe('?a=1&d=x&e=false');
    expect(buildQuery({})).toBe('');
    expect(buildQuery(undefined)).toBe('');
  });

  it('derives the websocket base from the api base or location', () => {
    expect(wsBase()).toBe('ws://localhost');
    process.env.NEXT_PUBLIC_API_URL = 'https://api.example.com';
    expect(wsBase()).toBe('wss://api.example.com');
    process.env.NEXT_PUBLIC_WS_URL = 'wss://ws.example.com/';
    expect(wsBase()).toBe('wss://ws.example.com');
  });
});

describe('token storage', () => {
  it('round-trips the token through localStorage', () => {
    expect(getToken()).toBeNull();
    setToken('abc');
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBe('abc');
    expect(getToken()).toBe('abc');
    clearToken();
    expect(getToken()).toBeNull();
  });
});

describe('apiFetch — request shaping', () => {
  it('calls the global fetch with the prefixed URL and JSON headers', async () => {
    process.env.NEXT_PUBLIC_API_URL = 'http://localhost:8000';
    mockFetch.mockResolvedValueOnce(jsonResponse(200, { ok: 1 }));
    const result = await apiFetch<{ ok: number }>('/api/v1/experiments', { query: { page: 2 } });
    expect(result).toEqual({ ok: 1 });
    const [url, init] = mockFetch.mock.calls[0];
    expect(url).toBe('http://localhost:8000/api/v1/experiments?page=2');
    expect(init.headers.Accept).toBe('application/json');
    expect(init.headers.Authorization).toBeUndefined();
  });

  it('adds the bearer header when a token is stored', async () => {
    setToken('tok-123');
    mockFetch.mockResolvedValueOnce(jsonResponse(200, {}));
    await apiFetch('/api/v1/auth/me');
    const [, init] = mockFetch.mock.calls[0];
    expect(init.headers.Authorization).toBe('Bearer tok-123');
  });

  it('does not add the bearer header when auth is false', async () => {
    setToken('tok-123');
    mockFetch.mockResolvedValueOnce(jsonResponse(200, {}));
    await apiFetch('/api/v1/auth/login', { auth: false });
    const [, init] = mockFetch.mock.calls[0];
    expect(init.headers.Authorization).toBeUndefined();
  });

  it('serialises `json` and sets Content-Type', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(201, { id: '1' }));
    await apiFetch('/api/v1/experiments', { method: 'POST', json: { name: 'x' } });
    const [, init] = mockFetch.mock.calls[0];
    expect(init.method).toBe('POST');
    expect(init.body).toBe(JSON.stringify({ name: 'x' }));
    expect(init.headers['Content-Type']).toBe('application/json');
  });

  it('passes a string body through and keeps caller headers', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(200, {}));
    await apiFetch('/x', { method: 'PUT', body: '{"a":1}', headers: { 'X-Test': '1' } });
    const [, init] = mockFetch.mock.calls[0];
    expect(init.body).toBe('{"a":1}');
    expect(init.headers['X-Test']).toBe('1');
    expect(init.headers['Content-Type']).toBe('application/json');
  });

  it('returns undefined for 204 responses', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(204, undefined));
    await expect(apiFetch('/x', { method: 'DELETE' })).resolves.toBeUndefined();
  });

  it('tolerates minimal mocked responses without json()/headers', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true } as Response);
    await expect(apiFetch('/x')).resolves.toBeUndefined();
  });

  it('rejects a non-JSON 2xx body (e.g. an HTML shell served by a proxy)', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse(200, undefined, {
        headers: { get: () => 'text/html' } as unknown as Headers,
        text: () => Promise.resolve('<html></html>'),
      }),
    );
    await expect(apiFetch('/api/v1/experiments')).rejects.toMatchObject({
      status: 200,
      message: expect.stringContaining('Expected a JSON response'),
    });
  });
});

describe('apiFetch — errors', () => {
  it('throws ApiError with the string detail as message', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(404, { detail: 'Experiment not found' }));
    const err = await rejection(apiFetch('/api/v1/experiments/x'));
    expect(isApiError(err)).toBe(true);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.detail).toBe('Experiment not found');
    expect(err.message).toBe('Experiment not found');
    expect(err.code).toBeUndefined();
  });

  it('exposes a typed detail.code', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse(403, { detail: { code: 'workspace_role_required', message: 'Owner role required' } }),
    );
    const err = await rejection(apiFetch('/api/v1/workspaces/'));
    expect(err.status).toBe(403);
    expect(err.code).toBe('workspace_role_required');
    expect(err.isForbidden).toBe(true);
    expect(err.message).toBe('Owner role required');
    expect(assignSpy).not.toHaveBeenCalled();
  });

  it('formats pydantic validation errors', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse(422, {
        detail: [{ loc: ['body', 'name'], msg: 'field required', type: 'value_error' }],
      }),
    );
    const err = await rejection(apiFetch('/x', { method: 'POST', json: {} }));
    expect(err.status).toBe(422);
    expect(err.message).toBe('name: field required');
  });

  it('falls back to statusText when the body is unreadable', async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 500, statusText: 'Internal Server Error' } as Response);
    await expect(apiFetch('/x')).rejects.toThrow('Internal Server Error');
  });

  it('wraps network failures as ApiError status 0', async () => {
    mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    const err = await rejection(apiFetch('/x'));
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
    expect(err.isNetworkError).toBe(true);
    expect(err.message).toContain("Can't reach the API");
  });

  it('messageForDetail handles the remaining shapes', () => {
    expect(messageForDetail(500, undefined)).toBe('Request failed with status 500');
    expect(messageForDetail(0, undefined)).toBe('Request failed');
    expect(messageForDetail(400, { msg: 'nope' })).toBe('nope');
    expect(messageForDetail(400, { code: 'x_code' })).toBe('x_code');
    expect(messageForDetail(400, ['a', 'b'])).toBe('a; b');
  });
});

describe('apiFetch — 401 handling', () => {
  it('clears the token and redirects to /login?next=<path>', async () => {
    setToken('stale');
    mockFetch.mockResolvedValueOnce(jsonResponse(401, { detail: 'Not authenticated' }));
    const err = await rejection(apiFetch('/api/v1/experiments'));
    expect(err.status).toBe(401);
    expect(err.isUnauthorized).toBe(true);
    expect(getToken()).toBeNull();
    expect(assignSpy).toHaveBeenCalledWith('/login?next=%2Fexperiments%3Fpage%3D2');
  });

  it('does not redirect when already on /login', async () => {
    window.history.replaceState({}, '', '/login');
    setToken('stale');
    mockFetch.mockResolvedValueOnce(jsonResponse(401, { detail: 'Invalid email or password' }));
    await expect(apiFetch('/api/v1/auth/me')).rejects.toThrow('Invalid email or password');
    expect(assignSpy).not.toHaveBeenCalled();
  });

  it('does not redirect or clear the token for unauthenticated requests (auth: false)', async () => {
    setToken('keep-me');
    mockFetch.mockResolvedValueOnce(jsonResponse(401, { detail: 'Invalid email or password' }));
    await expect(
      apiFetch('/api/v1/auth/login', { method: 'POST', json: {}, auth: false }),
    ).rejects.toThrow('Invalid email or password');
    expect(getToken()).toBe('keep-me');
    expect(assignSpy).not.toHaveBeenCalled();
  });

  it('honours redirectOn401: false but still clears the token', async () => {
    setToken('stale');
    mockFetch.mockResolvedValueOnce(jsonResponse(401, { detail: 'expired' }));
    await expect(apiFetch('/api/v1/auth/me', { redirectOn401: false })).rejects.toThrow('expired');
    expect(getToken()).toBeNull();
    expect(assignSpy).not.toHaveBeenCalled();
  });
});

describe('redirectToLogin / safeNextPath', () => {
  it('drops next for the root and login paths', () => {
    redirectToLogin('/');
    expect(assignSpy).toHaveBeenLastCalledWith('/login');
    redirectToLogin('/login?next=%2Fx');
    expect(assignSpy).toHaveBeenLastCalledWith('/login');
  });

  it('rejects protocol-relative and external targets', () => {
    expect(safeNextPath('//evil.com')).toBe('/');
    expect(safeNextPath('https://evil.com')).toBe('/');
    expect(safeNextPath(undefined, '/experiments')).toBe('/experiments');
    expect(safeNextPath('/feature-flags/1')).toBe('/feature-flags/1');
    redirectToLogin('//evil.com');
    expect(assignSpy).toHaveBeenLastCalledWith('/login');
  });
});
