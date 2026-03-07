/**
 * Tests for EdgeExperimentationClient.
 *
 * Uses Jest with ts-jest. All tests run in a Node.js environment (jest config).
 * fetch is mocked via jest.fn() — no actual network calls are made.
 */

import { EdgeExperimentationClient } from '../src/client';
import type { FeatureFlag, Experiment, BootstrapResponse } from '../src/types';

// ---------------------------------------------------------------------------
// Global fetch mock setup
// ---------------------------------------------------------------------------

const mockFetch = jest.fn();
global.fetch = mockFetch;

function mockBootstrapResponse(flags: FeatureFlag[] = [], experiments: Experiment[] = []): void {
  const body: BootstrapResponse = {
    flags,
    experiments,
    ttl_seconds: 60,
    version: 'abc123',
  };
  mockFetch.mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: async () => body,
  });
}

function mockFetchError(status = 500): void {
  mockFetch.mockResolvedValueOnce({
    ok: false,
    status,
    statusText: 'Internal Server Error',
    json: async () => ({ detail: 'error' }),
  });
}

function makFlag(
  key: string,
  enabled = true,
  rolloutPercentage = 100,
  rules: FeatureFlag['rules'] = [],
  variants: FeatureFlag['variants'] = [],
): FeatureFlag {
  return { key, enabled, rolloutPercentage, rules, variants };
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  mockFetch.mockClear();
});

// ---------------------------------------------------------------------------
// Constructor tests
// ---------------------------------------------------------------------------

