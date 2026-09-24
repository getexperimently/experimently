/**
 * Reading NEXT_PUBLIC_SITE_MODE. The DEFAULT is the point: a self-hoster who
 * sets nothing must get the full dashboard, and only the deliberate act of
 * building the public site removes it.
 */
describe('SITE_MODE', () => {
  const load = (v: string | undefined) => {
    let m: typeof import('@/utils/site-mode');
    jest.isolateModules(() => {
      if (v === undefined) delete process.env.NEXT_PUBLIC_SITE_MODE;
      else process.env.NEXT_PUBLIC_SITE_MODE = v;
      m = require('@/utils/site-mode');
    });
    return m!;
  };
  afterEach(() => { delete process.env.NEXT_PUBLIC_SITE_MODE; });

  it('is marketing only when set to exactly "marketing"', () => {
    expect(load('marketing').SITE_MODE).toBe('marketing');
    expect(load('marketing').isMarketingSite()).toBe(true);
  });

  it.each([undefined, '', 'platform', 'Marketing', 'MARKETING', 'prod', 'true'])(
    'falls back to platform for %p', (v) => {
      const m = load(v as string | undefined);
      expect(m.SITE_MODE).toBe('platform');
      expect(m.isMarketingSite()).toBe(false);
    },
  );

  it('lists the prefixes the marketing build prunes, and keeps the two that work', () => {
    const m = load(undefined);
    expect(m.PLATFORM_ONLY_PREFIXES).toEqual(
      expect.arrayContaining(['admin', 'experiments', 'feature-flags', 'results', 'workspaces', 'login']),
    );
    expect(m.PLATFORM_ONLY_PREFIXES).not.toContain('docs');
    expect(m.PLATFORM_ONLY_PREFIXES).not.toContain('power-calculator');
  });
});
