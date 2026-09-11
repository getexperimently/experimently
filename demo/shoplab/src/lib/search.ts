import type { Product } from '@/data/products';

export type SearchEngine = 'exact' | 'fuzzy';

export interface SearchHit {
  product: Product;
  /** Lower-cased words from the catalogue text that matched (used for highlighting). */
  matchedWords: string[];
  score: number;
}

export function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((t) => t.length > 0);
}

/** Legacy engine: case-insensitive substring match on the product name only. */
export function exactSearch(products: Product[], query: string): SearchHit[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  return products
    .filter((p) => p.name.toLowerCase().includes(q))
    .map((product) => ({ product, matchedWords: tokenize(q), score: 1 }));
}

/** Levenshtein distance with an early exit once `max` is exceeded. */
export function editDistance(a: string, b: string, max = Infinity): number {
  if (a === b) return 0;
  if (Math.abs(a.length - b.length) > max) return max + 1;
  const prev = new Array<number>(b.length + 1);
  const curr = new Array<number>(b.length + 1);
  for (let j = 0; j <= b.length; j += 1) prev[j] = j;
  for (let i = 1; i <= a.length; i += 1) {
    curr[0] = i;
    let rowMin = curr[0];
    for (let j = 1; j <= b.length; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      curr[j] = Math.min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost);
      rowMin = Math.min(rowMin, curr[j]);
    }
    if (rowMin > max) return max + 1;
    for (let j = 0; j <= b.length; j += 1) prev[j] = curr[j];
  }
  return prev[b.length];
}

function allowedTypos(token: string): number {
  if (token.length >= 7) return 2;
  if (token.length >= 4) return 1;
  return 0;
}

/**
 * New engine: every query token must match a word in name + description + category,
 * allowing prefixes and small typos. Hits are scored by where the match landed
 * (name > category > description) and by rating.
 */
export function fuzzySearch(products: Product[], query: string): SearchHit[] {
  const tokens = tokenize(query);
  if (tokens.length === 0) return [];
  const hits: SearchHit[] = [];
  for (const product of products) {
    const fields: Array<[string[], number]> = [
      [tokenize(product.name), 3],
      [tokenize(product.category), 2],
      [tokenize(product.description), 1],
    ];
    let score = 0;
    const matchedWords = new Set<string>();
    let every = true;
    for (const token of tokens) {
      let best = 0;
      for (const [words, weight] of fields) {
        for (const word of words) {
          let quality = 0;
          if (word === token) quality = 1;
          else if (word.startsWith(token)) quality = 0.8;
          else if (allowedTypos(token) > 0 && editDistance(word, token, allowedTypos(token)) <= allowedTypos(token)) {
            quality = 0.6;
          }
          if (quality > 0) {
            matchedWords.add(word);
            best = Math.max(best, quality * weight);
          }
        }
      }
      if (best === 0) {
        every = false;
        break;
      }
      score += best;
    }
    if (every) {
      hits.push({ product, matchedWords: Array.from(matchedWords), score: score + product.rating / 10 });
    }
  }
  return hits.sort((a, b) => b.score - a.score || a.product.name.localeCompare(b.product.name));
}

export function search(products: Product[], query: string, engine: SearchEngine): SearchHit[] {
  return engine === 'fuzzy' ? fuzzySearch(products, query) : exactSearch(products, query);
}

export interface Segment {
  text: string;
  hit: boolean;
}

/** Split `text` into segments so matched words can be wrapped in `<mark>`. Pure. */
export function highlightSegments(text: string, matchedWords: string[]): Segment[] {
  if (matchedWords.length === 0 || !text) return [{ text, hit: false }];
  const escaped = matchedWords
    .filter((w) => w.length > 0)
    .sort((a, b) => b.length - a.length)
    .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  if (escaped.length === 0) return [{ text, hit: false }];
  const re = new RegExp(`(${escaped.join('|')})`, 'gi');
  const segments: Segment[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = re.exec(text)) !== null) {
    const start = match.index;
    if (start > last) segments.push({ text: text.slice(last, start), hit: false });
    segments.push({ text: match[0], hit: true });
    last = start + match[0].length;
    if (match[0].length === 0) re.lastIndex += 1; // guard against zero-width loops
  }
  if (last < text.length) segments.push({ text: text.slice(last), hit: false });
  return segments;
}