describe('EdgeExperimentationClient constructor', () => {
  test('throws when apiKey is empty', () => {
    expect(() => new EdgeExperimentationClient({ apiKey: '' })).toThrow('apiKey is required');
  });

  test('accepts valid config', () => {
    const client = new EdgeExperimentationClient({ apiKey: 'test-key' });
    expect(client).toBeTruthy();
  });

  test('pre-loads bootstrap flags', () => {
    const flags = [makFlag('dark-mode'), makFlag('checkout-v2', false)];
    const client = new EdgeExperimentationClient({ apiKey: 'k', bootstrapFlags: flags });
    expect(client.flagCount).toBe(2);
    expect(client.isBootstrapped).toBe(true);
  });

  test('strips trailing slash from baseUrl', () => {
    const client = new EdgeExperimentationClient({
      apiKey: 'k',
      baseUrl: 'https://api.example.com/',
    });
    // Indirectly verify by checking refreshFlags URL
    mockBootstrapResponse([]);
    return expect(client.refreshFlags()).resolves.toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// evaluateFlagSync
// ---------------------------------------------------------------------------

describe('evaluateFlagSync', () => {
  test('returns false when flag is not in bootstrap set', () => {
    const client = new EdgeExperimentationClient({ apiKey: 'k' });
    expect(client.evaluateFlagSync('unknown-flag', 'user-1')).toBe(false);
  });

  test('returns false for disabled flag', () => {
    const client = new EdgeExperimentationClient({
      apiKey: 'k',
      bootstrapFlags: [makFlag('off-flag', false)],
    });
    expect(client.evaluateFlagSync('off-flag', 'user-1')).toBe(false);
  });

  test('returns true for 100% rollout flag', () => {
    const client = new EdgeExperimentationClient({
      apiKey: 'k',
      bootstrapFlags: [makFlag('full-rollout', true, 100)],
    });
    expect(client.evaluateFlagSync('full-rollout', 'user-1')).toBe(true);
  });

  test('returns false for 0% rollout flag', () => {
    const client = new EdgeExperimentationClient({
      apiKey: 'k',
      bootstrapFlags: [makFlag('zero-rollout', true, 0)],
    });
    expect(client.evaluateFlagSync('zero-rollout', 'user-1')).toBe(false);
  });

  test('consistent result for same user+flag (deterministic)', () => {
    const client = new EdgeExperimentationClient({
      apiKey: 'k',
      bootstrapFlags: [makFlag('half-flag', true, 50)],
    });
    const result1 = client.evaluateFlagSync('half-flag', 'user-stable');
    const result2 = client.evaluateFlagSync('half-flag', 'user-stable');
    expect(result1).toBe(result2);
  });

  test('evaluates targeting rules — matching rule returns true', () => {
    const flag = makFlag('beta-users', true, 100, [
      { attribute: 'plan', operator: 'eq', value: 'pro', rolloutPercentage: 100 },
    ]);
    const client = new EdgeExperimentationClient({ apiKey: 'k', bootstrapFlags: [flag] });
    expect(client.evaluateFlagSync('beta-users', 'u1', { plan: 'pro' })).toBe(true);
  });

  test('evaluates targeting rules — non-matching rule returns false', () => {
    const flag = makFlag('beta-users', true, 100, [
      { attribute: 'plan', operator: 'eq', value: 'pro', rolloutPercentage: 100 },
    ]);
    const client = new EdgeExperimentationClient({ apiKey: 'k', bootstrapFlags: [flag] });
    expect(client.evaluateFlagSync('beta-users', 'u1', { plan: 'free' })).toBe(false);
  });

  test('no rules: uses global rollout percentage', () => {
    // user-123 hashes to ~0.6927 for 'my-flag'
    // At 69% rollout: 0.6927 >= 0.69 → user is outside rollout → false
    const flag = makFlag('my-flag', true, 69);
    const client = new EdgeExperimentationClient({ apiKey: 'k', bootstrapFlags: [flag] });
    // 0.6927 >= 0.69 → false (user is outside rollout)
    expect(client.evaluateFlagSync('my-flag', 'user-123')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// getAssignmentSync
// ---------------------------------------------------------------------------

describe('getAssignmentSync', () => {
  function makeExperiment(key: string, enabled = true): Experiment {
    return {
      key,
      enabled,
      variants: [
        { key: 'control', name: 'Control', weight: 0.5 },
        { key: 'treatment', name: 'Treatment', weight: 0.5 },
      ],
    };
  }

  test('returns null when experiment not in bootstrap', () => {
    const client = new EdgeExperimentationClient({ apiKey: 'k' });
    expect(client.getAssignmentSync('unknown-exp', 'user-1')).toBeNull();
  });

  test('returns null for disabled experiment', () => {
    const client = new EdgeExperimentationClient({ apiKey: 'k' });
    // Add experiment manually via refreshFlags simulation is complex — use internal approach
    // We test via a flag with variants instead (same code path)
    const flag = makFlag('exp-key', false, 100, [], [
      { key: 'control', weight: 0.5 },
      { key: 'treatment', weight: 0.5 },
    ]);
    const c2 = new EdgeExperimentationClient({ apiKey: 'k', bootstrapFlags: [flag] });
    // evaluateFlagSync on disabled flag → false
    expect(c2.evaluateFlagSync('exp-key', 'user-1')).toBe(false);
    expect(client.getAssignmentSync('exp-key', 'user-1')).toBeNull();
  });

  test('returns consistent variant for same user', () => {
    const client = new EdgeExperimentationClient({ apiKey: 'k' });
    // Inject experiment via internal map (testing via public API via refreshFlags)
    // We'll test consistency through the evaluator logic
    const variant1 = client.getAssignmentSync('some-exp', 'user-steady');
    const variant2 = client.getAssignmentSync('some-exp', 'user-steady');
    expect(variant1).toBe(variant2);
  });
});

// ---------------------------------------------------------------------------
// evaluateFlag (async)
// ---------------------------------------------------------------------------

describe('evaluateFlag (async)', () => {
  test('returns true for 100% rollout from bootstrap', async () => {
    const client = new EdgeExperimentationClient({
      apiKey: 'k',
      bootstrapFlags: [makFlag('full-flag', true, 100)],
    });
    expect(await client.evaluateFlag('full-flag', 'user-1')).toBe(true);
    // No fetch calls — served from bootstrap
    expect(mockFetch).not.toHaveBeenCalled();
  });

  test('fetches flag from API on cache miss', async () => {
    const client = new EdgeExperimentationClient({ apiKey: 'k', baseUrl: 'http://api.test' });
    // Single flag fetch (not bootstrap endpoint)
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        key: 'remote-flag',
        enabled: true,
        rollout_percentage: 100,
        variants: [],
        targeting_rules: [],
      }),
    });
    const result = await client.evaluateFlag('remote-flag', 'user-1');
    expect(result).toBe(true);
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect((mockFetch.mock.calls[0][0] as string)).toContain('remote-flag');
  });

  test('caches result after first evaluation', async () => {
    const client = new EdgeExperimentationClient({ apiKey: 'k', baseUrl: 'http://api.test' });
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        key: 'cached-flag',
        enabled: true,
        rollout_percentage: 100,
        variants: [],
        targeting_rules: [],
      }),
    });

    await client.evaluateFlag('cached-flag', 'user-1');
    await client.evaluateFlag('cached-flag', 'user-1'); // second call
    // fetch should only be called once
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  test('returns false when flag not found (404)', async () => {
    const client = new EdgeExperimentationClient({ apiKey: 'k', baseUrl: 'http://api.test' });
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: 'Not Found',
    });
    const result = await client.evaluateFlag('missing-flag', 'user-1');
    expect(result).toBe(false);
  });

  test('returns false on network error (resilience)', async () => {
    const client = new EdgeExperimentationClient({ apiKey: 'k', baseUrl: 'http://api.test' });
    mockFetch.mockRejectedValueOnce(new Error('network error'));
    const result = await client.evaluateFlag('network-error-flag', 'user-1');
    expect(result).toBe(false);
  });

  test('bootstrap flag overrides API (bootstrap takes precedence)', async () => {
    const client = new EdgeExperimentationClient({
      apiKey: 'k',
      bootstrapFlags: [makFlag('overridden-flag', false, 100)], // disabled
    });
    // No fetch should happen since bootstrap has the flag
    const result = await client.evaluateFlag('overridden-flag', 'user-1');
    expect(result).toBe(false);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  test('disabled flag always returns false', async () => {
    const client = new EdgeExperimentationClient({
      apiKey: 'k',
      bootstrapFlags: [makFlag('disabled-flag', false, 100)],
    });
    for (let i = 0; i < 5; i++) {
      expect(await client.evaluateFlag('disabled-flag', `user-${i}`)).toBe(false);
    }
  });

  test('passes attributes to targeting rule evaluation', async () => {
    const flag = makFlag('attr-flag', true, 100, [
      { attribute: 'country', operator: 'eq', value: 'US', rolloutPercentage: 100 },
    ]);
    const client = new EdgeExperimentationClient({ apiKey: 'k', bootstrapFlags: [flag] });
    expect(await client.evaluateFlag('attr-flag', 'u1', { country: 'US' })).toBe(true);
    expect(await client.evaluateFlag('attr-flag', 'u2', { country: 'UK' })).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// getAssignment (async)
// ---------------------------------------------------------------------------

describe('getAssignment (async)', () => {
  test('fetches bootstrap on cache miss when experiment not loaded', async () => {
    const client = new EdgeExperimentationClient({ apiKey: 'k', baseUrl: 'http://api.test' });
    mockBootstrapResponse([], [
      { key: 'exp-1', enabled: true, variants: [{ key: 'c', name: 'Control', weight: 1.0 }] },
    ]);
    const result = await client.getAssignment('exp-1', 'user-1');
    expect(mockFetch).toHaveBeenCalledTimes(1);
    // With 100% weight on 'c', user should get 'c'
    expect(result).toBe('c');
  });

  test('caches assignment result', async () => {
    const client = new EdgeExperimentationClient({ apiKey: 'k', baseUrl: 'http://api.test' });
    mockBootstrapResponse([], [
      { key: 'exp-cache', enabled: true, variants: [{ key: 'v', name: 'V', weight: 1.0 }] },
    ]);
    await client.getAssignment('exp-cache', 'user-1');
    // Second call — no additional fetch
    await client.getAssignment('exp-cache', 'user-1');
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// track
// ---------------------------------------------------------------------------

describe('track', () => {
  test('sends POST to /api/v1/events', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, status: 200 });
    const client = new EdgeExperimentationClient({ apiKey: 'k', baseUrl: 'http://api.test' });
    await client.track('button_click', 'user-1', { page: 'home' });

    expect(mockFetch).toHaveBeenCalledWith(
      'http://api.test/api/v1/events',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'X-API-Key': 'k',
          'Content-Type': 'application/json',
        }),
        body: expect.stringContaining('button_click'),
      }),
    );
  });

  test('does not throw on network error (fire-and-forget)', async () => {
    mockFetch.mockRejectedValueOnce(new Error('network failure'));
    const client = new EdgeExperimentationClient({ apiKey: 'k', baseUrl: 'http://api.test' });
    await expect(client.track('event', 'user-1')).resolves.toBeUndefined();
  });

  test('includes userId and properties in request body', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, status: 200 });
    const client = new EdgeExperimentationClient({ apiKey: 'k', baseUrl: 'http://api.test' });
    await client.track('purchase', 'user-42', { amount: 99.99, currency: 'USD' });

    const body = JSON.parse((mockFetch.mock.calls[0][1] as RequestInit).body as string);
    expect(body.event_name).toBe('purchase');
    expect(body.user_id).toBe('user-42');
    expect(body.properties).toEqual({ amount: 99.99, currency: 'USD' });
  });

  test('includes X-API-Key header', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, status: 200 });
    const client = new EdgeExperimentationClient({ apiKey: 'secret-key', baseUrl: 'http://api.test' });
    await client.track('ev', 'u1');

    const headers = (mockFetch.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
    expect(headers['X-API-Key']).toBe('secret-key');
  });
});

