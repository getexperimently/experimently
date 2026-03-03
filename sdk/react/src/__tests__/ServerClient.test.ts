/**
 * @jest-environment node
 */
import { ServerClient } from '../client/ServerClient';
import { SdkConfig, UserContext, FeatureFlag } from '../client/types';

const baseConfig: SdkConfig = {
  apiKey: 'test-api-key',
  baseUrl: 'https://api.example.com',
};

const user: UserContext = { userId: 'user-123' };

const enabledFlag: FeatureFlag = {
  id: 'flag-1',
  key: 'my-flag',
  name: 'My Flag',
  enabled: true,
  rolloutPercentage: 100,
};

const disabledFlag: FeatureFlag = {
  id: 'flag-2',
  key: 'disabled-flag',
  name: 'Disabled Flag',
  enabled: false,
  rolloutPercentage: 0,
};

function mockFetch(response: object, status = 200): jest.Mock {
  const mock = jest.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(response),
  });
  global.fetch = mock;
  return mock;
}

afterEach(() => {
  jest.restoreAllMocks();
});

// ─── Constructor validation ───────────────────────────────────────────────────

describe('ServerClient constructor', () => {
  it('throws when apiKey is missing', () => {
    expect(
      () => new ServerClient({ apiKey: '', baseUrl: 'https://api.example.com' })
    ).toThrow('apiKey is required');
  });

  it('throws when baseUrl is missing', () => {
    expect(
      () => new ServerClient({ apiKey: 'key', baseUrl: '' })
    ).toThrow('baseUrl is required');
  });

  it('creates client with valid config', () => {
    expect(() => new ServerClient(baseConfig)).not.toThrow();
  });

  it('strips trailing slash from baseUrl', async () => {
    const fetchMock = mockFetch(enabledFlag);
    const client = new ServerClient({ ...baseConfig, baseUrl: 'https://api.example.com/' });
    await client.evaluateFeatureFlag('my-flag', user);
    expect(fetchMock.mock.calls[0][0]).toMatch(/^https:\/\/api\.example\.com\/api/);
    expect(fetchMock.mock.calls[0][0]).not.toMatch(/example\.com\/\/api/);
  });
});

// ─── evaluateFeatureFlag ──────────────────────────────────────────────────────

describe('ServerClient.evaluateFeatureFlag', () => {
  it('returns enabled flag evaluation with correct structure', async () => {
    mockFetch(enabledFlag);
    const client = new ServerClient(baseConfig);
    const result = await client.evaluateFeatureFlag('my-flag', user);
    expect(result.flagKey).toBe('my-flag');
    expect(result.isEnabled).toBe(true);
    expect(result.variant).not.toBeNull();
  });

  it('returns disabled flag evaluation when flag is disabled', async () => {
    mockFetch(disabledFlag);
    const client = new ServerClient(baseConfig);
    const result = await client.evaluateFeatureFlag('disabled-flag', user);
    expect(result.flagKey).toBe('disabled-flag');
    expect(result.isEnabled).toBe(false);
    expect(result.variant).toBeNull();
  });

  it('sends X-API-Key header in request', async () => {
    const fetchMock = mockFetch(enabledFlag);
    const client = new ServerClient(baseConfig);
    await client.evaluateFeatureFlag('my-flag', user);
    const headers = fetchMock.mock.calls[0][1].headers;
    expect(headers['X-API-Key']).toBe('test-api-key');
  });

  it('sends X-User-ID header in request', async () => {
    const fetchMock = mockFetch(enabledFlag);
    const client = new ServerClient(baseConfig);
    await client.evaluateFeatureFlag('my-flag', user);
    const headers = fetchMock.mock.calls[0][1].headers;
    expect(headers['X-User-ID']).toBe('user-123');
  });

  it('returns error evaluation on non-2xx response', async () => {
    mockFetch({}, 500);
    const client = new ServerClient(baseConfig);
    const result = await client.evaluateFeatureFlag('my-flag', user);
    expect(result.isEnabled).toBe(false);
    expect(result.variant).toBeNull();
    expect(result.error).toBeInstanceOf(Error);
  });

  it('returns error evaluation on network failure', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('Network error'));
    const client = new ServerClient(baseConfig);
    const result = await client.evaluateFeatureFlag('my-flag', user);
    expect(result.isEnabled).toBe(false);
    expect(result.variant).toBeNull();
    expect(result.error).toBeInstanceOf(Error);
  });
});

// ─── getAll ───────────────────────────────────────────────────────────────────

describe('ServerClient.getAll', () => {
  it('returns empty object for empty flagKeys array', async () => {
    const client = new ServerClient(baseConfig);
    const result = await client.getAll([], user);
    expect(result).toEqual({});
  });

  it('evaluates multiple flags and returns map keyed by flagKey', async () => {
    const fetchMock = jest.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(enabledFlag),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(disabledFlag),
      });
    global.fetch = fetchMock;

    const client = new ServerClient(baseConfig);
    const result = await client.getAll(['my-flag', 'disabled-flag'], user);

    expect(result).toHaveProperty('my-flag');
    expect(result).toHaveProperty('disabled-flag');
    expect(result['my-flag'].isEnabled).toBe(true);
    expect(result['disabled-flag'].isEnabled).toBe(false);
  });

  it('evaluates flags in parallel (calls fetch for each key)', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(enabledFlag),
    });
    global.fetch = fetchMock;

    const client = new ServerClient(baseConfig);
    await client.getAll(['flag-a', 'flag-b', 'flag-c'], user);

    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('returns all keys even when some fail', async () => {
    const fetchMock = jest.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(enabledFlag),
      })
      .mockRejectedValueOnce(new Error('Network error'));
    global.fetch = fetchMock;

    const client = new ServerClient(baseConfig);
    const result = await client.getAll(['my-flag', 'failing-flag'], user);

    expect(result).toHaveProperty('my-flag');
    expect(result).toHaveProperty('failing-flag');
    expect(result['my-flag'].isEnabled).toBe(true);
    expect(result['failing-flag'].isEnabled).toBe(false);
    expect(result['failing-flag'].error).toBeInstanceOf(Error);
  });
});

// ─── No browser APIs ─────────────────────────────────────────────────────────

describe('ServerClient — no browser-specific API usage', () => {
  it('does not reference document', async () => {
    // Temporarily make document undefined to simulate Node environment
    const originalDocument = global.document;
    // @ts-expect-error intentionally removing document
    delete global.document;

    mockFetch(enabledFlag);
    const client = new ServerClient(baseConfig);
    // Should not throw even when document is unavailable
    const result = await client.evaluateFeatureFlag('my-flag', user);
    expect(result.flagKey).toBe('my-flag');

    global.document = originalDocument;
  });

  it('does not reference window.localStorage', async () => {
    mockFetch(enabledFlag);
    const client = new ServerClient(baseConfig);
    const result = await client.evaluateFeatureFlag('my-flag', user);
    // If ServerClient tried to use localStorage it would have thrown
    expect(result).toBeDefined();
  });

  it('has separate per-instance cache (not shared between instances)', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(enabledFlag),
    });
    global.fetch = fetchMock;

    const client1 = new ServerClient(baseConfig);
    const client2 = new ServerClient(baseConfig);

    await client1.evaluateFeatureFlag('my-flag', user);
    await client2.evaluateFeatureFlag('my-flag', user);

    // Each instance has its own cache, so both should have made a fetch call
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('handles timeout configuration', async () => {
    expect(
      () => new ServerClient({ ...baseConfig, timeoutMs: 1000 })
    ).not.toThrow();
  });
});
