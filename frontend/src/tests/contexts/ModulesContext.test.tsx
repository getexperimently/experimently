import React from 'react';
import { render, renderHook, screen, waitFor, act } from '@testing-library/react';
import {
  MODULES_CACHE_TTL_MS,
  MODULES_ERROR_RETRY_MAX_MS,
  MODULES_ERROR_RETRY_MS,
  ModulesProvider,
  retryDelayMs,
  RequiresModule,
  __resetModulesCache,
  loadModules,
  useModules,
  useModule,
} from '@/contexts/ModulesContext';
import { MODULES, ModulesInfo, ModulesService } from '@/services/modules';

jest.mock('@/services/modules', () => {
  const actual = jest.requireActual('@/services/modules');
  return { ...actual, ModulesService: { get: jest.fn() } };
});

const mockGet = ModulesService.get as jest.Mock;

function full(overrides: Partial<ModulesInfo> = {}): ModulesInfo {
  return {
    profile: 'full',
    modules: [MODULES.RBAC],
    version: '1.0.0',
    ...overrides,
  };
}

const core: ModulesInfo = { profile: 'core', modules: [], version: '1.0.0' };

function wrapper({ children }: { children: React.ReactNode }) {
  return <ModulesProvider>{children}</ModulesProvider>;
}

beforeEach(() => {
  __resetModulesCache();
  mockGet.mockReset();
});

// ---------------------------------------------------------------------------
// The default
// ---------------------------------------------------------------------------