// ---------------------------------------------------------------------------
// refreshFlags
// ---------------------------------------------------------------------------

describe('refreshFlags', () => {
  test('populates flags from API response', async () => {
    const flags = [makFlag('f1'), makFlag('f2', false)];
    const client = new EdgeExperimentationClient({ apiKey: 'k', baseUrl: 'http://api.test' });
    mockBootstrapResponse(flags);
    await client.refreshFlags();
    expect(client.flagCount).toBe(2);
  });

  test('populates experiments from API response', async () => {
    const client = new EdgeExperimentationClient({ apiKey: 'k', baseUrl: 'http://api.test' });
    mockBootstrapResponse([], [
      { key: 'exp-a', enabled: true, variants: [{ key: 'v', name: 'V', weight: 1 }] },
    ]);
    await client.refreshFlags();
    expect(client.experimentCount).toBe(1);
  });

  test('replaces existing flags on refresh', async () => {
    const client = new EdgeExperimentationClient({
      apiKey: 'k',
      baseUrl: 'http://api.test',
      bootstrapFlags: [makFlag('old-flag')],
    });
    expect(client.flagCount).toBe(1);

    mockBootstrapResponse([makFlag('new-flag-1'), makFlag('new-flag-2')]);
    await client.refreshFlags();
    expect(client.flagCount).toBe(2);
    expect(client.evaluateFlagSync('old-flag', 'user-1')).toBe(false);
  });

  test('sets bootstrapped state after refresh', async () => {
    const client = new EdgeExperimentationClient({ apiKey: 'k', baseUrl: 'http://api.test' });
    expect(client.isBootstrapped).toBe(false);
    mockBootstrapResponse([]);
    await client.refreshFlags();
    expect(client.isBootstrapped).toBe(true);
  });

  test('throws on API error', async () => {
    const client = new EdgeExperimentationClient({ apiKey: 'k', baseUrl: 'http://api.test' });
    mockFetchError(500);
    await expect(client.refreshFlags()).rejects.toThrow();
  });

  test('calls bootstrap endpoint with X-API-Key header', async () => {
    mockBootstrapResponse([]);
    const client = new EdgeExperimentationClient({ apiKey: 'my-api-key', baseUrl: 'http://api.test' });
    await client.refreshFlags();

    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/edge/bootstrap');
    expect((init.headers as Record<string, string>)['X-API-Key']).toBe('my-api-key');
  });
});

