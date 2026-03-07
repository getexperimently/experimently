/**
 * Adapter-specific tests for Cloudflare Workers, Vercel Edge, and Deno Deploy.
 *
 * Tests are structured to run in Node.js (Jest) by mocking the platform-specific
 * APIs (KVNamespace, ExecutionContext, Deno.openKv, etc.).
 */

import { CloudflareExperimentationClient, withExperimentation } from '../src/adapters/cloudflare';
import type { KVNamespace, ExecutionContext } from '../src/adapters/cloudflare';
import { createEdgeMiddleware } from '../src/adapters/vercel';
import { DenoExperimentationClient, createDenoHandler } from '../src/adapters/deno';
import type { FeatureFlag, BootstrapResponse } from '../src/types';

// ---------------------------------------------------------------------------
// Global fetch mock
// ---------------------------------------------------------------------------

const mockFetch = jest.fn();
global.fetch = mockFetch;

function makeFlag(key: string, enabled = true, rollout = 100): FeatureFlag {
  return { key, enabled, rolloutPercentage: rollout };
}

function mockBootstrap(flags: FeatureFlag[] = []): void {
  const body: BootstrapResponse = {
    flags,
    experiments: [],
    ttl_seconds: 60,
    version: 'v1',
  };
  mockFetch.mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: async () => body,
  });
}

beforeEach(() => {
  mockFetch.mockClear();
});

// ---------------------------------------------------------------------------
// Cloudflare adapter tests
// ---------------------------------------------------------------------------

