import {
  CORE_PROFILE,
  MODULES,
  MODULES_PATH,
  MODULES_PROBE_TIMEOUT_MS,
  ModulesInfo,
  ModulesService,
  PROFILES,
  Profile,
  isProfile,
  moduleInstalled,
  normaliseModules,
} from '@/services/modules';

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

function full(overrides: Partial<ModulesInfo> = {}): ModulesInfo {
  return {
    profile: 'full',
    modules: [MODULES.RBAC, MODULES.WORKSPACES],
    version: '1.0.0',
    ...overrides,
  };
}

describe('MODULES', () => {
  it('names the ten modules, one per manifest group, in the contract order', () => {
    // `backend/app/core/hooks.py::KNOWN_MODULES` lists the same strings in
    // the same order; `backend/tests/unit/core/test_module_names.py` parses
    // this literal out of the source and compares the two.
    expect(Object.values(MODULES)).toEqual([
      'workspaces',
      'hipaa',
      'compliance',
      'sso',
      'rbac',
      'warehouse',
      'integrations',
      'counters',
      'etl',
      'split_url',
    ]);
  });
});

describe('Profile', () => {
  it('has two members: core and full', () => {
    expect(PROFILES).toEqual(['core', 'full']);
  });

  it('accepts both profiles and nothing else', () => {
    for (const profile of PROFILES) expect(isProfile(profile)).toBe(true);
    for (const bogus of ['FULL', 'ultimate', '', null, undefined, 3, {}]) {
      expect(isProfile(bogus)).toBe(false);
    }
  });

  it('types the union so a profile outside it cannot be assigned', () => {
    // Compile-time assertion: every member is assignable to Profile and the
    // set is exhaustive (a missing member makes `seen` fail to build).
    const seen: Record<Profile, true> = { core: true, full: true };
    expect(Object.keys(seen).sort()).toEqual([...PROFILES].sort());
  });
});

describe('normaliseModules', () => {
  it('passes a well-formed full body through', () => {
    expect(normaliseModules(full())).toEqual(full());
  });

  it('reads the core answer', () => {
    expect(normaliseModules({ profile: 'core', modules: [], version: '1.0.0' })).toEqual({
      ...CORE_PROFILE,
      version: '1.0.0',
    });
  });

  it('falls back to core for an unknown profile', () => {
    const info = normaliseModules({ ...full(), profile: 'ultimate' });
    expect(info.profile).toBe('core');
  });

  it('reads a non-array modules as none', () => {
    expect(normaliseModules({ ...full(), modules: 'rbac' }).modules).toEqual([]);
    expect(normaliseModules({ ...full(), modules: { rbac: true } }).modules).toEqual([]);
    expect(normaliseModules({ ...full(), modules: null }).modules).toEqual([]);
  });

  it('survives junk bodies', () => {
    expect(normaliseModules(null)).toEqual(CORE_PROFILE);
    expect(normaliseModules('<html>502</html>')).toEqual(CORE_PROFILE);
    expect(normaliseModules({})).toEqual(CORE_PROFILE);
  });

  it('drops non-string entries from modules', () => {
    expect(normaliseModules({ ...full(), modules: ['rbac', 7, null] }).modules).toEqual(['rbac']);
  });

  it('keeps the module list as the backend ordered it', () => {
    expect(normaliseModules({ ...full(), modules: ['sso', 'etl', 'rbac'] }).modules).toEqual([
      'sso',
      'etl',
      'rbac',
    ]);
  });
});

describe('moduleInstalled', () => {
  it('core has nothing installed', () => {
    expect(moduleInstalled(CORE_PROFILE, MODULES.RBAC)).toBe(false);
  });

  it('is true for a listed module and false for any other', () => {
    expect(moduleInstalled(full(), MODULES.RBAC)).toBe(true);
    expect(moduleInstalled(full(), MODULES.WORKSPACES)).toBe(true);
    expect(moduleInstalled(full(), MODULES.HIPAA)).toBe(false);
  });

  it('does not treat "*" as a wildcard — there is no such thing', () => {
    expect(moduleInstalled(full({ modules: ['*'] }), MODULES.RBAC)).toBe(false);
  });
});

describe('ModulesService.get', () => {
  it('GETs /api/v1/modules', async () => {
    ok(full());
    await expect(ModulesService.get()).resolves.toEqual(full());
    expect(mockFetch).toHaveBeenCalledWith(`${BASE}${MODULES_PATH}`, expect.any(Object));
    expect(MODULES_PATH).toBe('/api/v1/modules');
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
      const pending = ModulesService.get();
      const settled = pending.then(
        () => 'resolved',
        () => 'rejected',
      );
      jest.advanceTimersByTime(MODULES_PROBE_TIMEOUT_MS + 1);
      await expect(settled).resolves.toBe('rejected');
      expect(abortedWith).not.toBeNull();
    } finally {
      jest.useRealTimers();
    }
  });

  it('sends no Authorization header — the endpoint is public chrome', async () => {
    localStorage.setItem('experimently.token', 'tok');
    ok(full());
    await ModulesService.get();
    const init = mockFetch.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it('rejects when the API is unreachable — the caller decides what that means', async () => {
    mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    await expect(ModulesService.get()).rejects.toBeDefined();
  });
});
