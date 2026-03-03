import { ExperimentationClient } from '../client/ExperimentationClient';
import { SdkConfig, FeatureFlag, UserContext } from '../client/types';

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

const flagWithVariants: FeatureFlag = {
  id: 'flag-3',
  key: 'variant-flag',
  name: 'Variant Flag',
  enabled: true,
  rolloutPercentage: 100,
  variants: [
    { name: 'control', weight: 0.5 },
    { name: 'treatment', weight: 0.5 },
  ],
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

describe('ExperimentationClient constructor', () => {
  it('throws when apiKey is missing', () => {
    expect(
      () => new ExperimentationClient({ apiKey: '', baseUrl: 'https://api.example.com' })
    ).toThrow('apiKey is required');
  });

  it('throws when baseUrl is missing', () => {
    expect(
      () => new ExperimentationClient({ apiKey: 'key', baseUrl: '' })
    ).toThrow('baseUrl is required');
  });

  it('strips trailing slash from baseUrl', async () => {
    const fetchMock = mockFetch(enabledFlag);
    const client = new ExperimentationClient({ ...baseConfig, baseUrl: 'https://api.example.com/' });
    await client.evaluateFeatureFlag(user, 'my-flag');
    expect(fetchMock.mock.calls[0][0]).toMatch(/^https:\/\/api\.example\.com\/api/);
    expect(fetchMock.mock.calls[0][0]).not.toMatch(/example\.com\/\/api/);
  });

  it('creates client with valid config', () => {
    expect(() => new ExperimentationClient(baseConfig)).not.toThrow();
  });
});

// ─── evaluateFeatureFlag ──────────────────────────────────────────────────────

describe('evaluateFeatureFlag', () => {
  it('makes a GET request to the correct URL', async () => {
    const fetchMock = mockFetch(enabledFlag);
    const client = new ExperimentationClient(baseConfig);
    await client.evaluateFeatureFlag(user, 'my-flag');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe(
      'https://api.example.com/api/v1/feature-flags/my-flag/evaluate'
    );
  });

  it('sends X-API-Key header', async () => {
    const fetchMock = mockFetch(enabledFlag);
    const client = new ExperimentationClient(baseConfig);
    await client.evaluateFeatureFlag(user, 'my-flag');

    const headers = fetchMock.mock.calls[0][1].headers;
    expect(headers['X-API-Key']).toBe('test-api-key');
  });

  it('sends X-User-ID header', async () => {
    const fetchMock = mockFetch(enabledFlag);
    const client = new ExperimentationClient(baseConfig);
    await client.evaluateFeatureFlag(user, 'my-flag');

    const headers = fetchMock.mock.calls[0][1].headers;
    expect(headers['X-User-ID']).toBe('user-123');
  });

  it('returns null for a disabled flag', async () => {
    mockFetch(disabledFlag);
    const client = new ExperimentationClient(baseConfig);
    const result = await client.evaluateFeatureFlag(user, 'disabled-flag');
    expect(result).toBeNull();
  });

  it('returns "on" for an enabled flag with no variants', async () => {
    mockFetch(enabledFlag);
    const client = new ExperimentationClient(baseConfig);
    const result = await client.evaluateFeatureFlag(user, 'my-flag');
    expect(result).toBe('on');
  });

  it('returns a variant name for an enabled flag with variants', async () => {
    mockFetch(flagWithVariants);
    const client = new ExperimentationClient(baseConfig);
    const result = await client.evaluateFeatureFlag(user, 'variant-flag');
    expect(['control', 'treatment']).toContain(result);
  });

  it('returns null when user hash falls outside rollout percentage', async () => {
    // 0% rollout — nobody is included
    const zeroRolloutFlag: FeatureFlag = { ...enabledFlag, rolloutPercentage: 0 };
    mockFetch(zeroRolloutFlag);
    const client = new ExperimentationClient(baseConfig);
    const result = await client.evaluateFeatureFlag(user, 'my-flag');
    expect(result).toBeNull();
  });

  it('throws an Error on a non-2xx response', async () => {
    mockFetch({}, 500);
    const client = new ExperimentationClient(baseConfig);
    await expect(client.evaluateFeatureFlag(user, 'my-flag')).rejects.toThrow('API error: 500');
  });

  it('throws an Error on a 404 response', async () => {
    mockFetch({}, 404);
    const client = new ExperimentationClient(baseConfig);
    await expect(client.evaluateFeatureFlag(user, 'my-flag')).rejects.toThrow('API error: 404');
  });

  it('URL-encodes flag keys that contain special characters', async () => {
    const fetchMock = mockFetch(enabledFlag);
    const client = new ExperimentationClient(baseConfig);
    await client.evaluateFeatureFlag(user, 'my flag/key');
    expect(fetchMock.mock.calls[0][0]).toContain('my%20flag%2Fkey');
  });

  // ─── Cache behaviour ──────────────────────────────────────────────────────

  it('uses the cached result on the second call — fetch is only called once', async () => {
    const fetchMock = mockFetch(enabledFlag);
    const client = new ExperimentationClient(baseConfig);

    const first = await client.evaluateFeatureFlag(user, 'my-flag');
    const second = await client.evaluateFeatureFlag(user, 'my-flag');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(first).toBe(second);
  });

  it('caches null (disabled flag) as "off" sentinel and returns null on second call', async () => {
    const fetchMock = mockFetch(disabledFlag);
    const client = new ExperimentationClient(baseConfig);

    const first = await client.evaluateFeatureFlag(user, 'disabled-flag');
    const second = await client.evaluateFeatureFlag(user, 'disabled-flag');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(first).toBeNull();
    expect(second).toBeNull();
  });

  it('makes a fresh fetch after clearCache', async () => {
    const fetchMock = mockFetch(enabledFlag);
    const client = new ExperimentationClient(baseConfig);

    await client.evaluateFeatureFlag(user, 'my-flag');
    client.clearCache();
    await client.evaluateFeatureFlag(user, 'my-flag');

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('keeps separate cache entries per user', async () => {
    const fetchMock = mockFetch(enabledFlag);
    const client = new ExperimentationClient(baseConfig);

    await client.evaluateFeatureFlag({ userId: 'user-A' }, 'my-flag');
    await client.evaluateFeatureFlag({ userId: 'user-B' }, 'my-flag');

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

// ─── trackEvent ──────────────────────────────────────────────────────────────

describe('trackEvent', () => {
  it('sends a POST request to /api/v1/events', async () => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 200 });
    global.fetch = fetchMock;
    const client = new ExperimentationClient(baseConfig);

    await client.trackEvent('user-123', 'button_clicked');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('https://api.example.com/api/v1/events');
    expect(options.method).toBe('POST');
  });

  it('sends the correct JSON body', async () => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 200 });
    global.fetch = fetchMock;
    const client = new ExperimentationClient(baseConfig);

    await client.trackEvent('user-123', 'purchase', { amount: 99 });

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body).toEqual({
      user_id: 'user-123',
      event_name: 'purchase',
      properties: { amount: 99 },
    });
  });

  it('includes the X-API-Key header', async () => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 200 });
    global.fetch = fetchMock;
    const client = new ExperimentationClient(baseConfig);

    await client.trackEvent('user-123', 'click');

    const headers = fetchMock.mock.calls[0][1].headers;
    expect(headers['X-API-Key']).toBe('test-api-key');
  });

  it('does NOT throw on a network error (fire-and-forget)', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('Network failure'));
    const client = new ExperimentationClient(baseConfig);

    await expect(client.trackEvent('user-123', 'click')).resolves.toBeUndefined();
  });

  it('does NOT throw on a 500 server error', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 500 });
    const client = new ExperimentationClient(baseConfig);

    await expect(client.trackEvent('user-123', 'click')).resolves.toBeUndefined();
  });
});

// ─── clearCache ───────────────────────────────────────────────────────────────

describe('clearCache', () => {
  it('clears all cached entries so subsequent calls fetch fresh data', async () => {
    const fetchMock = mockFetch(enabledFlag);
    const client = new ExperimentationClient(baseConfig);

    await client.evaluateFeatureFlag(user, 'my-flag');
    await client.evaluateFeatureFlag({ userId: 'user-B' }, 'my-flag');
    client.clearCache();
    await client.evaluateFeatureFlag(user, 'my-flag');

    // Two calls before clear + one after = 3 total
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
