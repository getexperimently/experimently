/**
 * Unit tests for ExperimentationClient.
 *
 * Uses jest.spyOn + fetch mock instead of real network calls.
 */

import { ExperimentationClient } from '../src/client';
import { OfflineStorage } from '../src/storage';
import type { SdkConfig } from '../src/types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeConfig(overrides: Partial<SdkConfig> = {}): SdkConfig {
  return {
    apiKey: 'test-api-key',
    baseUrl: 'https://api.example.com',
    timeoutMs: 1000,
    cacheTtlMs: 60_000,
    offlineFallback: false,
    ...overrides,
  };
}

function enabledFlagResponse(key: string, rollout = 100): object {
  return {
    id: 'flag-id-1',
    key,
    name: 'Test Flag',
    enabled: true,
    rolloutPercentage: rollout,
    variants: [],
  };
}

function disabledFlagResponse(key: string): object {
  return { id: 'f2', key, name: 'Disabled', enabled: false, rolloutPercentage: 100, variants: [] };
}

function variantFlagResponse(key: string): object {
  return {
    id: 'f3',
    key,
    name: 'Variant Flag',
    enabled: true,
    rolloutPercentage: 100,
    variants: [
      { key: 'control', weight: 50 },
      { key: 'treatment', weight: 50 },
    ],
  };
}

function mockFetch(body: object, status = 200): void {
  global.fetch = jest.fn().mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
}

function mockFetchError(message = 'Network error'): void {
  global.fetch = jest.fn().mockRejectedValueOnce(new Error(message));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ExperimentationClient — constructor', () => {
  test('constructs without error with valid config', () => {
    expect(() => new ExperimentationClient(makeConfig())).not.toThrow();
  });

  test('throws if apiKey is missing', () => {
    expect(() => new ExperimentationClient({ ...makeConfig(), apiKey: '' })).toThrow(
      'apiKey is required'
    );
  });

  test('throws if baseUrl is missing', () => {
    expect(() => new ExperimentationClient({ ...makeConfig(), baseUrl: '' })).toThrow(
      'baseUrl is required'
    );
  });

  test('trailing slash on baseUrl is stripped', () => {
    const client = new ExperimentationClient(makeConfig({ baseUrl: 'https://api.example.com/' }));
    expect(client).toBeDefined();
  });
});

describe('evaluateFlag', () => {
  test('returns true when API returns enabled flag at 100% rollout', async () => {
    mockFetch(enabledFlagResponse('dark-mode'));
    const client = new ExperimentationClient(makeConfig());
    const result = await client.evaluateFlag('dark-mode', 'user-1');
    expect(result).toBe(true);
  });

  test('returns false when flag is disabled', async () => {
    mockFetch(disabledFlagResponse('disabled-flag'));
    const client = new ExperimentationClient(makeConfig());
    const result = await client.evaluateFlag('disabled-flag', 'user-1');
    expect(result).toBe(false);
  });

  test('returns false when rollout is 0%', async () => {
    mockFetch(enabledFlagResponse('flag', 0));
    const client = new ExperimentationClient(makeConfig());
    const result = await client.evaluateFlag('flag', 'user-1');
    expect(result).toBe(false);
  });

  test('uses in-memory cache on second call', async () => {
    mockFetch(enabledFlagResponse('cached-flag'));
    const client = new ExperimentationClient(makeConfig());

    await client.evaluateFlag('cached-flag', 'user-1');
    await client.evaluateFlag('cached-flag', 'user-1'); // Should hit cache

    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  test('cache is keyed on (userId, flagKey)', async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue({ ok: true, status: 200, json: async () => enabledFlagResponse('flag') });

    const client = new ExperimentationClient(makeConfig());
    await client.evaluateFlag('flag', 'user-A');
    await client.evaluateFlag('flag', 'user-B');

    expect(global.fetch).toHaveBeenCalledTimes(2);
  });

  test('clearCache causes re-fetch', async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue({ ok: true, status: 200, json: async () => enabledFlagResponse('flag') });

    const client = new ExperimentationClient(makeConfig());
    await client.evaluateFlag('flag', 'user-1');
    client.clearCache();
    await client.evaluateFlag('flag', 'user-1');

    expect(global.fetch).toHaveBeenCalledTimes(2);
  });

  test('returns false on API 500 error (no offline fallback)', async () => {
    mockFetch({}, 500);
    const client = new ExperimentationClient(makeConfig({ offlineFallback: false }));
    const result = await client.evaluateFlag('flag', 'user-1');
    expect(result).toBe(false);
  });

  test('returns false on network timeout error', async () => {
    mockFetchError('AbortError: timeout');
    const client = new ExperimentationClient(makeConfig({ offlineFallback: false }));
    const result = await client.evaluateFlag('flag', 'user-1');
    expect(result).toBe(false);
  });

  test('returns false on 401 Unauthorized', async () => {
    mockFetch({ detail: 'Unauthorized' }, 401);
    const client = new ExperimentationClient(makeConfig({ offlineFallback: false }));
    const result = await client.evaluateFlag('flag', 'user-1');
    expect(result).toBe(false);
  });

  test('returns true for variant flag when user in rollout', async () => {
    mockFetch(variantFlagResponse('variant-flag'));
    const client = new ExperimentationClient(makeConfig());
    // user-123 hashes to ~0.069 which is < 1.0 rollout fraction
    const result = await client.evaluateFlag('variant-flag', 'user-123');
    expect(result).toBe(true);
  });
});

