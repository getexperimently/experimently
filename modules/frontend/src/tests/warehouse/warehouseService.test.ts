/**
 * The warehouse client, through the real `apiFetch`: each call hits the SPEC 7
 * route with the right method, and the one secret travels only in a JSON body.
 */
import { warehouseService } from '@modules/services/warehouse';
import { SERVICE_ACCOUNT_JSON, KEY_SENTINEL } from './fixtures';

const mockFetch = jest.fn();
global.fetch = mockFetch as unknown as typeof fetch;

function ok(body: unknown, status = 200): Response {
  return {
    ok: true,
    status,
    headers: { get: () => 'application/json' },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response;
}

beforeEach(() => {
  mockFetch.mockReset();
  mockFetch.mockResolvedValue(ok({ connectors: [], connections: [], sources: [] }));
});

function call(i = 0): { url: string; init: RequestInit } {
  const [url, init] = mockFetch.mock.calls[i];
  return { url: String(url), init: init as RequestInit };
}

const BIGQUERY = {
  warehouse_type: 'bigquery' as const,
  name: 'Prod',
  billing_project: 'acme-billing',
  location: 'EU',
  max_bytes_per_query: 50_000_000_000,
  query_timeout_seconds: 300,
  max_runs_per_day: 20,
  service_account_json: SERVICE_ACCOUNT_JSON,
};

it.each([
  ['listConnectors', () => warehouseService.listConnectors(), 'GET', '/api/v1/warehouse/analysis/connectors'],
  ['listConnections', () => warehouseService.listConnections(), 'GET', '/api/v1/warehouse/analysis/connections'],
  ['getConnection', () => warehouseService.getConnection('c-1'), 'GET', '/api/v1/warehouse/analysis/connections/c-1'],
  ['deleteConnection', () => warehouseService.deleteConnection('c-1'), 'DELETE', '/api/v1/warehouse/analysis/connections/c-1'],
  ['testConnection', () => warehouseService.testConnection('c-1'), 'POST', '/api/v1/warehouse/analysis/connections/c-1/test'],
  ['regenerateKey', () => warehouseService.regenerateKey('c-1'), 'POST', '/api/v1/warehouse/analysis/connections/c-1/regenerate-key'],
  ['listSources', () => warehouseService.listSources(), 'GET', '/api/v1/warehouse/analysis/sources'],
  ['getSource', () => warehouseService.getSource('s-1'), 'GET', '/api/v1/warehouse/analysis/sources/s-1'],
  ['deleteSource', () => warehouseService.deleteSource('s-1'), 'DELETE', '/api/v1/warehouse/analysis/sources/s-1'],
  ['validateSource', () => warehouseService.validateSource('s-1'), 'POST', '/api/v1/warehouse/analysis/sources/s-1/validate'],
  ['previewSource', () => warehouseService.previewSource('s-1'), 'POST', '/api/v1/warehouse/analysis/sources/s-1/preview'],
])('%s calls %s %s', async (_name, run, method, pathname) => {
  await run();
  const { url, init } = call();
  expect(new URL(url, 'http://x').pathname).toBe(pathname);
  expect((init.method ?? 'GET').toUpperCase()).toBe(method);
});

it('escapes an id before it goes into the path', async () => {
  await warehouseService.getConnection('../sources?x=1');
  expect(call().url).toContain('/connections/..%2Fsources%3Fx%3D1');
});

it.each([
  ['createConnection', () => warehouseService.createConnection(BIGQUERY), 'POST', '/api/v1/warehouse/analysis/connections'],
  ['updateConnection', () => warehouseService.updateConnection('c-1', BIGQUERY), 'PUT', '/api/v1/warehouse/analysis/connections/c-1'],
  ['testUnsavedConnection', () => warehouseService.testUnsavedConnection(BIGQUERY), 'POST', '/api/v1/warehouse/analysis/connections/test'],
])('%s sends the key in the JSON body only', async (_name, run, method, pathname) => {
  await run();
  const { url, init } = call();
  expect(new URL(url, 'http://x').pathname).toBe(pathname);
  expect(init.method).toBe(method);
  expect(url).not.toContain(KEY_SENTINEL);
  expect(url).not.toContain('service_account');
  expect(JSON.stringify(init.headers)).not.toContain(KEY_SENTINEL);
  expect(JSON.parse(String(init.body)).service_account_json).toBe(SERVICE_ACCOUNT_JSON);
});
