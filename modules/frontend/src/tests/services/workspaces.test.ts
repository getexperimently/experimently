import { workspaceService } from '@modules/services/workspaces';
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
    text: () => Promise.resolve(JSON.stringify(data)),
  } as Response);
}

function mockError(status = 500, body = 'Internal Server Error') {
  mockFetch.mockResolvedValueOnce({
    ok: false,
    status,
    statusText: body,
    text: () => Promise.resolve(body),
  } as Response);
}

const deleteInit = expect.objectContaining({ method: 'DELETE' });

describe('workspaceService.list', () => {
  it('calls the correct URL', async () => {
    mockOk([]);
    await workspaceService.list();
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/workspaces/`, expect.any(Object));
  });

  it('returns parsed JSON', async () => {
    const payload = [{ id: 'w1', name: 'Team A' }];
    mockOk(payload);
    const result = await workspaceService.list();
    expect(result).toEqual(payload);
  });

  it('sends the bearer token when one is stored', async () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'tok');
    mockOk([]);
    await workspaceService.list();
    const [, opts] = mockFetch.mock.calls[0];
    expect(opts.headers.Authorization).toBe('Bearer tok');
  });
});

describe('workspaceService.create', () => {
  it('sends POST with body', async () => {
    const data = { name: 'New WS', slug: 'new-ws' };
    mockOk({ id: 'w1', ...data });
    await workspaceService.create(data);
    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/workspaces/`);
    expect(opts.method).toBe('POST');
    expect(opts.headers['Content-Type']).toBe('application/json');
    expect(JSON.parse(opts.body)).toEqual(data);
  });
});

describe('workspaceService.get', () => {
  it('calls the correct URL', async () => {
    mockOk({ id: 'w1' });
    await workspaceService.get('w1');
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/workspaces/w1`, expect.any(Object));
  });
});

describe('workspaceService.update', () => {
  it('sends PUT with body', async () => {
    const data = { name: 'Updated' };
    mockOk({ id: 'w1', ...data });
    await workspaceService.update('w1', data);
    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/workspaces/w1`);
    expect(opts.method).toBe('PUT');
  });
});

describe('workspaceService.delete', () => {
  it('sends DELETE request', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true } as Response);
    await workspaceService.delete('w1');
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/workspaces/w1`, deleteInit);
  });

  it('throws on error', async () => {
    mockError(404, 'Not Found');
    await expect(workspaceService.delete('w1')).rejects.toThrow('Not Found');
  });
});

describe('workspaceService.listMembers', () => {
  it('calls the correct URL', async () => {
    mockOk([]);
    await workspaceService.listMembers('w1');
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/workspaces/w1/members`, expect.any(Object));
  });
});

describe('workspaceService.addMember', () => {
  it('sends POST', async () => {
    const data = { user_id: 'u1', role: 'DEVELOPER' };
    mockOk({ ...data, username: 'dev1' });
    await workspaceService.addMember('w1', data);
    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/workspaces/w1/members`);
    expect(opts.method).toBe('POST');
  });
});

describe('workspaceService.updateMember', () => {
  it('sends PUT with role', async () => {
    mockOk({ user_id: 'u1', role: 'ADMIN' });
    await workspaceService.updateMember('w1', 'u1', 'ADMIN');
    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/workspaces/w1/members/u1`);
    expect(opts.method).toBe('PUT');
    expect(JSON.parse(opts.body)).toEqual({ role: 'ADMIN' });
  });
});

describe('workspaceService.removeMember', () => {
  it('sends DELETE', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true } as Response);
    await workspaceService.removeMember('w1', 'u1');
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/workspaces/w1/members/u1`, deleteInit);
  });
});

describe('workspaceService.sendInvite', () => {
  it('sends POST with email and role', async () => {
    mockOk({ token: 'tok' });
    await workspaceService.sendInvite('w1', 'a@b.com', 'VIEWER');
    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/workspaces/w1/invites`);
    expect(JSON.parse(opts.body)).toEqual({ email: 'a@b.com', role: 'VIEWER' });
  });
});

describe('workspaceService.getInvite', () => {
  it('calls correct URL', async () => {
    mockOk({ token: 'tok' });
    await workspaceService.getInvite('tok');
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/workspaces/invites/tok`, expect.any(Object));
  });
});

describe('workspaceService.acceptInvite', () => {
  it('sends POST', async () => {
    mockOk({ workspace_id: 'w1' });
    await workspaceService.acceptInvite('tok');
    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/workspaces/invites/tok/accept`);
    expect(opts.method).toBe('POST');
  });
});

describe('workspaceService.listAPIKeys', () => {
  it('calls correct URL', async () => {
    mockOk([]);
    await workspaceService.listAPIKeys('w1');
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/workspaces/w1/api-keys`, expect.any(Object));
  });
});

describe('workspaceService.createAPIKey', () => {
  it('sends POST with name and scopes', async () => {
    const data = { name: 'key1', scopes: ['read'] };
    mockOk({ id: 'k1', ...data, key: 'secret' });
    await workspaceService.createAPIKey('w1', data);
    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/workspaces/w1/api-keys`);
    expect(opts.method).toBe('POST');
    expect(JSON.parse(opts.body)).toEqual(data);
  });
});

describe('workspaceService.revokeAPIKey', () => {
  it('sends DELETE', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true } as Response);
    await workspaceService.revokeAPIKey('w1', 'k1');
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/workspaces/w1/api-keys/k1`, deleteInit);
  });
});

describe('workspaceService.rotateAPIKey', () => {
  it('sends POST', async () => {
    mockOk({ id: 'k1', key: 'new-secret' });
    await workspaceService.rotateAPIKey('w1', 'k1');
    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/workspaces/w1/api-keys/k1/rotate`);
    expect(opts.method).toBe('POST');
  });
});

describe('error handling', () => {
  it('throws with body text on error', async () => {
    mockError(400, 'Validation failed');
    await expect(workspaceService.get('w1')).rejects.toThrow('Validation failed');
  });

  it('throws with the JSON detail on error', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 403,
      statusText: 'Forbidden',
      text: () => Promise.resolve(JSON.stringify({ detail: { code: 'workspace_role_required' } })),
    } as Response);
    const err = await workspaceService.get('w1').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(403);
    expect(err.code).toBe('workspace_role_required');
  });

  it('throws with status on empty body', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: '',
      text: () => Promise.resolve(''),
    } as Response);
    await expect(workspaceService.get('w1')).rejects.toThrow('Request failed with status 500');
  });
});