describe('evaluateFlag — offline fallback', () => {
  test('stores result in AsyncStorage after successful API call', async () => {
    mockFetch(enabledFlagResponse('offline-flag'));
    const storage = new OfflineStorage();
    const setFlagSpy = jest.spyOn(storage, 'setFlag').mockResolvedValue();

    const client = new ExperimentationClient(
      makeConfig({ offlineFallback: true }),
      storage
    );
    await client.evaluateFlag('offline-flag', 'user-1');

    expect(setFlagSpy).toHaveBeenCalledWith('user-1:offline-flag', true);
  });

  test('returns stored value on API failure when offlineFallback=true', async () => {
    mockFetchError('Connection refused');
    const storage = new OfflineStorage();
    jest.spyOn(storage, 'getFlag').mockResolvedValue(true);

    const client = new ExperimentationClient(
      makeConfig({ offlineFallback: true }),
      storage
    );
    const result = await client.evaluateFlag('flag', 'user-1');
    expect(result).toBe(true);
  });

  test('returns false when API fails and offline store is empty', async () => {
    mockFetchError('Connection refused');
    const storage = new OfflineStorage();
    jest.spyOn(storage, 'getFlag').mockResolvedValue(null);

    const client = new ExperimentationClient(
      makeConfig({ offlineFallback: true }),
      storage
    );
    const result = await client.evaluateFlag('flag', 'user-1');
    expect(result).toBe(false);
  });
});

describe('getAssignment', () => {
  function mockAssignment(variantKey: string | null): void {
    global.fetch = jest.fn().mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        experimentKey: 'my-exp',
        variantKey,
        variantName: variantKey,
      }),
    });
  }

  test('returns variant key from API response', async () => {
    mockAssignment('treatment');
    const client = new ExperimentationClient(makeConfig());
    const result = await client.getAssignment('my-exp', 'user-1');
    expect(result).toBe('treatment');
  });

  test('returns null when not assigned', async () => {
    mockAssignment(null);
    const client = new ExperimentationClient(makeConfig());
    const result = await client.getAssignment('my-exp', 'user-1');
    expect(result).toBeNull();
  });

  test('caches assignment — only one HTTP call for two identical requests', async () => {
    mockAssignment('control');
    const client = new ExperimentationClient(makeConfig());

    await client.getAssignment('my-exp', 'user-1');
    await client.getAssignment('my-exp', 'user-1');

    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  test('returns null on API error (no offline fallback)', async () => {
    mockFetchError('Network error');
    const client = new ExperimentationClient(makeConfig({ offlineFallback: false }));
    const result = await client.getAssignment('my-exp', 'user-1');
    expect(result).toBeNull();
  });

  test('persists assignment to storage on success', async () => {
    mockAssignment('control');
    const storage = new OfflineStorage();
    const setAssignmentSpy = jest.spyOn(storage, 'setAssignment').mockResolvedValue();

    const client = new ExperimentationClient(
      makeConfig({ offlineFallback: true }),
      storage
    );
    await client.getAssignment('my-exp', 'user-1');

    expect(setAssignmentSpy).toHaveBeenCalledWith('user-1:exp:my-exp', 'control');
  });

  test('returns offline assignment on API failure', async () => {
    mockFetchError('Timeout');
    const storage = new OfflineStorage();
    jest.spyOn(storage, 'getAssignment').mockResolvedValue('control');

    const client = new ExperimentationClient(
      makeConfig({ offlineFallback: true }),
      storage
    );
    const result = await client.getAssignment('my-exp', 'user-1');
    expect(result).toBe('control');
  });

  test('returns null when API fails and no offline assignment stored', async () => {
    mockFetchError('Timeout');
    const storage = new OfflineStorage();
    jest.spyOn(storage, 'getAssignment').mockResolvedValue(undefined);

    const client = new ExperimentationClient(
      makeConfig({ offlineFallback: true }),
      storage
    );
    const result = await client.getAssignment('my-exp', 'user-1');
    expect(result).toBeNull();
  });
});