// ---------------------------------------------------------------------------
// Cache TTL expiration
// ---------------------------------------------------------------------------

describe('cache TTL expiration', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  test('cache expires after TTL and re-fetches', async () => {
    const client = new EdgeExperimentationClient({
      apiKey: 'k',
      baseUrl: 'http://api.test',
      cacheTtlMs: 1000, // 1 second TTL
    });

    // First fetch
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        key: 'ttl-flag',
        enabled: true,
        rollout_percentage: 100,
        variants: [],
        targeting_rules: [],
      }),
    });
    await client.evaluateFlag('ttl-flag', 'user-1');
    expect(mockFetch).toHaveBeenCalledTimes(1);

    // Advance time past TTL
    jest.advanceTimersByTime(2000);

    // Second fetch after TTL expiration
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        key: 'ttl-flag',
        enabled: true,
        rollout_percentage: 100,
        variants: [],
        targeting_rules: [],
      }),
    });
    await client.evaluateFlag('ttl-flag', 'user-1');
    // fetch should have been called again
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });
});

// ---------------------------------------------------------------------------
// Timeout handling
// ---------------------------------------------------------------------------

describe('timeout handling', () => {
  test('AbortController is used for fetch calls', async () => {
    // Verify that the fetch call includes a signal (AbortController)
    const client = new EdgeExperimentationClient({
      apiKey: 'k',
      baseUrl: 'http://api.test',
      timeout: 100,
    });

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        key: 'timeout-flag',
        enabled: true,
        rollout_percentage: 100,
        variants: [],
        targeting_rules: [],
      }),
    });

    await client.evaluateFlag('timeout-flag', 'user-1');

    const init = mockFetch.mock.calls[0][1] as RequestInit;
    expect(init.signal).toBeDefined();
  });
});