describe('defaulting to core', () => {
  it.each([
    ['a network failure', () => mockGet.mockRejectedValue(new TypeError('Failed to fetch'))],
    ['a 500', () => mockGet.mockRejectedValue(Object.assign(new Error('boom'), { status: 500 }))],
    ['a 404 (an older backend with no /modules route)', () =>
      mockGet.mockRejectedValue(Object.assign(new Error('Not Found'), { status: 404 }))],
  ])('falls back to core after %s', async (_label, arrange) => {
    arrange();
    const { result } = renderHook(() => useModules(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.profile).toBe('core');
    expect(result.current.modules).toEqual([]);
    expect(result.current.hasModule(MODULES.RBAC)).toBe(false);
    expect(result.current.error).toBeInstanceOf(Error);
  });

  it('renders core *while the request is still outstanding*, never module chrome', async () => {
    let resolve: (v: ModulesInfo) => void = () => undefined;
    mockGet.mockReturnValue(new Promise<ModulesInfo>((r) => { resolve = r; }));

    const { result } = renderHook(() => useModules(), { wrapper });
    expect(result.current.isLoading).toBe(true);
    expect(result.current.profile).toBe('core');
    expect(result.current.hasModule(MODULES.RBAC)).toBe(false);

    await act(async () => {
      resolve(full());
    });
    await waitFor(() => expect(result.current.profile).toBe('full'));
    expect(result.current.hasModule(MODULES.RBAC)).toBe(true);
  });

  it('returns core with no provider above it, and makes no request', () => {
    const { result } = renderHook(() => useModules());
    expect(result.current.profile).toBe('core');
    expect(result.current.modules).toEqual([]);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('never rejects out of loadModules, whatever the transport throws', async () => {
    mockGet.mockRejectedValue('a string, not an Error');
    const entry = await loadModules();
    expect(entry.info.profile).toBe('core');
    expect(entry.error).toBeInstanceOf(Error);
  });
});

// ---------------------------------------------------------------------------
// Caching
// ---------------------------------------------------------------------------

describe('caching', () => {
  it('fetches once and reuses the answer for five minutes', async () => {
    mockGet.mockResolvedValue(full());
    jest.useFakeTimers().setSystemTime(new Date('2026-09-11T00:00:00Z'));
    try {
      await loadModules();
      jest.setSystemTime(new Date('2026-09-11T00:04:59Z'));
      await loadModules();
      expect(mockGet).toHaveBeenCalledTimes(1);

      jest.setSystemTime(new Date(Date.now() + MODULES_CACHE_TTL_MS));
      await loadModules();
      expect(mockGet).toHaveBeenCalledTimes(2);
    } finally {
      jest.useRealTimers();
    }
  });

  it('shares one in-flight request between concurrent callers', async () => {
    mockGet.mockResolvedValue(full());
    const [a, b, c] = await Promise.all([loadModules(), loadModules(), loadModules()]);
    expect(mockGet).toHaveBeenCalledTimes(1);
    expect(a.info).toEqual(b.info);
    expect(b.info).toEqual(c.info);
  });

  it('does not re-request when a second provider mounts', async () => {
    mockGet.mockResolvedValue(full());
    const { result } = renderHook(() => useModules(), { wrapper });
    await waitFor(() => expect(result.current.profile).toBe('full'));

    render(
      <ModulesProvider>
        <span>second</span>
      </ModulesProvider>,
    );
    await waitFor(() => expect(screen.getByText('second')).toBeInTheDocument());
    expect(mockGet).toHaveBeenCalledTimes(1);
  });

  it('caches the core fallback too, so a dead backend is not hammered', async () => {
    mockGet.mockRejectedValue(new TypeError('Failed to fetch'));
    await loadModules();
    await loadModules();
    expect(mockGet).toHaveBeenCalledTimes(1);
  });

  it('a failed probe expires sooner than a good answer, and the provider retries it', async () => {
    // One 502 while the tab loaded used to render core chrome on a
    // full-profile instance for the whole session: the error was cached for
    // the full TTL and nothing ever asked again.
    jest.useFakeTimers();
    try {
      mockGet.mockRejectedValueOnce(new TypeError('Failed to fetch'));
      mockGet.mockResolvedValueOnce(full());

      const { result } = renderHook(() => useModules(), { wrapper });
      await act(async () => {
        await Promise.resolve();
      });
      expect(result.current.profile).toBe('core');
      expect(result.current.error).not.toBeNull();

      // Still inside the error window: no second request.
      await act(async () => {
        jest.advanceTimersByTime(MODULES_ERROR_RETRY_MS - 1);
        await Promise.resolve();
      });
      expect(mockGet).toHaveBeenCalledTimes(1);

      // Past it: the provider probes again on its own and heals.
      await act(async () => {
        jest.advanceTimersByTime(2);
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(mockGet).toHaveBeenCalledTimes(2);
      expect(result.current.profile).toBe('full');
      expect(result.current.error).toBeNull();
    } finally {
      jest.useRealTimers();
    }
  });

  it('refresh() bypasses the cache', async () => {
    mockGet.mockResolvedValueOnce(full({ modules: [MODULES.RBAC] }));
    const { result } = renderHook(() => useModules(), { wrapper });
    await waitFor(() => expect(result.current.modules).toEqual([MODULES.RBAC]));

    mockGet.mockResolvedValueOnce(full({ modules: [MODULES.RBAC, MODULES.WORKSPACES] }));
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.modules).toEqual([MODULES.RBAC, MODULES.WORKSPACES]);
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it('refresh() does not re-enter the loading state when it already has an answer', async () => {
    // `isLoading` means "nothing to show yet". Raising it for a refresh blanks
    // every consumer that gates on it -- including the retry button in
    // `ModuleUnavailableNotice`, which is the only thing that calls refresh().
    mockGet.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    const { result } = renderHook(() => useModules(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error).not.toBeNull();

    let resolveSecond: (value: ModulesInfo) => void = () => undefined;
    mockGet.mockImplementationOnce(
      () =>
        new Promise<ModulesInfo>((resolve) => {
          resolveSecond = resolve;
        }),
    );

    let settled: Promise<ModulesInfo> = Promise.resolve(core);
    await act(async () => {
      settled = result.current.refresh();
      await Promise.resolve();
    });

    // In flight: still no answer *newer* than the one we hold, but the one we
    // hold is still an answer.
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).not.toBeNull();

    await act(async () => {
      resolveSecond(full());
      await settled;
    });
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.profile).toBe('full');
  });

  it('a forced refresh that resolves first is not undone by the earlier request resolving last', async () => {
    // Request A (mount) is slow and answers core; request B (refresh) is fast
    // and answers full. B must win, and A must neither overwrite the cache
    // nor be applied when it finally settles.
    let resolveA: (value: ModulesInfo) => void = () => undefined;
    mockGet.mockImplementationOnce(
      () =>
        new Promise<ModulesInfo>((resolve) => {
          resolveA = resolve;
        }),
    );
    const { result } = renderHook(() => useModules(), { wrapper });
    expect(result.current.isLoading).toBe(true);

    mockGet.mockResolvedValueOnce(full());
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.profile).toBe('full');

    // Now the stale mount-time request settles with the pre-refresh answer.
    await act(async () => {
      resolveA(core);
      await Promise.resolve();
    });
    expect(result.current.profile).toBe('full');
    expect(result.current.modules).toEqual([MODULES.RBAC]);

    // And the cache holds the newer answer: a fresh caller gets the full
    // profile without another request.
    const entry = await loadModules();
    expect(entry.info.profile).toBe('full');
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it('backs off between retries and stops at the cap', () => {
    expect(retryDelayMs(0)).toBe(MODULES_ERROR_RETRY_MS);
    expect(retryDelayMs(1)).toBe(2 * MODULES_ERROR_RETRY_MS);
    expect(retryDelayMs(2)).toBe(4 * MODULES_ERROR_RETRY_MS);
    expect(retryDelayMs(10)).toBe(MODULES_ERROR_RETRY_MAX_MS);
    expect(retryDelayMs(-3)).toBe(MODULES_ERROR_RETRY_MS);
  });

  it('under StrictMode the retry chain is owned by one effect invocation', async () => {
    // StrictMode mounts, cleans up and mounts again. The first invocation's
    // `.then` must not schedule a timer that no live cleanup owns.
    jest.useFakeTimers();
    try {
      mockGet.mockRejectedValue(new TypeError('Failed to fetch'));
      const { unmount } = render(
        <React.StrictMode>
          <ModulesProvider>
            <span />
          </ModulesProvider>
        </React.StrictMode>,
      );
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(jest.getTimerCount()).toBe(1);
      unmount();
      expect(jest.getTimerCount()).toBe(0);
      const calls = mockGet.mock.calls.length;
      await act(async () => {
        jest.advanceTimersByTime(MODULES_ERROR_RETRY_MAX_MS);
        await Promise.resolve();
      });
      // Nothing fires after unmount.
      expect(mockGet.mock.calls.length).toBe(calls);
    } finally {
      jest.useRealTimers();
    }
  });

  it('a seeded provider makes no request at all', async () => {
    const { result } = renderHook(() => useModules(), {
      wrapper: ({ children }) => <ModulesProvider initial={full()}>{children}</ModulesProvider>,
    });
    expect(result.current.profile).toBe('full');
    expect(result.current.isLoading).toBe(false);
    expect(mockGet).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// The two profiles
// ---------------------------------------------------------------------------

describe('the two profiles', () => {
  it('core: no modules, nothing installed', async () => {
    mockGet.mockResolvedValue(core);
    const { result } = renderHook(() => useModules(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.profile).toBe('core');
    expect(result.current.version).toBe('1.0.0');
    expect(result.current.hasModule(MODULES.RBAC)).toBe(false);
  });

  it('full: exactly the modules the backend lists are installed', async () => {
    mockGet.mockResolvedValue(full({ modules: [MODULES.RBAC, MODULES.WORKSPACES] }));
    const { result } = renderHook(() => useModules(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.profile).toBe('full');
    expect(result.current.hasModule(MODULES.RBAC)).toBe(true);
    expect(result.current.hasModule(MODULES.WORKSPACES)).toBe(true);
    expect(result.current.hasModule(MODULES.HIPAA)).toBe(false);
  });

  it('exposes the ordered module list and the version', async () => {
    mockGet.mockResolvedValue(full({ modules: ['sso', 'rbac'], version: '2.3.4' }));
    const { result } = renderHook(() => useModules(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.modules).toEqual(['sso', 'rbac']);
    expect(result.current.version).toBe('2.3.4');
  });
});

// ---------------------------------------------------------------------------
// useModule / RequiresModule
// ---------------------------------------------------------------------------

describe('useModule', () => {
  it('is true only for an installed module', async () => {
    mockGet.mockResolvedValue(full({ modules: [MODULES.RBAC] }));
    const { result } = renderHook(
      () => ({ rbac: useModule(MODULES.RBAC), hipaa: useModule(MODULES.HIPAA) }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.rbac).toBe(true));
    expect(result.current.hipaa).toBe(false);
  });

  it('is false outside a provider', () => {
    const { result } = renderHook(() => useModule(MODULES.RBAC));
    expect(result.current).toBe(false);
  });
});

describe('RequiresModule', () => {
  function Subject() {
    return (
      <RequiresModule name={MODULES.RBAC} fallback={<span>not installed</span>}>
        <span>roles</span>
      </RequiresModule>
    );
  }

  it('renders children when the module is installed', async () => {
    mockGet.mockResolvedValue(full());
    render(
      <ModulesProvider>
        <Subject />
      </ModulesProvider>,
    );
    await waitFor(() => expect(screen.getByText('roles')).toBeInTheDocument());
    expect(screen.queryByText('not installed')).not.toBeInTheDocument();
  });

  it('renders the fallback in core', async () => {
    mockGet.mockRejectedValue(new TypeError('Failed to fetch'));
    render(
      <ModulesProvider>
        <Subject />
      </ModulesProvider>,
    );
    await waitFor(() => expect(screen.getByText('not installed')).toBeInTheDocument());
    expect(screen.queryByText('roles')).not.toBeInTheDocument();
  });

  it('renders nothing at all when no fallback is given', async () => {
    mockGet.mockResolvedValue(full({ modules: [MODULES.HIPAA] }));
    const { container } = render(
      <ModulesProvider>
        <RequiresModule name={MODULES.RBAC}>
          <span>roles</span>
        </RequiresModule>
      </ModulesProvider>,
    );
    await waitFor(() => expect(screen.queryByText('roles')).not.toBeInTheDocument());
    expect(container).toBeEmptyDOMElement();
  });
});
