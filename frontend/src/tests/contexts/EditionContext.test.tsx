import React from 'react';
import { render, renderHook, screen, waitFor, act } from '@testing-library/react';
import {
  EDITION_CACHE_TTL_MS,
  EDITION_ERROR_RETRY_MAX_MS,
  EDITION_ERROR_RETRY_MS,
  EditionProvider,
  retryDelayMs,
  RequiresFeature,
  __resetEditionCache,
  loadEdition,
  useEdition,
  useFeature,
} from '@/contexts/EditionContext';
import { EditionInfo, EditionService, FEATURES, LicenseStatus } from '@/services/edition';

jest.mock('@/services/edition', () => {
  const actual = jest.requireActual('@/services/edition');
  return { ...actual, EditionService: { get: jest.fn() } };
});

const mockGet = EditionService.get as jest.Mock;

function enterprise(overrides: Partial<EditionInfo> = {}): EditionInfo {
  return {
    edition: 'enterprise',
    features: [FEATURES.RBAC],
    status: 'active',
    expires_at: '2027-03-01T00:00:00Z',
    version: '1.0.0',
    ...overrides,
  };
}

function wrapper({ children }: { children: React.ReactNode }) {
  return <EditionProvider>{children}</EditionProvider>;
}

beforeEach(() => {
  __resetEditionCache();
  mockGet.mockReset();
});

// ---------------------------------------------------------------------------
// The default
// ---------------------------------------------------------------------------

