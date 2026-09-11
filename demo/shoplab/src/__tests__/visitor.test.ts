import {
  countryFromLocale,
  detectDevice,
  generateVisitorId,
  getOrCreateVisitor,
  getVisitor,
  isUuidV4,
  resetVisitor,
  VISITOR_ID_KEY,
} from '@/lib/visitor';

describe('visitor identity', () => {
  beforeEach(() => window.localStorage.clear());

  it('generates RFC 4122 v4 ids', () => {
    const ids = new Set(Array.from({ length: 20 }, () => generateVisitorId()));
    expect(ids.size).toBe(20);
    for (const id of ids) expect(isUuidV4(id)).toBe(true);
  });

  it('creates once, persists in localStorage, and flags the second visit as returning', () => {
    expect(getVisitor()).toBeNull();
    const first = getOrCreateVisitor();
    expect(first).not.toBeNull();
    expect(first?.attributes.returning).toBe(false);
    expect(window.localStorage.getItem(VISITOR_ID_KEY)).toBe(first?.id);

    const second = getOrCreateVisitor();
    expect(second?.id).toBe(first?.id);
    expect(second?.attributes.returning).toBe(true);
    expect(second?.attributes).toMatchObject({ device: expect.any(String), country: expect.any(String) });
  });

  it('resetVisitor mints a fresh id', () => {
    const first = getOrCreateVisitor();
    const fresh = resetVisitor();
    expect(fresh?.id).not.toBe(first?.id);
    expect(isUuidV4(fresh?.id)).toBe(true);
    expect(fresh?.attributes.returning).toBe(false);
    expect(window.localStorage.getItem(VISITOR_ID_KEY)).toBe(fresh?.id);
  });

  it('ignores a tampered id and replaces it', () => {
    window.localStorage.setItem(VISITOR_ID_KEY, 'not-a-uuid');
    expect(getVisitor()).toBeNull();
    const created = getOrCreateVisitor();
    expect(isUuidV4(created?.id)).toBe(true);
  });

  it('derives device and country attributes', () => {
    expect(detectDevice('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)', 390)).toBe('mobile');
    expect(detectDevice('Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)', 1024)).toBe('tablet');
    expect(detectDevice('Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0)', 1440)).toBe('desktop');
    expect(detectDevice('', 500)).toBe('mobile');
    expect(countryFromLocale('en-GB')).toBe('GB');
    expect(countryFromLocale('de_DE')).toBe('DE');
    expect(countryFromLocale('fr')).toBe('US');
    expect(countryFromLocale(undefined)).toBe('US');
  });
});
