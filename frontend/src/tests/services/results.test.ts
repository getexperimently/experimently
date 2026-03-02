import { ResultsService } from '@/services/results';

const mockFetch = jest.fn();
global.fetch = mockFetch;

const BASE = 'http://localhost:8000';

beforeEach(() => {
  mockFetch.mockReset();
  // Remove env override so tests use the default
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

describe('ResultsService.getResults', () => {
  it('calls the correct URL', async () => {
    mockOk({ experiment_id: 'abc' });
    await ResultsService.getResults('abc');
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/results/abc`);
  });

  it('appends metric_id param when provided', async () => {
    mockOk({});
    await ResultsService.getResults('abc', { metric_id: 'm1' });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain('metric_id=m1');
  });

  it('returns parsed JSON on success', async () => {
    const payload = { experiment_id: 'abc', experiment_name: 'Test' };
    mockOk(payload);
    const result = await ResultsService.getResults('abc');
    expect(result).toEqual(payload);
  });

  it('throws on non-ok response', async () => {
    mockError(404, 'Not Found');
    await expect(ResultsService.getResults('abc')).rejects.toThrow(
      'Failed to fetch results: Not Found'
    );
  });
});

describe('ResultsService.getDailyResults', () => {
  it('calls the correct URL', async () => {
    mockOk({ experiment_id: 'abc', series: [] });
    await ResultsService.getDailyResults('abc');
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/results/abc/daily`);
  });

  it('appends metric_id when provided', async () => {
    mockOk({});
    await ResultsService.getDailyResults('abc', 'm2');
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain('metric_id=m2');
  });

  it('throws on non-ok response', async () => {
    mockError(500, 'Server Error');
    await expect(ResultsService.getDailyResults('abc')).rejects.toThrow(
      'Failed to fetch daily results: Server Error'
    );
  });
});

describe('ResultsService.getSampleSize', () => {
  it('calls the correct URL', async () => {
    mockOk({ is_adequate: true });
    await ResultsService.getSampleSize('abc');
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}/api/v1/results/abc/sample-size`);
  });

  it('appends mde and power params', async () => {
    mockOk({});
    await ResultsService.getSampleSize('abc', { mde: 0.05, power: 0.8 });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain('mde=0.05');
    expect(url).toContain('power=0.8');
  });
});

describe('ResultsService.invalidateCache', () => {
  it('calls the correct URL with POST', async () => {
    mockOk({ status: 'ok', experiment_id: 'abc' });
    await ResultsService.invalidateCache('abc');
    expect(mockFetch).toHaveBeenCalledWith(
      `${BASE}/api/v1/results/abc/invalidate-cache`,
      { method: 'POST' }
    );
  });

  it('returns parsed response', async () => {
    const payload = { status: 'invalidated', experiment_id: 'abc' };
    mockOk(payload);
    const result = await ResultsService.invalidateCache('abc');
    expect(result).toEqual(payload);
  });
});
