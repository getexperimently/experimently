import { CATEGORIES, type Category, type Product } from '@/data/products';

/** The `algorithm` values carried by the `shoplab_plp_sort` variant configurations. */
export type SortAlgorithm = 'relevance' | 'price_asc' | 'ml';

export const SORT_ALGORITHMS: SortAlgorithm[] = ['relevance', 'price_asc', 'ml'];

export const SORT_LABELS: Record<SortAlgorithm, string> = {
  relevance: 'Relevance',
  price_asc: 'Price: low to high',
  ml: 'Recommended for you',
};

/** Coerce an unknown configuration value to a known algorithm (default `relevance`). */
export function normalizeAlgorithm(value: unknown): SortAlgorithm {
  return typeof value === 'string' && (SORT_ALGORITHMS as string[]).includes(value)
    ? (value as SortAlgorithm)
    : 'relevance';
}

/** Rating descending, then name ascending. Pure. */
export function sortByRelevance(products: Product[]): Product[] {
  return [...products].sort((a, b) => b.rating - a.rating || a.name.localeCompare(b.name));
}

/** Price ascending, then name ascending. Pure. */
export function sortByPriceAsc(products: Product[]): Product[] {
  return [...products].sort((a, b) => a.price - b.price || a.name.localeCompare(b.name));
}

/** FNV-1a 32-bit hash of a string. */
export function hashString(input: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < input.length; i += 1) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

/** Small deterministic PRNG (mulberry32). */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const FAVOURITE_WEIGHT = 2.2;

/**
 * Deterministic "taste profile" for a visitor: one favourite category gets a large
 * weight, the rest get a weight in [0.6, 1.2]. Pure.
 */
export function categoryAffinity(visitorId: string): Record<Category, number> {
  const rand = mulberry32(hashString(`${visitorId}:affinity`));
  const favourite = CATEGORIES[Math.floor(rand() * CATEGORIES.length)];
  const affinity = {} as Record<Category, number>;
  for (const category of CATEGORIES) {
    affinity[category] = category === favourite ? FAVOURITE_WEIGHT : 0.6 + rand() * 0.6;
  }
  return affinity;
}

/** The category the "ML" ranking pushes to the top for this visitor. */
export function favouriteCategory(visitorId: string): Category {
  const affinity = categoryAffinity(visitorId);
  return CATEGORIES.reduce((best, c) => (affinity[c] > affinity[best] ? c : best), CATEGORIES[0]);
}

/**
 * "ML personalised" ranking: a deterministic per-visitor shuffle weighted by category
 * affinity (with a small rating nudge). Same visitor → same order. Pure.
 */
export function sortByMl(products: Product[], visitorId: string): Product[] {
  const affinity = categoryAffinity(visitorId);
  const rand = mulberry32(hashString(`${visitorId}:shuffle`));
  const scored = products.map((p) => ({
    product: p,
    score: affinity[p.category] * (0.6 + rand() * 0.4) + p.rating / 25,
  }));
  scored.sort((a, b) => b.score - a.score || a.product.name.localeCompare(b.product.name));
  return scored.map((s) => s.product);
}

export function sortProducts(products: Product[], algorithm: SortAlgorithm, visitorId: string): Product[] {
  switch (algorithm) {
    case 'price_asc':
      return sortByPriceAsc(products);
    case 'ml':
      return sortByMl(products, visitorId);
    case 'relevance':
    default:
      return sortByRelevance(products);
  }
}
