/**
 * In-memory LRU-style cache with TTL support for the React Native SDK.
 */

import type { CacheEntry } from './types';

/**
 * Simple in-memory cache with per-entry TTL.
 *
 * Entries are evicted lazily on the next access after they expire.
 * This is intentionally lightweight — AsyncStorage handles persistence.
 */
export class EvaluationCache<T> {
  private readonly ttlMs: number;
  private readonly store = new Map<string, CacheEntry<T>>();

  constructor(ttlMs: number) {
    this.ttlMs = ttlMs;
  }

  /** Returns the cached value, or `undefined` if absent or expired. */
  get(key: string): T | undefined {
    const entry = this.store.get(key);
    if (!entry) return undefined;

    if (Date.now() > entry.expiresAt) {
      this.store.delete(key);
      return undefined;
    }

    return entry.value;
  }

  /** Returns true if a non-expired entry exists for `key`. */
  has(key: string): boolean {
    return this.get(key) !== undefined;
  }

  /** Stores `value` under `key` with the configured TTL. */
  set(key: string, value: T): void {
    this.store.set(key, { value, expiresAt: Date.now() + this.ttlMs });
  }

  /** Removes the entry for `key`. */
  delete(key: string): void {
    this.store.delete(key);
  }

  /** Removes all entries. */
  clear(): void {
    this.store.clear();
  }

  /** Number of entries (including potentially expired ones not yet evicted). */
  get size(): number {
    return this.store.size;
  }
}
