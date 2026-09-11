import { PRODUCTS } from '@/data/products';
import {
  favouriteCategory,
  normalizeAlgorithm,
  sortByMl,
  sortByPriceAsc,
  sortByRelevance,
  sortProducts,
} from '@/lib/sorting';

describe('sorting', () => {
  it('relevance = rating desc, then name asc for ties', () => {
    const names = sortByRelevance(PRODUCTS).map((p) => p.name);
    expect(names[0]).toBe('Field Watch'); // 4.9
    expect(names[1]).toBe('Ridge Runner Trail Shoes'); // 4.8
    // Two 4.7s: alphabetical tie-break.
    expect(names.slice(2, 4)).toEqual(['Stormshell Rain Jacket', 'Trailhead Backpack 45L']);
    // Two 4.6s.
    expect(names.slice(4, 6)).toEqual(['Merino Base Layer', 'Summit Tent 2P']);
    expect(names[names.length - 1]).toBe('Everyday Chino Pants'); // 4.1
  });

  it('price_asc = cheapest first, name tie-break', () => {
    const sorted = sortByPriceAsc(PRODUCTS);
    expect(sorted[0].name).toBe('Wool Beanie');
    expect(sorted[sorted.length - 1].name).toBe('Summit Tent 2P');
    for (let i = 1; i < sorted.length; i += 1) {
      expect(sorted[i].price).toBeGreaterThanOrEqual(sorted[i - 1].price);
    }
  });

  it('ml is deterministic per visitor and keeps every product', () => {
    const a = sortByMl(PRODUCTS, 'visitor-a').map((p) => p.id);
    const b = sortByMl(PRODUCTS, 'visitor-a').map((p) => p.id);
    expect(a).toEqual(b);
    expect([...a].sort()).toEqual(PRODUCTS.map((p) => p.id).sort());
  });

  it('ml puts the visitor’s favourite category on top and varies between visitors', () => {
    const orders = new Set<string>();
    for (let i = 0; i < 12; i += 1) {
      const visitorId = `00000000-0000-4000-8000-0000000000${i.toString().padStart(2, '0')}`;
      const sorted = sortByMl(PRODUCTS, visitorId);
      const favourite = favouriteCategory(visitorId);
      expect(sorted.slice(0, 3).map((p) => p.category)).toEqual([favourite, favourite, favourite]);
      orders.add(sorted.map((p) => p.id).join(','));
    }
    expect(orders.size).toBeGreaterThan(1);
  });

  it('normalizeAlgorithm falls back to relevance for unknown values', () => {
    expect(normalizeAlgorithm('price_asc')).toBe('price_asc');
    expect(normalizeAlgorithm('ml')).toBe('ml');
    expect(normalizeAlgorithm('relevance')).toBe('relevance');
    expect(normalizeAlgorithm('bogus')).toBe('relevance');
    expect(normalizeAlgorithm(undefined)).toBe('relevance');
    expect(normalizeAlgorithm(42)).toBe('relevance');
  });

  it('sortProducts dispatches on the algorithm and never mutates the catalogue', () => {
    const before = PRODUCTS.map((p) => p.id);
    expect(sortProducts(PRODUCTS, 'relevance', 'v').map((p) => p.id)).toEqual(sortByRelevance(PRODUCTS).map((p) => p.id));
    expect(sortProducts(PRODUCTS, 'price_asc', 'v').map((p) => p.id)).toEqual(sortByPriceAsc(PRODUCTS).map((p) => p.id));
    expect(sortProducts(PRODUCTS, 'ml', 'v').map((p) => p.id)).toEqual(sortByMl(PRODUCTS, 'v').map((p) => p.id));
    expect(PRODUCTS.map((p) => p.id)).toEqual(before);
  });
});