describe('CloudflareExperimentationClient', () => {
  function makeKv(stored: Record<string, string> = {}): KVNamespace {
    const store = { ...stored };
    return {
      async get(key: string) {
        return store[key] ?? null;
      },
      async put(key: string, value: string) {
        store[key] = value;
      },
    };
  }

  test('loads flags from KV when available', async () => {
    const flags = [makeFlag('kv-flag')];
    const bootstrapData: BootstrapResponse = {
      flags,
      experiments: [],
      ttl_seconds: 300,
      version: 'v1',
    };
    const kv = makeKv({ 'ep:bootstrap': JSON.stringify(bootstrapData) });

    const client = new CloudflareExperimentationClient({
      apiKey: 'k',
      kvNamespace: kv,
    });

    await client.loadFromKvOrApi();

    // Should not have called fetch (KV hit)
    expect(mockFetch).not.toHaveBeenCalled();
    expect(client.flagCount).toBe(1);
    expect(client.evaluateFlagSync('kv-flag', 'user-1')).toBe(true);
  });

  test('falls back to API when KV is empty', async () => {
    const kv = makeKv({}); // empty KV
    mockBootstrap([makeFlag('api-flag')]);

    const client = new CloudflareExperimentationClient({
      apiKey: 'k',
      baseUrl: 'http://api.test',
      kvNamespace: kv,
    });

    await client.loadFromKvOrApi();

    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(client.flagCount).toBe(1);
  });

  test('falls back to API when KV has corrupt data', async () => {
    const kv = makeKv({ 'ep:bootstrap': 'not-valid-json' });
    mockBootstrap([makeFlag('fallback-flag')]);

    const client = new CloudflareExperimentationClient({
      apiKey: 'k',
      baseUrl: 'http://api.test',
      kvNamespace: kv,
    });

    await client.loadFromKvOrApi();

    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(client.flagCount).toBe(1);
  });

  test('works without KV namespace (API only)', async () => {
    mockBootstrap([makeFlag('no-kv-flag')]);

    const client = new CloudflareExperimentationClient({
      apiKey: 'k',
      baseUrl: 'http://api.test',
    });

    await client.loadFromKvOrApi();
    expect(client.flagCount).toBe(1);
  });

  test('refreshAndStore fetches from API and writes to KV', async () => {
    const stored: Record<string, string> = {};
    const kv: KVNamespace = {
      async get(key: string) { return stored[key] ?? null; },
      async put(key: string, value: string) { stored[key] = value; },
    };

    mockBootstrap([makeFlag('refresh-flag')]);

    const client = new CloudflareExperimentationClient({
      apiKey: 'k',
      baseUrl: 'http://api.test',
      kvNamespace: kv,
    });

    await client.refreshAndStore();

    // KV should now have the bootstrap data
    expect(stored['ep:bootstrap']).toBeDefined();
    const parsed = JSON.parse(stored['ep:bootstrap']) as BootstrapResponse;
    expect(parsed.flags).toHaveLength(1);
    expect(parsed.flags[0].key).toBe('refresh-flag');
  });

  test('evaluateFlagSync works after KV load', async () => {
    const flags = [makeFlag('kv-sync-flag', true, 100)];
    const kv = makeKv({
      'ep:bootstrap': JSON.stringify({ flags, experiments: [], ttl_seconds: 60, version: 'v' }),
    });

    const client = new CloudflareExperimentationClient({
      apiKey: 'k',
      kvNamespace: kv,
    });
    await client.loadFromKvOrApi();

    expect(client.evaluateFlagSync('kv-sync-flag', 'user-123')).toBe(true);
  });

  test('refreshAndStore does not write to KV when no namespace configured', async () => {
    mockBootstrap([]);
    const client = new CloudflareExperimentationClient({
      apiKey: 'k',
      baseUrl: 'http://api.test',
    });
    // Should not throw
    await expect(client.refreshAndStore()).resolves.toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// withExperimentation HOF
// ---------------------------------------------------------------------------

describe('withExperimentation', () => {
  function makeCtx(): ExecutionContext {
    return {
      waitUntil: jest.fn(),
      passThroughOnException: jest.fn(),
    };
  }

  test('injects EP_CLIENT into env', async () => {
    mockBootstrap([makeFlag('injected-flag')]);
    // Second call for background refresh
    mockBootstrap([makeFlag('injected-flag')]);

    let capturedClient: unknown;
    const handler = jest.fn(async (_req: Request, env: Record<string, unknown>) => {
      capturedClient = env['EP_CLIENT'];
      return new Response('ok');
    });

    const wrapped = withExperimentation(handler, {
      apiKey: 'k',
      baseUrl: 'http://api.test',
    });

    const request = new Request('http://localhost/');
    const env: Record<string, unknown> = {};
    const ctx = makeCtx();

    await wrapped(request, env, ctx);

    expect(capturedClient).toBeInstanceOf(CloudflareExperimentationClient);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  test('calls ctx.waitUntil for background refresh', async () => {
    mockBootstrap([]);
    mockBootstrap([]); // background refresh

    const handler = jest.fn(async () => new Response('ok'));
    const wrapped = withExperimentation(handler, {
      apiKey: 'k',
      baseUrl: 'http://api.test',
    });

    const ctx = makeCtx();
    await wrapped(new Request('http://localhost/'), {}, ctx);

    expect((ctx.waitUntil as jest.Mock)).toHaveBeenCalledTimes(1);
  });

  test('custom clientEnvKey is used', async () => {
    mockBootstrap([]);
    mockBootstrap([]);

    let capturedEnv: Record<string, unknown> = {};
    const handler = jest.fn(async (_req: Request, env: Record<string, unknown>) => {
      capturedEnv = env;
      return new Response('ok');
    });

    const wrapped = withExperimentation(handler, {
      apiKey: 'k',
      baseUrl: 'http://api.test',
    }, 'MY_CLIENT');

    await wrapped(new Request('http://localhost/'), {}, makeCtx());

    expect(capturedEnv['MY_CLIENT']).toBeDefined();
  });

  test('passes original env properties through', async () => {
    mockBootstrap([]);
    mockBootstrap([]);

    let capturedEnv: Record<string, unknown> = {};
    const handler = jest.fn(async (_req: Request, env: Record<string, unknown>) => {
      capturedEnv = env;
      return new Response('ok');
    });

    const wrapped = withExperimentation(handler, { apiKey: 'k', baseUrl: 'http://api.test' });
    const env = { DB: 'my-db-binding', SECRET: 'shhh' };

    await wrapped(new Request('http://localhost/'), env, makeCtx());

    expect(capturedEnv['DB']).toBe('my-db-binding');
    expect(capturedEnv['SECRET']).toBe('shhh');
  });
});

// ---------------------------------------------------------------------------
// Vercel Edge adapter tests
// ---------------------------------------------------------------------------

describe('createEdgeMiddleware', () => {
  test('adds flag headers for flagKeys list', async () => {
    mockBootstrap([makeFlag('dark-mode', true, 100), makeFlag('checkout-v2', false, 100)]);
    // The middleware then calls fetch to pass through
    mockFetch.mockResolvedValueOnce(new Response('upstream ok'));

    const middleware = createEdgeMiddleware({
      apiKey: 'k',
      baseUrl: 'http://api.test',
      flagKeys: ['dark-mode', 'checkout-v2'],
    });

    const request = new Request('http://localhost/page');
    const response = await middleware(request);

    expect(response).toBeDefined();
    // Verify fetch was called with modified headers
    // The second fetch call is the pass-through with injected headers
    const passThrough = mockFetch.mock.calls[1];
    const passedReq = passThrough[0] as Request;
    expect(passedReq.headers.get('X-EP-Flag-dark-mode')).toBe('true');
    expect(passedReq.headers.get('X-EP-Flag-checkout-v2')).toBe('false');
  });

  test('extracts userId from X-User-Id header', async () => {
    mockBootstrap([makeFlag('user-flag', true, 100)]);
    mockFetch.mockResolvedValueOnce(new Response('ok'));

    const middleware = createEdgeMiddleware({
      apiKey: 'k',
      baseUrl: 'http://api.test',
      flagKeys: ['user-flag'],
    });

    const request = new Request('http://localhost/', {
      headers: { 'X-User-Id': 'user-from-header' },
    });
    await middleware(request);

    const passedReq = mockFetch.mock.calls[1][0] as Request;
    expect(passedReq.headers.get('X-EP-User-Id')).toBe('user-from-header');
  });

  test('extracts userId from cookie when header absent', async () => {
    mockBootstrap([makeFlag('cookie-flag', true, 100)]);
    mockFetch.mockResolvedValueOnce(new Response('ok'));

    const middleware = createEdgeMiddleware({
      apiKey: 'k',
      baseUrl: 'http://api.test',
      flagKeys: ['cookie-flag'],
    });

    const request = new Request('http://localhost/', {
      headers: { Cookie: 'ep_user_id=user-from-cookie; other=val' },
    });
    await middleware(request);

    const passedReq = mockFetch.mock.calls[1][0] as Request;
    expect(passedReq.headers.get('X-EP-User-Id')).toBe('user-from-cookie');
  });

  test('continues without throwing when bootstrap fails', async () => {
    mockFetch.mockRejectedValueOnce(new Error('bootstrap failed'));
    mockFetch.mockResolvedValueOnce(new Response('ok'));

    const middleware = createEdgeMiddleware({
      apiKey: 'k',
      baseUrl: 'http://api.test',
      flagKeys: ['some-flag'],
    });

    const request = new Request('http://localhost/');
    await expect(middleware(request)).resolves.toBeDefined();
  });

  test('uses custom userIdHeaderName', async () => {
    mockBootstrap([]);
    mockFetch.mockResolvedValueOnce(new Response('ok'));

    const middleware = createEdgeMiddleware({
      apiKey: 'k',
      baseUrl: 'http://api.test',
      userIdHeaderName: 'X-Custom-User',
      flagKeys: [],
    });

    const request = new Request('http://localhost/', {
      headers: { 'X-Custom-User': 'custom-user-id' },
    });
    await middleware(request);

    const passedReq = mockFetch.mock.calls[1][0] as Request;
    expect(passedReq.headers.get('X-EP-User-Id')).toBe('custom-user-id');
  });
});

// ---------------------------------------------------------------------------
// Deno Deploy adapter tests
// ---------------------------------------------------------------------------

describe('DenoExperimentationClient', () => {
  function makeDenoKv(stored: Record<string, unknown> = {}): import('../src/adapters/deno').DenoKv {
    const store = { ...stored };
    return {
      async get<T>(key: string[]) {
        const k = JSON.stringify(key);
        return { value: (store[k] ?? null) as T | null };
      },
      async set(key: string[], value: unknown) {
        store[JSON.stringify(key)] = value;
      },
    };
  }

  test('loads from Deno KV when available', async () => {
    const flags = [makeFlag('deno-kv-flag')];
    const stored = {
      '["ep","bootstrap"]': { flags, experiments: [], ttl_seconds: 300, version: 'v' },
    };
    const kv = makeDenoKv(stored);

    const client = new DenoExperimentationClient({ apiKey: 'k', kv });
    await client.loadFromKvOrApi();

    expect(mockFetch).not.toHaveBeenCalled();
    expect(client.flagCount).toBe(1);
  });

  test('falls back to API when Deno KV is empty', async () => {
    mockBootstrap([makeFlag('deno-api-flag')]);
    const kv = makeDenoKv({});

    const client = new DenoExperimentationClient({
      apiKey: 'k',
      baseUrl: 'http://api.test',
      kv,
    });
    await client.loadFromKvOrApi();

    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(client.flagCount).toBe(1);
  });

  test('refreshAndStore writes to Deno KV', async () => {
    mockBootstrap([makeFlag('deno-refresh-flag')]);
    // Use a shared store object so that writes from the KV mock are visible here
    const sharedStore: Record<string, unknown> = {};
    const kv: import('../src/adapters/deno').DenoKv = {
      async get<T>(key: string[]) {
        const k = JSON.stringify(key);
        return { value: (sharedStore[k] ?? null) as T | null };
      },
      async set(key: string[], value: unknown) {
        sharedStore[JSON.stringify(key)] = value;
      },
    };

    const client = new DenoExperimentationClient({
      apiKey: 'k',
      baseUrl: 'http://api.test',
      kv,
    });
    await client.refreshAndStore();

    const key = JSON.stringify(['ep', 'bootstrap']);
    expect(sharedStore[key]).toBeDefined();
    const data = sharedStore[key] as BootstrapResponse;
    expect(data.flags[0].key).toBe('deno-refresh-flag');
  });

  test('works without KV (API only)', async () => {
    mockBootstrap([makeFlag('deno-no-kv')]);
    const client = new DenoExperimentationClient({
      apiKey: 'k',
      baseUrl: 'http://api.test',
    });
    await client.loadFromKvOrApi();
    expect(client.flagCount).toBe(1);
  });
});

describe('createDenoHandler', () => {
  test('creates a handler that passes client to inner function', async () => {
    mockBootstrap([makeFlag('deno-handler-flag', true, 100)]);

    let receivedClient: unknown;
    const handler = createDenoHandler(
      async (_req, client) => {
        receivedClient = client;
        return new Response('handled');
      },
      { apiKey: 'k', baseUrl: 'http://api.test' },
    );

    const response = await handler(new Request('http://localhost/'));
    expect(response.status).toBe(200);
    expect(receivedClient).toBeInstanceOf(DenoExperimentationClient);
  });

  test('initialises client only once across calls (isolate singleton)', async () => {
    mockBootstrap([makeFlag('singleton-flag')]);

    const handler = createDenoHandler(
      async () => new Response('ok'),
      { apiKey: 'k', baseUrl: 'http://api.test' },
    );

    // Call handler twice
    await handler(new Request('http://localhost/'));
    await handler(new Request('http://localhost/'));

    // Bootstrap should only have been called once
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });
});
