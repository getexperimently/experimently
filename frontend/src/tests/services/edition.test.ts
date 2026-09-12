import {
  COMMUNITY_EDITION,
  EDITION_PATH,
  EDITION_PROBE_TIMEOUT_MS,
  EditionInfo,
  EditionService,
  FEATURES,
  LICENSE_STATUSES,
  LicenseStatus,
  expiryDate,
  featureEnabled,
  grantsFeature,
  isLicenseStatus,
  normaliseEdition,
} from '@/services/edition';

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

function ok(body: unknown) {
  mockFetch.mockResolvedValueOnce({
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    json: () => Promise.resolve(body),
  } as unknown as Response);
}

function enterprise(overrides: Partial<EditionInfo> = {}): EditionInfo {
  return {
    edition: 'enterprise',
    features: [FEATURES.RBAC, FEATURES.WORKSPACES],
    status: 'active',
    expires_at: '2027-03-01T00:00:00Z',
    version: '1.0.0',
    ...overrides,
  };
}

describe('LicenseStatus', () => {
  it('has five members, not four — `invalid` is a real state', () => {
    expect(LICENSE_STATUSES).toEqual(['none', 'active', 'grace', 'expired', 'invalid']);
    expect(LICENSE_STATUSES).toHaveLength(5);
  });

  it('accepts every backend status and nothing else', () => {
    for (const status of LICENSE_STATUSES) expect(isLicenseStatus(status)).toBe(true);
    for (const bogus of ['ACTIVE', 'lapsed', '', null, undefined, 3, {}]) {
      expect(isLicenseStatus(bogus)).toBe(false);
    }
  });

  it('types the union so a state outside it cannot be assigned', () => {
    // Compile-time assertion: every member is assignable to LicenseStatus and
    // the set is exhaustive (a missing member makes `exhaustive` fail to build).
    const seen: Record<LicenseStatus, true> = {
      none: true,
      active: true,
      grace: true,
      expired: true,
      invalid: true,
    };
    expect(Object.keys(seen).sort()).toEqual([...LICENSE_STATUSES].sort());
  });
});

describe('normaliseEdition', () => {
  it('passes a well-formed enterprise body through', () => {
    expect(normaliseEdition(enterprise())).toEqual(enterprise());
  });

  it('reads the Community answer', () => {
    expect(
      normaliseEdition({
        edition: 'ce',
        features: [],
        status: 'none',
        expires_at: null,
        version: '1.0.0',
      }),
    ).toEqual({ ...COMMUNITY_EDITION, version: '1.0.0' });
  });

  it('maps an unknown status on an enterprise body to `invalid`, never to a usable one', () => {
    const info = normaliseEdition({ ...enterprise(), status: 'totally-fine' });
    expect(info.status).toBe('invalid');
    expect(featureEnabled(info, FEATURES.RBAC)).toBe(false);
  });

  it('falls back to Community for an unknown edition', () => {
    const info = normaliseEdition({ ...enterprise(), edition: 'ultimate' });
    expect(info.edition).toBe('ce');
    expect(featureEnabled(info, FEATURES.RBAC)).toBe(false);
  });

  it('survives junk bodies', () => {
    expect(normaliseEdition(null)).toEqual(COMMUNITY_EDITION);
    expect(normaliseEdition('<html>502</html>')).toEqual(COMMUNITY_EDITION);
    expect(normaliseEdition({})).toEqual(COMMUNITY_EDITION);
  });

  it('drops non-string entries from features', () => {
    expect(normaliseEdition({ ...enterprise(), features: ['rbac', 7, null] }).features).toEqual([
      'rbac',
    ]);
  });
});

describe('grantsFeature / featureEnabled', () => {
  it('Community grants nothing, wildcard or not', () => {
    expect(grantsFeature(COMMUNITY_EDITION, FEATURES.RBAC)).toBe(false);
    expect(grantsFeature({ ...COMMUNITY_EDITION, features: ['*'] }, FEATURES.RBAC)).toBe(false);
  });

  it('grants a named feature and the wildcard', () => {
    expect(grantsFeature(enterprise(), FEATURES.RBAC)).toBe(true);
    expect(grantsFeature(enterprise({ features: ['*'] }), FEATURES.HIPAA)).toBe(true);
    expect(grantsFeature(enterprise(), FEATURES.HIPAA)).toBe(false);
  });

  it.each([
    ['active', true],
    ['grace', true],
    ['expired', false],
    ['invalid', false],
    ['none', false],
  ] as [LicenseStatus, boolean][])('status %s → usable: %s', (status, expected) => {
    expect(featureEnabled(enterprise({ status }), FEATURES.RBAC)).toBe(expected);
  });

  it('separates "the licence names it" from "it can be used"', () => {
    const lapsed = enterprise({ status: 'expired' });
    expect(grantsFeature(lapsed, FEATURES.RBAC)).toBe(true);
    expect(featureEnabled(lapsed, FEATURES.RBAC)).toBe(false);
  });
});

describe('expiryDate', () => {
  it('parses the ISO timestamp', () => {
    expect(expiryDate(enterprise())?.toISOString()).toBe('2027-03-01T00:00:00.000Z');
  });

  it('is null for Community and for junk', () => {
    expect(expiryDate(COMMUNITY_EDITION)).toBeNull();
    expect(expiryDate(enterprise({ expires_at: 'soon' }))).toBeNull();
  });
});

describe('EditionService.get', () => {
  it('GETs /api/v1/edition', async () => {
    ok(enterprise());
    await expect(EditionService.get()).resolves.toEqual(enterprise());
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}${EDITION_PATH}`, expect.any(Object));
  });

  it('passes an abort signal and gives up on a probe that hangs', async () => {
    // A probe that *hangs* (a stuck upstream behind an hour-long proxy read
    // timeout) used to pin the shared in-flight promise for the whole tab
    // session; a failure, by contrast, is retried. The timeout makes a hang
    // into a failure.
    jest.useFakeTimers();
    try {
      let abortedWith: unknown = null;
      mockFetch.mockImplementation(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener('abort', () => {
              abortedWith = init.signal?.reason ?? 'aborted';
              reject(new DOMException('The operation was aborted.', 'AbortError'));
            });
          }),
      );
      const pending = EditionService.get();
      const settled = pending.then(
        () => 'resolved',
        () => 'rejected',
      );
      jest.advanceTimersByTime(EDITION_PROBE_TIMEOUT_MS + 1);
      await expect(settled).resolves.toBe('rejected');
      expect(abortedWith).not.toBeNull();
    } finally {
      jest.useRealTimers();
    }
  });

  it('sends no Authorization header — the endpoint is public chrome', async () => {
    localStorage.setItem('experimently.token', 'tok');
    ok(enterprise());
    await EditionService.get();
    const init = mockFetch.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it('rejects when the API is unreachable — the caller decides what that means', async () => {
    mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    await expect(EditionService.get()).rejects.toBeDefined();
  });
});