describe('defaulting to Community', () => {
  it.each([
    ['a network failure', () => mockGet.mockRejectedValue(new TypeError('Failed to fetch'))],
    ['a 500', () => mockGet.mockRejectedValue(Object.assign(new Error('boom'), { status: 500 }))],
    ['a 404 (an older backend with no /edition route)', () =>
      mockGet.mockRejectedValue(Object.assign(new Error('Not Found'), { status: 404 }))],
  ])('falls back to Community after %s', async (_label, arrange) => {
    arrange();
    const { result } = renderHook(() => useEdition(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.edition).toBe('ce');
    expect(result.current.status).toBe('none');
    expect(result.current.features).toEqual([]);
    expect(result.current.isEnterprise).toBe(false);
    expect(result.current.hasFeature(FEATURES.RBAC)).toBe(false);
    expect(result.current.error).toBeInstanceOf(Error);
  });

  it('renders Community *while the request is still outstanding*, never enterprise chrome', async () => {
    let resolve: (v: EditionInfo) => void = () => undefined;
    mockGet.mockReturnValue(new Promise<EditionInfo>((r) => { resolve = r; }));

    const { result } = renderHook(() => useEdition(), { wrapper });
    expect(result.current.isLoading).toBe(true);
    expect(result.current.edition).toBe('ce');
    expect(result.current.hasFeature(FEATURES.RBAC)).toBe(false);

    await act(async () => {
      resolve(enterprise());
    });
    await waitFor(() => expect(result.current.isEnterprise).toBe(true));
  });

  it('returns Community with no provider above it, and makes no request', () => {
    const { result } = renderHook(() => useEdition());
    expect(result.current.edition).toBe('ce');
    expect(result.current.status).toBe('none');
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('never rejects out of loadEdition, whatever the transport throws', async () => {
    mockGet.mockRejectedValue('a string, not an Error');
    const entry = await loadEdition();
    expect(entry.info.edition).toBe('ce');
    expect(entry.error).toBeInstanceOf(Error);
  });
});

// ---------------------------------------------------------------------------
// Caching
// ---------------------------------------------------------------------------

describe('caching', () => {
  it('fetches once and reuses the answer for five minutes', async () => {
    mockGet.mockResolvedValue(enterprise());
    jest.useFakeTimers().setSystemTime(new Date('2026-09-11T00:00:00Z'));
    try {
      await loadEdition();
      jest.setSystemTime(new Date('2026-09-11T00:04:59Z'));
      await loadEdition();
      expect(mockGet).toHaveBeenCalledTimes(1);

      jest.setSystemTime(new Date(Date.now() + EDITION_CACHE_TTL_MS));
      await loadEdition();
      expect(mockGet).toHaveBeenCalledTimes(2);
    } finally {
      jest.useRealTimers();
    }
  });

  it('shares one in-flight request between concurrent callers', async () => {
    mockGet.mockResolvedValue(enterprise());
    const [a, b, c] = await Promise.all([loadEdition(), loadEdition(), loadEdition()]);
    expect(mockGet).toHaveBeenCalledTimes(1);
    expect(a.info).toEqual(b.info);
    expect(b.info).toEqual(c.info);
  });

  it('does not re-request when a second provider mounts', async () => {
    mockGet.mockResolvedValue(enterprise());
    const { result } = renderHook(() => useEdition(), { wrapper });
    await waitFor(() => expect(result.current.isEnterprise).toBe(true));

    render(
      <EditionProvider>
        <span>second</span>
      </EditionProvider>,
    );
    await waitFor(() => expect(screen.getByText('second')).toBeInTheDocument());
    expect(mockGet).toHaveBeenCalledTimes(1);
  });

  it('caches the Community fallback too, so a dead backend is not hammered', async () => {
    mockGet.mockRejectedValue(new TypeError('Failed to fetch'));
    await loadEdition();
    await loadEdition();
    expect(mockGet).toHaveBeenCalledTimes(1);
  });

  it('a failed probe expires sooner than a good answer, and the provider retries it', async () => {
    // One 502 while the tab loaded used to render Community chrome on an
    // Enterprise instance for the whole session: the error was cached for the
    // full TTL and nothing ever asked again.
    jest.useFakeTimers();
    try {
      mockGet.mockRejectedValueOnce(new TypeError('Failed to fetch'));
      mockGet.mockResolvedValueOnce(enterprise({ status: 'active' }));

      const { result } = renderHook(() => useEdition(), { wrapper });
      await act(async () => {
        await Promise.resolve();
      });
      expect(result.current.edition).toBe('ce');
      expect(result.current.error).not.toBeNull();

      // Still inside the error window: no second request.
      await act(async () => {
        jest.advanceTimersByTime(EDITION_ERROR_RETRY_MS - 1);
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
      expect(result.current.edition).toBe('enterprise');
      expect(result.current.error).toBeNull();
    } finally {
      jest.useRealTimers();
    }
  });

  it('refresh() bypasses the cache', async () => {
    mockGet.mockResolvedValueOnce(enterprise({ status: 'grace' }));
    const { result } = renderHook(() => useEdition(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe('grace'));

    mockGet.mockResolvedValueOnce(enterprise({ status: 'active' }));
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.status).toBe('active');
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it('a forced refresh that resolves first is not undone by the earlier request resolving last', async () => {
    // Request A (mount) is slow and answers Community; request B (refresh) is
    // fast and answers Enterprise. B must win, and A must neither overwrite
    // the cache nor be applied when it finally settles.
    let resolveA: (value: EditionInfo) => void = () => undefined;
    mockGet.mockImplementationOnce(
      () =>
        new Promise<EditionInfo>((resolve) => {
          resolveA = resolve;
        }),
    );
    const { result } = renderHook(() => useEdition(), { wrapper });
    expect(result.current.isLoading).toBe(true);

    mockGet.mockResolvedValueOnce(enterprise({ status: 'active' }));
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.edition).toBe('enterprise');

    // Now the stale mount-time request settles with the pre-refresh answer.
    await act(async () => {
      resolveA({ edition: 'ce', features: [], status: 'none', expires_at: null, version: '1' });
      await Promise.resolve();
    });
    expect(result.current.edition).toBe('enterprise');
    expect(result.current.status).toBe('active');

    // And the cache holds the newer answer: a fresh caller gets Enterprise
    // without another request.
    const entry = await loadEdition();
    expect(entry.info.edition).toBe('enterprise');
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it('backs off between retries and stops at the cap', () => {
    expect(retryDelayMs(0)).toBe(EDITION_ERROR_RETRY_MS);
    expect(retryDelayMs(1)).toBe(2 * EDITION_ERROR_RETRY_MS);
    expect(retryDelayMs(2)).toBe(4 * EDITION_ERROR_RETRY_MS);
    expect(retryDelayMs(10)).toBe(EDITION_ERROR_RETRY_MAX_MS);
    expect(retryDelayMs(-3)).toBe(EDITION_ERROR_RETRY_MS);
  });

  it('under StrictMode the retry chain is owned by one effect invocation', async () => {
    // StrictMode mounts, cleans up and mounts again. The first invocation's
    // `.then` must not schedule a timer that no live cleanup owns.
    jest.useFakeTimers();
    try {
      mockGet.mockRejectedValue(new TypeError('Failed to fetch'));
      const { unmount } = render(
        <React.StrictMode>
          <EditionProvider>
            <span />
          </EditionProvider>
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
        jest.advanceTimersByTime(EDITION_ERROR_RETRY_MAX_MS);
        await Promise.resolve();
      });
      // Nothing fires after unmount.
      expect(mockGet.mock.calls.length).toBe(calls);
    } finally {
      jest.useRealTimers();
    }
  });

  it('a seeded provider makes no request at all', async () => {
    const { result } = renderHook(() => useEdition(), {
      wrapper: ({ children }) => (
        <EditionProvider initial={enterprise()}>{children}</EditionProvider>
      ),
    });
    expect(result.current.isEnterprise).toBe(true);
    expect(result.current.isLoading).toBe(false);
    expect(mockGet).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// The five states
// ---------------------------------------------------------------------------

describe('the five licence states', () => {
  it.each([
    ['none', 'ce', false],
    ['active', 'enterprise', true],
    ['grace', 'enterprise', true],
    ['expired', 'enterprise', false],
    ['invalid', 'enterprise', false],
  ] as [LicenseStatus, 'ce' | 'enterprise', boolean][])(
    '%s → edition %s, rbac usable: %s',
    async (status, edition, usable) => {
      mockGet.mockResolvedValue(
        status === 'none'
          ? { edition: 'ce', features: [], status, expires_at: null, version: '1.0.0' }
          : enterprise({ status }),
      );
      const { result } = renderHook(() => useEdition(), { wrapper });
      await waitFor(() => expect(result.current.isLoading).toBe(false));

      expect(result.current.status).toBe(status);
      expect(result.current.edition).toBe(edition);
      expect(result.current.hasFeature(FEATURES.RBAC)).toBe(usable);
    },
  );

  it('an expired licence still *names* its features, it just cannot use them', async () => {
    mockGet.mockResolvedValue(enterprise({ status: 'expired' }));
    const { result } = renderHook(() => useEdition(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.grants(FEATURES.RBAC)).toBe(true);
    expect(result.current.hasFeature(FEATURES.RBAC)).toBe(false);
    expect(result.current.isEnterprise).toBe(true);
  });

  it('exposes expiry as a Date', async () => {
    mockGet.mockResolvedValue(enterprise());
    const { result } = renderHook(() => useEdition(), { wrapper });
    await waitFor(() => expect(result.current.expiresAt).not.toBeNull());
    expect(result.current.expiresAt?.toISOString()).toBe('2027-03-01T00:00:00.000Z');
  });
});

// ---------------------------------------------------------------------------
// useFeature / RequiresFeature
// ---------------------------------------------------------------------------

describe('useFeature', () => {
  it('is true only for a named, in-date feature', async () => {
    mockGet.mockResolvedValue(enterprise({ features: [FEATURES.RBAC] }));
    const { result } = renderHook(
      () => ({ rbac: useFeature(FEATURES.RBAC), hipaa: useFeature(FEATURES.HIPAA) }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.rbac).toBe(true));
    expect(result.current.hipaa).toBe(false);
  });

  it('honours the wildcard licence', async () => {
    mockGet.mockResolvedValue(enterprise({ features: ['*'] }));
    const { result } = renderHook(() => useFeature(FEATURES.WAREHOUSE), { wrapper });
    await waitFor(() => expect(result.current).toBe(true));
  });

  it('is false outside a provider', () => {
    const { result } = renderHook(() => useFeature(FEATURES.RBAC));
    expect(result.current).toBe(false);
  });
});

describe('RequiresFeature', () => {
  function Subject() {
    return (
      <RequiresFeature name={FEATURES.RBAC} fallback={<span>not licensed</span>}>
        <span>roles</span>
      </RequiresFeature>
    );
  }

  it('renders children when the feature is usable', async () => {
    mockGet.mockResolvedValue(enterprise());
    render(
      <EditionProvider>
        <Subject />
      </EditionProvider>,
    );
    await waitFor(() => expect(screen.getByText('roles')).toBeInTheDocument());
    expect(screen.queryByText('not licensed')).not.toBeInTheDocument();
  });

  it('renders the fallback in Community', async () => {
    mockGet.mockRejectedValue(new TypeError('Failed to fetch'));
    render(
      <EditionProvider>
        <Subject />
      </EditionProvider>,
    );
    await waitFor(() => expect(screen.getByText('not licensed')).toBeInTheDocument());
    expect(screen.queryByText('roles')).not.toBeInTheDocument();
  });

  it('renders nothing at all when no fallback is given', async () => {
    mockGet.mockResolvedValue(enterprise({ status: 'expired' }));
    const { container } = render(
      <EditionProvider>
        <RequiresFeature name={FEATURES.RBAC}>
          <span>roles</span>
        </RequiresFeature>
      </EditionProvider>,
    );
    await waitFor(() => expect(screen.queryByText('roles')).not.toBeInTheDocument());
    expect(container).toBeEmptyDOMElement();
  });
});