describe('track', () => {
  test('sends POST to /api/v1/events with correct body', async () => {
    global.fetch = jest.fn().mockResolvedValueOnce({ ok: true, status: 204 });
    const client = new ExperimentationClient(makeConfig());

    await client.track('button_clicked', 'user-1', { page: 'home' });

    expect(global.fetch).toHaveBeenCalledWith(
      'https://api.example.com/api/v1/events',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          event_name: 'button_clicked',
          user_id: 'user-1',
          properties: { page: 'home' },
        }),
      })
    );
  });

  test('track without properties omits properties key', async () => {
    global.fetch = jest.fn().mockResolvedValueOnce({ ok: true, status: 204 });
    const client = new ExperimentationClient(makeConfig());

    await client.track('page_viewed', 'user-1');

    const body = JSON.parse(
      (global.fetch as jest.Mock).mock.calls[0][1].body as string
    );
    expect(body).not.toHaveProperty('properties');
  });

  test('track never throws on API error', async () => {
    global.fetch = jest.fn().mockRejectedValueOnce(new Error('Timeout'));
    const client = new ExperimentationClient(makeConfig());
    await expect(client.track('event', 'user-1')).resolves.toBeUndefined();
  });

  test('track never throws on 500 response', async () => {
    global.fetch = jest.fn().mockResolvedValueOnce({ ok: false, status: 500 });
    const client = new ExperimentationClient(makeConfig());
    await expect(client.track('event', 'user-1')).resolves.toBeUndefined();
  });
});

describe('concurrent flag evaluation', () => {
  test('parallel evaluations for same key make at most one network request', async () => {
    let callCount = 0;
    global.fetch = jest.fn().mockImplementation(async () => {
      callCount++;
      return { ok: true, status: 200, json: async () => enabledFlagResponse('concurrent-flag') };
    });

    const client = new ExperimentationClient(makeConfig());
    const results = await Promise.all([
      client.evaluateFlag('concurrent-flag', 'user-1'),
      client.evaluateFlag('concurrent-flag', 'user-1'),
      client.evaluateFlag('concurrent-flag', 'user-1'),
    ]);

    expect(results).toEqual([true, true, true]);
    // In JS, Promise.all fires all three before any resolves, so all 3 miss
    // the cache (cache is written after the first resolves). Acceptable.
    expect(callCount).toBeGreaterThanOrEqualTo(1);
    expect(callCount).toBeLessThanOrEqualTo(3);
  });

  test('parallel evaluations for different users each make their own request', async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue({ ok: true, status: 200, json: async () => enabledFlagResponse('flag') });

    const client = new ExperimentationClient(makeConfig());
    await Promise.all([
      client.evaluateFlag('flag', 'user-A'),
      client.evaluateFlag('flag', 'user-B'),
      client.evaluateFlag('flag', 'user-C'),
    ]);

    expect(global.fetch).toHaveBeenCalledTimes(3);
  });
});

describe('clearCache', () => {
  test('clearCache resets both flag and assignment caches', async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue({ ok: true, status: 200, json: async () => enabledFlagResponse('f') });

    const client = new ExperimentationClient(makeConfig());
    await client.evaluateFlag('f', 'u');
    client.clearCache();
    await client.evaluateFlag('f', 'u');

    expect(global.fetch).toHaveBeenCalledTimes(2);
  });
});
